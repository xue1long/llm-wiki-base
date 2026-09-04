"""Phase 1.7 tests — V4 rewrite: no more is_immutable guard.

V4 (ADR-002, 2026-08-31): the is_immutable / lock_until edit-guard
mechanism has been removed. Pages are write-once KB entries; if a page
needs to be replaced, ``write_page`` overwrites it. There is no
immutable-flag concept to test.
"""
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page, read_page


def test_overwrite_always_allowed_v4(tmp_path):
    """V4: write_page overwrites any existing page — no immutable guard."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="x", title="X", type=PageType.CONCEPT,
                            body="## 定义\n\n旧内容\n"))
    path = p.wiki_concepts / "x.md"

    # Overwrite is allowed in V4.
    write_page(p, WikiPage(id="x", title="X", type=PageType.CONCEPT,
                            body="## 定义\n\n新内容\n"))
    assert "新内容" in read_page(path).body


def test_is_immutable_always_false_v4():
    """V4: is_immutable defaults to False and is never persisted to disk."""
    page = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    assert page.is_immutable is False
    # Even if we set it on the in-memory object, it's not serialized.
    page.is_immutable = True
    fm = page.to_frontmatter_dict()
    assert "is_immutable" not in fm
