"""Prompt TOML parser — mirrors src/wiki/templates/parser.py.

D9: enforces ``output_schema`` constraints to prevent malicious TOML
from injecting unknown enum values that bypass Stage-5 evidence
validation.

Allowed ``doc_type`` enum values are pinned to the 7 DocType constants
in ``src/pipeline/v7_extract/doc_classifier.DocType``. Any other value
in the enum block causes parse failure.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from .ast import PromptAST, PromptSection, PromptSlot


# Pinned whitelist — every value here must correspond to a DocType enum
# member in src/pipeline/v7_extract/doc_classifier.py.
# Any doc_type not in this set is rejected at parse time (D9).
_ALLOWED_DOC_TYPES: frozenset[str] = frozenset({
    "single_method",
    "multi_section",
    "collection",
    "qa_chat",
    "list",
    "tool",
    "incomplete",
})


class PromptParseError(Exception):
    """Raised when a prompt TOML fails to parse or fails D9 schema validation."""


def parse_prompt(path: Path) -> PromptAST:
    """Parse a prompt TOML file into a PromptAST.

    D9: validates ``output_schema.enum.doc_type`` against the pinned
    whitelist to prevent injection of unknown doc_type values.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PromptParseError(f"Cannot read prompt file {path}: {e}") from e

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise PromptParseError(f"Invalid TOML in {path}: {e}") from e

    if "meta" not in data or "prompt_kind" not in data["meta"]:
        raise PromptParseError(f"{path}: missing [meta].prompt_kind")

    sections: list[PromptSection] = []
    # Sections are declared as top-level tables. Only known headings are
    # accepted — this keeps the AST predictable and matches the LLM
    # call shape (system / user).
    for heading in ("system", "user"):
        block = data.get(heading)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise PromptParseError(
                f"{path}: [{heading}] must be a TOML table, got {type(block).__name__}"
            )
        body = block.get("text") or block.get("template") or ""
        sections.append(PromptSection(heading=heading, body_template=body))

    # Slots — declared as [[slot]] array-of-tables at top level.
    slots: list[PromptSlot] = []
    raw_slots = data.get("slot", [])
    if isinstance(raw_slots, list):
        for entry in raw_slots:
            if not isinstance(entry, dict) or "name" not in entry:
                raise PromptParseError(
                    f"{path}: each [[slot]] entry must be a table with 'name'"
                )
            slots.append(PromptSlot(
                name=entry["name"],
                required=bool(entry.get("required", True)),
                default=str(entry.get("default", "")),
                description=str(entry.get("description", "")),
            ))

    # Attach slots to sections — we attach every slot to every section
    # because the TOML schema declares slots at the top level rather
    # than per-section. This is fine for our current prompt shapes (each
    # slot is consumed in only one section); the renderer uses the flat
    # `required_slots` / `all_slots` API.
    if slots and sections:
        sections = [
            PromptSection(
                heading=sec.heading,
                body_template=sec.body_template,
                slots=list(slots),
            )
            for sec in sections
        ]

    schema = data.get("output_schema")
    if schema is not None:
        _validate_output_schema(schema, path)

    return PromptAST(
        prompt_kind=data["meta"]["prompt_kind"],
        version=data["meta"].get("version"),
        sections=sections,
        raw=text,
        output_schema=schema,
    )


def _validate_output_schema(schema: dict, path: Path) -> None:
    """D9: reject unknown doc_type enum values.

    A malicious prompt could declare a doc_type enum like
    ``["pwned"]`` to bypass Stage-5 evidence validation (which only
    checks that the LLM's doc_type is one of the 7 known values).
    By pinning the allowed enum set at parse time, we close this hole.
    """
    if not isinstance(schema, dict):
        raise PromptParseError(f"{path}: [output_schema] must be a table")

    enum_block = schema.get("enum")
    if not isinstance(enum_block, dict):
        return  # No enum block → nothing to validate

    doc_types = enum_block.get("doc_type")
    if doc_types is None:
        return
    if not isinstance(doc_types, list):
        raise PromptParseError(
            f"{path}: output_schema.enum.doc_type must be an array"
        )

    unknown = set(doc_types) - _ALLOWED_DOC_TYPES
    if unknown:
        raise PromptParseError(
            f"{path}: unknown doc_type in enum (D9): {sorted(unknown)}"
        )
