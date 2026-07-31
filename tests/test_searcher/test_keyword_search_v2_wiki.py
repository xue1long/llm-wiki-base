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
async def test_keyword_search_warns_when_paths_none(caplog):
    """When _keyword_search is invoked with paths=None, it must emit
    a WARNING on logger 'src.searcher.hybrid_search' containing
    'paths is None' so operators / callers can find legacy callers.
    """
    import logging
    caplog.set_level(logging.WARNING, logger="src.searcher.hybrid_search")
    results = await _keyword_search("anything", top_k=10, paths=None)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "expected a WARNING when paths is None"
    msg = warnings[0].message
    assert "paths is None" in msg, (
        f"deprecation message must mention 'paths is None'; got: {msg!r}"
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


@pytest.mark.asyncio
async def test_keyword_search_returns_project_relative_paths(tmp_path):
    """Keyword result paths must be project-relative (posix) so they share the
    same RRF fusion key as semantic results."""
    page = tmp_path / "wiki" / "sources" / "sub" / "nested.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Nested\n\nmagic term here\n", encoding="utf-8")
    paths = WikiPaths(tmp_path)
    results = await _keyword_search("magic term", top_k=10, paths=paths)
    assert results[0]["path"] == "wiki/sources/sub/nested.md"


@pytest.mark.asyncio
async def test_keyword_search_skips_archive_and_stubs(tmp_path):
    """Pages in wiki/_archive/ (heat archive target) and wiki/_stubs/
    (placeholders) must not be returned by keyword search, even though
    rglob walks them. The catalog (index.md) and audit log (log.md)
    must also be skipped so they do not match every query.
    """
    # Files that should NOT be found
    (tmp_path / "wiki" / "_archive").mkdir(parents=True)
    (tmp_path / "wiki" / "_archive" / "archived.md").write_text(
        "# Archived\\n\\nkeyword appears here but should be skipped\\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "_stubs").mkdir(parents=True)
    (tmp_path / "wiki" / "_stubs" / "stub.md").write_text(
        "# Stub\\n\\nkeyword appears here but should be skipped\\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "index.md").write_text(
        "# Catalog\\n\\nkeyword appears here but should be skipped\\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "log.md").write_text(
        "# Audit log\\n\\nkeyword appears here but should be skipped\\n",
        encoding="utf-8",
    )
    # Real page that SHOULD be found
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "real.md").write_text(
        "# Real\\n\\nkeyword appears here\\n",
        encoding="utf-8",
    )
    paths = WikiPaths(tmp_path)
    results = await _keyword_search("keyword", top_k=10, paths=paths)
    paths_found = sorted(r["path"] for r in results)
    assert len(paths_found) == 1, (
        f"keyword search must skip _archive / _stubs / index.md / log.md; "
        f"got paths={paths_found!r}"
    )
    assert "real.md" in paths_found[0]
