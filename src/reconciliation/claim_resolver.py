"""Task 34 — Phase 2 claim resolver + main entry.

Phase 2 of the reconciliation plane (ADR 0012). After Phase 1 groups
wiki pages into :py:class:`CanonicalConcept`, Phase 2 groups the
member claims (extracted by Stage 5B) within each canonical into
:py:class:`CanonicalClaim` aggregates using an LLM-driven
pair-wise verifier.

Architecture
------------
The resolver mirrors :mod:`identity_resolver` but operates on claims
instead of pages:

  * :py:func:`enumerate_claim_pairs` — produce the pair list for one
    canonical, capped at :py:data:`MAX_CLAIM_PAIRS_PER_RESOLVE_CALL`
    (R1 audit hard requirement — O(N^2) LLM blow-up guard).

  * :py:func:`build_claim_pair_evidence_pack` — bounded evidence pack
    per claim pair (Bounded Evidence §3.2): each claim's excerpt is
    truncated to :py:data:`MAX_EVIDENCE_CHARS`.

  * :py:func:`parse_llm_claim_verdicts` — pure function that parses
    the LLM's JSON reply, applies the pair_id whitelist, coerces
    unknown decisions to UNRESOLVED, clamps confidence, and emits
    :py:class:`ClaimDecisionRecord` with a *script-owned*
    ``decision_id``.

  * :py:func:`resolve_claim_identity` — public async entry point.
    Calls the LLM once per (canonical, member_claims) batch, retries
    up to ``max_retries`` times, and never raises (Failure Contract §1).

  * :py:func:`reconcile_canonical_claims` — Phase 2 main entry. Per
    canonical, runs :py:func:`resolve_claim_identity` and then
    :py:meth:`CanonicalClaimRegistry.apply_claim_decisions`. Aggregates
    metrics into :py:class:`ReconcileClaimResult`.

  * :py:func:`reconcile_unfinished_claim_resolutions` — startup hook
    (Round 2 R2 audit fix). Scans ``claim_decision_log.jsonl`` for
    in-flight resolutions (apply started but not finished) and
    returns the canonical ids that need retry.

Identity Contract
-----------------
The LLM emits only four fields per verdict:

    ``(pair_id, decision, confidence, reason)``

  * ``pair_id`` is **copied verbatim from the candidate pair list**
    the script gave it. The script built it as
    :py:func:`pair_id_for` of the two member claim ids.
  * ``decision`` must be one of the five strings in
    :py:class:`ClaimReconciliationDecision`. Unknown values are
    coerced to ``UNRESOLVED``.
  * ``canonical_claim_id`` is **never** set by the LLM. It is
    computed from sha1(canonical_id|text_hash|support_kind) at
    apply time via :py:func:`canonical_claim_id_for`.

Failure Contract §1
-------------------
``resolve_claim_identity`` never raises. Concretely:

  * The underlying ``llm.complete`` call is retried up to
    ``max_retries`` times. Every retry that raises is swallowed.
  * If every retry fails, every pair receives an ``UNRESOLVED``
    verdict (fail-closed).
  * JSON parse errors are also swallowed — every pair gets
    ``UNRESOLVED``.

Bounded Evidence §3.2
---------------------
The LLM context window is finite and cost is per-token. We expose
only :py:data:`MAX_EVIDENCE_CHARS` characters per claim excerpt and
cap the number of pairs at
:py:data:`MAX_CLAIM_PAIRS_PER_RESOLVE_CALL` so the prompt stays
bounded even when a canonical owns many member claims.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonical_claim_models import (
    ClaimDecisionRecord,
    ClaimReconciliationDecision,
    decision_id_for_pair,
    pair_id_for,
)
from .canonical_claim_registry import CanonicalClaimRegistry


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bounded Evidence (§3.2) + pair cap (R1 audit)
# ---------------------------------------------------------------------------


#: Maximum characters per claim excerpt fed to the LLM. Per-claim
#: cap so a single noisy claim can't dominate the prompt.
MAX_EVIDENCE_CHARS: int = 1500


#: Maximum number of claim pairs fed to the LLM in one call. R1
#: audit hard requirement: prevents O(N^2) LLM blow-up when a
#: canonical owns many member claims (10 claims → 45 pairs; 50
#: claims → 1225 pairs without the cap).
MAX_CLAIM_PAIRS_PER_RESOLVE_CALL: int = 50


# ---------------------------------------------------------------------------
# Prompt loading (lazy)
# ---------------------------------------------------------------------------


_PROMPT_FILENAME = "claim_resolve.toml"
_PROMPT_KIND = "claim_resolve"


def _load_prompt_template(project_root: Path | str | None) -> Any | None:
    """Load the ``claim_resolve`` TOML template, if available.

    Returns ``None`` when the template file is missing — :py:func:`resolve_claim_identity`
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
# Pair enumeration + bounded evidence
# ---------------------------------------------------------------------------


def enumerate_claim_pairs(
    member_claims: list[Any],
    *,
    max_pairs: int = MAX_CLAIM_PAIRS_PER_RESOLVE_CALL,
) -> list[tuple[str, str]]:
    """Enumerate the pair list for one canonical, capped at ``max_pairs``.

    Pair enumeration strategy:
      * O(N^2) over ``member_claims``, deduplicated on
        ``(min, max)`` order.
      * When the number of candidate pairs exceeds ``max_pairs``,
        prioritize pairs whose combined text length is shortest
        first (typical LLM judgement on shorter, less repetitive
        text is more accurate).

    Parameters
    ----------
    member_claims:
        List of claim objects exposing ``.claim_id`` and ``.text``.
        Only ``.claim_id`` is used here; ``.text`` length is read for
        prioritization only when ``len(pairs) > max_pairs``.
    max_pairs:
        Cap on the returned list. Defaults to
        :py:data:`MAX_CLAIM_PAIRS_PER_RESOLVE_CALL` (50, R1 audit).

    Failure Contract: never raises. Empty / missing ``.claim_id``
    attributes are filtered out.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for claim in member_claims:
        cid = getattr(claim, "claim_id", "") or ""
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)

    # O(N^2) enumerate, but we truncate the candidate text lookups
    # to keep the prioritization cheap.
    candidate_pairs: list[tuple[int, str, str]] = []
    text_lookup: dict[str, str] = {}
    for claim in member_claims:
        cid = getattr(claim, "claim_id", "") or ""
        text_lookup[cid] = getattr(claim, "text", "") or ""

    n = len(ids)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = ids[i], ids[j]
            combined_len = len(text_lookup.get(a, "")) + len(text_lookup.get(b, ""))
            candidate_pairs.append((combined_len, a, b))

    if len(candidate_pairs) <= max_pairs:
        return [(a, b) for _length, a, b in candidate_pairs]

    # Prioritize by shortest combined text first (R1 audit — top-N
    # truncation rule from the spec).
    candidate_pairs.sort(key=lambda t: (t[0], t[1], t[2]))
    return [(a, b) for _length, a, b in candidate_pairs[:max_pairs]]


def build_claim_pair_evidence_pack(
    claim_a: Any,
    claim_b: Any,
    *,
    source_bytes: dict[str, bytes] | None = None,
) -> dict[str, str]:
    """Build the bounded evidence pack for one claim pair.

    Parameters
    ----------
    claim_a, claim_b:
        Claim objects exposing ``.claim_id``, ``.text``, and
        ``.evidence_refs`` (list of :py:class:`EvidenceRef`). When
        ``evidence_refs`` is empty, ``.text`` is used as the excerpt.
    source_bytes:
        Optional ``item_id -> bytes`` map for resolving
        :py:class:`EvidenceRef` byte ranges to text. When absent, the
        resolver falls back to ``claim.text`` (truncated).

    Returns
    -------
    dict[str, str]
        Two-key pack:
          * ``"claim_a_excerpt"`` — first ``MAX_EVIDENCE_CHARS``
            characters of the evidence excerpt for claim_a (with a
            ``"..."`` marker when truncated).
          * ``"claim_b_excerpt"`` — same for claim_b.
    """
    src = source_bytes or {}

    def _excerpt(claim: Any) -> str:
        text = getattr(claim, "text", "") or ""
        refs = getattr(claim, "evidence_refs", None) or []
        if refs and src:
            # Use the first evidence ref whose bytes are available.
            try:
                ref = refs[0]
                item_id = getattr(ref, "item_id", "") or ""
                item_bytes = src.get(item_id)
                if item_bytes is not None:
                    start = int(getattr(ref, "start_byte", 0) or 0)
                    end = int(getattr(ref, "end_byte", start) or start)
                    raw = item_bytes[start:end].decode("utf-8", errors="replace")
                    if len(raw) > MAX_EVIDENCE_CHARS:
                        return raw[:MAX_EVIDENCE_CHARS] + "..."
                    return raw
            except Exception:
                # Evidence bytes missing / malformed → fall through to text.
                pass
        if len(text) > MAX_EVIDENCE_CHARS:
            return text[:MAX_EVIDENCE_CHARS] + "..."
        return text

    return {
        "claim_a_excerpt": _excerpt(claim_a),
        "claim_b_excerpt": _excerpt(claim_b),
    }


# ---------------------------------------------------------------------------
# LLM verdict parsing
# ---------------------------------------------------------------------------


def parse_llm_claim_verdicts(
    raw: str,
    *,
    pairs: list[tuple[str, str]],
    canonical_id: str,
    resolver_fingerprint: str,
) -> list[ClaimDecisionRecord]:
    """Parse the LLM JSON reply into per-pair decision records.

    Parameters
    ----------
    raw:
        The raw text returned by the LLM. May be empty, malformed, or
        contain extra noise — anything non-JSON is treated as an empty
        verdict list (the caller — :py:func:`resolve_claim_identity` —
        will map this to "all UNRESOLVED").
    pairs:
        The pair list the LLM was given. Any verdict citing a
        ``pair_id`` not in this list is **dropped** — the LLM cannot
        fabricate pair ids (Identity Contract).
    canonical_id:
        Wired into every record.
    resolver_fingerprint:
        Copied verbatim into every record.

    Returns
    -------
    list[ClaimDecisionRecord]
        One record per *valid* verdict. The order follows the LLM's
        verdict array order; records are deduplicated by ``pair_id``
        keeping the first occurrence.

    The LLM never emits ``canonical_claim_id``; the helper does not
    look for it (Identity Contract).
    """
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

    # Build a whitelist of canonicalized pair_ids.
    allowed: set[str] = set()
    canonicalized_lookup: dict[str, tuple[str, str]] = {}
    for a, b in pairs:
        pid = pair_id_for(a, b)
        allowed.add(pid)
        canonicalized_lookup[pid] = (a, b)

    seen: set[str] = set()
    out: list[ClaimDecisionRecord] = []
    now_ms = int(time.time() * 1000)

    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        pair_raw = verdict.get("pair_id")
        if not isinstance(pair_raw, str):
            continue
        # Accept the pair_id in either canonical order; coerce to
        # canonical for dedup.
        ordered = pair_id_for(*pair_raw.split("|", 1)) if "|" in pair_raw else pair_raw
        if ordered not in allowed or ordered in seen:
            continue
        seen.add(ordered)

        decision_raw = verdict.get("decision")
        if isinstance(decision_raw, ClaimReconciliationDecision):
            decision = decision_raw
        elif isinstance(decision_raw, str):
            try:
                decision = ClaimReconciliationDecision(decision_raw)
            except ValueError:
                decision = ClaimReconciliationDecision.UNRESOLVED
        else:
            decision = ClaimReconciliationDecision.UNRESOLVED

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
        if len(reason) > 30:
            # Spec: reason <= 30 chars
            reason = reason[:30]

        evidence_refs_raw = verdict.get("evidence_refs", [])
        evidence_refs = (
            list(evidence_refs_raw) if isinstance(evidence_refs_raw, list) else []
        )

        out.append(
            ClaimDecisionRecord(
                decision_id=decision_id_for_pair(ordered, canonical_id, decision),
                pair_id=ordered,
                canonical_id=canonical_id,
                decision=decision,
                confidence=conf,
                reason=reason,
                evidence_refs=evidence_refs,
                resolver_fingerprint=resolver_fingerprint,
                created_at_ms=now_ms,
            )
        )

    return out


# ---------------------------------------------------------------------------
# Per-canonical resolve entry point
# ---------------------------------------------------------------------------


async def resolve_claim_identity(
    canonical_id: str,
    member_claims: list[Any],
    *,
    source_bytes: dict[str, bytes],
    llm: Any,
    template: Any | None = None,
    project_root: Path | str | None = None,
    resolver_fingerprint: str = "",
    max_retries: int = 3,
) -> list[ClaimDecisionRecord]:
    """Phase 2 — claim resolver entry point.

    Parameters
    ----------
    canonical_id:
        The owning :py:class:`CanonicalConcept` id. Capped in scope:
        a single canonical may own many member claims, but this
        function does not paginate (the cap is enforced by
        :py:func:`enumerate_claim_pairs`).
    member_claims:
        List of claim objects exposing ``.claim_id``, ``.text``, and
        ``.evidence_refs``. Empty list → no LLM call, no records.
    source_bytes:
        ``item_id -> bytes`` map used by
        :py:func:`build_claim_pair_evidence_pack` to resolve
        :py:class:`EvidenceRef` byte ranges.
    llm:
        Async LLM client exposing ``complete(*, prompt_kind,
        user_prompt, system_prompt, max_tokens, temperature) -> str``.
    template:
        Optional pre-loaded prompt template (the TOML file's parsed
        payload). When ``None`` we try to load ``claim_resolve.toml``
        next to the module.
    project_root:
        Optional project root used to locate the TOML template file.
    resolver_fingerprint:
        F4 fingerprint wired into every record.
    max_retries:
        Number of LLM retries before we give up and map every
        pair to UNRESOLVED. Defaults to ``3``.

    Returns
    -------
    list[ClaimDecisionRecord]
        One record per *valid* verdict. The order follows the LLM's
        verdict array order. **Never raises** — technical failure
        maps every pair to :py:data:`ClaimReconciliationDecision.UNRESOLVED`.
    """
    # Empty input → no LLM call, no records.
    if not member_claims or not canonical_id:
        return []

    pairs = enumerate_claim_pairs(
        member_claims,
        max_pairs=MAX_CLAIM_PAIRS_PER_RESOLVE_CALL,
    )
    if not pairs:
        return []

    # Load the prompt template (best-effort; failure is non-fatal).
    if template is None:
        template = _load_prompt_template(project_root)

    user_prompt = _render_user_prompt(
        template,
        canonical_id=canonical_id,
        pairs=pairs,
        member_claims=member_claims,
        source_bytes=source_bytes,
    )
    system_prompt = _render_system_prompt(template)

    # Try up to ``max_retries`` times; any failure is swallowed. On
    # total failure we map every pair to UNRESOLVED below.
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

    # Parse whatever we got. parse_llm_claim_verdicts returns one
    # record per *valid* verdict; missing pairs stay UNRESOLVED.
    emitted = parse_llm_claim_verdicts(
        raw,
        pairs=pairs,
        canonical_id=canonical_id,
        resolver_fingerprint=resolver_fingerprint,
    ) if raw else []

    if last_error is not None and not emitted:
        # Every retry raised → every pair is UNRESOLVED.
        return _all_unresolved(
            pairs=pairs,
            canonical_id=canonical_id,
            resolver_fingerprint=resolver_fingerprint,
            reason=f"llm_technical_failure:{type(last_error).__name__}",
        )

    # Merge emitted verdicts with UNRESOLVED fallback for any pair
    # the LLM omitted.
    emitted_by_pid = {r.pair_id: r for r in emitted}
    out: list[ClaimDecisionRecord] = []
    now_ms = int(time.time() * 1000)
    for a, b in pairs:
        pid = pair_id_for(a, b)
        existing = emitted_by_pid.get(pid)
        if existing is not None:
            out.append(existing)
            continue
        out.append(
            ClaimDecisionRecord(
                decision_id=decision_id_for_pair(
                    pid, canonical_id, ClaimReconciliationDecision.UNRESOLVED
                ),
                pair_id=pid,
                canonical_id=canonical_id,
                decision=ClaimReconciliationDecision.UNRESOLVED,
                confidence=0.0,
                reason="llm_omitted_pair",
                evidence_refs=[],
                resolver_fingerprint=resolver_fingerprint,
                created_at_ms=now_ms,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Internal helpers (prompt rendering + all-unresolved fallback)
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
    canonical_id: str,
    pairs: list[tuple[str, str]],
    member_claims: list[Any],
    source_bytes: dict[str, bytes],
) -> str:
    """Render the user prompt from the template, with a safe fallback.

    The fallback (when ``template is None`` or the ``[user].template``
    field is missing) is a hand-built prompt that uses the same slot
    names the TOML expects, so the LLM sees a consistent shape
    regardless of whether the TOML loaded successfully.
    """
    # Build the per-pair block for both the templated and fallback
    # prompts. Each pair is rendered with bounded evidence.
    pair_lines: list[str] = []
    for a, b in pairs:
        claim_a = _find_claim(member_claims, a)
        claim_b = _find_claim(member_claims, b)
        pack = build_claim_pair_evidence_pack(
            claim_a, claim_b, source_bytes=source_bytes
        )
        pair_lines.append(
            f"=== pair: {a} | {b} ===\n"
            f"  claim_a_id: {a}\n"
            f"  text_a: {pack['claim_a_excerpt']}\n"
            f"  claim_b_id: {b}\n"
            f"  text_b: {pack['claim_b_excerpt']}"
        )
    claim_pairs_text = "\n".join(pair_lines) if pair_lines else "(no pairs)"
    pair_count = len(pairs)
    max_pairs = MAX_CLAIM_PAIRS_PER_RESOLVE_CALL

    if template is not None:
        try:
            tpl = template.get("user", {}).get("template", "") or ""
        except (AttributeError, TypeError):
            tpl = ""
        if tpl:
            try:
                return tpl.format(
                    canonical_id=canonical_id,
                    claim_pairs_text=claim_pairs_text,
                    max_pairs=max_pairs,
                    pair_count=pair_count,
                    decisions_block="",
                )
            except (KeyError, IndexError, ValueError):
                # Malformed template — fall through to the safe literal.
                pass

    return (
        f"Canonical concept: {canonical_id}\n"
        f"Pair count: {pair_count} (capped at {max_pairs})\n"
        "\n"
        "Claim pairs (compare text_a vs text_b; emit pair_id verbatim):\n"
        f"{claim_pairs_text}\n"
        "\n"
        "For each pair, return a verdict using EXACTLY these strings:\n"
        '  - "same":       the two claims express the same view\n'
        '  - "overlap":    they partially overlap but are not identical\n'
        '  - "conflict":   they contradict each other\n'
        '  - "unresolved": insufficient evidence to decide\n'
        "\n"
        "Respond with JSON in exactly this shape:\n"
        '{"verdicts": [{"pair_id": "claim_id_A|claim_id_B", '
        '"decision": "same|overlap|conflict|unresolved", '
        '"confidence": 0.0..1.0, "reason": "<=30 chars"}]}'
    )


def _find_claim(member_claims: list[Any], claim_id: str) -> Any:
    """Locate a claim by id in ``member_claims``.

    Failure Contract: never raises. Returns ``None`` when the id is
    not found so the caller can fall back gracefully.
    """
    for claim in member_claims:
        if getattr(claim, "claim_id", "") == claim_id:
            return claim
    return None


def _all_unresolved(
    *,
    pairs: list[tuple[str, str]],
    canonical_id: str,
    resolver_fingerprint: str,
    reason: str,
) -> list[ClaimDecisionRecord]:
    """Emit one UNRESOLVED record per pair (fail-closed)."""
    now_ms = int(time.time() * 1000)
    out: list[ClaimDecisionRecord] = []
    for a, b in pairs:
        pid = pair_id_for(a, b)
        out.append(
            ClaimDecisionRecord(
                decision_id=decision_id_for_pair(
                    pid, canonical_id, ClaimReconciliationDecision.UNRESOLVED
                ),
                pair_id=pid,
                canonical_id=canonical_id,
                decision=ClaimReconciliationDecision.UNRESOLVED,
                confidence=0.0,
                reason=reason[:30],
                evidence_refs=[],
                resolver_fingerprint=resolver_fingerprint,
                created_at_ms=now_ms,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Result dataclass + Phase 2 main entry
# ---------------------------------------------------------------------------


@dataclass
class ReconcileClaimResult:
    """Aggregate metrics from one :py:func:`reconcile_canonical_claims` run.

    Attributes
    ----------
    processed:
        Number of canonicals visited by the pipeline.
    created_new:
        Number of freshly-created CanonicalClaim records (SINGLE
        back-fill or first-ever apply on a canonical).
    merged_existing:
        Number of SAME / OVERLAP decisions that joined an existing
        CanonicalClaim in the registry.
    unresolved:
        Number of UNRESOLVED decisions emitted.
    errors:
        Number of canonicals whose pipeline raised before completion
        (technical failures distinct from "resolver couldn't decide").
    """

    processed: int = 0
    created_new: int = 0
    merged_existing: int = 0
    unresolved: int = 0
    errors: int = 0


async def reconcile_canonical_claims(
    canonical_ids: list[str],
    *,
    project_root: Path | str,
    llm: Any,
    body_by_canonical: dict[str, dict[str, bytes]] | None = None,
    resolver_fingerprint: str = "",
    template: Any | None = None,
    member_claims_by_canonical: dict[str, list[Any]] | None = None,
) -> ReconcileClaimResult:
    """Phase 2 main entry.

    Per canonical:
      1. enumerate pairs (capped at MAX_CLAIM_PAIRS_PER_RESOLVE_CALL)
      2. ``resolve_claim_identity(canonical, member_claims)``
      3. ``registry.apply_claim_decisions(canonical, decisions)``

    The member-claim source is supplied via ``member_claims_by_canonical``
    (a ``canonical_id -> list[Claim]`` map). When a canonical has no
    entry in the map (or the list is empty), the canonical is counted
    as processed but no LLM call is issued.

    Failure Contract §1: per-canonical errors are isolated. A
    canonical whose pipeline raises is counted as ``errors`` and the
    batch continues.
    """
    registry = CanonicalClaimRegistry(
        project_root, resolver_fingerprint=resolver_fingerprint
    )
    claims_map = member_claims_by_canonical or {}
    sources_map = body_by_canonical or {}

    result = ReconcileClaimResult()

    for canonical_id in canonical_ids:
        if not canonical_id:
            result.errors += 1
            continue
        result.processed += 1
        member_claims = claims_map.get(canonical_id, [])
        source_bytes = sources_map.get(canonical_id, {})

        try:
            decisions = await resolve_claim_identity(
                canonical_id=canonical_id,
                member_claims=member_claims,
                source_bytes=source_bytes,
                llm=llm,
                template=template,
                project_root=project_root,
                resolver_fingerprint=resolver_fingerprint,
            )
        except Exception as exc:
            _LOG.warning(
                "reconcile_canonical_claims: resolve failed for canonical=%s: %s",
                canonical_id, exc,
            )
            result.errors += 1
            continue

        if not decisions:
            continue

        # Tally per-decision verdict before applying.
        for d in decisions:
            if d.decision is ClaimReconciliationDecision.UNRESOLVED:
                result.unresolved += 1
            elif d.decision in (
                ClaimReconciliationDecision.SAME,
                ClaimReconciliationDecision.OVERLAP,
            ):
                result.merged_existing += 1
            else:
                result.created_new += 1

        try:
            registry.apply_claim_decisions(
                canonical_id,
                decisions,
                resolver_fingerprint=resolver_fingerprint,
            )
        except Exception as exc:
            _LOG.warning(
                "reconcile_canonical_claims: apply failed for canonical=%s: %s",
                canonical_id, exc,
            )
            result.errors += 1
            continue

    return result


# ---------------------------------------------------------------------------
# Startup hook (Round 2 R2 audit fix)
# ---------------------------------------------------------------------------


def _read_claim_decision_log(project_root: Path | str) -> list[dict[str, Any]]:
    """Best-effort read of ``claim_decision_log.jsonl``.

    Returns an empty list on missing / malformed log (Failure
    Contract §1).
    """
    from .canonical_claim_registry import claim_decision_log_path

    path = claim_decision_log_path(project_root)
    if not path.exists():
        return []
    try:
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(raw, dict):
                    out.append(raw)
        return out
    except Exception as exc:
        _LOG.warning(
            "_read_claim_decision_log: failed for %s: %s", path, exc
        )
        return []


async def reconcile_unfinished_claim_resolutions(
    project_root: Path | str,
    *,
    current_fingerprint: str,
) -> list[str]:
    """Startup hook — recover in-flight Phase 2 resolutions.

    Scans ``claim_decision_log.jsonl`` and finds canonical_ids whose
    ``apply_claim_decisions`` step is in-flight (the registry has
    apply-time records but the resolver_fingerprint on the
    canonical_claim records has not been updated to
    ``current_fingerprint``).

    Mirrors Phase 1's :py:func:`reconcile_stale_signals` pattern
    (Task 31). Returns the list of canonical ids that need retry.

    Failure Contract §1: never raises. A missing or corrupted log
    file yields an empty result.
    """
    try:
        log_entries = _read_claim_decision_log(project_root)
        # Collect distinct canonical_ids whose decisions are still
        # in-flight (resolver_fingerprint drift).
        in_flight: set[str] = set()
        for entry in log_entries:
            cid = entry.get("canonical_id")
            fp = entry.get("resolver_fingerprint", "")
            if isinstance(cid, str) and cid and fp != current_fingerprint:
                in_flight.add(cid)
        # Also surface canonicals whose CanonicalClaim records show
        # fingerprint drift (the on-disk registry view).
        registry = CanonicalClaimRegistry(
            project_root, resolver_fingerprint=current_fingerprint
        )
        stale_ccids = set(registry.find_stale(current_fingerprint))
        # A canonical claim is "stale" because its members haven't
        # been re-resolved under the current fingerprint — the owning
        # canonical concept id is the unit of retry.
        drift_canonicals: set[str] = set()
        if stale_ccids:
            for cc in registry.load_canonical_claims().values():
                if cc.canonical_claim_id in stale_ccids and cc.canonical_id:
                    drift_canonicals.add(cc.canonical_id)
        return sorted(in_flight | drift_canonicals)
    except Exception as exc:  # pragma: no cover - defensive guard
        _LOG.warning(
            "reconcile_unfinished_claim_resolutions: scan failed for root=%s: %s",
            project_root, exc,
        )
        return []


# Suppress "imported but unused" lint on items used by tests via
# ``__all__`` / dynamic imports.
_ = asyncio


__all__ = [
    "MAX_CLAIM_PAIRS_PER_RESOLVE_CALL",
    "MAX_EVIDENCE_CHARS",
    "ReconcileClaimResult",
    "build_claim_pair_evidence_pack",
    "enumerate_claim_pairs",
    "parse_llm_claim_verdicts",
    "reconcile_canonical_claims",
    "reconcile_unfinished_claim_resolutions",
    "resolve_claim_identity",
]
