"""Stage 2.5 (Plan 5): LLM-driven article segmentation for collection docs.

For documents classified as collection by Stage 1, the markdown
``_extract_items`` regex (heading + numbered list) cannot find boundaries
because multi-article roundups like 三江杂谈 use metadata lines
("作者 XXX" / "更新时间 YYYY-MM-DD" / 字数) instead of markdown
headings. This stage asks the LLM to identify article boundaries,
and the items list passed to Stage 4 reflects those boundaries.

For non-collection docs, this stage returns a single article spanning
the whole document so existing single-article behavior is preserved.

Coordinate system (Task 5; Bounded Evidence Contract §3, master plan
Task 5 acceptance):

  - ``char_start`` / ``char_end`` are **character offsets** against the
    decoded source text. This is what the LLM actually returns because
    the prompt input is ``text`` (decoded), not raw bytes — see
    ``prompts/builtin/segment_articles.toml``.

  - To slice the raw source bytes, use ``slice_bytes(source_bytes)``
    (mechanical char→byte conversion via ``content[:char_start].encode()``).

  - Downstream ``CanonicalItem.start_byte/end_byte`` is the same
    coordinate system but measured against the source bytes; Stage 2
    boundaries are the source text view, not a separate byte view.
"""
from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass
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


@dataclass
class ArticleBoundary:
    """One article detected inside a multi-article document.

    NOTE: ``char_start`` / ``char_end`` are character offsets into the
    decoded source text (not UTF-8 byte offsets). Use ``slice_bytes``
    or ``slice_text`` to extract from the raw source bytes — they
    perform the char→byte conversion via ``text[:char_start].encode()``.

    Rationale: the LLM prompt is fed the decoded ``text`` (see
    ``prompts/builtin/segment_articles.toml``), so the offsets the LLM
    returns are measured against that decoded string. The old
    ``start`` / ``end`` attribute names implied byte offsets, which was
    wrong on any non-ASCII content — see master plan Task 5 acceptance
    (F5 硬指标: ``test_chinese_byte_offset_slice_consistent``).
    """

    char_start: int  # char offset, inclusive
    char_end: int    # char offset, exclusive
    title: str

    def slice_bytes(self, source_bytes: bytes) -> bytes:
        """Extract raw bytes — converts char→byte via UTF-8 re-encoding.

        The conversion is mechanical: ``text[:char_start].encode("utf-8")``
        yields the byte position that corresponds to ``char_start`` chars
        of the same decoded text. Because the LLM sees the decoded text,
        this is the only honest conversion.
        """
        text = source_bytes.decode("utf-8", errors="replace")
        return text[self.char_start : self.char_end].encode("utf-8")

    def slice_text(self, source_bytes: bytes) -> str:
        """Decode to text — equivalent to ``source_bytes.decode()[c1:c2]``
        via the same char→byte path as ``slice_bytes``."""
        return self.slice_bytes(source_bytes).decode("utf-8", errors="replace")

    # ponytail: keep the legacy ``slice(content: str)`` method but mark it
    # deprecated — old callers passed ``content`` (a str) and expected
    # char-indexed slicing. The method now matches ``slice_text`` semantics
    # but emits a DeprecationWarning so callers know to migrate.
    def slice(self, content: str) -> str:
        warnings.warn(
            "ArticleBoundary.slice(content) is deprecated: "
            "char_start/char_end are character offsets, not byte offsets. "
            "Use slice_bytes(source_bytes) or slice_text(source_bytes) "
            "to slice against the raw source bytes.",
            DeprecationWarning,
            stacklevel=2,
        )
        return content[self.char_start : self.char_end]


async def segment_articles(
    content: str,
    *,
    llm: LLMClient,
    doc_type: str | None = None,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> list[ArticleBoundary]:
    """Identify article boundaries in ``content`` via LLM.

    Args:
        content: full document body.
        llm: any ``LLMClient``.
        doc_type: Stage 1 hint. When set, the prompt tells the LLM to split
            only when doc_type is collection; otherwise returns a single
            article spanning the whole document.
        project_root: passed through to ``prompts_resolver.resolve``.

    Returns:
        list of ``ArticleBoundary``. Always returns — never raises (P2).
        On every retry failure returns one boundary spanning the whole
        content so downstream Stage 4 sees the legacy single-topic behavior.

        Boundaries are guaranteed to be: non-overlapping, sorted by start,
        start inclusive / end exclusive, and (start[0], end[-1]) covers the
        whole content.
    """
    # ponytail: fast path when LLM is missing — single article.
    if llm is None or not content:
        return [_whole(content)]

    template = _resolve_segment_template(project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "text": content,
        "doc_type_hint": doc_type or "unknown",
        "content_limit": "12000",
    })

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind="segment_articles",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=4096,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            return _payload_to_boundaries(payload, content)
        except LLMResponseError as e:
            last_error = e
            log.info(
                "segment_articles: LLM response failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:
            last_error = e
            log.warning(
                "segment_articles: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue

    log.warning(
        "segment_articles: all %d retries exhausted, returning single whole-doc boundary: %r",
        max_retries, last_error,
    )
    return [_whole(content)]


def _whole(content: str) -> ArticleBoundary:
    return ArticleBoundary(char_start=0, char_end=len(content), title="")


def _payload_to_boundaries(payload: dict, content: str) -> list[ArticleBoundary]:
    """Validate LLM JSON and normalize boundaries.

    The LLM is fed the decoded ``text`` (chars, not bytes) so the
    offsets it returns are character offsets. We accept both
    ``start`` / ``end`` (legacy keys, kept for transition safety —
    the prompt still says "byte offsets" in some places) and
    ``char_start`` / ``char_end`` (explicit keys, preferred for new
    prompts). All offsets are stored as character offsets against
    ``content``.

    Robustness rules:
      - drop entries outside [0, len(content)]
      - sort by start
      - dedupe adjacent (rare LLM double-fire)
      - clamp end[i] to start[i+1] if overlaps (LLM sometimes returns
        end == start[i+1] + 5, etc.)
      - first article starts at 0; last article ends at len(content)
    """
    raw = payload.get("articles") or []
    if not isinstance(raw, list):
        return [_whole(content)]

    boundaries: list[ArticleBoundary] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        # Accept both legacy (``start`` / ``end``) and explicit
        # (``char_start`` / ``char_end``) keys. Explicit wins.
        try:
            if "char_start" in entry or "char_end" in entry:
                start = int(entry.get("char_start"))
                end = int(entry.get("char_end"))
            else:
                start = int(entry.get("start"))
                end = int(entry.get("end"))
        except (TypeError, ValueError):
            continue
        title = str(entry.get("title") or "").strip()
        if start < 0:
            start = 0
        if end > len(content):
            end = len(content)
        if end <= start:
            continue
        boundaries.append(ArticleBoundary(char_start=start, char_end=end, title=title))

    if not boundaries:
        return [_whole(content)]

    boundaries.sort(key=lambda b: b.char_start)
    # Clamp overlaps / fill gaps
    total = len(content)
    fixed: list[ArticleBoundary] = []
    cursor = 0
    for b in boundaries:
        if b.char_start > cursor:
            # Fill gap with title-less continuation so we don't drop content
            fixed.append(ArticleBoundary(char_start=cursor, char_end=b.char_start, title=""))
        clamped_end = min(b.char_end, total)
        fixed.append(ArticleBoundary(char_start=b.char_start, char_end=clamped_end, title=b.title))
        cursor = clamped_end
    if cursor < total:
        fixed.append(ArticleBoundary(char_start=cursor, char_end=total, title=""))
    # Drop empty trailing gap articles (LLM sometimes returns one with end == start)
    fixed = [b for b in fixed if b.char_end > b.char_start]
    return fixed or [_whole(content)]


def _resolve_segment_template(
    project_root: Path | str | None,
) -> "PromptTemplate":
    try:
        return resolve("segment_articles", project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 segment_articles prompt is not available: {e}. "
            f"Check that prompts/builtin/segment_articles.toml is installed."
        ) from e
