from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.dedup import find_duplicates
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page


def test_find_duplicates_empty(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    assert find_duplicates(p) == []


def test_find_duplicates_returns_empty_mvp(tmp_path):
    """MVP: even with multiple entities, returns []."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body="apple"))
    write_page(p, WikiPage(id="b", title="B", type=PageType.ENTITY, body="banana"))
    assert find_duplicates(p) == []
