import json
from pathlib import Path

from src.wiki.features.slug_aliases import SlugAliasRegistry
from src.wiki.migrate.v2_aliases import (
    extract_aliases,
    extract_alias_records,
    write_alias_registry,
)


def test_extracts_only_entity_aliases_in_forward_direction():
    aliases = extract_aliases(
        file_stem="Claude Code",
        frontmatter={"type": "entity", "aliases": ["claude-code", "ClaudeCode"]},
    )

    assert aliases == {
        "claude-code": "Claude Code",
        "ClaudeCode": "Claude Code",
    }


def test_non_entity_and_empty_aliases_are_ignored():
    assert extract_aliases("x", {"type": "concept", "aliases": ["foo"]}) == {}
    assert extract_aliases("x", {"type": "entity", "aliases": ["", "  ", None]}) == {}


def test_alias_records_preserve_original_and_are_sorted_deterministically():
    records = extract_alias_records(
        "Obsidian",
        {"type": "entity", "aliases": ["  OB  ", "Obsidian", "OB"]},
    )

    assert records == [
        {"alias": "OB", "canonical": "Obsidian", "original": "OB"},
        {"alias": "Obsidian", "canonical": "Obsidian", "original": "Obsidian"},
    ]


def test_write_is_compatible_with_slug_alias_registry(tmp_path: Path):
    path = tmp_path / ".llm-wiki" / "slug_aliases.json"
    write_alias_registry(
        {"claude-code": "Claude Code", "ClaudeCode": "Claude Code", "OB": "Obsidian"},
        path,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["aliases"] == {
        "OB": "Obsidian",
        "ClaudeCode": "Claude Code",
        "claude-code": "Claude Code",
    }
    registry = SlugAliasRegistry(tmp_path)
    assert registry.get_canonical("ClaudeCode") == "Claude Code"
    assert registry.has_aliases_for("Claude Code") == ["ClaudeCode", "claude-code"]


def test_conflicting_alias_does_not_overwrite_first_mapping(tmp_path: Path):
    path = tmp_path / "slug_aliases.json"
    write_alias_registry(
        [("same", "First"), ("same", "Second")],
        path,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["aliases"] == {"same": "First"}
    assert data["conflicts"] == [
        {"alias": "same", "existing": "First", "incoming": "Second"}
    ]
