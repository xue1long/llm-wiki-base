"""Tests for scripts/extract_full.py — v3.0 (async run_full)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scripts.extract_full import run_full
from src.pipeline.v7_extract.llm_client import FakeLLMClient


@pytest.fixture(autouse=True)
def _scrub_d9_temp_whitelist(monkeypatch):
    """D9: pilot tests pass tmp_path as project_root, which lives under
    %TEMP% on Windows. Clear the temp env vars so the resolver accepts it."""
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TMP", raising=False)


def _write_source(root: Path, name: str, content: str = "# 标题\n\n" + "正文。" * 300) -> None:
    path = root / "raw" / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_full_dry_run_batches_sources_and_resumes_from_checkpoint(tmp_path: Path) -> None:
    for index in range(5):
        _write_source(tmp_path, f"source-{index}.md")
    checkpoint = tmp_path / ".index" / "full.json"
    report_path = tmp_path / "report.json"

    first = asyncio.run(run_full(
        tmp_path, batch_size=2, checkpoint_path=checkpoint, json_output=report_path,
    ))
    second = asyncio.run(run_full(
        tmp_path, batch_size=2, checkpoint_path=checkpoint, json_output=report_path,
    ))

    assert first["mode"] == "dry-run"
    assert first["summary"]["selected"] == 5
    assert first["summary"]["batches"] == 3
    assert first["summary"]["errors"] == 0
    assert second["summary"]["batches_skipped"] == 3
    assert second["summary"]["results_reused"] is True
    assert len(second["results"]) == 5
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["completed_batches"] == [1, 2, 3]
    assert not (tmp_path / "wiki").exists()


def test_full_dry_run_writes_report_only_when_requested(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md")
    json_path = tmp_path / "full.json"
    markdown_path = tmp_path / "full.md"

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "checkpoint.json",
        json_output=json_path,
        markdown_output=markdown_path,
    ))

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert "# V7 Extract Full Batch Report" in markdown_path.read_text(encoding="utf-8")


def test_full_apply_is_fail_closed_before_pilot_approval(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md")

    # Default: dry_run=False raises unless V7_ALLOW_APPLY is set.
    with pytest.raises(RuntimeError, match="V7_ALLOW_APPLY"):
        asyncio.run(run_full(tmp_path, dry_run=False))


def test_full_apply_succeeds_with_V7_ALLOW_APPLY_env(
    tmp_path: Path, monkeypatch,
) -> None:
    """Plan 2: setting V7_ALLOW_APPLY=1 unlocks --apply. The pipeline runs
    to completion and low-confidence pages are recorded for review_queue
    triage (handled separately by Stage 7)."""
    _write_source(tmp_path, "one.md")
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")

    report = asyncio.run(run_full(tmp_path, dry_run=False))
    assert report["mode"] == "apply"
    assert report["summary"]["errors"] == 0


def test_full_apply_writes_concepts(tmp_path: Path, monkeypatch) -> None:
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    fake = FakeLLMClient()
    fake.script(
        "classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}'
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "扩句法", '
        '"item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_id": "raw/sources/complete.md", '
        '"source_text_excerpt": "定义"}, "characteristics": {"item_id": '
        '"raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"examples": {"item_id": "raw/sources/complete.md", '
        '"source_text_excerpt": "定义"}, "related_concepts": {"item_id": '
        '"raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"references": {"item_id": "raw/sources/complete.md", '
        '"source_text_excerpt": "定义"}}}'
    ))
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        dry_run=False,
        llm=fake,
    ))

    assert report["mode"] == "apply"
    assert list((tmp_path / "wiki" / "concepts").glob("*.md"))


def test_full_dry_run_records_llm_enabled_when_injected(tmp_path: Path) -> None:
    """`llm_enabled` reflects injection and the run stays dry-run-only."""
    _write_source(tmp_path, "one.md")
    fake = FakeLLMClient()
    # Stage 1 needs a valid response, otherwise classify_doc returns INCOMPLETE
    fake.script(
        "classify",
        '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}',
    )
    # Stage 3: mark incomplete so the run stops early (no Stage 4/5 calls)
    fake.script("completeness", '{"complete": false, "reason": "too short"}')

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        llm=fake,
    ))

    assert report["mode"] == "dry-run"
    assert report["llm_enabled"] is True
    assert fake.calls, "injected LLM should have been invoked"


# ---------------------------------------------------------------------------
# Wave 2 / Task 2: run_full summary now carries five-state counters
# (plan §4 Task 5 partial) and separates ``errors`` from blocked outcomes.
# ---------------------------------------------------------------------------


def test_full_summary_has_by_status_counters(tmp_path: Path) -> None:
    """``summary['by_status']`` carries all five ExtractionStatus values
    as int counters."""
    for index in range(3):
        _write_source(tmp_path, f"source-{index}.md")

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
    ))
    by_status = report["summary"]["by_status"]
    assert set(by_status.keys()) == {
        "written", "blocked", "failed", "incomplete", "skipped",
    }
    for value in by_status.values():
        assert isinstance(value, int)
    # selected + processed still surface for backwards compat.
    assert report["summary"]["selected"] == 3
    assert report["summary"]["processed"] >= 0


def test_full_summary_errors_strictly_equal_failed_count(tmp_path: Path) -> None:
    """``summary['errors']`` is now strictly the count of FAILED results
    (plan §4 Task 5: blocked outcomes no longer inflate ``errors``)."""
    _write_source(tmp_path, "one.md")

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
    ))
    summary = report["summary"]
    assert summary["errors"] == summary["by_status"]["failed"]
    # Sanity: legacy_status aggregate is also present.
    assert set(summary["by_legacy_status"].keys()) == {
        "ok", "needs_review", "incomplete",
    }


def test_full_summary_pages_counts_written_only(tmp_path: Path) -> None:
    """``summary['pages']`` only counts ``written_page_ids`` —
    blocked / failed pages must NOT contribute."""
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    fake = FakeLLMClient()
    fake.script(
        "classify",
        '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}',
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "扩句法", '
        '"item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_id": "raw/sources/complete.md", '
        '"source_text_excerpt": "定义"}, "characteristics": {"item_id": '
        '"raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"examples": {"item_id": "raw/sources/complete.md", '
        '"source_text_excerpt": "定义"}, "related_concepts": {"item_id": '
        '"raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"references": {"item_id": "raw/sources/complete.md", '
        '"source_text_excerpt": "定义"}}}'
    ))

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        llm=fake,
    ))
    summary = report["summary"]
    # ``pages`` matches the sum of written_page_ids across results.
    by_result = {item["source"]: item for item in report["results"]}
    expected_pages = sum(
        len(item.get("written_page_ids", []))
        for item in by_result.values()
    )
    assert summary["pages"] == expected_pages
    # And it must equal ``by_status["written"]`` times 1 for the single
    # source case (no blocked or failed pages were produced).
    assert summary["pages"] == summary["by_status"]["written"]
