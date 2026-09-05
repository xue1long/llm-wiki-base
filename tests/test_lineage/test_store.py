from __future__ import annotations

import sqlite3

import pytest

from src.lineage.api import LineageStore


def test_store_registers_source_idempotently(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash-a", "discovered")
    store.register_source("src-1", "raw/a.md", "hash-a", "discovered")
    assert store.source("src-1")["source_path"] == "raw/a.md"


def test_store_rejects_illegal_transition(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash-a", "discovered")
    with pytest.raises(ValueError):
        store.transition_source("src-1", "discovered", "book_compiled")


def test_store_keeps_many_to_many_artifact_links(tmp_path):
    store = LineageStore.open(tmp_path)
    for source_id in ("src-1", "src-2"):
        store.register_source(source_id, f"raw/{source_id}.md", "hash", "ingested")
    store.link_artifact("wiki", "wiki-synthesis", ("src-1", "src-2"),
                        "wiki/synthesis/x.md", "wiki-hash", "committed")
    assert store.artifact_sources("wiki-synthesis") == ("src-1", "src-2")


def test_store_health_reports_sqlite_integrity(tmp_path):
    store = LineageStore.open(tmp_path)
    health = store.health()
    assert health.integrity_ok is True
    assert health.orphan_links == 0


def test_store_enables_foreign_keys(tmp_path):
    store = LineageStore.open(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        store.link_artifact("wiki", "wiki-1", ("missing",), "x.md", "h", "committed")
