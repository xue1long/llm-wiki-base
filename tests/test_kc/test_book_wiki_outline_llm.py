from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.partition import build_chapter_chunks, partition_pages


def page(pid, typ="concept", tax=None, chars=10):
    return PageRecord(pid, pid, typ, f"{typ}s/{pid}.md", tax, "summary", (ContentBlock(pid+":0", pid, None, "x" * chars, 0),), (), pid, chars, None)


def snap(*pages):
    return WikiSnapshot("s", "/wiki", "wiki-v3", tuple(pages), ())


def test_partition_is_stable_and_fallback_is_optional():
    result = partition_pages(snap(page("b", tax="z"), page("a", tax="z"), page("u", tax=None), page("e", typ="entity", tax="a")))
    assert list(result) == ["concept-z", "entity-a", "fallback"]
    assert result["concept-z"] == ("a", "b")
    assert result["fallback"] == ("u",)
    assert "fallback" not in partition_pages(snap(page("a", tax="z")))


def test_chunks_keep_whole_pages_and_blocks():
    snapshot = snap(page("a", chars=6), page("b", chars=6), page("huge", chars=100))
    chunks = build_chapter_chunks(snapshot, {"v": ("a", "b", "huge")}, context_window=10, output_reserve=2)
    assert chunks["v:0"] == ("a",)
    assert chunks["v:1"] == ("b",)
    assert chunks["v:2"] == ("huge",)
