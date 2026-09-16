"""Task 29 — Reconciliation identity resolver.

Stage 6R's verdict-emission step. Given ONE new wiki page and the
``max_candidates`` short-list produced by :mod:`candidate_retrieval`,
the identity resolver asks an LLM to classify the relationship between
the new page and every candidate canonical concept, returning one
:py:class:`ReconciliationDecisionRecord` per candidate.

Architecture
------------
The resolver has four moving parts:

  * ``build_evidence_pack`` — produces the **bounded evidence pack**:
    title + key slot content + evidence excerpts, each truncated to a
    pre-declared character budget. The LLM never sees the whole page
    body (Bounded Evidence §3.2 — confidentiality / cost / determinism).

  * ``render_candidates_block`` — formats the short-list as a
    human-readable block the LLM can cite verbatim.

  * ``parse_llm_verdicts`` — pure function that parses the LLM's JSON
    reply, applies the canonical-id whitelist, coerces unknown
    decisions to ``UNRESOLVED``, clamps confidence, and emits
    :py:class:`ReconciliationDecisionRecord` instances with a
    *script-owned* ``decision_id``.

  * ``resolve_identity`` — the public async entry point. Calls the LLM
    once per (page, candidates) batch, retries up to ``max_retries``
    times, and never raises (Failure Contract §1): a technical failure
    maps every candidate to ``UNRESOLVED`` so the caller can still
    proceed.

Identity Contract
-----------------
The LLM emits only four fields per verdict:

    ``(canonical_id, decision, confidence, reason)``

  * ``canonical_id`` is **copied verbatim from the candidate list** the
    script gave it. Any canonical_id not in the candidate list is
    dropped by :py:func:`parse_llm_verdicts` — the LLM cannot fabricate
    a canonical_id that doesn't exist.

  * ``decision`` must be one of the eight strings in
    :py:class:`ReconciliationDecision`. Unknown values are coerced to
    ``UNRESOLVED``.

  * ``decision_id`` is **never** set by the LLM; it is computed from
    ``sha1(page_id|canonical_id|decision)[:12]`` and prefixed ``dec-``.
    This makes the id deterministic and prevents the LLM from
    influencing id generation.

Failure Contract §1
-------------------
``resolve_identity`` never raises. Concretely:

  * The underlying ``llm.complete`` call is retried up to
    ``max_retries`` times. Every retry that raises is swallowed.
  * If every retry fails, every candidate receives an ``UNRESOLVED``
    verdict (fail-closed). The function returns a non-empty list of
    decision records so the caller can continue the pipeline.
  * JSON parse errors are also swallowed — every candidate gets
    ``UNRESOLVED``.

Bounded Evidence §3.2
---------------------
The LLM context window is finite and cost is per-token. We expose only
``MAX_KEY_SLOT_CHARS`` characters per key slot and ``MAX_EVIDENCE_CHARS``
characters of page body. Truncation is silent and lossy; the audit trail
knows the *original* was longer but does not store the original.

The downstream pipeline can re-resolve a verdict by re-running the
resolver with a fuller evidence pack, so lossy truncation is acceptable
for the v1 contract.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .canonical_models import (
    ReconciliationDecision,
    ReconciliationDecisionRecord,
    decision_id_for,
)
from .candidate_retrieval import (
    CanonicalIndex,
    ReconciliationCandidate,
)


# ---------------------------------------------------------------------------
# Bounded Evidence (§3.2)
# ---------------------------------------------------------------------------


#: Maximum characters per key slot fed to the LLM. Per-slot cap so a
#: single noisy slot can't dominate the prompt.
MAX_KEY_SLOT_CHARS: int = 600

#: Maximum characters of page-body evidence fed to the LLM. Total cap
#: so even with many key slots the prompt stays bounded.
MAX_EVIDENCE_CHARS: int = 1500


# ---------------------------------------------------------------------------
# Prompt loading (lazy)
# ---------------------------------------------------------------------------


_PROMPT_FILENAME = "identity_resolve.toml"
_PROMPT_KIND = "identity_resolve"


def _load_prompt_template(project_root: Path | str | None) -> Any | None:
    """Load the identity_resolve TOML template, if available.

    Returns ``None`` when the template file is missing — :py:func:`resolve_identity`
    falls back to a hand-built prompt in that case. We never raise here:
    a missing prompt file must not block the pipeline.
    """
    candidates: list[Path] = []
    if project_root is not None:
        candidates.append(
            Path(project_root)
            / "src"
            / "reconciliation"
            / "prompts"
            / "builtin"
            / _PROMPT_FILENAME
        )
    # Fallback: relative to this module.
    candidates.append(
        Path(__file__).parent / "prompts" / "builtin" / _PROMPT_FILENAME
    )
    for path in candidates:
        try:
            if not path.is_file():
                continue
            try:
                import tomllib  # py3.11+
            except ImportError:  # pragma: no cover - py<3.11 fallback
                import tomli as tomllib  # type: ignore[no-redef]
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            if data.get("meta", {}).get("prompt_kind") == _PROMPT_KIND:
                return data
        except Exception:
            # A malformed TOML or I/O error is non-fatal: the resolver
            # falls back to a hand-built prompt and still returns
            # UNRESOLVED verdicts on technical failure.
            continue
    return None


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def build_evidence_pack(
    new_page: Any,
    *,
    key_slot_names: tuple[str, ...] = ("definition", "characteristics"),
    body_by_page: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the bounded evidence pack fed to the LLM.

    Parameters
    ----------
    new_page:
        A wiki page object exposing ``.id``, ``.title``, ``.slots``
        (a ``dict[str, str]`` of named slot content), and ``.body``
        (raw Markdown). The signature uses ``Any`` so this module
        doesn't import the full wiki model — the runtime page type
        is the wiki's :py:class:`WikiPage` from ``src.wiki.core``.
    key_slot_names:
        Ordered list of slot names to extract; each is truncated to
        :py:data:`MAX_KEY_SLOT_CHARS` characters.
    body_by_page:
        Optional ``page_id -> body text`` map. When the new page's
        ``.body`` is empty (e.g. slot-only pages), the resolver
        looks up its id here. Either way the body is truncated to
        :py:data:`MAX_EVIDENCE_CHARS`.

    Returns
    -------
    dict[str, str]
        A two-key pack:

          * ``"key_slots_text"`` — ``"label: truncated_content"`` for
            each requested slot, joined by ``" | "``.
          * ``"evidence_text"``  — the page body, truncated to
            :py:data:`MAX_EVIDENCE_CHARS` characters with a ``"..."``
            marker when truncation happened.
    """
    slots: dict[str, Any] = getattr(new_page, "slots", {}) or {}
    page_id: str = getattr(new_page, "id", "") or ""
    body: str = getattr(new_page, "body", "") or ""
    if not body and body_by_page is not None:
        body = body_by_page.get(page_id, "") or ""

    slot_parts: list[str] = []
    for name in key_slot_names:
        raw = slots.get(name, "") or ""
        text = str(raw)
        if len(text) > MAX_KEY_SLOT_CHARS:
            text = text[:MAX_KEY_SLOT_CHARS] + "..."
        slot_parts.append(f"{name}: {text}")
    key_slots_text = " | ".join(slot_parts)

    if len(body) > MAX_EVIDENCE_CHARS:
        evidence_text = body[:MAX_EVIDENCE_CHARS] + "..."
    else:
        evidence_text = body

    return {
        "key_slots_text": key_slots_text,
        "evidence_text": evidence_text,
    }


def render_candidates_block(
    candidates: list[ReconciliationCandidate],
    index: CanonicalIndex,
) -> str:
    """Render the candidate list as an LLM-readable block.

    Each candidate is rendered as::

        === <canonical_id> ===
        Label: <preferred_label>
        Score: <score> (<strategy>)
        Aliases: <comma-separated>

    Missing labels / aliases default to ``"(unknown)"`` / ``""`` so the
    LLM still gets a well-formed block. The function never raises; a
    malformed index entry is treated as ``"(unknown)"``.
    """
    if not candidates:
        return "(no candidates)"
    lines: list[str] = []
    for cand in candidates:
        entry = index.get(cand.canonical_id)
        label = entry.preferred_label if entry is not None else "(unknown)"
        aliases = ", ".join(entry.aliases) if entry is not None else ""
        lines.append(f"=== {cand.canonical_id} ===")
        lines.append(f"Label: {label}")
        lines.append(f"Score: {cand.score:.3f} ({cand.strategy})")
        lines.append(f"Aliases: {aliases}")
    return "\n".join(lines)


def parse_llm_verdicts(
    raw: str,
    *,
    new_page_id: str,
    candidates: list[ReconciliationCandidate],
    resolver_fingerprint: str,
) -> list[ReconciliationDecisionRecord]:
    """Parse the LLM JSON reply into decision records (pure function).

    Parameters
    ----------
    raw:
        The raw text returned by the LLM. May be empty, malformed, or
        contain extra noise — anything non-JSON is treated as an empty
        verdict list (the caller — :py:func:`resolve_identity` — will
        map this to "all UNRESOLVED").
    new_page_id:
        The wiki page id the verdict is about; wired into
        :py:attr:`ReconciliationDecisionRecord.candidate_page_id` and
        the ``decision_id`` hash.
    candidates:
        The short-list the LLM was given. Any verdict citing a
        ``canonical_id`` not in this list is **dropped** — the LLM
        cannot fabricate canonical ids (Identity Contract).
    resolver_fingerprint:
        Copied verbatim into every record.

    Returns
    -------
    list[ReconciliationDecisionRecord]
        One record per *valid* verdict. The order follows the LLM's
        verdict array order; records are deduplicated by
        ``canonical_id`` keeping the first occurrence (the LLM is not
        expected to emit duplicates, but we tolerate it gracefully).
    """
    # Empty / non-JSON input → empty list. Caller will treat this as
    # "no verdicts emitted" and map every candidate to UNRESOLVED.
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    verdicts = payload.get("verdicts")
    if not isinstance(verdicts, list):
        return []

    allowed = {c.canonical_id for c in candidates}
    # Build a lookup so we can preserve the candidate order when the
    # LLM emits them in a different sequence. Verdicts referencing
    # canonical_ids not in `allowed` are dropped entirely.
    seen: set[str] = set()
    out: list[ReconciliationDecisionRecord] = []
    now_ms = int(time.time() * 1000)

    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        cid_raw = verdict.get("canonical_id")
        if not isinstance(cid_raw, str):
            continue
        if cid_raw not in allowed or cid_raw in seen:
            continue
        seen.add(cid_raw)

        decision_raw = verdict.get("decision")
        if isinstance(decision_raw, ReconciliationDecision):
            decision = decision_raw
        elif isinstance(decision_raw, str):
            try:
                decision = ReconciliationDecision(decision_raw)
            except ValueError:
                decision = ReconciliationDecision.UNRESOLVED
        else:
            decision = ReconciliationDecision.UNRESOLVED

        # Confidence: clamp to [0, 1]; coerce non-numeric to 0.0.
        conf_raw = verdict.get("confidence", 0.0)
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.0:
            conf = 0.0
        elif conf > 1.0:
            conf = 1.0

        reason_raw = verdict.get("reason", "") or ""
        reason = str(reason_raw)
        if len(reason) > 200:
            reason = reason[:200]

        evidence_refs_raw = verdict.get("evidence_refs", [])
        evidence_refs = (
            list(evidence_refs_raw) if isinstance(evidence_refs_raw, list) else []
        )

        out.append(
            ReconciliationDecisionRecord(
                decision_id=decision_id_for(new_page_id, cid_raw, decision),
                candidate_page_id=new_page_id,
                candidate_canonical_id=cid_raw,
                decision=decision,
                confidence=conf,
                reason=reason,
                evidence_refs=evidence_refs,
                resolver_fingerprint=resolver_fingerprint,
                created_at_ms=now_ms,
            )
        )

    return out


async def resolve_identity(
    new_page_id: str,
    new_page_title: str,
    new_page: Any,
    candidates: list[ReconciliationCandidate],
    index: CanonicalIndex,
    *,
    llm: Any,
    template: Any | None = None,
    project_root: Path | str | None = None,
    body_by_page: dict[str, str] | None = None,
    resolver_fingerprint: str = "",
    max_retries: int = 3,
) -> list[ReconciliationDecisionRecord]:
    """Stage 6R — identity resolver entry point.

    Parameters
    ----------
    new_page_id:
        Wiki page id being reconciled.
    new_page_title:
        Human-readable title; included verbatim in the prompt.
    new_page:
        The wiki page object (any type exposing ``.slots`` and
        ``.body``). May be ``None`` — in which case the evidence pack
        contains only the title.
    candidates:
        Short-list from :py:func:`candidate_retrieval.retrieve_candidates`.
        Order is preserved when mapping UNRESOLVED fallback.
    index:
        Pre-built :py:class:`CanonicalIndex` used to render the
        candidate labels / aliases in the prompt.
    llm:
        Anything that exposes ``async complete(*, prompt_kind,
        user_prompt, system_prompt, max_tokens, temperature) -> str``.
        Matches the project's :py:class:`LLMClient` interface.
    template:
        Optional pre-loaded prompt template (the TOML file's parsed
        payload). When ``None`` we try to load
        ``identity_resolve.toml`` next to the module.
    project_root:
        Optional project root used to locate the TOML template file.
    body_by_page:
        Optional ``page_id -> body`` map for slot-only pages.
    resolver_fingerprint:
        F4 fingerprint wired into every record.
    max_retries:
        Number of LLM retries before we give up and map every
        candidate to UNRESOLVED. Defaults to ``3``.

    Returns
    -------
    list[ReconciliationDecisionRecord]
        One record per input candidate. The order matches
        ``candidates``. **Never raises** — technical failure maps every
        candidate to :py:data:`ReconciliationDecision.UNRESOLVED`.
    """
    # Empty candidate list → no LLM call, no records. This is the
    # "nothing to resolve" fast path; the caller can short-circuit.
    if not candidates:
        return []

    # Load the prompt template (best-effort; failure is non-fatal).
    if template is None:
        template = _load_prompt_template(project_root)

    # Build the bounded evidence pack + candidates block.
    pack = build_evidence_pack(
        new_page, body_by_page=body_by_page
    )
    candidates_block = render_candidates_block(candidates, index)

    user_prompt = _render_user_prompt(
        template,
        page_id=new_page_id,
        page_title=new_page_title,
        key_slots_text=pack["key_slots_text"],
        evidence_text=pack["evidence_text"],
        candidates_block=candidates_block,
    )
    system_prompt = _render_system_prompt(template)

    # Try up to ``max_retries`` times; any failure is swallowed. On
    # total failure we map every candidate to UNRESOLVED below.
    raw = ""
    last_error: Exception | None = None
    for _ in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind=_PROMPT_KIND,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=2048,
                temperature=0.0,
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            raw = ""
            continue

    # Parse whatever we got. parse_llm_verdicts returns one record per
    # *valid* verdict; missing canonical_ids stay UNRESOLVED.
    emitted = parse_llm_verdicts(
        raw,
        new_page_id=new_page_id,
        candidates=candidates,
        resolver_fingerprint=resolver_fingerprint,
    ) if raw else []

    if last_error is not None and not emitted:
        # Every retry raised → every candidate is UNRESOLVED.
        return _all_unresolved(
            candidates=candidates,
            new_page_id=new_page_id,
            resolver_fingerprint=resolver_fingerprint,
            reason=f"llm_technical_failure:{type(last_error).__name__}",
        )

    # Merge emitted verdicts with UNRESOLVED fallback for any candidate
    # the LLM omitted. This guarantees a record per input candidate,
    # which downstream Task 30 expects.
    emitted_by_cid = {
        r.candidate_canonical_id: r for r in emitted if r.candidate_canonical_id
    }
    out: list[ReconciliationDecisionRecord] = []
    now_ms = int(time.time() * 1000)
    for cand in candidates:
        existing = emitted_by_cid.get(cand.canonical_id)
        if existing is not None:
            out.append(existing)
            continue
        out.append(
            ReconciliationDecisionRecord(
                decision_id=decision_id_for(
                    new_page_id, cand.canonical_id, ReconciliationDecision.UNRESOLVED
                ),
                candidate_page_id=new_page_id,
                candidate_canonical_id=cand.canonical_id,
                decision=ReconciliationDecision.UNRESOLVED,
                confidence=0.0,
                reason="llm_omitted_candidate",
                evidence_refs=[],
                resolver_fingerprint=resolver_fingerprint,
                created_at_ms=now_ms,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_system_prompt(template: Any | None) -> str:
    """Pull ``[system].text`` from the template, or fall back to a literal."""
    if template is None:
        return ""
    try:
        text = template.get("system", {}).get("text", "") or ""
    except (AttributeError, TypeError):
        return ""
    return str(text)


def _render_user_prompt(
    template: Any | None,
    *,
    page_id: str,
    page_title: str,
    key_slots_text: str,
    evidence_text: str,
    candidates_block: str,
) -> str:
    """Render the user prompt from the template, with a safe fallback.

    The fallback (when ``template is None`` or the ``[user].template``
    field is missing) is a hand-built prompt that uses the same slot
    names the TOML expects, so the LLM sees a consistent shape
    regardless of whether the TOML loaded successfully.
    """
    if template is not None:
        try:
            tpl = template.get("user", {}).get("template", "") or ""
        except (AttributeError, TypeError):
            tpl = ""
        if tpl:
            try:
                return tpl.format(
                    page_id=page_id,
                    page_title=page_title,
                    key_slots_text=key_slots_text,
                    evidence_text=evidence_text,
                    candidates_block=candidates_block,
                )
            except (KeyError, IndexError, ValueError):
                # Malformed template — fall through to the safe literal.
                pass

    return (
        "New page being reconciled:\n"
        f"  page_id: {page_id}\n"
        f"  title: {page_title}\n"
        f"  key slots: {key_slots_text}\n"
        f"  evidence excerpts: {evidence_text}\n"
        "\n"
        "Candidate canonical concepts (cite canonical_id verbatim):\n"
        f"{candidates_block}\n"
        "\n"
        "For each candidate, return a verdict using EXACTLY these strings:\n"
        '  - "same":       the new page and this candidate refer to the same concept\n'
        '  - "alias":      the new page is an alternative label for this candidate\n'
        '  - "broader":    the new page is a hypernym of this candidate (candidate is narrower)\n'
        '  - "narrower":   the new page is a hyponym of this candidate (candidate is broader)\n'
        '  - "overlap":    they share members but neither contains the other\n'
        '  - "conflict":   they refer to different concepts (mark for human review)\n'
        '  - "distinct":   they are different concepts (no relation)\n'
        '  - "unresolved": insufficient evidence to decide\n'
        "\n"
        'Respond with JSON in exactly this shape:\n'
        '{"verdicts": [{"canonical_id": "...", "decision": "same|alias|...", '
        '"confidence": 0.0..1.0, "reason": "<=30 chars"}]}'
    )


def _all_unresolved(
    *,
    candidates: list[ReconciliationCandidate],
    new_page_id: str,
    resolver_fingerprint: str,
    reason: str,
) -> list[ReconciliationDecisionRecord]:
    """Emit one UNRESOLVED record per candidate (fail-closed)."""
    now_ms = int(time.time() * 1000)
    out: list[ReconciliationDecisionRecord] = []
    for cand in candidates:
        out.append(
            ReconciliationDecisionRecord(
                decision_id=decision_id_for(
                    new_page_id, cand.canonical_id, ReconciliationDecision.UNRESOLVED
                ),
                candidate_page_id=new_page_id,
                candidate_canonical_id=cand.canonical_id,
                decision=ReconciliationDecision.UNRESOLVED,
                confidence=0.0,
                reason=reason[:200],
                evidence_refs=[],
                resolver_fingerprint=resolver_fingerprint,
                created_at_ms=now_ms,
            )
        )
    return out


__all__ = [
    "MAX_KEY_SLOT_CHARS",
    "MAX_EVIDENCE_CHARS",
    "build_evidence_pack",
    "render_candidates_block",
    "parse_llm_verdicts",
    "resolve_identity",
]