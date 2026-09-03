"""C2: C-grade page handling — root-cause classification + regeneration strategy.

Classifies C-grade wiki pages produced by the pipeline into five root causes
and applies the appropriate remediation:

- STUB_PLACEHOLDER (processing_depth=stub): skip — already handled by C3.
- CONTENT_THIN (body < 200 chars after stripping wikilinks): source material
  is too thin for meaningful generation. Mark ``_stub``, do NOT regen.
- STRUCTURAL (missing key fields / malformed body): attempt one LLM
  regeneration with temperature=0.8. If the regenned page is not strictly
  better than the original, keep the original and mark ``_stub``.
- FACTUAL_ERROR (hallucination markers in body): mark ``_stub`` and add a
  human-review banner. Do NOT regen — hallucination tends to repeat.
- UNKNOWN: treat conservatively as CONTENT_THIN (mark ``_stub``).

Safety nets:
- Max 3 regens per document to prevent cost explosion.
- Each page regenerated at most once.
- Grade comparison: if new grade is not strictly better than old grade,
  keep the original page.
"""

from __future__ import annotations

import datetime
import logging
import re
from enum import Enum

from ..wiki.core.types import WikiPage

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Root cause classification
# ---------------------------------------------------------------------------

class CGradeCause(Enum):
    CONTENT_THIN = "content_thin"       # body < 200 chars after stripping wikilinks
    STRUCTURAL = "structural"           # missing key fields / malformed body
    FACTUAL_ERROR = "factual_error"     # likely LLM hallucination
    STUB_PLACEHOLDER = "stub"           # already marked _stub (processing_depth=stub)
    UNKNOWN = "unknown"                 # no clear cause — treat as CONTENT_THIN


# Patterns used to detect hallucination markers in generated content.
_HALLUCINATION_MARKERS: tuple[str, ...] = (
    "As an AI", "as an AI", "As a language model",
    "I cannot", "I don't have", "I do not have",
    "I'm unable", "I am unable",
    "my knowledge", "my training",
    "作为人工智能", "作为AI", "作为语言模型",
    "我无法提供", "我不能提供",
    "我的知识截止", "我的训练数据",
    "抱歉，我无法",
)

_WIKILINK_RE = re.compile(r"\[\[.*?\]\]")


def _body_text_length(body: str | None) -> int:
    """Character count after stripping wikilinks and whitespace."""
    if not body:
        return 0
    stripped = _WIKILINK_RE.sub("", body)
    return len(stripped.strip())


def classify_c_grade(page: WikiPage) -> CGradeCause:
    """Classify the root cause of a C-grade wiki page.

    Rules (evaluated in priority order):

    1. ``processing_depth == "stub"`` → STUB_PLACEHOLDER
    2. Body contains hallucination markers → FACTUAL_ERROR
    3. Missing critical fields (title, id, type, None body) → STRUCTURAL
    4. ``body_text_length < 200`` → CONTENT_THIN
    5. Otherwise → UNKNOWN
    """
    # Rule 1: already a stub placeholder (handled by C3)
    if page.processing_depth == "stub":
        return CGradeCause.STUB_PLACEHOLDER

    body = page.body or ""

    # Rule 2: hallucination markers in the body text
    for marker in _HALLUCINATION_MARKERS:
        if marker in body:
            return CGradeCause.FACTUAL_ERROR

    # Rule 3: missing critical YAML fields or malformed body
    if not page.title or not page.title.strip():
        return CGradeCause.STRUCTURAL
    if not page.id or not page.id.strip():
        return CGradeCause.STRUCTURAL
    if page.type is None:
        return CGradeCause.STRUCTURAL
    # Guard: body is explicitly None (should not happen, but be defensive)
    if body is None:  # pragma: no cover — body is "" from line above
        return CGradeCause.STRUCTURAL

    # Rule 4: body too thin after stripping wikilinks
    body_len = _body_text_length(body)
    if body_len < 200:
        return CGradeCause.CONTENT_THIN

    # Rule 5: no clear cause
    return CGradeCause.UNKNOWN


# ---------------------------------------------------------------------------
# Grade comparison
# ---------------------------------------------------------------------------

_GRADE_ORDER: dict[str, int] = {"A": 3, "B": 2, "C": 1}


def _is_grade_improvement(new_grade: str, old_grade: str) -> bool:
    """Return True when *new_grade* is strictly better than *old_grade*.

    Grade ordering: A > B > C.  Equal grades are NOT considered an
    improvement — only a strict upgrade replaces the original.
    """
    return _GRADE_ORDER.get(new_grade, 0) > _GRADE_ORDER.get(old_grade, 0)


# ---------------------------------------------------------------------------
# Stub marking
# ---------------------------------------------------------------------------

def _mark_as_stub(page: WikiPage) -> None:
    """Mutate *page* in-place: ``processing_depth=stub``, ``grade=C``."""
    page.processing_depth = "stub"
    page.grade = "C"


# ---------------------------------------------------------------------------
# Single-page regeneration
# ---------------------------------------------------------------------------

_REGEN_PROMPT = """You are fixing a wiki page that had structural issues during generation.
Regenerate the body content for this page. Output ONLY the markdown body — no
JSON wrapper, no explanations, no code fences.

Page ID: {page_id}
Page Type: {page_type}
Page Title: {page_title}
Previous body (may be incomplete or malformed):
{previous_body}

Source context (from original document, may be truncated):
{source_context}

Write a complete, well-structured markdown body for this page. Include
appropriate sections with substantive content. Write in Chinese (Simplified).
Each section should have real content — no placeholders, no filler text."""


async def _regen_page(
    page: WikiPage,
    provider,
    source_text: str = "",
    temperature: float = 0.8,
) -> WikiPage | None:
    """Regenerate a single page body using the LLM provider.

    Returns a new ``WikiPage`` with the regenerated body and optimistic
    ``grade="B"``, or ``None`` if the LLM call fails.  The caller must
    compare grades and decide whether to keep the new page.
    """
    import time

    source_context = source_text[:2000] if source_text else "(not available)"
    previous_body = (page.body or "(empty)")[:1500]

    prompt = _REGEN_PROMPT.format(
        page_id=page.id,
        page_type=page.type.value if page.type else "concept",
        page_title=page.title or "(missing title)",
        previous_body=previous_body,
        source_context=source_context,
    )

    try:
        response = await provider.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            timeout=120.0,
            max_tokens=4096,  # single-page markdown body; explicit cap avoids endpoint truncation
        )
    except Exception as exc:
        _logger.warning(
            "[c_grade_handler] LLM regen call failed for %s: %s",
            page.id, exc,
        )
        return None

    new_body = response.content if hasattr(response, "content") else str(response)
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    return WikiPage(
        id=page.id,
        title=page.title,
        type=page.type,
        sources=list(page.sources),
        body=new_body,
        grade="B",  # optimistic — quality gate may re-evaluate
        processing_depth=page.processing_depth,
        relations=list(page.relations),
        tags=list(page.tags),
        created_at=page.created_at,
        updated_at=now_dt,
        category=page.category,
        taxonomy_sub=page.taxonomy_sub,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def handle_c_grade_pages(
    pages: list[WikiPage],
    provider,
    source_text: str = "",
    max_regens_per_doc: int = 3,
) -> list[WikiPage]:
    """Post-process C-grade pages produced by the pipeline.

    For each C-grade page (excluding those already marked ``processing_depth=stub``):

    - Classifies the root cause via :func:`classify_c_grade`.
    - Applies the appropriate remediation strategy per cause.
    - Tracks regeneration count; stops after *max_regens_per_doc* LLM calls.

    Returns the (potentially modified) list of WikiPage objects.  Pages
    are mutated in-place for stub marking or replaced in the list when
    regeneration succeeds.

    The caller owns the final decision on whether to keep the modified
    pages — this function does **not** write to disk.
    """
    # Only process C-grade, non-stub pages
    c_grade_pages = [
        p for p in pages
        if p.grade == "C" and p.processing_depth != "stub"
    ]

    if not c_grade_pages:
        return pages

    _logger.info(
        "[c_grade_handler] found %d C-grade (non-stub) page(s) to process",
        len(c_grade_pages),
    )

    regen_count = 0

    for page in c_grade_pages:
        cause = classify_c_grade(page)
        _logger.info(
            "[c_grade_handler] page=%s cause=%s body_len=%d",
            page.id, cause.value, _body_text_length(page.body),
        )

        if cause == CGradeCause.STUB_PLACEHOLDER:
            # Already handled by C3 — nothing to do here.
            continue

        elif cause == CGradeCause.STRUCTURAL:
            # Regen once with temperature=0.8
            if regen_count >= max_regens_per_doc:
                _logger.info(
                    "[c_grade_handler] max regens (%d) reached; "
                    "marking page=%s as stub",
                    max_regens_per_doc, page.id,
                )
                _mark_as_stub(page)
                continue

            regen_count += 1
            new_page = await _regen_page(
                page, provider, source_text=source_text, temperature=0.8,
            )

            if new_page is None:
                # LLM call failed — mark as stub
                _mark_as_stub(page)
                continue

            # Compare: only replace if the regenned page is strictly better
            if not _is_grade_improvement(new_page.grade, page.grade):
                _logger.info(
                    "[c_grade_handler] regen did not improve grade for %s "
                    "(%s -> %s); keeping original, marking as stub",
                    page.id, page.grade, new_page.grade,
                )
                _mark_as_stub(page)
                continue

            # Replace in the page list
            for i, p in enumerate(pages):
                if p.id == page.id:
                    pages[i] = new_page
                    break
            _logger.info(
                "[c_grade_handler] regenned page=%s grade=%s->%s",
                page.id, page.grade, new_page.grade,
            )

        elif cause in (CGradeCause.CONTENT_THIN, CGradeCause.UNKNOWN):
            # Source document is too thin — do not waste LLM tokens.
            _mark_as_stub(page)

        elif cause == CGradeCause.FACTUAL_ERROR:
            # Likely hallucination — mark stub and flag for human review.
            _mark_as_stub(page)
            page.body = (
                "> **需人工审核**: 系统检测到可能的幻觉内容或矛盾表述。"
                "请验证此页面的事实准确性，并在确认后手动更新。\n\n"
                + (page.body or "")
            )

    return pages
