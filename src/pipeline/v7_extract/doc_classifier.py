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

import asyncio
import json
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
# Numbered list items. Matches all common separators (1,xxx / 1. xxx / 1)xxx / 1、xxx / 第N条).
# Requires the number to start at line start (with optional indent / full-width space).
_NUMBERED_LIST_RE = re.compile(
    r"^[　\s]*(?:\d+[\s,，\.、)]|第[一二三四五六七八九十百\d]+条)"
    r"\s*\S",
    re.MULTILINE,
)
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
# Speaker label without timestamp (e.g. "主持人：", "嘉宾："). Requires the
# Chinese full-width colon "：" to avoid false positives on prose.
# Allows 2-20 Chinese chars / word chars before the colon.
_SPEAKER_LINE_RE = re.compile(
    r"^[\u4e00-\u9fff\w]{2,20}：",
    re.MULTILINE,
)
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
# Explicit "body missing" markers that signal incomplete docs.
_BODY_MISSING_MARKERS = (
    "正文内容缺失", "正文缺失", "内容缺失",
    "仅引言", "仅有引言", "仅有简介", "正文待补",
    "[body missing]", "[content missing]", "[to be continued]",
)
# "工具表" / "参考" / "对照表" markers — heuristic for tool docs
_TOOL_MARKERS = (
    "百家姓", "对照表", "速查表", "参考表", "等级表", "对照参考",
    "工具表", "checklist", "wikipedia", "wikipedia-style", "reference table",
)
# Explicit dialogue-record labels. Title line that begins with one of
# these markers + a colon-free body strongly implies qa_chat.
_DIALOGUE_LABELS = (
    "讲课记录", "聊天记录", "问答实录", "访谈记录", "对话记录",
    "讲课实录", "访谈实录", "聊天实录", "对话实录", "问答记录",
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

    # 2. Empty / title-only -> incomplete (high confidence). Use a
    # conservative threshold (200 chars) AND require no body substance:
    # frontmatter + a single short intro, with no structural cues at all.
    # Real short articles with definitions / examples still produce at least
    # one of: chat timestamp, numbered list, named section, speaker line,
    # explicit dialogue label, multi-paragraph body.
    if text_len < 800:
        n_named_sections = _count_named_sections(text)
        n_list_items = _count_numbered_list_items(text)
        n_speakers = _count_speaker_lines(text)
        n_timestamps = _count_chat_timestamps(text)
        has_dialogue_label = _has_dialogue_label(text)
        if (
            n_named_sections < 1
            and n_list_items < 1
            and n_timestamps < 1
            and n_speakers < 1
            and not has_dialogue_label
        ):
            if _looks_like_title_only(text):
                return Classification(
                    DocType.INCOMPLETE,
                    0.95,
                    f"text len {text_len} < 800, no sections, no timestamps, "
                    "no speaker lines, no dialogue label; "
                    "appears to be title + intro only",
                )

    # 3. Reference table markers -> tool (high confidence)
    if any(marker in text for marker in _TOOL_MARKERS):
        return Classification(DocType.TOOL, 0.92, "reference-table marker found")

    # 3b. Explicit "body missing" markers -> incomplete (high confidence).
    if any(marker in text for marker in _BODY_MISSING_MARKERS):
        return Classification(
            DocType.INCOMPLETE, 0.95,
            "explicit body-missing marker found",
        )

    # 4. Chat timestamps + talkers -> qa_chat
    n_timestamps = _count_chat_timestamps(text)
    if n_timestamps >= 8:
        return Classification(
            DocType.QA_CHAT, 0.95,
            f"{n_timestamps} chat timestamps detected",
        )

    # 4b. Explicit dialogue-record label -> qa_chat (works on short docs).
    if _has_dialogue_label(text):
        return Classification(
            DocType.QA_CHAT, 0.93,
            "explicit dialogue-record label found",
        )

    # 4c. Repeated speaker lines (>= 4 distinct speaker labels OR >= 6 total
    # speaker lines spanning >= 2 distinct speakers) -> qa_chat even
    # without timestamps. The fixture uses 主持人 + 嘉宾 (2 distinct,
    # 6 turns), which the distinct-only rule misses.
    n_speaker_lines = len(_SPEAKER_LINE_RE.findall(text))
    n_speakers = _count_speaker_lines(text)
    if n_speakers >= 4 or (n_speakers >= 2 and n_speaker_lines >= 6):
        return Classification(
            DocType.QA_CHAT, 0.88,
            f"{n_speaker_lines} speaker lines / {n_speakers} distinct speakers",
        )

    # 5. Numbered list — 1,xxx / 1. xxx / 1)xxx / 1、xxx / 第N条 — count >= 8 -> list.
    # The lower threshold (was 30) catches documents like "20 个签约条件"
    # which were previously misclassified as single_method.
    n_list_items = _count_numbered_list_items(text)
    if n_list_items >= 8:
        return Classification(
            DocType.LIST, 0.92,
            f"{n_list_items} numbered list items (>= 8)",
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
    # Use the module-level regex — matches "1、xxx" / "1. xxx" / "1) xxx"
    # / "1, xxx" / "第N条 xxx". Requires at least one non-whitespace
    # character after the number/separator to avoid body-prose false
    # positives.
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


def _count_speaker_lines(text: str) -> int:
    """Count speaker labels (e.g. "主持人：", "嘉宾：").

    Distinct speaker count, not raw line count — a single speaker
    monopolising a transcript shouldn't trigger qa_chat.
    """
    matches = _SPEAKER_LINE_RE.findall(text)
    return len({m for m in matches})


def _has_dialogue_label(text: str) -> bool:
    """Detect an explicit dialogue-record title (讲课记录 etc.) near the top
    of the document. We check only the first 400 chars to avoid matching
    prose that happens to contain the phrase."""
    head = text[:400]
    return any(label in head for label in _DIALOGUE_LABELS)


def _looks_like_title_only(text: str) -> bool:
    """Heuristic: frontmatter + a brief intro only, no body content.

    Conservative: requires the body (after stripping frontmatter) to be
    very short (< 200 chars) AND have at most 2 paragraph breaks. Short
    articles with definitions / examples / suggestions quickly grow
    past these limits and remain non-incomplete.
    """
    body = text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end > 0:
            body = body[end + 5:]
    body = body.strip()
    if not body:
        return True
    if len(body) >= 200:
        return False
    # <= 2 paragraph breaks and short -> title-only.
    paragraph_breaks = sum(1 for _ in re.finditer(r"\n\s*\n", body))
    return paragraph_breaks <= 1


# ---------------------------------------------------------------------------
# LLM-fallback wrapper
# ---------------------------------------------------------------------------

async def _invoke_llm_classifier(llm, content: str, filename_hint: str) -> Classification | None:
    """Run the LLM and parse its JSON response. Returns None on any
    parse/validation failure so the caller can fall back to the
    heuristic result.
    """
    user_prompt = _build_classify_prompt(content, filename_hint)
    try:
        raw = await llm.complete(
            prompt_kind="classify",
            user_prompt=user_prompt,
            system_prompt=(
                "You are a V7 document classifier. Reply with a single JSON "
                "object and nothing else. The JSON must have keys "
                '`doc_type` (one of: single_method, multi_section, '
                "collection, qa_chat, list, tool, incomplete), "
                "`confidence` (a float in [0, 1]), and "
                '`rationale` (a short string).'
            ),
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    doc_type = payload.get("doc_type")
    confidence = payload.get("confidence")
    rationale = payload.get("rationale")
    if not isinstance(doc_type, str):
        return None
    try:
        doc_type_enum = DocType(doc_type)
    except ValueError:
        return None
    if not isinstance(confidence, (int, float)):
        return None
    confidence_f = float(confidence)
    if confidence_f < 0.0 or confidence_f > 1.0:
        return None
    if math.isnan(confidence_f) or math.isinf(confidence_f):
        return None
    return Classification(
        doc_type=doc_type_enum,
        confidence=confidence_f,
        rationale=str(rationale) if rationale is not None else "llm classification",
    )


def _build_classify_prompt(content: str, filename_hint: str) -> str:
    """Build the prompt the LLM sees for Stage 1 classification."""
    head = content[:4000]
    file_hint = f"\nFilename hint: {filename_hint}" if filename_hint else ""
    return (
        "Classify this document into exactly one of the following types:\n"
        "  - single_method: one author, one topic, complete method article\n"
        "  - multi_section: one author, many numbered sections (master-class)\n"
        "  - collection: multiple distinct articles from multiple authors\n"
        "  - qa_chat: chat-record / Q&A interview between authors\n"
        "  - list: enumerated numbered items (e.g. 20 个签约条件)\n"
        "  - tool: reference table / lookup data\n"
        "  - incomplete: title + intro only — body is empty / truncated\n\n"
        f"Document body (first 4000 chars):\n```\n{head}\n```{file_hint}\n\n"
        "Respond with a single JSON object:\n"
        '{"doc_type": "<one of the 7>", "confidence": <float 0..1>, '
        '"rationale": "<short reason>"}'
    )


# Late import — keep the math import below the helpers above so the
# module loads even if math was implicitly imported elsewhere.
import math  # noqa: E402


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
    # LLM fallback path (RFC v6 Stage 1.b).
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        # We're already inside an event loop — schedule the call.
        return _run_llm_fallback_sync(llm, content, filename_hint, heuristic)
    return asyncio.run(
        _async_classify_doc_fallback(llm, content, filename_hint, heuristic)
    )


def _run_llm_fallback_sync(llm, content, filename_hint, heuristic):
    """Bridge sync -> async when an event loop is already running.

    Used by callers like the pilot script that drive classify_doc from
    inside an asyncio coroutine. Runs the LLM call via a fresh thread
    so we never nest event loops.
    """
    import concurrent.futures

    def _runner() -> Classification | None:
        return asyncio.run(
            _async_classify_doc_fallback(llm, content, filename_hint, heuristic)
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_runner).result() or heuristic


async def _async_classify_doc_fallback(
    llm, content, filename_hint, heuristic: Classification
) -> Classification:
    """Async body of the LLM fallback. Returns heuristic if LLM yields
    no usable result."""
    result = await _invoke_llm_classifier(llm, content, filename_hint)
    return result if result is not None else heuristic
