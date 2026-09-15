"""T1.1: PromptAST dataclass tests (mirror src/wiki/templates/types.py)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.pipeline.v7_extract.prompts import (
    PromptAST,
    PromptSection,
    PromptSlot,
    PromptTemplate,
)


def test_prompt_slot_required_default():
    s = PromptSlot(name="content")
    assert s.required is True
    assert s.default == ""
    assert s.description == ""


def test_prompt_slot_optional_with_default():
    s = PromptSlot(name="limit", required=False, default="4000", description="max chars")
    assert s.required is False
    assert s.default == "4000"
    assert s.description == "max chars"


def test_prompt_slot_is_frozen():
    s = PromptSlot(name="content")
    with pytest.raises(FrozenInstanceError):
        s.name = "other"  # type: ignore[misc]


def test_prompt_section_basic():
    sec = PromptSection(
        heading="system",
        body_template="You are a classifier.",
        slots=[PromptSlot(name="content")],
    )
    assert sec.heading == "system"
    assert sec.body_template == "You are a classifier."
    assert len(sec.slots) == 1


def test_prompt_ast_required_slots_only_returns_required():
    ast = PromptAST(
        prompt_kind="classify",
        version="1.0",
        sections=[
            PromptSection(
                heading="system",
                body_template="sys",
                slots=[PromptSlot(name="sys_only", required=False)],
            ),
            PromptSection(
                heading="user",
                body_template="user {content}",
                slots=[
                    PromptSlot(name="content", required=True),
                    PromptSlot(name="filename_hint", required=False),
                ],
            ),
        ],
    )
    assert ast.required_slots == ["content"]
    all_names = [s.name for s in ast.all_slots]
    assert all_names == ["sys_only", "content", "filename_hint"]


def test_prompt_ast_system_and_user_section_helpers():
    ast = PromptAST(
        prompt_kind="classify",
        version="1.0",
        sections=[
            PromptSection(heading="system", body_template="SYS BODY"),
            PromptSection(heading="user", body_template="USER BODY"),
        ],
    )
    assert ast.system_section == "SYS BODY"
    assert ast.user_section == "USER BODY"


def test_prompt_ast_no_sections_returns_empty():
    ast = PromptAST(prompt_kind="x", version="1.0", sections=[])
    assert ast.system_section == ""
    assert ast.user_section == ""
    assert ast.all_slots == []


def test_prompt_ast_output_schema_optional():
    ast = PromptAST(
        prompt_kind="x",
        version="1.0",
        sections=[],
        output_schema={"type": "json", "required": ["a"]},
    )
    assert ast.output_schema == {"type": "json", "required": ["a"]}


def test_prompt_ast_ast_is_frozen():
    ast = PromptAST(prompt_kind="x", version="1.0", sections=[])
    with pytest.raises(FrozenInstanceError):
        ast.prompt_kind = "y"  # type: ignore[misc]


def test_prompt_template_basic_construction():
    tpl = PromptTemplate(
        prompt_kind="classify",
        version="1.0",
        system_section="SYS",
        user_template="USER {content}",
        output_schema=None,
        source="bundled",
        path=Path("/tmp/classify.toml"),
    )
    assert tpl.prompt_kind == "classify"
    assert tpl.source == "bundled"
    assert tpl.source_label == "bundled@1.0"


def test_prompt_template_source_label_without_version():
    tpl = PromptTemplate(
        prompt_kind="classify",
        version=None,
        system_section="",
        user_template="",
        output_schema=None,
        source="project",
        path=Path("/tmp/x.toml"),
    )
    assert tpl.source_label == "project@?"
