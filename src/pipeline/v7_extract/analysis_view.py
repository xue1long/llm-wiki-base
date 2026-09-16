"""Stage 2 AnalysisView + offset mapping for HTML sources (Task 43).

Renders an HTML byte stream into plain text while preserving a
bidirectional offset map: ``raw_byte_offset`` ↔ ``rendered_text_offset``.

Use case: Stage 2/5 receive HTML sources (URL ingestion). The LLM must
only see rendered plain text (Bounded Evidence Contract §3.2), but
extracted byte offsets must reference the original raw HTML bytes so
``EvidenceRef.excerpt_from(raw_bytes)`` returns the canonical source
material.

Pure-stdlib implementation (no BeautifulSoup / lxml dependency).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable


# Tags whose contents MUST NOT enter the rendered text.
_NON_TEXT_TAGS = frozenset({"script", "style", "head", "noscript", "template"})

# Tags whose inner text is treated as a "block" (separator = newline).
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "header", "footer", "nav",
    "li", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "thead", "tbody", "tfoot",
    "br", "hr",
    "blockquote", "pre",
})


@dataclass(frozen=True)
class TextMapping:
    """One contiguous text node inside the HTML.

    raw_byte_start / raw_byte_end point into the original ``raw_bytes``
    (inclusive start, exclusive end). ``rendered_offset`` is the offset
    inside ``view.rendered_text`` where this text begins.
    """

    raw_byte_start: int
    raw_byte_end: int
    rendered_offset: int


@dataclass
class AnalysisView:
    raw_bytes: bytes
    rendered_text: str
    mappings: list[TextMapping] = field(default_factory=list)
    tag_stack_at_offset: dict[int, str] = field(default_factory=dict)

    def lookup_rendered_offset(self, raw_byte_offset: int) -> int | None:
        for m in self.mappings:
            if m.raw_byte_start <= raw_byte_offset < m.raw_byte_end:
                return m.rendered_offset + (raw_byte_offset - m.raw_byte_start)
        return None

    def lookup_raw_offset(self, rendered_offset: int) -> int | None:
        for m in self.mappings:
            if m.rendered_offset > rendered_offset:
                break
            text_len = m.raw_byte_end - m.raw_byte_start
            if m.rendered_offset + text_len > rendered_offset:
                return m.raw_byte_start + (rendered_offset - m.rendered_offset)
        return None


class _ViewBuilder(HTMLParser):
    """Walks HTML, builds TextMappings + rendered_text + tag-stack map.

    The parser doesn't expose raw byte offsets directly; we approximate
    by counting characters consumed via a manual ``_cursor`` advanced by
    the data length in ``handle_data`` and tag-length estimates in
    ``handle_starttag``/``handle_endtag``. This is intentionally a Task 43
    best-effort model; full DOM parsing is out of scope.

    Strategy:
      * Skip ``<script>``, ``<style>``, ``<head>``, ``<noscript>``,
        ``<template>`` contents entirely.
      * Each non-whitespace text node yields one ``TextMapping``.
      * Block-level closing tags append a newline separator.
    """

    def __init__(self, raw_bytes: bytes) -> None:
        super().__init__(convert_charrefs=True)
        self.raw_bytes = raw_bytes
        self.rendered_text_parts: list[str] = []
        self.mappings: list[TextMapping] = []
        self.tag_stack_at_offset: dict[int, str] = {}
        self._stack: list[str] = []
        self._skip_depth: int = 0
        self._current_rendered_offset: int = 0
        self._cursor: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_stack_at_offset[self._cursor] = tag
        # Approximate: open tag in source "<tag ...>" = 1 char opener + tag chars.
        self._cursor += 1 + len(tag)
        if tag in _NON_TEXT_TAGS:
            self._skip_depth += 1
        self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        # "</tag>" length.
        self._cursor += 2 + len(tag)
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        elif tag in self._stack:
            self._stack.remove(tag)
        if tag in _NON_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in _BLOCK_TAGS:
            if not self.rendered_text_parts or not self.rendered_text_parts[-1].endswith("\n"):
                self.rendered_text_parts.append("\n")
                self._current_rendered_offset += 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            self._cursor += len(data.encode("utf-8", errors="replace"))
            return
        if not data:
            return
        start_byte = self._cursor
        encoded = data.encode("utf-8", errors="replace")
        end_byte = start_byte + len(encoded)
        self._cursor = end_byte
        stripped = data.strip()
        if not stripped:
            return
        leading_ws = len(data) - len(data.lstrip())
        trailing_ws = len(data) - len(data.rstrip())
        mapping = TextMapping(
            raw_byte_start=start_byte + leading_ws,
            raw_byte_end=end_byte - trailing_ws,
            rendered_offset=self._current_rendered_offset,
        )
        if (
            self.rendered_text_parts
            and not self.rendered_text_parts[-1].endswith(("\n", " "))
        ):
            self.rendered_text_parts.append(" ")
            self._current_rendered_offset += 1
        self.rendered_text_parts.append(stripped)
        self._current_rendered_offset += len(stripped)
        self.mappings.append(mapping)

    def handle_entityref(self, name: str) -> None:
        # HTMLParser with convert_charrefs=True already converts entity refs
        # to text via handle_data; this hook is unreachable in practice.
        # Keep for completeness in case convert_charrefs is ever flipped.
        self._cursor += 1 + len(name) + 1  # "&name;"

    def handle_charref(self, name: str) -> None:
        # Numeric char ref (e.g. &#65;). Already converted to text by parser.
        self._cursor += 2 + len(name) + 1  # "&#name;"


def AnalysisView_from_html(raw_bytes: bytes) -> AnalysisView:
    """Parse ``raw_bytes`` (HTML) and return an AnalysisView."""
    builder = _ViewBuilder(raw_bytes)
    text = raw_bytes.decode("utf-8", errors="replace")
    builder._cursor = 0  # type: ignore[attr-defined]
    builder.feed(text)
    builder.close()
    rendered_text = "".join(builder.rendered_text_parts)
    return AnalysisView(
        raw_bytes=raw_bytes,
        rendered_text=rendered_text,
        mappings=builder.mappings,
        tag_stack_at_offset=builder.tag_stack_at_offset,
    )


# Attach as classmethod on the dataclass for ergonomic ``AnalysisView.from_html``.
def _from_html(cls, raw_bytes: bytes) -> AnalysisView:
    return AnalysisView_from_html(raw_bytes)


AnalysisView.from_html = classmethod(_from_html)  # type: ignore[attr-defined]


__all__ = ["AnalysisView", "TextMapping"]