"""Tests for WikiPaths + ensure_knowledge_base."""
from src.wiki.paths import WikiPaths
from src.wiki.ensure import ensure_knowledge_base


def test_wiki_paths_under_root(tmp_path):
    p = WikiPaths(tmp_path)
    assert p.wiki == tmp_path / "wiki"
    assert p.wiki_sources == tmp_path / "wiki" / "sources"
    assert p.wiki_entities == tmp_path / "wiki" / "entities"
    assert p.wiki_concepts == tmp_path / "wiki" / "concepts"
    assert p.wiki_synthesis == tmp_path / "wiki" / "synthesis"
    assert p.wiki_stubs == tmp_path / "wiki" / "_stubs"
    assert p.raw_sources == tmp_path / "raw" / "sources"
    assert p.index == tmp_path / ".index"
    assert p.llm_wiki == tmp_path / ".llm-wiki"
    assert p.llm_wiki_log == tmp_path / "wiki" / "log.md"
    assert p.llm_wiki_index == tmp_path / "wiki" / "index.md"


def test_ensure_knowledge_base_creates_dirs(tmp_path):
    p = ensure_knowledge_base(tmp_path)
    assert p.wiki_sources.exists()
    assert p.wiki_entities.exists()
    assert p.wiki_concepts.exists()
    assert p.wiki_synthesis.exists()
    assert p.wiki_stubs.exists()
    assert p.raw_sources.exists()
    assert p.index.exists()
    assert p.llm_wiki.exists()


def test_ensure_knowledge_base_idempotent(tmp_path):
    """Calling twice doesn't raise."""
    ensure_knowledge_base(tmp_path)
    p2 = ensure_knowledge_base(tmp_path)
    assert p2.wiki.exists()
