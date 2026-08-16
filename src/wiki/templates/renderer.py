"""Render wiki page templates from a slot-filled dict into body markdown.

The Generator (`src/pipeline/generator.py`) asks the LLM to return its
output as a structured ``slots`` dict (slot name → content). This module
takes those slots plus the original template body and assembles the final
markdown that ends up on disk via ``page_writer.write_page``.

Section-aware approach:

- We parse the template (which has had includes expanded by the resolver
  but still carries ``<!-- slot:NAME -->`` markers) into a ``TemplateAST``.
- We walk each ``TemplateSection`` and decide whether to keep or drop it:
  * If every slot in the section is optional AND empty in the LLM output,
    the entire section (heading + body) is dropped — that heading no longer
    appears in the rendered body.
  * Otherwise the section is kept; each slot marker is replaced with
    either its content, an empty string (optional + empty), or the
    missing-placeholder text (required + empty).

Per Plan 27 (2026-07-26 wiki schema v2.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence, Union

from ..core.types import PageType
from . import parser as template_parser


# ---------------------------------------------------------------------------
# Slot fill status — used by the Generator's retry loop.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotFillStatus:
    """Audit of how a slot dict maps against a required-slot list.

    Attributes:
        given:    Required slots that appear in ``slots`` with non-empty content.
        missing:  Required slots absent or empty in ``slots``.
        extra:    Slots present in ``slots`` but not required. Informational;
                  the schema's ``additionalProperties: false`` also rejects them.
    """

    given: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)


def compute_slot_fill_status(
    available: dict[str, object],
    required: Sequence[str],
) -> SlotFillStatus:
    """Classify slots in ``available`` against the ``required`` list.

    A slot counts as "given" when its value is a non-empty string or a
    non-empty list. Empty string, empty list, ``None``, and missing keys
    all count as "missing".
    """
    given: list[str] = []
    missing: list[str] = []
    for name in required:
        if _is_present(available.get(name)):
            given.append(name)
        else:
            missing.append(name)
    extra = sorted(n for n in available if n not in set(required))
    return SlotFillStatus(given=given, missing=missing, extra=extra)


def _is_present(value: object) -> bool:
    """Heuristic: ``value`` carries substantive content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_is_present(v) for v in value)
    return True


# ---------------------------------------------------------------------------
# Body rendering.
# ---------------------------------------------------------------------------


# 3+ blank-line collapse (skipping optional sections can introduce them).
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n[ \t]*\n+(?=\S|\Z)")
# Plain HTML comments (semantic hints in templates). The two wiki-template
# header comments are re-injected separately by render_body and are not part
# of section bodies, so stripping every comment here never loses the lint
# version gate (O3 / F3 follow-up: template hints must not leak into the
# rendered page body).
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def render_body(
    template_body: str,
    slots: dict[str, Union[str, Sequence[str]]],
    page_type: PageType,
    optional: Sequence[str] = (),
    missing_placeholder: str = "（待补充）",
    template_version: str = "",
) -> str:
    """Render slot content into ``template_body`` and return body markdown.

    Args:
        template_body: The template's raw markdown (includes already
            expanded by the resolver; ``<!-- slot:NAME -->`` markers
            still present).
        slots: Map of slot name → content. Values may be strings or
            sequences of strings (which are joined as markdown bullets).
        page_type: The page type — used to validate the template header.
        optional: Names of slots whose entire sections may be skipped
            when empty (``<!-- slot:NAME? -->`` and ``<!-- if:X -->``
            slots). Slots already flagged optional by the parser are
            added automatically; this only needs to enumerate *additional*
            ones, if any.
        missing_placeholder: Text inserted under a required heading when
            the LLM left the slot empty (after the retry budget was
            exhausted).
        template_version: Version string of the bundled/user/project
            template that produced this page. When non-empty, the
            output is prefixed with the
            ``<!-- wiki-template-version: ... -->`` /
            ``<!-- wiki-template-type: ... -->`` marker pair so the
            ``LINT-MISSING-SECTION`` rule can gate structural checks
            on freshly generated pages.

            Plan 27 v2.3 originally relied on the markers being
            preserved by the parser. The parser intentionally strips
            them (so the rendered body has no template comments);
            re-injecting here keeps the lint mechanism working
            without polluting the markdown the user reads.

    Returns:
        Body markdown with all slot markers replaced, the template
        header re-injected (if template_version was supplied), and
        whitespace tidied. Ready to drop into ``WikiPage.body``.
    """
    optional_set = set(optional)
    ast = template_parser.parse(template_body, expected_type=page_type)

    out: list[str] = []
    if template_version:
        # Re-inject the two header comments that ``parser.parse``
        # stripped in step 3. Without these, the page body has no
        # version marker and the LINT-MISSING-SECTION rule never
        # triggers on freshly generated pages.
        out.append(f"<!-- wiki-template-version: {template_version} -->")
        out.append(f"<!-- wiki-template-type: {page_type.value} -->")
        out.append("")
    for section in ast.sections:
        # Every slot in the section optional AND empty → drop the section.
        if section.slots and all(
            (s.is_optional or s.name in optional_set) and not _is_present(slots.get(s.name))
            for s in section.slots
        ):
            continue

        out.append(section.heading)
        out.append("")

        # Replace markers in body template slot-by-slot, then strip any
        # remaining plain HTML comments (semantic hints in the template).
        body = section.body_template
        for s in section.slots:
            value = slots.get(s.name)
            is_opt = s.is_optional or (s.name in optional_set)
            body = body.replace(s.raw_marker, _render_value(value, is_opt, missing_placeholder))
        body = _HTML_COMMENT_RE.sub("", body)

        body = body.rstrip()
        if body:
            out.append(body)
            out.append("")

    # Collapse 3+ blank lines down to 2 (markdown convention).
    text = "\n".join(out).rstrip() + "\n"
    return _BLANK_LINE_RE.sub("\n\n", text)


def _render_value(
    value: object,
    is_optional: bool,
    missing_placeholder: str,
) -> str:
    """Render one slot's value (string | list | None) into body content."""
    if not _is_present(value):
        return "" if is_optional else missing_placeholder
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(
            str(v) if str(v).startswith("- ") else f"- {v}"
            for v in value
        )
    return str(value)
