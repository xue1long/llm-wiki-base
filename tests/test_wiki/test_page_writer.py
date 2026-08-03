"""Tests for src.wiki.page_writer."""
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.page_writer import (
    PageNotFoundError, page_path_for, read_page, write_page,
)
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.features.tag_namespace import TagValidationError


def test_page_path_for(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    path = page_path_for(p, PageType.ENTITY, "foo")
    assert path == p.wiki_entities / "foo.md"
    # Source → wiki_sources, etc.
    assert page_path_for(p, PageType.SOURCE, "src") == p.wiki_sources / "src.md"
    assert page_path_for(p, PageType.CONCEPT, "c") == p.wiki_concepts / "c.md"
    assert page_path_for(p, PageType.SYNTHESIS, "s") == p.wiki_synthesis / "s.md"


def test_write_and_read_page(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    page = WikiPage(
        id="foo", title="Foo", type=PageType.ENTITY,
        sources=["raw/sources/x.pdf"], created_at=1000, updated_at=2000,
        body="Foo body content",
    )
    write_page(p, page)

    path = page_path_for(p, PageType.ENTITY, "foo")
    assert path.exists()

    loaded = read_page(path)
    assert loaded.id == "foo"
    assert loaded.title == "Foo"
    assert loaded.body == "Foo body content"
    assert loaded.sources == ["raw/sources/x.pdf"]


def test_write_page_overwrites_existing(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    page_v1 = WikiPage(id="foo", title="v1", type=PageType.ENTITY, body="v1")
    page_v2 = WikiPage(id="foo", title="v2", type=PageType.ENTITY, body="v2")
    write_page(p, page_v1)
    write_page(p, page_v2)
    loaded = read_page(page_path_for(p, PageType.ENTITY, "foo"))
    assert loaded.title == "v2"
    assert loaded.body == "v2"


def test_read_page_missing(tmp_path):
    ensure_knowledge_base(tmp_path)
    with pytest.raises(PageNotFoundError):
        read_page(tmp_path / "wiki" / "entities" / "nope.md")


def test_read_page_without_frontmatter(tmp_path):
    """Bare markdown file → WikiPage with SOURCE type and stem-as id."""
    ensure_knowledge_base(tmp_path)
    path = tmp_path / "bare.md"
    path.write_text("just some content\n", encoding="utf-8")
    p = read_page(path)
    assert p.id == "bare"
    assert p.type == PageType.SOURCE
    assert "just some content" in p.body


def test_write_page_rejects_invalid_tag_value(tmp_path):
    """write_page raises TagValidationError when tags have out-of-domain values."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    page = WikiPage(id="foo", title="Foo", type=PageType.ENTITY, tags=["题材/bogus"])
    with pytest.raises(TagValidationError) as exc:
        write_page(p, page)
    assert "题材/bogus" in exc.value.invalid_values


def test_write_page_allows_valid_tags(tmp_path):
    """write_page succeeds when tags are valid and mandatory pairs present."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    page = WikiPage(id="foo", title="Foo", type=PageType.ENTITY,
                    tags=["题材/现言", "状态/完结", "素材/ugc", "可信度/ugc"])
    write_page(p, page)
    assert page_path_for(p, PageType.ENTITY, "foo").exists()
