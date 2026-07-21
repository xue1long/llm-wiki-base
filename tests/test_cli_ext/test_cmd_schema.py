# tests/test_cli_ext/test_cmd_schema.py
import json
from pathlib import Path

# Import migrations to trigger auto-registration
from src.schemas.migrations import v1_to_v2, v2_to_v2_1

from src.cli_ext.schema_cmd import (
    cmd_schema_list,
    cmd_schema_diff,
    cmd_schema_upgrade,
)


def test_cmd_schema_list(tmp_path, monkeypatch, capsys):
    """schema list shows registered schemas + versions."""
    from src.cli_ext import schema_cmd
    from src.schemas.registry import MigrationRegistry
    from src.schemas.migration import SchemaVersion

    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, _dummy_mig()
    )

    args = type("Args", (), {})()
    cmd_schema_list(args)

    out = capsys.readouterr().out
    assert "wiki_page" in out
    assert "v1.0" in out
    assert "v2.0" in out


def test_cmd_schema_diff(tmp_path, monkeypatch, capsys):
    """schema diff shows field changes between versions."""
    # Set up project context (CWD-based)
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    (kb / "wiki" / "sources").mkdir(parents=True)
    (kb / "wiki" / "sources" / "a.md").write_text(
        "---\nschema_version: v2.0\nid: a\n---\nbody\n", encoding="utf-8"
    )
    monkeypatch.chdir(kb)

    args = type("Args", (), {"schema": "wiki_page", "from_v": "v2.0", "to_v": "v2.1"})()
    cmd_schema_diff(args)

    out = capsys.readouterr().out
    assert "v2.0" in out and "v2.1" in out
    # Migration path exists (v2.0→v2.1 is registered)
    assert "Migration path" in out


def test_cmd_schema_upgrade(tmp_path, monkeypatch, capsys):
    """schema upgrade applies migration + reports result."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    (kb / "wiki" / "sources").mkdir(parents=True)
    (kb / "wiki" / "sources" / "a.md").write_text(
        "---\nschema_version: v2.0\nid: a\n---\nbody\n", encoding="utf-8"
    )

    monkeypatch.chdir(kb)

    args = type("Args", (), {"to": "v2.1", "preview": False})()
    cmd_schema_upgrade(args)

    out = capsys.readouterr().out
    assert "Upgraded" in out or "v2.1" in out
    # File updated
    text = (kb / "wiki" / "sources" / "a.md").read_text()
    assert "v2.1" in text


def _dummy_mig():
    from src.schemas.migration import Migration, MigrationPlan, MigrationResult, SchemaVersion
    class _M(Migration):
        schema_name = "wiki_page"
        from_version = SchemaVersion.V1_0
        to_version = SchemaVersion.V2_0
        def preview(self, ctx): return MigrationPlan(self.from_version, self.to_version, ["dummy"], [], True)
        def up(self, ctx): return MigrationResult(success=True)
        def down(self, ctx): return MigrationResult(success=True)
    return _M()