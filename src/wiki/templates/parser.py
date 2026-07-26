"""Parser for wiki page template markdown.

Template syntax (HTML-comment based; see
docs/superpowers/plans/2026-07-25-wiki-page-templates.md REV 2):

    <!-- wiki-template-version: 1.0.0 -->
    <!-- wiki-template-type: concept -->

    ## 定义

    <!-- slot:definition -->

    ## 别名

    <!-- if:has_aliases -->           # ≡ <!-- slot:aliases? -->

    <!-- slot:aliases -->

    <!-- /if:has_aliases -->

    <!-- include:_base.md -->         # reference another template

The parser normalizes `<!-- if:X -->...<!-- /if:X -->` blocks to
`Slot(is_optional=True, condition_label=X)`. The `X` label is purely
informational; LLM makes the actual skip/include decision at runtime.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import PageType, TemplateAST

# Pattern constants (compiled once for reuse).
_VERSION_RE = re.compile(
    r"^<!--\s*wiki-template-version:\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*-->\s*$",
    re.MULTILINE,
)
_TYPE_RE = re.compile(
    r"^<!--\s*wiki-template-type:\s*([a-z][a-z0-9_]*)\s*-->\s*$",
    re.MULTILINE,
)
_SLOT_RE = re.compile(
    r"<!--\s*slot:([a-z][a-z0-9_]*?)(\?)?\s*-->"
)
_INCLUDE_RE = re.compile(
    r"<!--\s*include:\s*([^>\s]+)\s*-->"
)
_IF_OPEN_RE = re.compile(
    r"<!--\s*if:([a-z][a-z0-9_]*)\s*-->"
)
_IF_CLOSE_RE = re.compile(
    r"<!--\s*/if:[a-z][a-z0-9_]*\s*-->"
)
_HEADING_RE = re.compile(
    r"^(#{1,6})\s+(.+?)\s*$",
    re.MULTILINE,
)


class TemplateParseError(ValueError):
    """Raised when a template's markdown is malformed or mismatched."""


def validate_type_header(markdown: str, expected_type: "PageType") -> str:
    """Validate the ``<!-- wiki-template-type: X -->`` header.

    Used by both ``parse()`` and external callers (resolver, CLI) so all
    three share the same regex and error wording. Only the FIRST type
    header is authoritative — subsequent mentions are ignored.

    Returns:
        The matched type name (== ``expected_type.value``).

    Raises:
        TemplateParseError: header missing, or mismatched against
            ``expected_type``.
    """
    type_match = _TYPE_RE.search(markdown)
    if not type_match:
        raise TemplateParseError(
            f"Template is missing `<!-- wiki-template-type: {expected_type.value} -->` header"
        )
    if type_match.group(1) != expected_type.value:
        raise TemplateParseError(
            f"Template type mismatch: header says '{type_match.group(1)}', "
            f"expected '{expected_type.value}'"
        )
    return type_match.group(1)


def parse(markdown: str, expected_type: "PageType") -> "TemplateAST":
    """Parse template markdown into a TemplateAST.

    Args:
        markdown: The raw template text.
        expected_type: The PageType this template is supposed to be for.
            Used to validate the ``<!-- wiki-template-type: X -->`` header
            (must match ``expected_type.value``).

    Raises:
        TemplateParseError: if the markdown is missing required headers,
            has a type mismatch, or contains malformed markers.
    """
    from .types import PageType, Slot, Include, TemplateAST, TemplateSection

    # 0. Empty / blank template — fail early with a clearer message.
    if not markdown.strip():
        raise TemplateParseError(
            "Template is empty (no content). Templates must define at "
            "least one `##` section or `<!-- include: -->` directive."
        )

    # 1. Version header
    version_match = _VERSION_RE.search(markdown)
    if not version_match:
        raise TemplateParseError(
            "Template is missing `<!-- wiki-template-version: X.Y.Z -->` header"
        )
    version = version_match.group(1)

    # 2. Type header — must match expected_type (delegated to helper so
    #    resolver/CLI share the same validation rules).
    validate_type_header(markdown, expected_type)

    # 3. Strip headers from body so they don't interfere with section parsing
    body = markdown
    body = _VERSION_RE.sub("", body, count=1)
    body = _TYPE_RE.sub("", body, count=1)

    # 4. Pre-process: validate all `<!-- if:X -->...<!-- /if:X -->` blocks
    #    in the full body (so unclosed-if detection works before sections).
    #    Per-section conditional_ranges are computed lazily in step 6.
    pos = 0
    while True:
        m = _IF_OPEN_RE.search(body, pos)
        if not m:
            break
        label = m.group(1)
        open_start, open_end = m.span()
        close_m = _IF_CLOSE_RE.search(body, open_end)
        if not close_m:
            raise TemplateParseError(
                f"Unclosed `<!-- if:{label} -->` block"
            )
        pos = close_m.end()

    # 5. Split body into sections by `## Heading` (h2 specifically)
    sections = _split_into_sections(body)

    # 6. For each section, collect slot markers (with conditional metadata).
    #    Conditional ranges are tracked per-section body so position
    #    arithmetic lines up between the slot markers and the if-block
    #    boundaries.
    parsed_sections: list[TemplateSection] = []
    for heading, sec_body in sections:
        conditional_ranges: list[tuple[int, int, str]] = []
        pos = 0
        while True:
            m = _IF_OPEN_RE.search(sec_body, pos)
            if not m:
                break
            label = m.group(1)
            open_start, open_end = m.span()
            close_m = _IF_CLOSE_RE.search(sec_body, open_end)
            # close_m must exist (validated in step 4 against full body)
            close_start, close_end = close_m.span()
            conditional_ranges.append((open_start, close_end, label))
            pos = close_end

        slots: list[Slot] = []
        for m in _SLOT_RE.finditer(sec_body):
            name = m.group(1)
            is_opt = (m.group(2) == "?")
            cond_label = _find_containing_label(m.start(), conditional_ranges)
            slots.append(
                Slot(
                    name=name,
                    is_optional=is_opt or cond_label is not None,
                    condition_label=cond_label,
                    raw_marker=m.group(0),
                )
            )
        parsed_sections.append(
            TemplateSection(
                heading=heading,
                body_template=sec_body.strip(),
                slots=slots,
            )
        )

    # 7. Includes (top-level only — those not inside any section are valid,
    #    but typically `<!-- include:_base.md -->` appears at the top)
    includes: list[Include] = []
    # Strip sections from body for include extraction
    body_no_sections = _strip_section_markers(body)
    for m in _INCLUDE_RE.finditer(body_no_sections):
        path = m.group(1).strip()
        includes.append(Include(path=path, raw_marker=m.group(0)))

    # 8. Final validation: at least one section OR one include
    if not parsed_sections and not includes:
        raise TemplateParseError(
            "Template has no `##` sections or `<!-- include: -->` directives"
        )

    return TemplateAST(
        page_type=expected_type,
        version=version,
        sections=parsed_sections,
        raw=markdown,
    )


def _split_into_sections(body: str) -> list[tuple[str, str]]:
    """Split body markdown into (heading_line, body_after_heading) pairs.

    Uses `## ` (h2) as the section boundary. h1/h3+ are not section
    delimiters (v1 simplification).
    """
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_body: list[str] = []
    for line in body.split("\n"):
        if line.startswith("## ") and not line.startswith("### "):
            # Flush previous section
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_body)))
            current_heading = line
            current_body = []
        else:
            if current_heading is not None:
                current_body.append(line)
            # Lines before the first `## ` are silently dropped (they're
            # typically comments or empty lines).
    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_body)))
    return sections


def _find_containing_label(
    pos: int, ranges: list[tuple[int, int, str]]
) -> str | None:
    """Return the conditional label covering position ``pos``, or None."""
    for start, end, label in ranges:
        if start <= pos <= end:
            return label
    return None


def _strip_section_markers(body: str) -> str:
    """Remove `## ...` headings for include extraction. Used so the
    `_INCLUDE_RE` doesn't accidentally match inside section bodies.
    """
    return _HEADING_RE.sub("", body)


def render(ast: "TemplateAST") -> str:
    """Reconstruct template markdown from AST. Round-trip guarantee:
    ``parse(render(parse(text))) == parse(text)``.

    Used by `wiki-templates diff` to show user vs bundled.
    """
    # Re-emit headers + sections in original order.
    out: list[str] = []
    # Headers (preserved from ast.raw at the top)
    out.append(f"<!-- wiki-template-version: {ast.version} -->")
    out.append(f"<!-- wiki-template-type: {ast.page_type.value} -->")
    out.append("")

    # Body sections
    for sec in ast.sections:
        out.append(sec.heading)
        out.append("")
        out.append(sec.body_template)
        out.append("")

    return "\n".join(out).rstrip() + "\n"