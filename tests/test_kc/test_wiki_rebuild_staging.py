"""Task 6 tests: Wiki rebuild staging-first (P1).

Plan 2026-08-29-kc-integrity-idempotency-layered.md §Task 6 — rebuild_wiki_view
先生成内存/staging，全部成功后才调用既有 writer。

Coverage:
1. Successful rebuild: all views compile, all pages written; report
   passed=True, all page_ids listed.
2. Compile failure (empty evidence or empty top-k): no page writes happen
   (staging-first contract); reason_codes contains the failing view id.
3. Write failure (write_page raises mid-batch): partial-write guard — no
   subsequent writes; the already-written pages remain (Wiki is the
   source of truth and may be cleaned up by the caller, but we don't
   roll back completed writes).
4. Empty input list: trivial success (passed=True, page_ids=[]).
5. Rebuild preserves existing valid wiki pages (no destructive
   overwrite of unrelated pages).
"""
from __future__ import annotations


from src.kc.views.wiki_template_compiler import (
    rebuild_wiki_view,
)


def _page(pid: str, body: str = "ok"):
    """Real WikiPage (write_page expects a WikiPage, not a dict)."""
    from src.wiki.core.types import PageType, WikiPage
    return WikiPage(id=pid, title=pid, type=PageType.CONCEPT, body=body)


# ---------------------------------------------------------------------------
# 1. Successful rebuild
# ---------------------------------------------------------------------------


def test_rebuild_wiki_view_writes_all_pages_on_success(tmp_path) -> None:
    from src.wiki.storage.ensure import ensure_knowledge_base

    paths = ensure_knowledge_base(tmp_path)

    views = [
        {
            "page": _page("alpha", body="alpha body"),
            "topic_scope": {"concept_ids": ["alpha"]},
            "publication_version": 1,
            "knowledge_units": [{"id": "ku_alpha", "claim": "Alpha claim"}],
            "conflicts": [],
            "evidence_lookup": {"ku_alpha": {"document_id": "doc", "block_id": "b1"}},
        },
        {
            "page": _page("beta", body="beta body"),
            "topic_scope": {"concept_ids": ["beta"]},
            "publication_version": 1,
            "knowledge_units": [{"id": "ku_beta", "claim": "Beta claim"}],
            "conflicts": [],
            "evidence_lookup": {"ku_beta": {"document_id": "doc", "block_id": "b2"}},
        },
    ]

    report = rebuild_wiki_view(paths, views)

    assert report.passed is True
    assert report.reason_codes == ()
    assert sorted(report.page_ids) == ["alpha", "beta"]
    assert (paths.wiki_concepts / "alpha.md").exists()
    assert (paths.wiki_concepts / "beta.md").exists()


# ---------------------------------------------------------------------------
# 2. Compile failure → no writes
# ---------------------------------------------------------------------------


def test_rebuild_wiki_view_aborts_before_write_on_compile_failure(tmp_path) -> None:
    """Empty top-k (knowledge_units) is treated as a compile failure;
    the staging-first contract means no page writes happen."""
    from src.wiki.storage.ensure import ensure_knowledge_base

    paths = ensure_knowledge_base(tmp_path)

    views = [
        {
            "page": _page("alpha", body="alpha body"),
            "topic_scope": {"concept_ids": ["alpha"]},
            "publication_version": 1,
            "knowledge_units": [],  # empty → compile failure
            "conflicts": [],
            "evidence_lookup": {},
        },
    ]

    report = rebuild_wiki_view(paths, views)

    assert report.passed is False
    assert "compile_failed" in report.reason_codes
    assert "alpha" in report.failed_ids
    # No page file written
    assert not (paths.wiki_concepts / "alpha.md").exists()


# ---------------------------------------------------------------------------
# 3. Write failure → partial-write guard
# ---------------------------------------------------------------------------


def test_rebuild_wiki_view_stops_on_write_failure(tmp_path, monkeypatch) -> None:
    """write_page 在中间失败 → 后续不写；已写的页面不被回滚（Wiki is the
    source of truth and a partial rebuild is reported with the failing
    page in failed_ids; reason_codes 含 write_failed)."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.storage import page_writer

    paths = ensure_knowledge_base(tmp_path)

    views = [
        {"page": _page("a"), "topic_scope": {}, "publication_version": 1,
         "knowledge_units": [{"id": "k1", "claim": "c"}], "conflicts": [],
         "evidence_lookup": {"k1": {"document_id": "d", "block_id": "b"}}},
        {"page": _page("b"), "topic_scope": {}, "publication_version": 1,
         "knowledge_units": [{"id": "k2", "claim": "c"}], "conflicts": [],
         "evidence_lookup": {"k2": {"document_id": "d", "block_id": "b"}}},
        {"page": _page("c"), "topic_scope": {}, "publication_version": 1,
         "knowledge_units": [{"id": "k3", "claim": "c"}], "conflicts": [],
         "evidence_lookup": {"k3": {"document_id": "d", "block_id": "b"}}},
    ]

    original = page_writer.write_page
    calls = []

    def flaky_write(paths_arg, page_arg, **kwargs):
        calls.append(page_arg.id)
        if page_arg.id == "b":
            raise OSError("disk full")
        return original(paths_arg, page_arg, **kwargs)

    # rebuild_wiki_view imports write_page lazily inside the function, so
    # patch the source module attribute.
    monkeypatch.setattr(
        "src.wiki.storage.page_writer.write_page",
        flaky_write,
    )

    report = rebuild_wiki_view(paths, views)

    assert report.passed is False
    assert "write_failed" in report.reason_codes
    assert "b" in report.failed_ids
    # a was written; b failed; c was NOT attempted (staging-first stop)
    assert calls == ["a", "b"]
    assert (paths.wiki_concepts / "a.md").exists()
    assert not (paths.wiki_concepts / "b.md").exists()
    assert not (paths.wiki_concepts / "c.md").exists()
    # 'a' is reported as written; 'b' as failed; 'c' as skipped
    assert "a" in report.page_ids
    assert "c" in report.skipped_ids


# ---------------------------------------------------------------------------
# 4. Empty input → trivial success
# ---------------------------------------------------------------------------


def test_rebuild_wiki_view_empty_input_is_trivial_success(tmp_path) -> None:
    from src.wiki.storage.ensure import ensure_knowledge_base

    paths = ensure_knowledge_base(tmp_path)

    report = rebuild_wiki_view(paths, [])

    assert report.passed is True
    assert report.reason_codes == ()
    assert report.page_ids == []
    assert report.failed_ids == []


# ---------------------------------------------------------------------------
# 5. Rebuild preserves unrelated wiki pages
# ---------------------------------------------------------------------------


def test_rebuild_does_not_overwrite_unrelated_wiki_pages(tmp_path) -> None:
    """rebuild_wiki_view 写自己的 page_ids，但不动其它已存在的 wiki 页。"""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.storage.page_writer import write_page
    from src.wiki.core.types import PageType, WikiPage

    paths = ensure_knowledge_base(tmp_path)
    # Survivor: an unrelated page that must not be touched.
    survivor = WikiPage(
        id="survivor",
        title="Survivor",
        type=PageType.CONCEPT,
        body="original survivor body",
    )
    write_page(paths, survivor)
    original_survivor_body = (paths.wiki_concepts / "survivor.md").read_text(
        encoding="utf-8",
    )

    views = [
        {"page": _page("rebuild-target", body="new body"),
         "topic_scope": {}, "publication_version": 1,
         "knowledge_units": [{"id": "ku", "claim": "c"}], "conflicts": [],
         "evidence_lookup": {"ku": {"document_id": "d", "block_id": "b"}}},
    ]

    report = rebuild_wiki_view(paths, views)

    assert report.passed is True
    # Survivor still intact
    assert (paths.wiki_concepts / "survivor.md").read_text(
        encoding="utf-8",
    ) == original_survivor_body
    # Rebuild target written
    assert (paths.wiki_concepts / "rebuild-target.md").exists()
