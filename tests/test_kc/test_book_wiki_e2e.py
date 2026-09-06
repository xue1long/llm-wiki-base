"""Failure injection checks for the V3 wiki-to-book safety boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.kc.views.book.wiki.compiler import (
    build_from_wiki,
    compile_book,
    publish_book,
    resolve_active_version,
)
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.preflight import LockBusyError, acquire_run_lock, release_run_lock
from src.kc.views.book.wiki.scanner import SnapshotChangedError, scan_wiki_snapshot


def _project(tmp_path: Path, pages: int = 2) -> Path:
    root = tmp_path / "project"
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    for kind in ("concepts", "entities", "synthesis"):
        (root / "wiki" / kind).mkdir(parents=True)
    for i in range(pages):
        (root / "wiki" / "concepts" / f"p{i}.md").write_text(
            f"---\nid: p{i}\ntitle: Page {i}\ntype: concept\n---\nBody {i}\n", encoding="utf-8"
        )
    return root


def _artifact(tmp_path: Path):
    page = PageRecord("p1", "Title", "concept", "concepts/p1.md", "tax", "Summary", (
        ContentBlock("p1:0", "p1", "Heading", "Body", 0),
    ), (), "abc", 4, None)
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{"chapter_id": "c1", "title": "Chapter", "page_ids": ["p1"], "overview_refs": ["p1"]}],
    }]}]
    return compile_book(snapshot, outline, {"p1": page}, fingerprint={}, state_dir=tmp_path / ".index")


def test_dynamic_page_count_and_dry_run_do_not_publish(tmp_path):
    root = _project(tmp_path, pages=7)
    result = build_from_wiki(root, output_dir=root / "book-wiki")
    assert result["status"] == "planned"
    assert result["snapshot_id"]
    assert not (root / "book-wiki" / "CURRENT.json").exists()


def test_pointer_corruption_is_fail_closed_and_old_release_survives_pointer_failure(tmp_path, monkeypatch):
    artifact = _artifact(tmp_path)
    output = tmp_path / "book-wiki"
    first = publish_book(artifact, output, apply=True, lock=None)
    assert first.status == "committed"
    old = resolve_active_version(output)
    assert old is not None
    pointer = output / "CURRENT.json"
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    payload["manifest_sha256"] = "corrupt"
    pointer.write_text(json.dumps(payload), encoding="utf-8")
    assert resolve_active_version(output) is None

    second = _artifact(tmp_path)
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("pointer down")))
    failed = publish_book(second, output, apply=True, lock=None)
    monkeypatch.setattr(os, "replace", real_replace)
    assert failed.status == "failed"
    assert old.is_dir()
    assert resolve_active_version(output) is None  # corrupt old pointer remains untouched


def test_lock_busy_and_exception_release(tmp_path):
    path = tmp_path / "run.lock"
    first = acquire_run_lock(path, stale_after_seconds=3600)
    with pytest.raises(LockBusyError):
        acquire_run_lock(path, stale_after_seconds=3600)
    release_run_lock(first)
    with pytest.raises(RuntimeError):
        with acquire_run_lock(path, stale_after_seconds=3600):
            raise RuntimeError("boom")
    assert not path.exists()


def test_snapshot_change_is_rejected(tmp_path, monkeypatch):
    root = _project(tmp_path, pages=1)
    original = Path.read_bytes
    changed = {"done": False}

    def read_bytes(path: Path):
        data = original(path)
        if path.name == "p0.md" and not changed["done"]:
            changed["done"] = True
            path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(SnapshotChangedError):
        scan_wiki_snapshot(root / "wiki")


def test_unresolved_relation_is_reported_in_manifest(tmp_path):
    page = PageRecord("p1", "Title", "concept", "concepts/p1.md", "tax", "Summary", (
        ContentBlock("p1:0", "p1", None, "Body", 0),
    ), (("related", "missing"),), "abc", 4, None)
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{"chapter_id": "c1", "title": "C", "page_ids": ["p1"], "overview_refs": ["p1"]}],
    }]}]
    artifact = compile_book(snapshot, outline, {"p1": page}, fingerprint={}, state_dir=tmp_path / ".index")
    assert artifact.manifest["relation_stats"]["unresolved"] == 1
    assert artifact.manifest["relation_stats"]["unresolved_targets"] == ["missing"]


def test_unresolved_relation_over_threshold_blocks_build(tmp_path):
    root = _project(tmp_path, pages=1)
    page = root / "wiki" / "concepts" / "p0.md"
    page.write_text(
        "---\nid: p0\ntitle: Page 0\ntype: concept\nrelations:\n  - type: related\n    target: absent\n---\nBody\n",
        encoding="utf-8",
    )
    result = build_from_wiki(root, output_dir=root / "book-wiki")
    assert result["status"] == "failed"
    assert "unresolved-relation-over-threshold" in result["reason_codes"]


def test_build_lock_busy_is_a_blocking_result(tmp_path):
    root = _project(tmp_path, pages=1)
    lock = acquire_run_lock(root / ".index" / "book-wiki.lock", stale_after_seconds=3600)
    try:
        with pytest.raises(LockBusyError):
            build_from_wiki(root, output_dir=root / "book-wiki", apply=True)
    finally:
        release_run_lock(lock)


def test_staging_write_failure_does_not_create_pointer(tmp_path, monkeypatch):
    root = _project(tmp_path, pages=1)
    original = Path.write_text

    def fail(path: Path, data: str, *args, **kwargs):
        if ".index" in path.parts and "versions" in path.parts:
            raise OSError("disk full")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(OSError):
        build_from_wiki(root, output_dir=root / "book-wiki", apply=False)
    assert not (root / "book-wiki" / "CURRENT.json").exists()
