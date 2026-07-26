"""Tests for src/wiki/stubs.py."""
import pytest
from src.wiki.features.stubs import StubMaterializerWorker
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page


def test_find_referenced_stubs(tmp_path):
    """_find_referenced_stubs returns stubs referenced by other wiki pages via wikilinks."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # Page that references a stub via [[stub-id]]
    write_page(paths, WikiPage(
        id="main", title="Main", type=PageType.ENTITY, body="see [[foo-target]] and [[bar-notexist]]",
    ))
    # Create the stub that main references
    (paths.wiki_stubs / "foo-target.md").write_text(
        "---\nid: foo-target\ntitle: Foo Target\ntype: stub\n---\n\nstub body\n",
        encoding="utf-8",
    )

    worker = StubMaterializerWorker(paths, provider=None)
    refs = worker._find_referenced_stubs()
    assert "foo-target" in refs
    assert "bar-notexist" not in refs


@pytest.mark.asyncio
async def test_materialize_one(tmp_path):
    """_materialize_one generates a real page and removes the stub."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # Page that references a stub
    write_page(paths, WikiPage(
        id="main", title="Main", type=PageType.ENTITY, body="see [[foo-target]] for context",
    ))
    # Create the stub
    stub_path = paths.wiki_stubs / "foo-target.md"
    stub_path.write_text(
        "---\nid: foo-target\ntitle: Foo Target\ntype: stub\n---\n\nstub body\n",
        encoding="utf-8",
    )

    # Use a ScriptedLLMProvider that returns a page dict (v2.3 schema
    # uses `slots` instead of `body_markdown`).
    from src.shared.test_helpers import ScriptedLLMProvider
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "foo-target", "type": "concept", "title": "Foo Target Real",
             "frontmatter_extra": {},
             "slots": {"definition": "Real body about foo-target.",
                       "characteristics": ["c"],
                       "examples": ["e"],
                       "related_concepts": ["rc"],
                       "references": ["r"]}},
        ]}
    ])

    worker = StubMaterializerWorker(paths, provider)
    result = await worker._materialize_one("foo-target")
    assert result is True
    # Stub removed
    assert not stub_path.exists()
    # Real page created
    real_path = paths.wiki_concepts / "foo-target.md"
    assert real_path.exists()
    content = real_path.read_text(encoding="utf-8")
    assert "Real body" in content