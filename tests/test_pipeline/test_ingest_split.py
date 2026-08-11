"""NDG Phase 1: tests for generate_ingest / commit_ingest split semantics.

These tests lock in the contract that generate_ingest writes nothing to disk
and commit_ingest is the sole write path.
"""
import pytest
from pathlib import Path

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.shared.test_helpers import ScriptedLLMProvider

from src.pipeline.ingest import generate_ingest, commit_ingest


@pytest.fixture(autouse=True)
def _legacy_pipeline_mode(monkeypatch):
    """These tests were written for the legacy pipeline path.
    Force legacy mode so they don't enter the candidate path."""
    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "legacy")


# ---------------------------------------------------------------------------
# generate_ingest disk-write safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_ingest_no_disk_write(tmp_path: Path):
    """generate_ingest must NOT write any pages, index, or log."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "test.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("some content", encoding="utf-8")

    provider = ScriptedLLMProvider([
        {"pages": [{"id": "test-concept", "type": "entity", "title": "Test",
                     "slots": {}}]},
    ])

    pages, extra, meta = await generate_ingest(
        paths=paths, source_path=raw,
        source_text="some content", provider=provider,
    )

    # No wiki pages written
    for d in [paths.wiki_sources, paths.wiki_entities,
              paths.wiki_concepts, paths.wiki_synthesis]:
        assert not list(d.glob("*.md")), f"{d} should be empty after generate_ingest"

    # No index or log
    assert not paths.llm_wiki_index.exists(), "index.md must not be written"
    assert not paths.llm_wiki_log.exists(), "log.md must not be written"

    # Meta fields present
    assert meta["rejected"] is False
    assert meta["source_slug"]
    assert meta["source_page_id"]
    assert meta["source_grade"] in ("A", "C")
    assert meta["downstream_count"] >= 0
    assert meta["extra_pages_count"] == 0

    # Check the returned types
    assert isinstance(pages, list)
    assert isinstance(extra, list)
    assert isinstance(meta, dict)
    assert len(pages) >= 1  # at least source page

    # Now commit and verify writes happen
    await commit_ingest(paths, raw, pages, extra, task_id="test")
    assert paths.llm_wiki_index.exists(), "index.md must exist after commit_ingest"
    assert list(paths.wiki_entities.glob("*.md")), "entity pages must exist after commit"
    source_pages = list(paths.wiki_sources.glob("*.md"))
    assert source_pages, "source page must exist after commit"


@pytest.mark.asyncio
async def test_generate_ingest_hard_reject_no_disk_write(tmp_path: Path, monkeypatch):
    """Hard-reject path (RUFLO_SANITIZER_SKIP_LLM=1) must not write."""
    monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "junk.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("junk", encoding="utf-8")  # short text → sanitizer rejects

    provider = ScriptedLLMProvider([])  # won't be called

    pages, extra, meta = await generate_ingest(
        paths=paths, source_path=raw,
        source_text="junk", provider=provider,
    )

    assert meta["rejected"] is True
    assert len(pages) == 1
    assert pages[0].grade == "C"
    assert extra == []

    # No wiki, index, or log written
    for d in [paths.wiki_sources, paths.wiki_entities,
              paths.wiki_concepts, paths.wiki_synthesis]:
        assert not list(d.glob("*.md")), f"{d} should be empty"

    assert not paths.llm_wiki_index.exists()
    assert not paths.llm_wiki_log.exists()


# ---------------------------------------------------------------------------
# commit_ingest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commit_ingest_writes_pages_index_and_log(tmp_path: Path):
    """commit_ingest writes pages, updates index, and logs the event."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    pages = [
        WikiPage(id="src-1", title="Source", type=PageType.SOURCE,
                 sources=["raw/sources/test.md"], body="body", grade="A"),
        WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                 sources=["raw/sources/test.md"], body="body"),
    ]

    await commit_ingest(paths, Path("raw/sources/test.md"), pages, task_id="test")

    # Pages written
    assert (paths.wiki_sources / "src-1.md").exists()
    assert (paths.wiki_entities / "ent-1.md").exists()

    # Index updated
    index_text = paths.llm_wiki_index.read_text(encoding="utf-8")
    assert "src-1" in index_text
    assert "ent-1" in index_text

    # Log written
    assert paths.llm_wiki_log.exists()


@pytest.mark.asyncio
async def test_commit_ingest_rejected_log(tmp_path: Path):
    """commit_ingest with event='rejected' writes a rejected audit entry."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    pages = [WikiPage(id="rej-1", title="Rejected", type=PageType.SOURCE,
                      sources=["raw/sources/bad.md"], body="", grade="C")]

    await commit_ingest(
        paths, Path("raw/sources/bad.md"), pages, task_id="t-rej",
        event="rejected", detail="mostly_blank",
        log_task_id="rej-1",
    )

    log_text = paths.llm_wiki_log.read_text(encoding="utf-8")
    assert "rejected" in log_text


# ---------------------------------------------------------------------------
# run_ingest hard-reject audit trail (backward compat)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_ingest_hard_reject_writes_rejected_log(tmp_path: Path, monkeypatch):
    """generate_ingest hard-reject must write a 'rejected' audit event via commit_ingest.

    The prefilter in run_ingest() now intercepts degraded sources before they
    reach generate_ingest.  This test calls generate_ingest + commit_ingest
    directly to exercise the SKIP_LLM path without triggering the prefilter.
    """
    monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "junk.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("x", encoding="utf-8")  # < 5 chars → should_skip_llm = True

    provider = ScriptedLLMProvider([])

    pages, extra, meta = await generate_ingest(
        paths=paths, source_path=raw,
        source_text="x", provider=provider,
    )

    assert meta["rejected"] is True
    assert len(pages) == 1
    assert pages[0].grade == "C"
    assert pages[0].type == PageType.SOURCE

    # No disk writes yet (generate_ingest contract).
    # Commit explicitly.
    await commit_ingest(paths, raw, pages, extra, task_id="t-rej")

    # Page + index + rejected log exist
    assert list(paths.wiki_sources.glob("*.md"))
    assert paths.llm_wiki_index.exists()

    log_text = paths.llm_wiki_log.read_text(encoding="utf-8")
    assert "rejected" in log_text
