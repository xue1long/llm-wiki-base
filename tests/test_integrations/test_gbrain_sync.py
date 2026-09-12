from __future__ import annotations

import json

from src.integrations.gbrain.api import (
    build_wiki_snapshot,
    load_manifest,
    reconcile_manifest,
    save_manifest,
)


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
