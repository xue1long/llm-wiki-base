"""Tests for friendly error handling in schema CLI commands.

Verifies that:
- `cmd_schema_diff`, `cmd_schema_upgrade`, `cmd_schema_downgrade` catch
  ValueError from SchemaVersion(...) and exit 2 with a stderr message.
- `cmd_schema_backup restore` rejects a missing --name (exit 2 + stderr).
"""
import json

import pytest

from src.cli_ext.schema_cmd import (
    cmd_schema_diff,
    cmd_schema_upgrade,
    cmd_schema_downgrade,
    cmd_schema_backup,
)
from src.schemas.migration import SchemaVersion
from src.schemas.registry import MigrationRegistry


def _reset_registry_with_real_migrations():
    """Reset MigrationRegistry to a known state with the real v2.x migrations."""
    from src.schemas.migrations.v1_to_v2 import V1ToV2WikiPageMigration
    from src.schemas.migrations.v2_to_v2_1 import V2ToV2_1WikiPageMigration

    MigrationRegistry._clear()
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, V1ToV2WikiPageMigration()
    )
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, V2ToV2_1WikiPageMigration()
    )


# ---------- cmd_schema_diff ----------

def test_schema_diff_invalid_from_version_exits_2(monkeypatch, tmp_path, capsys):
    """cmd_schema_diff with a non-version from_v prints stderr + exits 2."""
    _reset_registry_with_real_migrations()
    # Set up a minimal project so we get past ProjectContext.resolve
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(kb)

    args = type("Args", (), {"schema": "wiki_page", "from_v": "garbage", "to_v": "v2.0"})()
    with pytest.raises(SystemExit) as exc:
        cmd_schema_diff(args)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid version" in err
    assert "garbage" in err


def test_schema_diff_invalid_to_version_exits_2(monkeypatch, tmp_path, capsys):
    """cmd_schema_diff with a non-version to_v prints stderr + exits 2."""
    _reset_registry_with_real_migrations()
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(kb)

    args = type("Args", (), {"schema": "wiki_page", "from_v": "v2.0", "to_v": "nope"})()
    with pytest.raises(SystemExit) as exc:
        cmd_schema_diff(args)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid version" in err
    assert "nope" in err


# ---------- cmd_schema_upgrade ----------

def test_schema_upgrade_invalid_version_exits_2(monkeypatch, tmp_path, capsys):
    """cmd_schema_upgrade with a non-version --to prints stderr + exits 2."""
    _reset_registry_with_real_migrations()
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(kb)

    args = type("Args", (), {"to": "garbage", "preview": False})()
    with pytest.raises(SystemExit) as exc:
        cmd_schema_upgrade(args)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid version" in err
    assert "garbage" in err


# ---------- cmd_schema_downgrade ----------

def test_schema_downgrade_invalid_version_exits_2(monkeypatch, tmp_path, capsys):
    """cmd_schema_downgrade with a non-version --to prints stderr + exits 2."""
    _reset_registry_with_real_migrations()
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(kb)

    args = type("Args", (), {"to": "garbage", "preview": False})()
    with pytest.raises(SystemExit) as exc:
        cmd_schema_downgrade(args)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid version" in err
    assert "garbage" in err


# ---------- cmd_schema_backup restore ----------

def test_schema_backup_restore_missing_name_exits_2(monkeypatch, tmp_path, capsys):
    """cmd_schema_backup restore without --name prints stderr + exits 2."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid", "name": "p", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(kb)

    args = type("Args", (), {"action": "restore", "name": None})()
    with pytest.raises(SystemExit) as exc:
        cmd_schema_backup(args)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Backup name required" in err
