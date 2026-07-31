"""Shared helpers for the Collector → Analyzer → Generator pipeline.

Currently houses ``parse_llm_json`` — a lenient JSON parser used by both
the Analyzer and Generator steps. Without ``response_format`` enforcement
(MiniMax / DeepSeek / Kimi all reject any ``response_format`` parameter),
the model often wraps its JSON in markdown fences or appends a prose
preamble, so a strict ``json.loads(content)`` is too brittle.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source text cleaning for deterministic injection into wiki source pages
# ---------------------------------------------------------------------------

# Characters stripped from source text before injection: zero-width space
# (U+200B), zero-width non-joiner (U+200C), zero-width joiner (U+200D),
# byte-order mark (U+FEFF).
_ZERO_WIDTH_RE = re.compile(r'[​‌‍﻿]')

# 3+ consecutive blank lines collapsed to 2 (matches render_body convention).
_MULTI_BLANK_RE = re.compile(r'\n[ \t]*\n[ \t]*\n+')


def clean_source_text(text: str) -> str:
    """Clean raw source text for injection into wiki source page body.

    Rules (deliberately minimal — preserve ALL actual content):
    1. Strip zero-width characters (ZWSP, ZWNJ, ZWJ, BOM).
    2. Collapse 3+ consecutive blank lines to 2.
    3. Strip leading/trailing whitespace; append a single trailing newline.

    Returns empty string when the input is empty or whitespace-only
    (so the optional ``main_content`` slot drops gracefully).
    """
    if not text or not text.strip():
        return ""
    cleaned = _ZERO_WIDTH_RE.sub("", text)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip() + "\n"


# ---------------------------------------------------------------------------
# Source text denoising — rule-based, lossless platform-chrome removal
# ---------------------------------------------------------------------------

# Whole-line platform chrome (feishu exports etc.). Exact match ONLY — a line
# equal to one of these is structural UI chrome, never document content. The
# tradeoff (an exact-match string that IS the content of some hypothetical doc
# is also removed) is documented and accepted; operators can extend this set.
# ``编辑``/``分享`` are borderline (a tutorial COULD contain such a bare line)
# but in feishu exports they are always button labels — kept here deliberately.
_CHROME_LINES = {
    "登录/注册",
    "评论（0）",
    "评论(0)",
    "帮助中心",
    "效率指南",
    "上传日志",
    "联系客服",
    "功能更新",
    "飞书云文档",
    "分享",
    "编辑",
    "外部",
    "添加图标",
    "添加封面",
    "展示文档信息",
    "*此文档由 GPU 加速转录生成*",
}

# Structural metadata lines — regexes are anchored and specific enough to never
# match prose. These values are already captured by the 来源元数据 slot, so
# they are redundant in the body.
_META_LINE_RES = (
    re.compile(r"^来源[:：]\s*https?://"),    # feishu source URL
    re.compile(r"^下载时间[:：].*\d{4}"),     # download timestamp
    re.compile(r"^最新修改时间为.*[月日]"),   # feishu chrome (old export)
    re.compile(r"^最近修改[:：]"),            # feishu chrome (new export)
)

# feishu-export H1 title artifact: ``# <title> -`` (trailing " -").
_FEISHU_H1_RE = re.compile(r"^#\s+.+ -\s*$")

# Leading YAML frontmatter block (``---\n...\n---\n``).
_FRONTMATTER_RE = re.compile(r"^---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


def denoise_source_text(text: str) -> str:
    """Rule-based denoising for source-page ``main_content``.

    Removes ONLY structural platform chrome:
      1. leading YAML frontmatter block,
      2. metadata lines (来源/下载时间/最新修改/最近修改 — already captured
         by the 来源元数据 slot),
      3. feishu H1 title artifacts (``# Title -``),
      4. whole-line chrome from :data:`_CHROME_LINES`.
    Then delegates to :func:`clean_source_text` for whitespace normalisation.

    Lossless by construction: content lines are preserved verbatim (only
    exact-match chrome / specific anchored metadata regexes are dropped).
    Never does semantic or context-aware removal.
    """
    if not text or not text.strip():
        return ""
    text = _FRONTMATTER_RE.sub("", text, count=1)
    kept: list[str] = []
    for ln in text.splitlines():
        s = ln.rstrip()
        if s in _CHROME_LINES:
            continue
        if any(rx.match(s) for rx in _META_LINE_RES):
            continue
        if _FEISHU_H1_RE.match(s):
            continue
        kept.append(ln)
    return clean_source_text("\n".join(kept))


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL)

# Reasoning-model <think> blocks (MiniMax-M3, DeepSeek-R1).  Stripped at the
# provider layer as well; kept here as defense-in-depth.
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# Common JSON syntax errors made by LLMs that we can repair.
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")       # ,  → ]  or  , → }
_SINGLE_QUOTE_KEY_RE = re.compile(r"'([^']+)'(\s*):")  # 'key': → "key":
# Single-quoted string values: : 'value',  →  : "value",
_SINGLE_QUOTE_VAL_RE = re.compile(r"([:\[,])(\s*)'([^']*)'(\s*)([,}\]])")
# Bare [[wikilinks]] on their own line in JSON arrays — the LLM sometimes
# emits wikilink targets as raw JSON values (outside string quotes), which
# is invalid.  Match lines like ``          [[feishu-yunwendang]],`` and
# wrap in double-quotes.  Line-anchored to avoid touching [[wikilinks]]
# that already sit inside a quoted string value.
_BARE_WIKILINK_RE = re.compile(
    r'^(\s*)\[\[([^\]]+)\]\](,?)\s*$', re.MULTILINE,
)
_BARE_WIKILINK_SUB = r'\1"[[\2]]"\3'

# JSON forbids literal control characters (\\n, \\r, \\t) inside string
# values — they MUST be escaped.  Weaker models (qwen3.5-9b, MiniMax-M3)
# often embed markdown tables and multi-paragraph prose directly inside
# JSON strings, producing output like:
#
#   {"body": "| Col1 | Col2 |
#   |------|------|
#   | a    | b    |"}
#
# The literal newlines break json.loads even though the structure is
# otherwise valid.  _escape_string_controls walks the raw text with a
# minimal JSON string state machine and escapes any literal \\n / \\r / \\t
# it finds between unescaped double-quotes.


def _escape_string_controls(text: str) -> str:
    """Escape literal ``\\n``, ``\\r``, ``\\t`` inside JSON string values.

    Walks the input character-by-character tracking ``in_string`` and
    ``escape`` state.  Already-escaped sequences (``\\\\n``, ``\\\\t``,
    ``\\\\r``) pass through unchanged; only bare control characters that
    appear between two unescaped double-quotes are converted.
    """
    result: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == "\\":
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            result.append(ch)
            in_string = not in_string
            continue
        if in_string:
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        else:
            result.append(ch)

    return "".join(result)


def _repair_json(text: str) -> str:
    """Attempt to repair common LLM JSON syntax errors before parsing."""
    # 1. Strip markdown fences (the content INSIDE is what we repair)
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1)

    # 2. Extract the first balanced JSON object or array
    for opener, closer in (("{", "}"), ("[", "]")):
        idx = text.find(opener)
        if idx == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        end = -1
        for i in range(idx, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > idx:
            text = text[idx : end + 1]
            break

    # 3. Escape literal control chars inside JSON strings — weaker models
    #    often embed markdown tables / multi-paragraph prose directly inside
    #    string values, producing bare newlines that break json.loads.
    text = _escape_string_controls(text)

    # 4. Fix bare [[wikilinks]] — LLM sometimes emits wikilink targets as
    #    raw array elements instead of quoted strings.
    text = _BARE_WIKILINK_RE.sub(_BARE_WIKILINK_SUB, text)

    # 5. Remove trailing commas (most common LLM JSON error)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)

    # 6. Fix single-quoted keys: 'key': → "key":
    text = _SINGLE_QUOTE_KEY_RE.sub(r'"\1"\2:', text)

    # 7. Fix single-quoted string values: : 'value', → : "value",
    text = _SINGLE_QUOTE_VAL_RE.sub(r'\1\2"\3"\4\5', text)

    return text


def parse_llm_json(llm_resp: Any) -> dict:
    """Parse ``LLMResponse.content`` (or a raw dict/str) as a JSON object.

    Tries in order:
      1. Strict ``json.loads`` on the trimmed content.
      2. Markdown-fenced JSON block (```json ... ``` or ``` ... ```).
      3. Balanced JSON object/array extraction.
      4. JSON repair — fix trailing commas, single-quoted keys, then
         re-attempt steps 1-3 on the repaired text.

    Raises ``json.JSONDecodeError`` when no JSON object/array can be
    located. Never returns a partial / silently-empty result.
    """
    # Raw dict (legacy mock / unit test): use as-is.
    if isinstance(llm_resp, dict):
        return llm_resp
    # LLMResponse / any object exposing .content
    content = getattr(llm_resp, "content", llm_resp)
    if not isinstance(content, str):
        # Last-ditch: stringify and parse (covers invalid mocks returning bytes/None).
        content = str(content)

    s = content.strip()
    if not s:
        raise json.JSONDecodeError("LLM returned empty content", content, 0)

    # 0a. Strip <think> blocks (defense-in-depth; also done at provider level).
    s = _THINK_RE.sub("", s).strip()

    # 0b. Pre-repair: escape literal control chars inside JSON strings,
    #    then quote bare [[wikilinks]] BEFORE any parse attempt.
    #    If we let a balanced-extraction step succeed first on a tail
    #    fragment, we lose the root object.  Fixing early ensures Step 1
    #    (strict) sees the repaired text and returns the full payload.
    s = _escape_string_controls(s)
    s = _BARE_WIKILINK_RE.sub(_BARE_WIKILINK_SUB, s)

    # 1. Strict JSON.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 2. Markdown-fenced JSON.
    fence = _FENCE_RE.search(s)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Last balanced JSON object/array (strategy 0: many LLMs append
    #    JSON after a long prose preamble; the LAST structural token is
    #    much more likely to be the actual payload than the first).
    #    Uses string-aware depth tracking so braces inside prose strings
    #    (e.g. "Chapter 3 (finale)") don't corrupt the parse.
    _found_in_tail = False
    for opener, closer in (("{", "}"), ("[", "]")):
        idx = s.rfind(opener)
        if idx == -1:
            continue
        # Only try from the tail if the candidate is in the last 25%
        # of the response — avoids grabbing an inline brace from prose.
        if idx < len(s) * 0.75:
            continue
        _found_in_tail = True
        depth = 0
        in_string = False
        escape = False
        for i in range(idx, len(s)):
            ch = s[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[idx : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # Try repair on the tail candidate
                        repaired = _repair_json(candidate)
                        if repaired:
                            try:
                                return json.loads(repaired)
                            except json.JSONDecodeError:
                                pass
                    break  # Done with this opener/closer pair
        # Continue to try the other pair; only skip fallback if both
        # pairs landed in the tail region (idx >= 75%).
    if _found_in_tail:
        # Don't fall through to first-balanced extraction — we already
        # found plausible tail candidates that just didn't parse.
        pass  # (still try step 4 as a last resort, but log a hint)
    # (if no candidate was in the tail, fall through to step 4)

    # 4. First balanced JSON object / array.
    for opener, closer in (("{", "}"), ("[", "]")):
        idx = s.find(opener)
        if idx == -1:
            continue
        depth = 0
        for i in range(idx, len(s)):
            ch = s[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[idx : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # 5. JSON repair — fix common LLM syntax errors and re-attempt.
    repaired = _repair_json(s)
    if repaired and repaired != s:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        # Also try repairing the balanced extraction from the original text.
        # (Step 4 might have found a candidate but it failed to parse.)
        for opener, closer in (("{", "}"), ("[", "]")):
            idx2 = s.find(opener)
            if idx2 == -1:
                continue
            depth2 = 0
            for i in range(idx2, len(s)):
                ch2 = s[i]
                if ch2 == opener:
                    depth2 += 1
                elif ch2 == closer:
                    depth2 -= 1
                    if depth2 == 0:
                        candidate2 = _repair_json(s[idx2 : i + 1])
                        if candidate2:
                            try:
                                return json.loads(candidate2)
                            except json.JSONDecodeError:
                                pass

    # 6. All strategies exhausted — save a debug dump for diagnosis
    #    and raise the error.
    _dump_failed_json(content)

    raise json.JSONDecodeError(
        f"no JSON object/array found in LLM response ({len(content)} chars)",
        content, 0,
    )


def _dump_failed_json(content: str) -> None:
    """Save an unparseable LLM response to disk so failure patterns can be
    diagnosed.  The dump directory is configured via
    ``RUFLO_JSON_DEBUG_DIR`` (defaults to ``.index/staging/failed_json``
    under the project root discovered from CWD or ``os.getcwd()``)."""
    try:
        debug_root = os.environ.get("RUFLO_JSON_DEBUG_DIR", "")
        if not debug_root:
            cwd = Path.cwd()
            debug_root = str(cwd / ".index" / "staging" / "failed_json")
        os.makedirs(debug_root, exist_ok=True)
        digest = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
        dump_path = os.path.join(debug_root, f"failed_{digest}.txt")
        # Rotate: keep at most 100 dumps
        def _safe_mtime(fp: str) -> float:
            """Return mtime or 0 if the file was deleted concurrently."""
            try:
                return os.path.getmtime(fp)
            except OSError:
                return 0.0

        existing = sorted(
            [f for f in os.listdir(debug_root) if f.startswith("failed_")],
            key=lambda f: _safe_mtime(os.path.join(debug_root, f)),
        )
        while len(existing) >= 100:
            try:
                os.remove(os.path.join(debug_root, existing[0]))
            except OSError:
                pass
            existing.pop(0)
        with open(dump_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        _logger.warning(
            "[parse_llm_json] saved unparseable response (%d chars) to %s",
            len(content), dump_path,
        )
    except Exception:
        _logger.warning(
            "[parse_llm_json] failed to write debug dump", exc_info=True,
        )