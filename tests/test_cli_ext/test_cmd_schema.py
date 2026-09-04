# tests/test_cli_ext/test_cmd_schema.py
import json

# Import migrations to trigger auto-registration
from src.schemas.migrations import v1_to_v2, v2_to_v2_1  # noqa: F401

from src.cli_ext.schema_cmd import (
    cmd_schema_list,
    cmd_schema_diff,
    cmd_schema_upgrade,
)


def _reset_registry_with_real_migrations():
    """Reset MigrationRegistry to a known state with the real v2.x migrations.

    tests/test_schemas/test_migration_path_finds_hops uses MigrationRegistry._clear()
    but does not restore state, leaving dummy (no-op) migrations in the registry.
    When v2_to_v2_2 is also imported (via tests/test_schemas/test_v2_to_v2_2.py),
    its auto-registration overwrites the V2.0→V2_1 slot with a no-op stub.

    This helper makes tests below independent of the test_schemas test order.
    """
    from src.schemas.migration import SchemaVersion
    from src.schemas.registry import MigrationRegistry
    from src.schemas.migrations.v1_to_v2 import V1ToV2WikiPageMigration
    from src.schemas.migrations.v2_to_v2_1 import V2ToV2_1WikiPageMigration

    MigrationRegistry._clear()
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, V1ToV2WikiPageMigration()
    )
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, V2ToV2_1WikiPageMigration()
    )


def test_cmd_schema_list(tmp_path, monkeypatch, capsys):
    """schema list shows registered schemas + versions."""
    from src.schemas.registry import MigrationRegistry
    from src.schemas.migration import SchemaVersion

    # Reset registry to avoid colliding with the auto-registered v1_to_v2
    # migration that this test module imports at the top.
    MigrationRegistry._clear()
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
    _reset_registry_with_real_migrations()
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
    _reset_registry_with_real_migrations()
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
