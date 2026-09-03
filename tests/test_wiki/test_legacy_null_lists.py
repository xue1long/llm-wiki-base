from src.wiki.core.types import WikiPage


def test_legacy_null_lists_are_read_as_empty_lists():
    page = WikiPage.from_dict({
        "id": "x", "title": "t", "type": "concept",
        "tags": None, "relations": None, "sources": None,
    })
    assert page.tags == []
    assert page.relations == []
    assert page.sources == []
