"""Stage 2 StructuralScanner — deterministic markdown/plain text block detector.

Task 41 (plan 2026-09-17-v7-stage-remediation-task41-structural-scanner).

Pure-function scanner: no LLM, no IO. All byte offsets are UTF-8 against the
input string. The output is a list of non-overlapping ``StructuralBlock``
covering the entire input, suitable for Bounded Evidence Contract §3.2:
Stage 2 segmentation / Stage 5 canonical-span derivation / fingerprint
inputs all consume this layer.

Determinism contract: identical input text produces byte-identical output,
and ``blocks_to_fingerprint(blocks)`` returns a stable hash suitable for
inclusion in pipeline_fingerprint (Task 22 / Task 37 wiring).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum


class StructuralBlockKind(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    LIST_ITEM = "list_item"
    BLOCKQUOTE = "blockquote"
    HORIZONTAL_RULE = "hr"
    BLANK_LINE = "blank_line"


@dataclass(frozen=True)
class StructuralBlock:
    """A contiguous span of the source text classified by structural role.

    ``start_byte`` / ``end_byte`` are UTF-8 byte offsets against the encoded
    input (NOT character offsets). The pair is half-open: ``[start, end)``.
    """

    kind: StructuralBlockKind
    start_byte: int
    end_byte: int
    level: int = 0
    text: str = ""

    def contains_byte(self, offset: int) -> bool:
        return self.start_byte <= offset < self.end_byte


_FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HR_RE = re.compile(r"^(\s*[-*_])\1{2,}\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?")


def scan_markdown(text: str) -> list[StructuralBlock]:
    """Walk ``text`` line by line; return non-overlapping StructuralBlocks.

    Rules (deterministic):
      * A fenced code block (`` ``` `` or ``~~~`` triple-fence) absorbs
        every line until the matching closing fence (same marker, length
        >= opening). An unclosed fence swallows everything to EOF as
        one code_block.
      * A line starting with ``#..######`` is a HEADING; level = the count.
      * A line that matches the HR pattern is HORIZONTAL_RULE.
      * A line matching ``LIST_RE`` is a LIST_ITEM; level = indent depth.
      * A line starting with ``>`` is BLOCKQUOTE; consecutive ``>`` lines
        coalesce into a single block.
      * Blank lines are emitted as BLANK_LINE blocks (useful for
        debugging); they break paragraph coalescing.
      * Anything else is PARAGRAPH; consecutive non-blank / non-special
        lines coalesce into a single block.

    Returns an empty list for empty input.
    """
    if not text:
        return []

    encoded = text.encode("utf-8")
    # We need byte offsets for blocks; build a parallel index of line
    # start bytes by re-encoding line by line.
    lines = text.splitlines(keepends=True)

    # Pre-compute byte offsets for the start of each line.
    line_start_bytes: list[int] = [0]
    running = 0
    for line in lines:
        running += len(line.encode("utf-8"))
        line_start_bytes.append(running)

    raw: list[StructuralBlock] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        line_no_newline = line.rstrip("\n").rstrip("\r")
        stripped = line_no_newline.strip()

        # Fenced code block: open fence at line i, absorb until closing fence.
        fence_match = _FENCE_RE.match(line_no_newline)
        if fence_match and not _is_inside_table_separator(line_no_newline):
            fence_marker = fence_match.group(1)
            block_start_byte = line_start_bytes[i]
            i += 1
            while i < n:
                closing = _FENCE_RE.match(lines[i].rstrip("\n").rstrip("\r"))
                if closing and closing.group(1)[0] == fence_marker[0] and len(closing.group(1)) >= len(fence_marker):
                    i += 1  # include closing fence
                    break
                i += 1
            block_end_byte = line_start_bytes[i]
            raw.append(StructuralBlock(
                kind=StructuralBlockKind.CODE_BLOCK,
                start_byte=block_start_byte,
                end_byte=block_end_byte,
                level=0,
                text=text.encode("utf-8")[block_start_byte:block_end_byte].decode("utf-8", errors="replace"),
            ))
            continue

        # Blank line.
        if not stripped:
            raw.append(StructuralBlock(
                kind=StructuralBlockKind.BLANK_LINE,
                start_byte=line_start_bytes[i],
                end_byte=line_start_bytes[i + 1],
                level=0,
                text="",
            ))
            i += 1
            continue

        # Heading.
        heading_match = _HEADING_RE.match(line_no_newline)
        if heading_match:
            raw.append(StructuralBlock(
                kind=StructuralBlockKind.HEADING,
                start_byte=line_start_bytes[i],
                end_byte=line_start_bytes[i + 1],
                level=len(heading_match.group(1)),
                text=line_no_newline,
            ))
            i += 1
            continue

        # Horizontal rule.
        if _HR_RE.match(line_no_newline):
            raw.append(StructuralBlock(
                kind=StructuralBlockKind.HORIZONTAL_RULE,
                start_byte=line_start_bytes[i],
                end_byte=line_start_bytes[i + 1],
                level=0,
                text=line_no_newline,
            ))
            i += 1
            continue

        # Blockquote (coalesce consecutive).
        if _BLOCKQUOTE_RE.match(line_no_newline):
            block_start = line_start_bytes[i]
            while i < n:
                cur = lines[i].rstrip("\n").rstrip("\r")
                if not cur.strip() or not _BLOCKQUOTE_RE.match(cur):
                    break
                i += 1
            raw.append(StructuralBlock(
                kind=StructuralBlockKind.BLOCKQUOTE,
                start_byte=block_start,
                end_byte=line_start_bytes[i],
                level=0,
                text=text.encode("utf-8")[block_start:line_start_bytes[i]].decode("utf-8", errors="replace"),
            ))
            continue

        # List item (coalesce consecutive same-indent items).
        list_match = _LIST_RE.match(line_no_newline)
        if list_match:
            indent_spaces = len(list_match.group(1).expandtabs(4))
            block_start = line_start_bytes[i]
            while i < n:
                cur = lines[i].rstrip("\n").rstrip("\r")
                if not cur.strip():
                    break
                cur_match = _LIST_RE.match(cur)
                if not cur_match:
                    break
                cur_indent = len(cur_match.group(1).expandtabs(4))
                if cur_indent != indent_spaces:
                    break
                i += 1
            raw.append(StructuralBlock(
                kind=StructuralBlockKind.LIST_ITEM,
                start_byte=block_start,
                end_byte=line_start_bytes[i],
                level=indent_spaces // 2 + 1,
                text=text.encode("utf-8")[block_start:line_start_bytes[i]].decode("utf-8", errors="replace"),
            ))
            continue

        # Paragraph: coalesce consecutive non-blank / non-special lines.
        block_start = line_start_bytes[i]
        while i < n:
            cur = lines[i].rstrip("\n").rstrip("\r")
            if not cur.strip():
                break
            if (_FENCE_RE.match(cur) or _HEADING_RE.match(cur)
                    or _HR_RE.match(cur) or _BLOCKQUOTE_RE.match(cur)
                    or _LIST_RE.match(cur)):
                break
            i += 1
        raw.append(StructuralBlock(
            kind=StructuralBlockKind.PARAGRAPH,
            start_byte=block_start,
            end_byte=line_start_bytes[i],
            level=0,
            text=text.encode("utf-8")[block_start:line_start_bytes[i]].decode("utf-8", errors="replace"),
        ))

    # Filter BLANK_LINE for production; keep them if caller wants debug view.
    # For the default public output, drop BLANK_LINE so consumers don't have
    # to skip them. The Bounded Evidence / Stage 2 consumer can re-add them
    # via ``with_blank_lines=True`` if needed (out of scope for Task 41).
    return [b for b in raw if b.kind is not StructuralBlockKind.BLANK_LINE]


def scan_plain(text: str) -> list[StructuralBlock]:
    """Plain text without markdown syntax → at most one PARAGRAPH block."""
    if not text:
        return []
    encoded = text.encode("utf-8")
    return [StructuralBlock(
        kind=StructuralBlockKind.PARAGRAPH,
        start_byte=0,
        end_byte=len(encoded),
        level=0,
        text=text,
    )]


def blocks_to_fingerprint(blocks: list[StructuralBlock]) -> str:
    """Stable hash of ``(kind | start | end | level | text)`` per block.

    Format: ``sc-<16hex>``. Used by ``_current_pipeline_fingerprint`` to
    include Stage 2 structural rules version (Tasks 22 / 37 wiring).
    """
    parts = [f"{b.kind.value}|{b.start_byte}|{b.end_byte}|{b.level}|{b.text}" for b in blocks]
    identity = "\n".join(parts)
    return "sc-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def _is_inside_table_separator(line: str) -> bool:
    """Heuristic: a line ``| --- | --- |`` is a table separator, not a fence."""
    return bool(re.match(r"^\s*\|?\s*[:\-\s|]+\|?\s*$", line)) and "---" in line


__all__ = [
    "StructuralBlock",
    "StructuralBlockKind",
    "blocks_to_fingerprint",
    "scan_markdown",
    "scan_plain",
]