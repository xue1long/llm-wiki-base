"""Tests for src/wiki/dedup_auto.py."""
import pytest
from src.wiki.dedup_auto import DedupHistoryStore, dedup_auto, DedupMergeRecord
from src.wiki.types import PageType, WikiPage
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page


def test_dedup_auto_records(tmp_path):
    """DedupHistoryStore.record() creates a history JSON + archived .md files."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"))
    write_page(paths, WikiPage(id="b", title="B", type=PageType.ENTITY, body="y"))

    record = DedupHistoryStore.record(paths, canonical="a", merged=["b"], confidence="high")

    assert isinstance(record, DedupMergeRecord)
    assert record.canonical_slug == "a"
    assert record.merged_slugs == ["b"]
    # History JSON exists
    history_json = paths.root / ".index" / "dedup_history" / f"{record.id}.json"
    assert history_json.exists()
    # Merged file removed from entities
    assert not (paths.wiki_entities / "b.md").exists()
    # Canonical still exists
    assert (paths.wiki_entities / "a.md").exists()
    # Archived in history
    archive = paths.root / ".index" / "dedup_history" / record.id / "b.md"
    assert archive.exists()


def test_dedup_auto_with_no_duplicates(tmp_path):
    """dedup_auto returns empty list when no duplicates found."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    # Empty KB → no duplicates
    records = dedup_auto(paths, provider=None, threshold="high")
    assert records == []
