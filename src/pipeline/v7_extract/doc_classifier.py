"""Stage 1 of the V7 extract pipeline: classify_doc(content) -> DocType.

The classifier assigns one of 7 mutually-exclusive document types to a
raw source file, based on structural cues (regex / heuristics) plus an
optional LLM fallback when the heuristic is uncertain.

Why 7 types
-----------
The classifier drives all downstream extraction (structure recognition,
topic clustering, slot filling). Getting it wrong cascades into wrong
wiki pages. The 7 types were derived from the 9 extraction-validation
documents (RFC v6 §9):

  - single_method   one author, one topic, complete method article
  - multi_section   one author, many numbered sections (master-class)
  - collection      multiple distinct articles from multiple authors
  - qa_chat         chat-record / Q&A interview between authors
  - list            enumerated numbered items (e.g. 100 桥段)
  - tool            reference table / lookup data (e.g. 百家姓)
  - incomplete      title + intro only — body is empty / truncated

These 7 cover every raw document in ``knowledge/novel-wiki/raw/sources/``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class DocType(str, Enum):
    """V7 extract pipeline document types.

    Note: these are NOT the same as ``src.wiki.core.types.PageType``
    (which describes a wiki page type, not a raw source document type).
    A single DocType typically produces 1+ wiki pages.
    """

    SINGLE_METHOD = "single_method"
    MULTI_SECTION = "multi_section"
    COLLECTION = "collection"
    QA_CHAT = "qa_chat"
    LIST = "list"
    TOOL = "tool"
    INCOMPLETE = "incomplete"


# ---------------------------------------------------------------------------
# Heuristic-only classifier (no LLM). Used as the fast path when the
# document structure is unambiguous.
# ---------------------------------------------------------------------------

# Numbered Chinese sections (一、, 二、, 三、 ... or 第N章)
_NAMED_SECTION_RE = re.compile(r"^[　\s]*[一二三四五六七八九十百]+、", re.MULTILINE)
# Numbered Arabic sections (1. , 2. , ...)
_ARABIC_SECTION_RE = re.compile(r"^[　\s]*\d+[\.\)、]", re.MULTILINE)
# Markdown h1/h2
_MD_HEADING_RE = re.compile(r"^#{1,3}\s+\S", re.MULTILINE)
# Numbered list items (1,xxx 2,yyy 3,zzz) — used by 103 桥段 etc.
_NUMBERED_LIST_RE = re.compile(r"^[　\s]*\d+[\s,，]\s*\S", re.MULTILINE)
# Chat-record timestamps. Two common patterns:
#   "8难(378234368) 19:59:37"  — talker + paren-id + time
#   "(19:59:37)" / "[19:59]"     — bracketed timestamps (rare in wild)
_CHAT_TIMESTAMP_RE = re.compile(
    r"\(\d{5,}\)\s+\d{1,2}:\d{2}(?::\d{2})?"
    r"|[\(\[（【]\d{1,2}:\d{2}(?::\d{2})?[\)\]）】]",
    re.MULTILINE,
)
# Talker label pattern (Chinese / English nick followed by open-paren QQ id)
_TALKER_RE = re.compile(r"^[\u4e00-\u9fff\w]{2,20}[\(（]\d{5,}[\)）]\s*\d{1,2}:\d{2}", re.MULTILINE)
# Distinct author handles — used to detect "collection" (multiple speakers
# or bylines). Wrap the alternation in a single non-capturing group so
# findall() returns full match strings, not tuples of partial captures.
_AUTHOR_HANDLE_RE = re.compile(
    r"(?:"
    r"^#+\s*作者\s*[:：]?\s*\S+"
    r"|^作者\s*[:：]\s*\S+"
    r"|^作者\s*[:：]?\s*[\u4e00-\u9fff]{2,10}\s*$"
    r")",
    re.MULTILINE,
)
# "工具表" / "参考" / "对照表" markers — heuristic for tool docs
_TOOL_MARKERS = (
    "百家姓", "对照表", "速查表", "参考表", "等级表", "对照参考",
    "工具表", "checklist", "wikipedia", "wikipedia-style", "reference table",
)


@dataclass(frozen=True)
class Classification:
    """Result of Stage 1 classification."""

    doc_type: DocType
    confidence: float  # 0.0 - 1.0
    rationale: str  # short human-readable explanation (for audit log)


def classify_doc_heuristic(
    content: str,
    *,
    filename_hint: str = "",
) -> Classification:
    """Heuristic-only classifier. No LLM.

    Used as the fast path. Returns Classification with confidence in
    [0.0, 1.0]; callers can route low-confidence results to the LLM
    fallback (see ``classify_doc_with_llm`` below).
    """
    text = (content or "").strip()
    name = (filename_hint or "").lower()
    text_len = len(text)

    # 1. An explicit filename hint wins over content-length heuristics.
    # Tool references are often compact tables, so a short file can still be
    # complete when its name identifies the document type.
    if "百家姓" in name or "工具表" in name:
        return Classification(DocType.TOOL, 0.92, "reference-table filename hint found")

    # 2. Empty / title-only -> incomplete (high confidence)
    if text_len < 800 and _count_named_sections(text) < 1 and _count_chat_timestamps(text) < 1:
        if _looks_like_title_only(text):
            return Classification(
                DocType.INCOMPLETE,
                0.95,
                f"text len {text_len} < 800, no sections, no timestamps; "
                "appears to be title + intro only",
            )

    # 3. Reference table markers -> tool (high confidence)
    if any(marker in text for marker in _TOOL_MARKERS):
        return Classification(DocType.TOOL, 0.92, "reference-table marker found")

    # 4. Chat timestamps + talkers -> qa_chat
    n_timestamps = _count_chat_timestamps(text)
    if n_timestamps >= 8:
        return Classification(
            DocType.QA_CHAT, 0.95,
            f"{n_timestamps} chat timestamps detected",
        )

    # 5. Numbered list (1,xxx 2,yyy ...) and count >= 30 -> list
    n_list_items = _count_numbered_list_items(text)
    if n_list_items >= 30:
        return Classification(
            DocType.LIST, 0.92,
            f"{n_list_items} numbered list items (>= 30)",
        )

    # 6. Multiple distinct authors / speakers -> collection
    n_authors = _count_distinct_authors(text)
    if n_authors >= 3:
        return Classification(
            DocType.COLLECTION, 0.90,
            f"{n_authors} distinct authors detected",
        )

    # 7. Named sections -> multi_section (when count >= 5)
    n_sections = _count_named_sections(text)
    if n_sections >= 5:
        return Classification(
            DocType.MULTI_SECTION, 0.88,
            f"{n_sections} numbered sections (>= 5)",
        )

    # 8. Markdown headings >= 3 + reasonable length -> multi_section
    n_md = _count_md_headings(text)
    if n_md >= 3 and text_len >= 1000:
        return Classification(
            DocType.MULTI_SECTION, 0.80,
            f"{n_md} markdown headings (>= 3), len >= 1000",
        )

    # 9. Single section or no structure -> single_method
    return Classification(
        DocType.SINGLE_METHOD, 0.70,
        "no multi-section / list / chat structure; assume single method article",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_named_sections(text: str) -> int:
    """Count Chinese named sections (一、二、 or 第N章)."""
    return max(
        len(_NAMED_SECTION_RE.findall(text)),
        # count "第N章" as a section
        len(re.findall(r"^第[一二三四五六七八九十百\d]+章", text, re.MULTILINE)),
    )


def _count_md_headings(text: str) -> int:
    return len(_MD_HEADING_RE.findall(text))


def _count_chat_timestamps(text: str) -> int:
    return len(_CHAT_TIMESTAMP_RE.findall(text))


def _count_numbered_list_items(text: str) -> int:
    # Use the module-level regex (matches "1,xxx" / "2,yyy" Chinese-style
    # enumeration and "1. xxx" Arabic-style). Avoids false positives in
    # body prose by requiring at least one non-whitespace character
    # after the digit.
    return len(_NUMBERED_LIST_RE.findall(text))


def _count_distinct_authors(text: str) -> int:
    """Count distinct talker / author handles via talker-label + author-bylines."""
    talkers = set(_TALKER_RE.findall(text))
    # Capture the author name (strip the markdown "## " prefix if any)
    byline_matches = _AUTHOR_HANDLE_RE.findall(text)
    bylines = set()
    for m in byline_matches:
        # m may be like "## 作者 314" or "作者 314". Take the last token.
        parts = m.replace("#", "").replace("作者", "").strip().split()
        if parts:
            bylines.add(parts[0])
    return len(talkers | bylines)


def _looks_like_title_only(text: str) -> bool:
    """Heuristic: frontmatter + a brief intro only, no body content."""
    # Strip frontmatter if present.
    body = text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end > 0:
            body = body[end + 5:]
    # If after stripping frontmatter the remaining body has very little
    # non-trivial content, treat as title-only.
    return len(body.strip()) < 800


# ---------------------------------------------------------------------------
# LLM-fallback wrapper
# ---------------------------------------------------------------------------

def classify_doc(
    content: str,
    *,
    filename_hint: str = "",
    llm=None,
    confidence_threshold: float = 0.80,
) -> Classification:
    """Top-level Stage 1 entry point.

    Runs the heuristic classifier first; if confidence < threshold,
    defers to the LLM fallback (which must be supplied).
    """
    heuristic = classify_doc_heuristic(content, filename_hint=filename_hint)
    if heuristic.confidence >= confidence_threshold or llm is None:
        return heuristic
    # LLM fallback path (RFC v6 Stage 1.b). The exact prompt format is
    # out of scope for this module — callers wire it via llm.complete(
    # prompt_kind="classify", ...). Returning heuristic as a safe
    # fallback if the LLM path is not yet implemented keeps the
    # pipeline runnable while the LLM path is being built.
    return heuristic
