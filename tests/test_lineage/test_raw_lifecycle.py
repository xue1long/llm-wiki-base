from __future__ import annotations

import pytest

from src.lineage.api import LineageStore


def test_discover_raw_registers_new_source_and_hash(tmp_path):
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True)
    (raw / "a.md").write_text("one", encoding="utf-8")
    result = LineageStore.open(tmp_path).discover_raw_sources()
    assert result.complete is True
    assert result.changes[0].status == "discovered"
    assert result.changes[0].source_path == "raw/sources/a.md"


def test_changed_raw_becomes_stale(tmp_path):
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True)
    path = raw / "a.md"
    path.write_text("one", encoding="utf-8")
    store = LineageStore.open(tmp_path)
    first = store.discover_raw_sources()
    source_id = first.changes[0].source_id
    store.register_source(source_id, "raw/sources/a.md", first.changes[0].source_hash, "ingested")
    path.write_text("two", encoding="utf-8")
    result = store.discover_raw_sources()
    assert result.changes[0].status == "stale"


def test_assessment_and_explicit_delete_are_visible(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.bin", "hash", "discovered")
    store.record_raw_assessment("src-1", "raw_unsupported", ("unsupported_format",))
    assert store.source("src-1")["status"] == "raw_unsupported"
    store.record_raw_tombstone("src-1", "raw/sources/a.bin", "hash", explicit=True)
    assert store.source("src-1")["status"] == "deleted"


def test_incomplete_scan_does_not_tombstone_missing_source(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.md", "hash", "ingested")
    result = store.discover_raw_sources()
    assert result.complete is False
    assert result.changes == ()
    assert store.source("src-1")["status"] == "ingested"


def test_scan_io_failure_is_incomplete(monkeypatch, tmp_path):
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True)
    store = LineageStore.open(tmp_path)
    monkeypatch.setattr(type(raw), "rglob", lambda *_: (_ for _ in ()).throw(OSError("denied")))
    assert store.discover_raw_sources().complete is False


def test_tombstone_requires_explicit_confirmation(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.md", "hash", "ingested")
    with pytest.raises(ValueError):
        store.record_raw_tombstone("src-1", "raw/sources/a.md", "hash")


def test_mark_ingested_updates_existing_raw_only(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.md", "hash", "discovered")
    assert store.mark_raw_ingested("raw/sources/a.md") == "src-1"
    assert store.source("src-1")["status"] == "ingested"
    assert store.mark_raw_ingested("raw/sources/missing.md") is None
