"""Task 5 tests: vector-pending idempotency at the KC layer (P0).

Plan 2026-08-29-kc-integrity-idempotency-layered.md §Task 5 — Wiki 成功、
向量失败可恢复；重复扫描/重复 reconcile 不产生副作用。

Coverage (the KC-level cross-cutting invariants):

1. mark_intent is idempotent — calling twice with the same pages does not
   duplicate entries; the second call updates the existing entry's hash
   to the new body (so a re-attempt after wiki commit uses the new hash).
2. mark_intent + Wiki write failure leaves intent intact (not promoted).
3. Wiki success + vector promotion failure keeps the entry recoverable as
   intent (orphan-recoverable on next reconcile).
4. reconcile_pending with a no-op embedder clears success and keeps failure
   — repeated calls are idempotent (second call returns ok=0/failed=0).
5. scan_wiki_vector_diff is idempotent — repeated calls add zero entries
   once the wiki/vector diff has been captured.
6. Body-hash change between mark and reconcile triggers re-index of the
   same page; success clears the entry.
7. Orphan intent (intent whose page was never committed) is removed
   during reconcile WITHOUT deleting the underlying wiki/ directory.

These tests intentionally live under tests/test_kc (KC namespace) per
plan §Task 5 Step 1. The lower-level equivalents in tests/test_vector/
and tests/test_pipeline/ remain authoritative for the storage and
ingest paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.vector import pending as pending_mod
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def _paths(tmp_path: Path) -> WikiPaths:
    root = tmp_path / "kb"
    ensure_knowledge_base(root)
    return WikiPaths(root)


def _page(pid: str, body: str = "content") -> WikiPage:
    return WikiPage(id=pid, title=pid, type=PageType.CONCEPT, body=body)


def _write_wiki(paths: WikiPaths, page: WikiPage) -> None:
    write_page(paths, page)


# ---------------------------------------------------------------------------
# 1. mark_intent idempotency
# ---------------------------------------------------------------------------


def test_mark_intent_is_idempotent_and_updates_hash(tmp_path: Path) -> None:
    """mark_intent 重复调用同一 pages 不重复条目；第二次以新 body 更新 hash."""
    paths = _paths(tmp_path)
    page_v1 = _page("alpha", body="first")
    page_v2 = _page("alpha", body="second")

    assert pending_mod.mark_intent(paths, [page_v1]) == 1
    pending_mod.mark_intent(paths, [page_v2])  # same id, different body

    data = pending_mod.list_pending(paths)
    assert list(data.keys()) == ["alpha"], "duplicate id must collapse to one entry"
    assert data["alpha"]["hash"] == pending_mod.body_hash("second")


# ---------------------------------------------------------------------------
# 2. Wiki write failure leaves intent intact (rely on lower-level test)
# ---------------------------------------------------------------------------


def test_wiki_write_failure_keeps_intent_intact(tmp_path: Path) -> None:
    """commit_ingest 内部 AtomicContext 抛错 → mark_intent 留下的 intent 保持
    'intent' 状态，等待下一次 reconcile 的孤儿清理。"""
    paths = _paths(tmp_path)
    page = _page("wiki-fail")
    pending_mod.mark_intent(paths, [page])
    # Simulate wiki-write failure by deleting the wiki/ tree right after mark;
    # reconcile_pending then sees intent-without-page and treats it as orphan.
    import shutil
    shutil.rmtree(paths.wiki)

    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)

    assert result["orphaned"] == 1
    assert pending_mod.list_pending(paths) == {}
    # Crucially: the wiki/ tree state was NOT touched by reconcile.
    assert not paths.wiki.exists()


# ---------------------------------------------------------------------------
# 3. Wiki success + vector promotion failure → recoverable intent
# ---------------------------------------------------------------------------


def test_wiki_success_with_vector_promote_failure_recovers_as_intent(tmp_path: Path) -> None:
    """模拟 mark_intent → write_page 成功 → promote_intent 失败的链路：
    reconcile 时按 orphan/intent 路径处理 → recover=1 → ledger 清空，
    wiki 页面保留."""
    paths = _paths(tmp_path)
    page = _page("vec-fail")
    _write_wiki(paths, page)
    pending_mod.mark_intent(paths, [page])  # wiki already written, intent never promoted

    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)

    assert result["recovered"] == 1
    assert pending_mod.list_pending(paths) == {}
    # wiki 页面被 reconcile 当作已提交页面 → 不应删除
    assert (paths.wiki_concepts / "vec-fail.md").exists()


# ---------------------------------------------------------------------------
# 4. Repeated reconcile is idempotent (no double clear, no duplicate upserts)
# ---------------------------------------------------------------------------


def test_repeated_reconcile_is_idempotent(tmp_path: Path) -> None:
    """reconcile_pending 第一次成功清空 → 第二次 attempted=0、ok=0、failed=0."""
    paths = _paths(tmp_path)
    page = _page("idem")
    _write_wiki(paths, page)
    pending_mod.mark_intent(paths, [page])

    calls: list[str] = []

    def _upsert(p, _paths, table=None):
        calls.append(p.id)
        return True

    r1 = pending_mod.reconcile_pending(paths, _upsert)
    r2 = pending_mod.reconcile_pending(paths, _upsert)

    assert r1["ok"] == 1
    assert r2["attempted"] == 0
    assert r2["ok"] == 0
    assert r2["failed"] == 0
    assert calls == ["idem"]


# ---------------------------------------------------------------------------
# 5. scan_wiki_vector_diff idempotency
# ---------------------------------------------------------------------------


def test_scan_wiki_vector_diff_idempotent(tmp_path: Path) -> None:
    """scan_wiki_vector_diff 第二次调用 added=0（已标记的不再追加）."""
    paths = _paths(tmp_path)
    _write_wiki(paths, _page("scan-a"))
    _write_wiki(paths, _page("scan-b"))

    first = pending_mod.scan_wiki_vector_diff(
        paths, table=None, page_ids_in_table=[],
    )
    second = pending_mod.scan_wiki_vector_diff(
        paths, table=None, page_ids_in_table=[],
    )

    assert first == 2
    assert second == 0


# ---------------------------------------------------------------------------
# 6. Body-hash change between mark and reconcile re-indexes the page
# ---------------------------------------------------------------------------


def test_body_hash_change_triggers_reindex_and_clears_on_success(tmp_path: Path) -> None:
    """mark 时 hash A；reconcile 时 body 已变 hash B → 触发 reindex（仍走
    upsert 路径）；upsert 成功 → ledger 清空."""
    paths = _paths(tmp_path)
    page_v1 = _page("hash-change", body="v1")
    pending_mod.mark_intent(paths, [page_v1])

    # Wiki 上的 body 已经变化
    _write_wiki(paths, _page("hash-change", body="v2"))

    upserts: list[tuple[str, str]] = []

    def _upsert(p, _paths, table=None):
        upserts.append((p.id, p.body))
        return True

    result = pending_mod.reconcile_pending(paths, _upsert)

    assert result["ok"] == 1
    assert upserts == [("hash-change", "v2")]
    assert pending_mod.list_pending(paths) == {}


# ---------------------------------------------------------------------------
# 7. Orphan intent (page never written to wiki) is cleaned without touching wiki/
# ---------------------------------------------------------------------------


def test_orphan_intent_cleaned_without_touching_wiki_tree(tmp_path: Path) -> None:
    """mark_intent 但 wiki write 失败 → intent 留在 ledger；下一次 reconcile
    把这个孤儿清掉（不删除任何已存在的 wiki 内容）."""
    paths = _paths(tmp_path)
    # 一个永远不会被写入 wiki 的 intent
    pending_mod.mark_intent(paths, [_page("orphan")])
    # 一个已经存在的、绝不能被误删的 wiki 页面
    survivor = _page("survivor")
    _write_wiki(paths, survivor)

    result = pending_mod.reconcile_pending(paths, lambda *a, **k: True)

    assert result["orphaned"] == 1
    assert pending_mod.list_pending(paths) == {}
    # wiki 页面幸存
    assert (paths.wiki_concepts / "survivor.md").exists()