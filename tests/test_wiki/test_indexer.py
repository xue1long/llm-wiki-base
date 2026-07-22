from src.wiki.types import PageType, WikiPage
from src.wiki.indexer import append_to_index, read_index, _format_entry
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths


def test_format_entry():
    entry = _format_entry("foo", PageType.ENTITY, "Foo")
    assert "foo" in entry
    assert "Foo" in entry
    assert "entity" in entry.lower()


def test_append_to_index_creates_file(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    append_to_index(p, [("foo", PageType.ENTITY, "Foo"), ("bar", PageType.SOURCE, "Bar")])

    content = p.llm_wiki_index.read_text(encoding="utf-8")
    assert "# Wiki Index" in content
    assert "foo" in content
    assert "bar" in content


def test_append_to_index_idempotent(tmp_path):
    """Re-appending same entries doesn't duplicate."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    append_to_index(p, [("foo", PageType.ENTITY, "Foo")])
    append_to_index(p, [("foo", PageType.ENTITY, "Foo")])
    content = p.llm_wiki_index.read_text(encoding="utf-8")
    # Count occurrences of "foo" in entries (not in heading)
    lines = [l for l in content.split("\n") if "foo" in l and l.startswith("-")]
    assert len(lines) == 1


def test_read_index_parses_entries(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    append_to_index(p, [("foo", PageType.ENTITY, "Foo")])
    entries = read_index(p)
    assert ("foo", PageType.ENTITY, "Foo") in entries