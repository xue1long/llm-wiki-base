"""Regression: _write_rejected_source_page persists the source path in the
project-relative form (``raw/sources/...``), not the raw absolute path.

The absolute-path form previously broke ``src/services/files.py``
``_collect_referenced_raw_paths`` (which matches frontmatter sources against
``f.relative_to(paths.root).as_posix()``), so rejected sources showed as
"not ingested".
"""
import pytest

from src.wiki.core.paths import WikiPaths
from src.pipeline import ingest
from src.pipeline.sanitizer import SanitizerResult


@pytest.mark.asyncio
async def test_rejected_source_page_sources_is_project_relative(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    src = paths.raw_sources / "foo.txt"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("junk", encoding="utf-8")

    result = SanitizerResult(
        text="x",
        quality_score=0.1,
        warnings=["mostly_blank"],
        should_skip_llm=True,
    )

    pages = await ingest._write_rejected_source_page(
        paths=paths,
        source_path=src,
        source_text="junk",
        result=result,
        task_id="t-rejected",
    )

    assert len(pages) == 1
    assert pages[0].sources == ["raw/sources/foo.txt"]
