from __future__ import annotations

import json
from pathlib import Path

from src.integrations.gbrain.api import (
    build_wiki_snapshot,
    load_manifest,
    reconcile_manifest,
    save_manifest,
)
from src.integrations.gbrain.types import SearchConfig
from src.integrations.gbrain.sync import run_initial_import


def _project(root):
    metadata = root / ".llm-wiki"
    metadata.mkdir(parents=True)
    (metadata / "project.json").write_text(
        json.dumps({"id": "11111111-1111-4111-8111-111111111111", "name": "demo"}),
        encoding="utf-8",
    )


def test_snapshot_excludes_catalog_archive_and_stubs(tmp_path):
    _project(tmp_path)
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "_archive").mkdir()
    (tmp_path / "wiki" / "_stubs").mkdir()
    (tmp_path / "wiki" / "sources" / "a.md").write_text("alpha", encoding="utf-8")
    (tmp_path / "wiki" / "index.md").write_text("catalog", encoding="utf-8")
    (tmp_path / "wiki" / "log.md").write_text("log", encoding="utf-8")
    (tmp_path / "wiki" / "_archive" / "old.md").write_text("old", encoding="utf-8")
    (tmp_path / "wiki" / "_stubs" / "stub.md").write_text("stub", encoding="utf-8")

    snapshot = build_wiki_snapshot(tmp_path)

    assert [item.slug for item in snapshot] == ["wiki/sources/a"]
    assert snapshot[0].path == "wiki/sources/a.md"
    assert snapshot[0].page_type == "source"
    assert len(snapshot[0].content_hash) == 64


def test_snapshot_boundary_excludes_non_searchable_project_content(tmp_path):
    _project(tmp_path)
    for relative in (
        "wiki/sources/keep.md",
        "wiki/_archive/old.md",
        "wiki/_stubs/stub.md",
        "wiki/.index/hidden.md",
        "wiki/book/book.md",
        "wiki/sources/notes.txt",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    (tmp_path / ".index" / "gbrain" / "outside.md").parent.mkdir(parents=True)
    (tmp_path / ".index" / "gbrain" / "outside.md").write_text("outside", encoding="utf-8")
    (tmp_path / "book").mkdir()
    (tmp_path / "book" / "chapter.md").write_text("book", encoding="utf-8")

    assert [entry.path for entry in build_wiki_snapshot(tmp_path)] == ["wiki/sources/keep.md"]


def test_initial_import_uses_the_snapshot_boundary(tmp_path):
    _project(tmp_path)
    config = SearchConfig(source_id="source-1", source_name="demo")
    for relative in ("wiki/sources/keep.md", "wiki/_archive/old.md", "wiki/_stubs/stub.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    imported = []

    def runner(command, cwd):
        if command[3] == "sources" and command[4] == "status":
            return type("Result", (), {"stdout": json.dumps({"sources": []})})()
        if command[3] == "import":
            imported.extend(path.relative_to(Path(command[4])).as_posix() for path in Path(command[4]).rglob("*.md"))

    run_initial_import(tmp_path, config, tmp_path / "runtime", runner=runner)

    assert imported == ["wiki/sources/keep.md"]


def test_initial_import_reuses_registered_source(tmp_path):
    _project(tmp_path)
    config = SearchConfig(source_id="source-1", source_name="demo")
    page = tmp_path / "wiki" / "sources" / "keep.md"
    page.parent.mkdir(parents=True)
    page.write_text("keep", encoding="utf-8")
    calls = []
    registered = False

    def runner(command, cwd):
        nonlocal registered
        calls.append(command)
        if command[3] == "sources" and command[4] == "add":
            registered = True
        return type(
            "Result",
            (),
            {
                "stdout": json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": config.source_id,
                                "local_path": str(tmp_path / "wiki"),
                            }
                        ]
                        if registered
                        else []
                    }
                )
            },
        )()

    run_initial_import(tmp_path, config, tmp_path / "runtime", runner=runner)
    run_initial_import(tmp_path, config, tmp_path / "runtime", runner=runner)

    assert [command[4] for command in calls if command[3] == "sources"] == ["status", "add", "status"]
    assert len([command for command in calls if command[3] == "import"]) == 2


def test_manifest_reconcile_reports_add_update_delete(tmp_path):
    _project(tmp_path)
    source_dir = tmp_path / "wiki" / "concepts"
    source_dir.mkdir(parents=True)
    old = source_dir / "old.md"
    keep = source_dir / "keep.md"
    old.write_text("old", encoding="utf-8")
    keep.write_text("before", encoding="utf-8")
    save_manifest(tmp_path, build_wiki_snapshot(tmp_path))

    old.unlink()
    keep.write_text("after", encoding="utf-8")
    (source_dir / "new.md").write_text("new", encoding="utf-8")
    plan = reconcile_manifest(tmp_path)

    assert plan.added == ["wiki/concepts/new"]
    assert plan.updated == ["wiki/concepts/keep"]
    assert plan.deleted == ["wiki/concepts/old"]
    assert load_manifest(tmp_path)["wiki/concepts/keep"]["path"] == "wiki/concepts/keep.md"
