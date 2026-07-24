"""Regression: _keyword_search must find pages under the v2 wiki tree.

The F17 fix routed keyword search through paths.knowledge_dir (= <root>/wiki).
But v2 wiki pages live under the typed subdirectories
(<root>/wiki/{sources,entities,concepts,synthesis}/). Without rglob,
the keyword search returns 0 results for every real v2 project even
though the embedding fallback (which exercises this path) keeps
running.
"""
import pytest

from src.searcher.hybrid_search import _keyword_search
from src.wiki.core.paths import WikiPaths


@pytest.mark.asyncio
async def test_keyword_search_scans_v2_wiki_tree(tmp_path):
    """When paths=WikiPaths is provided, _keyword_search must recurse
    into wiki/sources, wiki/entities, wiki/concepts, wiki/synthesis
    and find every .md file that contains the query term."""
    # Create one file in each v2 typed subdir with a unique keyword
    pages = {
        "wiki/sources/s.md": "alpha content here",
        "wiki/entities/e.md": "beta content here",
        "wiki/concepts/c.md": "gamma content here",
        "wiki/synthesis/y.md": "delta content here",
    }
    for rel, body in pages.items():
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"# {{title}}\n\n{body}\n", encoding="utf-8")

    paths = WikiPaths(tmp_path)
    # Query for a term that appears in EVERY file.
    results = await _keyword_search("content", top_k=10, paths=paths)
    titles = sorted(r["title"] for r in results)

    # Without rglob, this list would be empty (no top-level *.md under wiki/).
    assert titles == ["c", "e", "s", "y"], (
        f"_keyword_search must recurse into all v2 typed subdirs; "
        f"got titles={titles!r}"
    )


@pytest.mark.asyncio
async def test_keyword_search_finds_nested_pages(tmp_path):
    """Pages nested deeper than one level must also be found."""
    # Place a page under wiki/sources/sub/nested.md
    nested = tmp_path / "wiki" / "sources" / "sub"
    nested.mkdir(parents=True)
    (nested / "nested.md").write_text(
        "# Nested\n\ncontains the magic term here\n", encoding="utf-8"
    )
    paths = WikiPaths(tmp_path)
    results = await _keyword_search("magic term", top_k=10, paths=paths)
    assert len(results) == 1
    assert "nested" in results[0]["path"]
