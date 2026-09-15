"""PromptAST — mirror of src/wiki/templates/types.py.

Alignment map (D5):
    TemplateAST     →  PromptAST
    Template        →  PromptTemplate
    TemplateSection →  PromptSection
    Slot            →  PromptSlot
    TemplateSource  →  PromptSource

Differences from TemplateAST (intentional):
  * PromptSection.heading is one of {"system", "user", "examples",
    "constraints"} instead of an arbitrary "## Heading" string. LLM
    prompts have a fixed structural shape (system + user template) so
    we constrain heading values at the AST level.
  * PromptAST carries an optional ``output_schema`` dict that describes
    the JSON contract the LLM is expected to return. The renderer
    validates against this contract (see D9 / T1.3).
  * PromptTemplate exposes flat ``system_section`` + ``user_template``
    strings — easier to feed straight into an LLM call than walking a
    multi-section AST.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


PromptSource = Literal["project", "user", "bundled"]


@dataclass(frozen=True)
class PromptSlot:
    """A ``{slot_name}`` placeholder declared in a prompt template.

    Mirrors ``src/wiki/templates/types.Slot`` — but represents a
    *runtime* substitution target (the LLM does the rendering), not
    a static template fill target.
    """

    name: str
    required: bool = True
    default: str = ""
    description: str = ""


@dataclass(frozen=True)
class PromptSection:
    """One logical chunk of a prompt.

    In practice ``heading`` will be ``"system"`` (the system message)
    or ``"user"`` (the user-prompt template). The AST allows multiple
    user sections (e.g. user_header + user_data) so the renderer can
    compose them, but the TOML files we ship today only use one.
    """

    heading: str
    body_template: str
    slots: list[PromptSlot] = field(default_factory=list)


@dataclass(frozen=True)
class PromptAST:
    """Parsed structure of a single V7 prompt TOML file."""

    prompt_kind: str
    version: str | None
    sections: list[PromptSection]
    raw: str = ""
    output_schema: dict | None = None

    @property
    def all_slots(self) -> list[PromptSlot]:
        return [s for sec in self.sections for s in sec.slots]

    @property
    def required_slots(self) -> list[str]:
        return [s.name for s in self.all_slots if s.required]

    @property
    def system_section(self) -> str:
        for sec in self.sections:
            if sec.heading == "system":
                return sec.body_template
        return ""

    @property
    def user_section(self) -> str:
        for sec in self.sections:
            if sec.heading == "user":
                return sec.body_template
        return ""


@dataclass(frozen=True)
class PromptTemplate:
    """Resolved Prompt, ready to render and ship to an LLM.

    Mirrors ``src/wiki/templates/types.Template``:

        Template          →  PromptTemplate
        Template.body     →  PromptTemplate.user_template
        Template.version  →  PromptTemplate.version
        Template.source   →  PromptTemplate.source
        Template.path     →  PromptTemplate.path

    The system section is split out from the user template (rather than
    kept as a single markdown blob) because LLMClient.complete() takes
    them as separate ``system_prompt`` / ``user_prompt`` arguments.
    """

    prompt_kind: str
    version: str | None
    system_section: str
    user_template: str
    output_schema: dict | None
    source: PromptSource
    path: Path

    @property
    def source_label(self) -> str:
        return f"{self.source}@{self.version or '?'}"
