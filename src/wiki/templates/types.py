"""Wiki page template types and constants."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from src.wiki import PageType


# ---------------------------------------------------------------------------
# Source identification (v3 version tracking)
# ---------------------------------------------------------------------------

TemplateSource = Literal["project", "user", "bundled"]


# ---------------------------------------------------------------------------
# Slot / Include models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """A `<!-- slot:NAME -->` placeholder for LLM-generated content.

    `is_optional=True` means the entire section (heading + slot content)
    may be omitted when the LLM has nothing to put in it. Equivalent to
    `<!-- if:X -->...<!-- /if:X -->` — both forms are normalized to
    this flag by the parser (see Bug 4/5 fix in
    docs/superpowers/plans/2026-07-25-wiki-page-templates.md REV 2).
    """
    name: str
    is_optional: bool = False
    condition_label: str | None = None  # The X in `<!-- if:X -->`, if any
    raw_marker: str = ""               # The original `<!-- slot:NAME -->` text


@dataclass(frozen=True)
class Include:
    """A `<!-- include:PATH -->` directive."""
    path: str
    raw_marker: str = ""


@dataclass(frozen=True)
class TemplateAST:
    """Parsed structure of a wiki page template.

    Sections are tracked in document order; the parser identifies each
    `## Heading` and the slots that belong to it (until the next
    heading).
    """
    page_type: PageType
    version: str | None
    sections: list["TemplateSection"] = field(default_factory=list)
    raw: str = ""           # original markdown (for round-trip)

    @property
    def all_slots(self) -> list[Slot]:
        out: list[Slot] = []
        for sec in self.sections:
            out.extend(sec.slots)
        return out


@dataclass(frozen=True)
class TemplateSection:
    """A `## Heading` block with its associated slots.

    `heading` is the raw `## ...` line including the leading hashes.
    `body_template` is the markdown between this heading and the next
    `## ...` heading, **with slot markers preserved**.
    """
    heading: str
    body_template: str
    slots: list[Slot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Resolved template (output of resolver)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Template:
    """A resolved wiki page template ready for prompt injection."""
    type: PageType
    body_markdown: str   # Include directives expanded, slot markers preserved
    version: str | None
    source: TemplateSource
    path: Path

    @property
    def source_label(self) -> str:
        return f"{self.source}@{self.version or '?'}"


# ---------------------------------------------------------------------------
# Constants used by resolver
# ---------------------------------------------------------------------------

PROJECT_TEMPLATE_DIRNAME = ".wiki-templates"
USER_TEMPLATE_DIR = Path.home() / ".config" / "ruflo-kb" / "wiki-templates"
BUNDLED_DIR = Path(__file__).parent / "bundled"

# Maximum include depth (defensive; visited-set catches all cycles).
MAX_INCLUDE_DEPTH = 3

# Filename pattern: a template is `<type>.md` where <type> matches
# PageType.value. Fragments are files starting with `_`.
TEMPLATE_FILENAME_GLOB = "[a-z]*.md"   # matches all PageType values
FRAGMENT_FILENAME_PREFIX = "_"