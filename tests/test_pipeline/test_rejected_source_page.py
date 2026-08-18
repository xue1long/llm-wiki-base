"""R4 regression — low-quality-document rejection branch must succeed.

Audit A-03: `_write_rejected_source_page` used `async with AtomicContext()`
(no async protocol) and passed a non-existent `ctx` argument to
`write_page` / `append_to_index` / `log_event`. With
`RUFLO_SANITIZER_SKIP_LLM=1` and a degraded source, the branch raised
instead of producing the grade=C source page.

This test drives the real branch through `generate_ingest` and verifies
the page, index entry and log line are all produced (no disk writes from
generate_ingest itself — commit happens in `commit_ingest`; here we
verify the *returned page* plus that the atomic context path is usable).
"""
import asyncio

import pytest

from src.pipeline.ingest import generate_ingest
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType


def _make_paths(tmp_path) -> WikiPaths:
    """Build a minimal WikiPaths with the wiki tree present."""
    root = tmp_path / "kb"
    root.mkdir()
    for sub in ("sources", "entities", "concepts", "synthesis"):
        (root / "wiki" / sub).mkdir(parents=True, exist_ok=True)
    return WikiPaths(root)


def _low_quality_text() -> str:
    """Text that fails the sanitizer (high U+FFFD ratio → skip LLM)."""
    return "\ufffd" * 200


@pytest.mark.asyncio
async def test_rejected_source_page_returns_grade_c(monkeypatch, tmp_path):
    """SKIP_LLM=1 + degraded source → grade=C page, no exception."""
    monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")
    paths = _make_paths(tmp_path)

    pages, extra, meta = await generate_ingest(
        paths=paths,
        source_path=str(tmp_path / "bad.txt"),
        source_text=_low_quality_text(),
        provider=None,
        task_id="t-reject",
    )

    assert len(pages) == 1
    page = pages[0]
    assert page.grade == "C"
    assert page.type == PageType.SOURCE
    assert "已跳过处理" in page.body
    assert meta.get("rejected") is True
    assert not list((paths.root / "wiki").rglob("*.md"))


@pytest.mark.asyncio
async def test_rejected_source_page_commits_only_after_explicit_commit(monkeypatch, tmp_path):
    """Generation is side-effect free; explicit commit persists the page."""
    monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")
    paths = _make_paths(tmp_path)

    pages, _, _ = await generate_ingest(
        paths=paths,
        source_path=str(tmp_path / "bad2.txt"),
        source_text=_low_quality_text(),
        provider=None,
        task_id="t-reject-2",
    )

    from src.pipeline.ingest import commit_ingest
    await commit_ingest(
        paths, str(tmp_path / "bad2.txt"), pages, [], task_id="t-reject-2",
    )

    # The page file must exist on disk.
    page = pages[0]
    assert page.id
    written = list((paths.root / "wiki" / "sources").glob("*.md"))
    assert len(written) == 1
    assert page.id in written[0].name


@pytest.mark.asyncio
async def test_normal_source_untouched_by_skip_flag(monkeypatch, tmp_path):
    """With SKIP_LLM=1 but a *good* source, the rejection branch is skipped.

    The sanitizer marks healthy text as not-skip; the opt-in env flag alone
    must not trigger the rejection path. We assert at the sanitizer boundary
    (which gates the branch) rather than driving the whole LLM pipeline.
    """
    monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")
    from src.pipeline.sanitizer import sanitize

    result = sanitize("这是一段完全正常的中文内容。" * 10)
    assert result.should_skip_llm is False
