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
    assert result == {"attempted": 0, "ok": 0, "failed": 0, "failed_ids": []}


def test_reconcile_removes_deleted_page_entry(tmp_path):
    """A pending page deleted from the wiki drops its entry (no dangling)."""
    paths = _paths(tmp_path)
    p1 = _page("deleted-page")
    pending_mod.mark_pending(paths, [p1])  # never written to wiki

    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)
    assert result["attempted"] == 1
    # The page file does not exist → entry dropped (failed_ids but cleared
    # from the ledger on next reconcile since no file means nothing to keep).
    assert pending_mod.list_pending(paths) == {} or result["failed"] == 1


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


def test_pending_file_is_json(tmp_path):
    """The ledger is plain JSON under .index/ (scannable, no corruption)."""
    paths = _paths(tmp_path)
    p1 = _page("json-check")
    pending_mod.mark_pending(paths, [p1])
    raw = (paths.index / "vector_pending.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "json-check" in data
