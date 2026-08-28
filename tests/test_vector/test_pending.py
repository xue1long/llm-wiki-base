"""R7 — vector-pending compensation ledger tests.

Coverage:
- mark_pending persists page ids + body hashes into .index/vector_pending.json.
- clear_pending removes entries after a successful upsert.
- reconcile_pending re-indexes pending pages, clears successes, keeps failures.
- scan_wiki_vector_diff re-marks wiki pages missing from the vector table
  (crash-recovery safety net).
- Idempotency: reconcile success clears; failure keeps the entry pending.
"""
import json

import pytest

from src.vector import pending as pending_mod
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage


def _paths(tmp_path) -> WikiPaths:
    root = tmp_path / "kb"
    root.mkdir()
    for sub in ("sources", "entities", "concepts", "synthesis"):
        (root / "wiki" / sub).mkdir(parents=True, exist_ok=True)
    return WikiPaths(root)


def _write_page(paths: WikiPaths, page: WikiPage) -> None:
    from src.wiki.storage.page_writer import write_page
    write_page(paths, page)


def _page(pid: str, body: str = "content") -> WikiPage:
    return WikiPage(id=pid, title=pid, type=PageType.CONCEPT, body=body)


# ---------------------------------------------------------------------------
# 1. mark / clear roundtrip
# ---------------------------------------------------------------------------

def test_mark_and_clear_roundtrip(tmp_path):
    paths = _paths(tmp_path)
    p1 = _page("alpha")

    pending_mod.mark_pending(paths, [p1])
    data = pending_mod.list_pending(paths)
    assert "alpha" in data
    assert data["alpha"]["hash"] == pending_mod.body_hash("content")

    cleared = pending_mod.clear_pending(paths, ["alpha"])
    assert cleared == 1
    assert pending_mod.list_pending(paths) == {}


def test_mark_intent_persists_intent_state(tmp_path):
    paths = _paths(tmp_path)
    page = _page("intent-page")

    assert pending_mod.mark_intent(paths, [page]) == 1

    data = pending_mod.list_pending(paths)
    assert data["intent-page"]["publication_state"] == "intent"


def test_promote_intent_marks_committed_page_pending(tmp_path):
    paths = _paths(tmp_path)
    page = _page("promote-page")
    pending_mod.mark_intent(paths, [page])

    assert pending_mod.promote_intent(paths, ["promote-page"]) == 1

    data = pending_mod.list_pending(paths)
    assert data["promote-page"]["publication_state"] == "pending"


def test_mark_absent_clear_is_noop(tmp_path):
    paths = _paths(tmp_path)
    assert pending_mod.clear_pending(paths, ["nope"]) == 0


# ---------------------------------------------------------------------------
# 2. reconcile
# ---------------------------------------------------------------------------

def test_reconcile_clears_successful(tmp_path):
    paths = _paths(tmp_path)
    p1 = _page("alpha")
    _write_page(paths, p1)
    pending_mod.mark_pending(paths, [p1])

    calls = []
    def _fake_upsert(page, paths, table=None):
        calls.append(page.id)
        return True

    result = pending_mod.reconcile_pending(paths, _fake_upsert)
    assert calls == ["alpha"]
    assert result["ok"] == 1
    assert result["failed"] == 0
    assert pending_mod.list_pending(paths) == {}


def test_reconcile_keeps_failed(tmp_path):
    paths = _paths(tmp_path)
    p1 = _page("beta")
    _write_page(paths, p1)
    pending_mod.mark_pending(paths, [p1])

    def _failing_upsert(page, paths, table=None):
        return False

    result = pending_mod.reconcile_pending(paths, _failing_upsert)
    assert result["failed"] == 1
    assert result["failed_ids"] == ["beta"]
    # Still pending for a later retry.
    assert "beta" in pending_mod.list_pending(paths)


def test_reconcile_raises_keeps_pending(tmp_path):
    paths = _paths(tmp_path)
    p1 = _page("gamma")
    _write_page(paths, p1)
    pending_mod.mark_pending(paths, [p1])

    def _throwing_upsert(page, paths, table=None):
        raise RuntimeError("provider down")

    result = pending_mod.reconcile_pending(paths, _throwing_upsert)
    assert result["failed"] == 1
    assert "gamma" in pending_mod.list_pending(paths)


def test_reconcile_empty_is_noop(tmp_path):
    paths = _paths(tmp_path)
    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)
    assert result["attempted"] == 0
    assert result["ok"] == 0
    assert result["failed"] == 0
    assert result["failed_ids"] == []
    assert result["intent"] == 0
    assert result["pending"] == 0
    assert result["recovered"] == 0
    assert result["orphaned"] == 0


def test_reconcile_recovers_intent_and_is_idempotent(tmp_path):
    paths = _paths(tmp_path)
    page = _page("recoverable")
    _write_page(paths, page)
    pending_mod.mark_intent(paths, [page])
    calls = []

    def _upsert(page, paths, table=None):
        calls.append(page.id)
        return True

    first = pending_mod.reconcile_pending(paths, _upsert)
    second = pending_mod.reconcile_pending(paths, _upsert)

    assert first["recovered"] == 1
    assert first["intent"] == 1
    assert second["attempted"] == 0
    assert calls == ["recoverable"]


def test_reconcile_removes_orphaned_intent_only(tmp_path):
    paths = _paths(tmp_path)
    page = _page("orphaned")
    pending_mod.mark_intent(paths, [page])

    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)

    assert result["orphaned"] == 1
    assert result["failed"] == 0
    assert pending_mod.list_pending(paths) == {}


def test_reconcile_keeps_missing_pending_entry(tmp_path):
    """A committed-page pending entry stays retryable when its file is absent."""
    paths = _paths(tmp_path)
    p1 = _page("deleted-page")
    pending_mod.mark_pending(paths, [p1])  # never written to wiki

    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)
    assert result["attempted"] == 1
    assert result["failed"] == 1
    assert pending_mod.list_pending(paths)["deleted-page"]["publication_state"] == "pending"


# ---------------------------------------------------------------------------
# 3. scan_wiki_vector_diff (crash recovery)
# ---------------------------------------------------------------------------

def test_scan_marks_missing_pages(tmp_path):
    paths = _paths(tmp_path)
    p1 = _page("in-wiki")
    _write_page(paths, p1)

    added = pending_mod.scan_wiki_vector_diff(paths, table=None, page_ids_in_table=[])
    assert added == 1
    data = pending_mod.list_pending(paths)
    assert "in-wiki" in data
    assert data["in-wiki"]["publication_state"] == "pending"


def test_scan_skips_indexed_and_pending(tmp_path):
    paths = _paths(tmp_path)
    p1 = _page("indexed")
    p2 = _page("already-pending")
    _write_page(paths, p1)
    _write_page(paths, p2)
    pending_mod.mark_pending(paths, [p2])

    added = pending_mod.scan_wiki_vector_diff(paths, table=None, page_ids_in_table=["indexed"])
    assert added == 0  # both already known (indexed or pending)
    data = pending_mod.list_pending(paths)
    assert "indexed" not in data
    assert "already-pending" in data
    assert data["already-pending"]["publication_state"] == "pending"


def test_scan_treats_indexed_chunk_as_indexed_page(tmp_path):
    paths = _paths(tmp_path)
    page = _page("chunked-page")
    _write_page(paths, page)

    added = pending_mod.scan_wiki_vector_diff(
        paths, table=None, page_ids_in_table=["chunked-page-chunk-0"]
    )

    assert added == 0
    assert pending_mod.list_pending(paths) == {}


def test_pending_file_is_json(tmp_path):
    """The ledger is plain JSON under .index/ (scannable, no corruption)."""
    paths = _paths(tmp_path)
    p1 = _page("json-check")
    pending_mod.mark_pending(paths, [p1])
    raw = (paths.index / "vector_pending.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "json-check" in data


def test_corrupt_ledger_fails_closed_without_overwrite(tmp_path):
    paths = _paths(tmp_path)
    ledger = pending_mod.pending_path(paths)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="ledger"):
        pending_mod.mark_pending(paths, [_page("must-survive")])

    assert ledger.read_text(encoding="utf-8") == "{not-json"
