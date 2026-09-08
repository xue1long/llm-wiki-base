import asyncio
from types import SimpleNamespace
import pytest

from src.kc.views.book.wiki.encyclopedic_outline import (
    EncyclopedicUnavailable, generate_encyclopedic_outline, safe_summary,
)
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot


def _snapshot():
    page = PageRecord("p1", "Title", "concept", "secret/source.md", "tax", "safe summary",
                      (ContentBlock("p1:b1", "p1", "H", "secret body", 0),), (), "x", 1, None)
    return WikiSnapshot("s", "/tmp/wiki", "v2.0", (page,), ())


def test_safe_summary_excludes_body_and_source():
    item = safe_summary(_snapshot())[0]
    assert "body" not in item and "path" not in item
    assert item["block_ids"] == ["p1:b1"]


def test_safe_summary_redacts_obvious_pii_and_caps_length():
    snapshot = _snapshot()
    page = snapshot.pages[0]
    page = PageRecord(page.page_id, page.title, page.page_type, page.path, page.primary_taxonomy,
                      "contact alice@example.com " + "x" * 600, page.content_blocks, page.relation_targets,
                      page.content_sha256, page.char_count, page.token_count, page.custom_type)
    item = safe_summary(WikiSnapshot(snapshot.snapshot_id, snapshot.wiki_root, snapshot.schema_version, (page,), ())) [0]
    assert item["summary"] == ""


def test_unknown_evidence_is_rejected():
    response = SimpleNamespace(content='{"issues": ["i"], "consensus": [{"claim":"c","evidence":[{"page_id":"p1","block_id":"bad"}]}], "disagreement": []}')
    async def complete(*args, **kwargs):
        return response
    with pytest.raises(EncyclopedicUnavailable, match="unknown evidence"):
        asyncio.run(generate_encyclopedic_outline(_snapshot(), SimpleNamespace(complete=complete)))


def test_missing_provider_is_explicit():
    with pytest.raises(EncyclopedicUnavailable, match="provider unavailable"):
        asyncio.run(generate_encyclopedic_outline(_snapshot(), None))
