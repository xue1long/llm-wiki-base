"""L3 publication-intent ordering around ``commit_ingest``."""
from __future__ import annotations

import pytest

from src.pipeline import ingest as ingest_mod
from src.vector import pending as pending_mod
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base


def _setup(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "source.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("source", encoding="utf-8")
    return paths, raw


def _page(page_id: str = "page-1") -> WikiPage:
    return WikiPage(
        id=page_id,
        title=page_id,
        type=PageType.CONCEPT,
        body="body",
    )


@pytest.mark.asyncio
async def test_commit_creates_intent_before_first_wiki_write(tmp_path, monkeypatch):
    paths, raw = _setup(tmp_path)
    page = _page()
    states = []
    original_write_page = ingest_mod.write_page

    def observe_write(paths_arg, page_arg, **kwargs):
        states.append(pending_mod.list_pending(paths_arg)[page_arg.id]["publication_state"])
        return original_write_page(paths_arg, page_arg, **kwargs)

    monkeypatch.setattr(ingest_mod, "write_page", observe_write)

    await ingest_mod.commit_ingest(paths, raw, [page], task_id="intent-order")

    assert states == ["intent"]
    assert pending_mod.list_pending(paths)[page.id]["publication_state"] == "pending"
    assert (paths.index / "staging" / "intent-order" / "publish.marker").exists()


@pytest.mark.asyncio
async def test_ledger_failure_aborts_before_wiki_write(tmp_path, monkeypatch):
    paths, raw = _setup(tmp_path)
    page = _page()
    write_calls = []

    def fail_mark_intent(*args, **kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(pending_mod, "mark_intent", fail_mark_intent)
    monkeypatch.setattr(
        ingest_mod,
        "write_page",
        lambda *args, **kwargs: write_calls.append(args[1].id),
    )

    with pytest.raises(OSError, match="ledger unavailable"):
        await ingest_mod.commit_ingest(paths, raw, [page], task_id="ledger-fail")

    assert write_calls == []
    assert not (paths.wiki_concepts / f"{page.id}.md").exists()


@pytest.mark.asyncio
async def test_wiki_commit_failure_keeps_intent_not_pending(tmp_path, monkeypatch):
    paths, raw = _setup(tmp_path)
    page = _page()

    def fail_write(*args, **kwargs):
        raise OSError("wiki unavailable")

    monkeypatch.setattr(
        ingest_mod,
        "write_page",
        fail_write,
    )

    with pytest.raises(OSError, match="wiki unavailable"):
        await ingest_mod.commit_ingest(paths, raw, [page], task_id="wiki-fail")

    assert pending_mod.list_pending(paths)[page.id]["publication_state"] == "intent"
    assert not (paths.wiki_concepts / f"{page.id}.md").exists()

    result = pending_mod.reconcile_pending(paths, lambda *args, **kwargs: True)
    assert result["orphaned"] == 1
    assert pending_mod.list_pending(paths) == {}


@pytest.mark.asyncio
async def test_promotion_failure_keeps_recoverable_intent(tmp_path, monkeypatch):
    paths, raw = _setup(tmp_path)
    page = _page()

    def fail_promote(*args, **kwargs):
        raise OSError("promotion unavailable")

    monkeypatch.setattr(pending_mod, "promote_intent", fail_promote)

    await ingest_mod.commit_ingest(paths, raw, [page], task_id="promotion-fail")

    assert (paths.wiki_concepts / f"{page.id}.md").exists()
    assert pending_mod.list_pending(paths)[page.id]["publication_state"] == "intent"

    result = pending_mod.reconcile_pending(paths, lambda *args, **kwargs: True)
    assert result["recovered"] == 1
    assert pending_mod.list_pending(paths) == {}
