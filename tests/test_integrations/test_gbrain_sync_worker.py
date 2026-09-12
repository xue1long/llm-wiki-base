from __future__ import annotations

import json

from src.integrations.gbrain.api import (
    build_wiki_snapshot,
    ensure_search_config,
    save_manifest,
)
from src.integrations.gbrain.sync import (
    build_mcp_intent,
    build_import_command,
    build_source_add_command,
    reconcile_and_sync,
    run_initial_import,
)
from src.integrations.gbrain.worker import run_incremental_sync


def _project(root):
    metadata = root / ".llm-wiki"
    metadata.mkdir(parents=True)
    (metadata / "project.json").write_text(
        json.dumps({"id": "11111111-1111-4111-8111-111111111111", "name": "demo"}),
        encoding="utf-8",
    )


def test_import_command_is_fixed_to_project_wiki_and_source(tmp_path):
    _project(tmp_path)
    config = ensure_search_config(tmp_path)

    command = build_import_command(tmp_path, config, tmp_path / "external" / "gbrain")

    assert command == [
        "bun",
        "run",
        "src/cli.ts",
        "import",
        str(tmp_path / "wiki"),
        "--source-id",
        config.source_id,
    ]

    assert build_source_add_command(tmp_path, config) == [
        "bun",
        "run",
        "src/cli.ts",
        "sources",
        "add",
        config.source_id,
        "--path",
        str(tmp_path / "wiki"),
        "--name",
        config.source_name,
        "--no-federated",
    ]

    assert build_mcp_intent("upsert", config.source_id, "wiki/sources/a", "body") == {
        "tool": "put_page",
        "source_id": config.source_id,
        "arguments": {"slug": "wiki/sources/a", "content": "body"},
    }
    assert build_mcp_intent("delete", config.source_id, "wiki/sources/a", None)["tool"] == "delete_page"
    assert build_mcp_intent("restore", config.source_id, "wiki/sources/a", None)["tool"] == "restore_page"

    calls = []

    def runner(command, cwd):
        calls.append((command, cwd))
        if command[3] == "sources" and command[4] == "status":
            return type("Result", (), {"stdout": '{"sources": []}'})()

    run_initial_import(tmp_path, config, tmp_path / "external" / "gbrain", runner=runner)
    assert len(calls) == 3
    assert calls[0][0][3:5] == ["sources", "status"]
    assert calls[1][0] == build_source_add_command(tmp_path, config)
    assert calls[2][0][0:4] == command[0:4]
    assert calls[2][0][5:] == command[5:]
    assert all(cwd == tmp_path / "external" / "gbrain" for _, cwd in calls)


def test_reconcile_syncs_changes_and_only_commits_manifest_after_success(tmp_path):
    _project(tmp_path)
    page_dir = tmp_path / "wiki" / "sources"
    page_dir.mkdir(parents=True)
    old = page_dir / "old.md"
    keep = page_dir / "keep.md"
    old.write_text("old", encoding="utf-8")
    keep.write_text("before", encoding="utf-8")
    save_manifest(tmp_path, build_wiki_snapshot(tmp_path))
    old.unlink()
    keep.write_text("after", encoding="utf-8")
    new = page_dir / "new.md"
    new.write_text("new", encoding="utf-8")

    calls = []
    result = reconcile_and_sync(tmp_path, lambda *args: calls.append(args))

    assert result.success is True
    assert [(call[0], call[2]) for call in calls] == [
        ("upsert", "wiki/sources/keep"),
        ("upsert", "wiki/sources/new"),
        ("delete", "wiki/sources/old"),
    ]
    assert result.failed == []


def test_reconcile_retries_and_keeps_manifest_on_failure(tmp_path):
    _project(tmp_path)
    page_dir = tmp_path / "wiki" / "sources"
    page_dir.mkdir(parents=True)
    page = page_dir / "new.md"
    page.write_text("new", encoding="utf-8")
    calls = []

    def apply(*args):
        calls.append(args)
        raise RuntimeError("mcp down")

    result = reconcile_and_sync(tmp_path, apply, max_attempts=2)

    assert result.success is False
    assert result.failed == ["wiki/sources/new"]
    assert len(calls) == 2


def test_run_incremental_sync_updates_remote_and_keeps_ready_state(tmp_path):
    _project(tmp_path)
    page_dir = tmp_path / "wiki" / "sources"
    page_dir.mkdir(parents=True)
    page = page_dir / "new.md"
    page.write_text("new", encoding="utf-8")
    config = ensure_search_config(tmp_path)
    save_manifest(tmp_path, [])
    calls = []

    result = run_incremental_sync(
        tmp_path,
        tmp_path / "runtime",
        apply_intent=lambda *args: calls.append(args),
    )

    assert result.success is True
    assert calls == [("upsert", config.source_id, "wiki/sources/new", "new")]


def test_reconcile_restores_tombstone_before_upsert(tmp_path):
    _project(tmp_path)
    page = tmp_path / "wiki" / "sources" / "old.md"
    page.parent.mkdir(parents=True)
    page.write_text("old", encoding="utf-8")
    save_manifest(tmp_path, build_wiki_snapshot(tmp_path))
    page.unlink()
    reconcile_and_sync(tmp_path, lambda *args: None)

    page.write_text("restored", encoding="utf-8")
    calls = []
    result = reconcile_and_sync(tmp_path, lambda *args: calls.append(args))

    assert result.success is True
    assert [(call[0], call[2]) for call in calls] == [
        ("restore", "wiki/sources/old"),
        ("upsert", "wiki/sources/old"),
    ]
