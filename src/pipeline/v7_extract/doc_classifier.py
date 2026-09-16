"""Stage 1 of the V7 extract pipeline: classify_doc(content) -> Classification.

v3 (plan 2026-09-15): pure-LLM classification. Heuristics deleted (T2.1).
The classifier delegates to the prompts/ sub-package — the prompt text,
output schema, retry policy, and three-layer override all live in
``prompts/builtin/classify.toml`` (or a project/user override).

v4 (plan 2026-09-17 Stage 1 remediation): extended ``Classification`` with
failure metadata + traits + fingerprint so Stage 3/4 can consume them.
Technical failure (LLM timeout / parse / network) now sets ``failed=True``
explicitly, instead of smuggling itself into ``doc_type='incomplete'``.
The ``incomplete`` value is retained for backward compatibility with
existing tests + the v2 ``DocType`` enum.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve

if TYPE_CHECKING:
    from .prompts.ast import PromptTemplate


log = logging.getLogger(__name__)


# The 7 mutually-exclusive document types (RFC v6 §9). Mirrors
# ``DocType`` in the rest of v7_extract; we re-declare the values
# here as plain strings so callers don't need to import the enum
# to compare classifications against the LLM's raw output.
#
# Note: ``incomplete`` is preserved here for backward compatibility with
# the v2 ``DocType`` enum and existing tests. v4 callers should check
# ``classification.failed`` first — a Classification with
# ``doc_type='incomplete'`` and ``failed=False`` is a legacy artefact,
# one with ``failed=True`` is a real Stage 1 failure.
_VALID_DOC_TYPES: frozenset[str] = frozenset({
    "single_method",
    "multi_section",
    "collection",
    "qa_chat",
    "list",
    "tool",
    "incomplete",
})


# Backwards-compat shim: v2 used a DocType enum (deleted in v3).
# v3 uses plain strings everywhere, but other modules still import
# the symbol — keep a minimal stub until T2.2-T2.5 finish migrating
# completeness_checker / topic_clusterer / slot_filler / wiki_writer.
from enum import Enum


class DocType(str, Enum):
    """Deprecated alias for the 7 string doc_type values. v3 uses
    strings directly; this enum is kept only so v2 modules that haven't
    been migrated yet can still ``from .doc_classifier import DocType``
    without ImportError. Remove after Phase 2 is complete."""

    SINGLE_METHOD = "single_method"
    MULTI_SECTION = "multi_section"
    COLLECTION = "collection"
    QA_CHAT = "qa_chat"
    LIST = "list"
    TOOL = "tool"
    INCOMPLETE = "incomplete"


# Structural signal patterns for evidence_summary (used by Stage 4
# to consume traits + by future Stage 3 to detect collection).
# ponytail: kept as plain module-level constants — only the regexes
# Stage 4 actually reads today. Add more here when needed.
_H2_RE = re.compile(r"(?m)^##\s+")
_AUTHOR_BYLINE_RE = re.compile(r"(?m)^\s*作者\s*[:：]\s*\S{1,20}\s*$")


class Classification:
    """Result of Stage 1.

    v4 contract (Stage 1 remediation):
      - ``doc_type`` is always one of the 7 known DocType strings.
      - ``confidence`` is in [0.0, 1.0]; 0.0 typically means "LLM failed".
      - ``failed`` is True iff this Classification is the result of a
        technical failure (LLM timeout / parse / network). Callers MUST
        check ``failed`` before trusting ``doc_type`` — a ``failed=True``
        Classification with ``doc_type='incomplete'`` is **not** a
        content-incomplete signal, it is a Stage 1 malfunction.
      - ``uncertain`` is True iff the LLM ran but returned an ambiguous
        result (e.g. confidence below threshold or schema loosely matched).
        Distinct from ``failed`` — uncertain means "LLM said something,
        we don't trust it"; failed means "LLM didn't say anything useful".
      - ``traits`` is a free-form list of structural flags the LLM
        observed (e.g. ``['possible_collection', 'multi_author']``).
        Stage 4 reads ``traits`` to adjust its own structural authority.
      - ``evidence_summary`` records what structural coverage the
        classifier actually saw (h2_count, author_marker_count, …) so
        downstream stages can spot blind spots.
      - ``classifier_fingerprint`` is a stable hash of (template version,
        prompt_kind, model policy). Used by the source-skip gate to
        detect prompt upgrades.
    """

    __slots__ = (
        "doc_type", "confidence", "rationale",
        "failed", "error", "uncertain",
        "traits", "evidence_summary", "classifier_fingerprint",
    )

    def __init__(
        self,
        doc_type: str,
        confidence: float,
        rationale: str,
        *,
        failed: bool = False,
        error: str | None = None,
        uncertain: bool = False,
        traits: list[str] | None = None,
        evidence_summary: dict[str, Any] | None = None,
        classifier_fingerprint: str = "",
    ) -> None:
        if doc_type not in _VALID_DOC_TYPES:
            raise ValueError(f"doc_type must be one of {_VALID_DOC_TYPES}, got {doc_type!r}")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")
        self.doc_type = doc_type
        self.confidence = confidence
        self.rationale = rationale
        self.failed = failed
        self.error = error
        self.uncertain = uncertain
        self.traits = traits or []
        self.evidence_summary = evidence_summary or {}
        self.classifier_fingerprint = classifier_fingerprint

    def __repr__(self) -> str:
        return (
            f"Classification(doc_type={self.doc_type!r}, "
            f"confidence={self.confidence}, "
            f"failed={self.failed}, "
            f"uncertain={self.uncertain}, "
            f"traits={self.traits!r}, "
            f"rationale={self.rationale!r})"
        )

    def __eq__(self, other) -> bool:
        if not isinstance(other, Classification):
            return NotImplemented
        # ponytail: equality on the legacy fields only — the v4
        # metadata (failed, traits, …) is operational state, not
        # identity. Two Classifications with the same doc_type +
        # confidence + rationale are equal regardless of fingerprint.
        return (
            self.doc_type == other.doc_type
            and self.confidence == other.confidence
            and self.rationale == other.rationale
        )


async def classify_doc(
    content: str,
    *,
    filename_hint: str = "",
    llm: LLMClient,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> Classification:
    """Classify a raw source document using the LLM (P2: never raises).

    Workflow:
      1. Resolve the ``classify`` prompt (project > user > bundled).
      2. Build an evidence pack + compute coverage (h2 / author markers)
         so downstream stages can consume structural hints without
         re-scanning the full content.
      3. Render the user template with {evidence_pack}, {filename_hint}.
      4. Call the LLM up to ``max_retries`` times on schema / parse
         failures (D2: schema-validation retry).
      5. Return a Classification. On failure, set ``failed=True``,
         ``error=<last_error>``, ``doc_type='incomplete'`` (legacy
         compat — callers must check ``failed`` first).

    Note:
      P2: ``classify_doc`` returns a Classification in every failure
      mode. Callers do NOT need a try/except.
    """
    template = _resolve_classify_template(project_root)
    evidence_pack, evidence_summary = _build_evidence_pack(content)
    fingerprint = _compute_classifier_fingerprint(template)

    system_prompt, user_prompt = render_prompt(template, {
        "content": evidence_pack,
        "filename_hint": filename_hint,
        "content_limit": "4000",
    })

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind="classify",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=1024,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            return _payload_to_classification(
                payload,
                evidence_summary=evidence_summary,
                fingerprint=fingerprint,
            )
        except LLMResponseError as e:
            last_error = e
            log.info(
                "classify_doc: LLM response failed schema validation "
                "(attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:  # network / LLM provider / etc.
            last_error = e
            log.warning(
                "classify_doc: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue

    log.error(
        "classify_doc: all %d retries exhausted, returning FAILED INCOMPLETE. last_error=%r",
        max_retries, last_error,
    )
    # v4: technical failure is now explicit. ``failed=True`` + ``error=``
    # signal Stage 1 malfunction; ``doc_type='incomplete'`` is kept for
    # backward compat with the v2 DocType enum + existing tests, but
    # callers must check ``failed`` first.
    return Classification(
        doc_type="incomplete",
        confidence=0.0,
        rationale=f"stage1_failed_after_{max_retries}_retries: {last_error}",
        failed=True,
        error=str(last_error),
        evidence_summary=evidence_summary,
        classifier_fingerprint=fingerprint,
    )


def _payload_to_classification(
    payload: dict,
    *,
    evidence_summary: dict[str, Any] | None = None,
    fingerprint: str = "",
) -> Classification:
    """Convert a validated LLM JSON payload into a Classification.

    The output_schema (in classify.toml) ensures doc_type is in the
    enum and confidence is in [0, 1]. We still validate defensively
    in case the parser is bypassed (e.g. tests calling the helpers
    directly).
    """
    doc_type = payload["doc_type"]
    confidence = float(payload["confidence"])
    rationale = payload.get("rationale") or ""

    # ponytail: only parse the v4 metadata if the LLM actually emitted
    # them. Old prompts (and old tests) don't have these keys; we keep
    # the legacy call sites working by defaulting everything.
    traits_raw = payload.get("traits") or []
    if isinstance(traits_raw, list):
        traits = [str(t) for t in traits_raw if t]
    else:
        traits = []

    # Heuristic: low confidence → mark uncertain. The threshold is
    # deliberately generous so we don't drown Stage 4 in uncertain
    # signals; tune later when we have gold set coverage.
    uncertain = bool(payload.get("uncertain", confidence < 0.4))

    return Classification(
        doc_type=doc_type,
        confidence=confidence,
        rationale=str(rationale),
        failed=False,
        uncertain=uncertain,
        traits=traits,
        evidence_summary=evidence_summary,
        classifier_fingerprint=fingerprint,
    )


def _build_evidence_pack(content: str) -> tuple[str, dict[str, Any]]:
    """Build the evidence pack + summary.

    ponytail: HEAD/TAIL windows + structural counts. Future Stage 3
    will reuse this for its own evidence pack (F2 remediation), but
    Stage 1 only needs the counts in ``evidence_summary``.

    Returns (pack_text, evidence_summary_dict). pack_text is bounded by
    the prompt's content_limit (4000 chars); we never let it grow
    larger.
    """
    n = len(content)
    summary: dict[str, Any] = {
        "document_chars": n,
        "h2_count": len(_H2_RE.findall(content)),
        "author_marker_count": len(_AUTHOR_BYLINE_RE.findall(content)),
    }

    # HEAD-only evidence pack: Stage 1 classifies by intent, not by
    # tail evidence, so a single head window is sufficient. If the
    # document is very short, just send the whole thing.
    if n <= 4000:
        pack = content
    else:
        pack = content[:4000]

    return pack, summary


def _compute_classifier_fingerprint(template: Any) -> str:
    """Stable hash of the classify prompt + a static version tag.

    ponytail: hash the prompt kind + template version + a short body
    sample. The hash changes when the prompt template body changes, so
    source-skip can detect prompt upgrades.
    """
    version = getattr(template, "version", "") or ""
    body = getattr(template, "raw_body", "") or ""
    identity = f"classify|{version}|{body[:200]}"
    return "cls-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def _resolve_classify_template(project_root: Path | str | None) -> "PromptTemplate":
    """Resolve the classify prompt, raising RuntimeError if missing.

    We don't fall back — the v3 architecture requires every pipeline
    stage to have a working prompt. If bundled/classify.toml is
    missing, that's a deployment bug, not a recoverable runtime
    condition.

    ``project_root=None`` skips the D9 whitelist check (useful for
    tests and for callers that don't have a project to scope to).
    """
    try:
        return resolve("classify", project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 classify prompt is not available: {e}. "
            f"Check that prompts/builtin/classify.toml is installed."
        ) from e
