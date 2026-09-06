from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.reading_aids import build_glossary, build_index


def test_glossary_deduplicates_wikilinks_and_includes_page_title():
    pages = (
        PageRecord("p1", "Alpha", "concept", "wiki/concepts/p1.md", "topic", "First sentence. More.",
                   (ContentBlock("p1:0", "p1", None, "See [[p2]] and [[p2]].", 0),), (), "h", 1, None),
        PageRecord("p2", "Beta", "entity", "wiki/entities/p2.md", None, "Beta summary.", (), (), "h", 1, None),
    )
    glossary = build_glossary(WikiSnapshot("s", "wiki", "v2", pages, ()))
    assert set(glossary) == {"p1", "p2"}
    assert glossary["p2"].title == "Beta"


def test_index_maps_all_pages_and_outline_assignments():
    pages = (PageRecord("p1", "Alpha", "concept", "x", "topic", "", (), (), "h", 0, None),)
    index = build_index(WikiSnapshot("s", "wiki", "v2", pages, ()), [{"volumes": [{"chapters": [{"chapter_id": "c1", "page_ids": ["p1"]}]}]}])
    assert index.entries["p1"].chapter_id == "c1"
    assert index.entries["p1"].page_type == "concept"
