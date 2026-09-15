"""Stage 1 of the V7 extract pipeline: classify_doc(content) -> Classification.

v3 (plan 2026-09-15): pure-LLM classification. Heuristics deleted (T2.1).
The classifier delegates to the prompts/ sub-package — the prompt text,
output schema, retry policy, and three-layer override all live in
``prompts/builtin/classify.toml`` (or a project/user override).

Why we removed the heuristic
----------------------------
v2 used regex + length heuristics first, with LLM as fallback. The
heuristic could not recognise semantic intent (a 5-stage article was
treated like a generic single_method doc). spot-check accuracy stalled
at 10% because the heuristic was the gatekeeper.

v3 removes the heuristic entirely. Stage 1 is now a pure async LLM
call. P2 (``failure semantics``) guarantees we never crash the pipeline
on bad LLM output: any error is folded into a Classification with
``doc_type=INCOMPLETE, confidence=0.0`` and the source is recorded in
the failure queue.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

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


class Classification:
    """Result of Stage 1.

    v3 contract:
      - doc_type is always one of the 7 known DocType strings
      - confidence is in [0.0, 1.0]; 0.0 means "the LLM failed, we
        don't know what type this is" — the caller is expected to
        route this to the failure queue (P2)
    """

    __slots__ = ("doc_type", "confidence", "rationale")

    def __init__(
        self,
        doc_type: str,
        confidence: float,
        rationale: str,
    ) -> None:
        if doc_type not in _VALID_DOC_TYPES:
            raise ValueError(f"doc_type must be one of {_VALID_DOC_TYPES}, got {doc_type!r}")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")
        self.doc_type = doc_type
        self.confidence = confidence
        self.rationale = rationale

    def __repr__(self) -> str:
        return (
            f"Classification(doc_type={self.doc_type!r}, "
            f"confidence={self.confidence}, rationale={self.rationale!r})"
        )

    def __eq__(self, other) -> bool:
        if not isinstance(other, Classification):
            return NotImplemented
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
      2. Render the user template with {content}, {filename_hint},
         {content_limit}.
      3. Call the LLM up to ``max_retries`` times on schema / parse
         failures (D2: schema-validation retry).
      4. Return a Classification with doc_type=INCOMPLETE,
         confidence=0.0 if the LLM failed every retry.

    Note:
      P2: ``classify_doc`` returns a Classification in every failure
      mode. Callers do NOT need a try/except.
    """
    template = _resolve_classify_template(project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "content": content,
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
            return _payload_to_classification(payload)
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
        "classify_doc: all %d retries exhausted, returning INCOMPLETE. last_error=%r",
        max_retries, last_error,
    )
    return Classification(
        doc_type="incomplete",
        confidence=0.0,
        rationale=f"stage1_failed_after_{max_retries}_retries: {last_error}",
    )


def _payload_to_classification(payload: dict) -> Classification:
    """Convert a validated LLM JSON payload into a Classification.

    The output_schema (in classify.toml) ensures doc_type is in the
    enum and confidence is in [0, 1]. We still validate defensively
    in case the parser is bypassed (e.g. tests calling the helpers
    directly).
    """
    doc_type = payload["doc_type"]
    confidence = float(payload["confidence"])
    rationale = payload.get("rationale") or ""
    return Classification(
        doc_type=doc_type,
        confidence=confidence,
        rationale=str(rationale),
    )


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
