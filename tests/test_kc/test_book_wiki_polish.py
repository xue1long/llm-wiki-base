import asyncio
from types import SimpleNamespace

from src.kc.views.book.wiki.aggregator import aggregate_chapter
from src.kc.views.book.wiki.model import ContentBlock, PageRecord
from src.kc.views.book.wiki.polish_llm import PolishedChapter, polish_chapter
from src.kc.views.book.wiki.polish_validate import validate_polished_chapter


def _draft():
    blocks = (ContentBlock("p:0", "p", "H", "body [[p]]", 0),)
    page = PageRecord("p", "P", "concept", "wiki/p.md", "x", "s", blocks, (), "h", 1, None)
    return aggregate_chapter({"chapter_id": "c", "page_ids": ["p"]}, {"p": page})


def test_validation_rejects_deleted_or_changed_content_and_bad_transition():
    draft = _draft()
    bad = PolishedChapter("c", (), ("new [[x]]",), True, None, "see nowhere", None, "changed")
    errors = validate_polished_chapter(draft, bad)
    assert {"block_order_mismatch", "body_hash_mismatch", "wikilink_mismatch", "transition_in_invalid_reference", "new_wikilink"} <= set(errors)


def test_valid_editorial_metadata_passes():
    draft = _draft()
    good = PolishedChapter("c", ("p",), ("Overview [p:0]",), True, None, "see p:0", "end p:0")
    assert validate_polished_chapter(draft, good) == ()


def test_malformed_llm_response_falls_back_without_rewriting():
    class Provider:
        async def complete(self, *_args, **_kwargs):
            return SimpleNamespace(content="not json", truncated=False)

    result = asyncio.run(polish_chapter(_draft(), Provider()))
    assert result.polished is False
    assert result.block_order == ("p",)
