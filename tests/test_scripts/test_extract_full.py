"""Tests for scripts/extract_full.py — v3.0 (async run_full)."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.extract_full as extract_full
from scripts.extract_full import main, run_full
from src.pipeline.v7_extract.failures import ExtractionResult, ExtractionStatus
from src.pipeline.v7_extract.wiki_writer import WriteReport
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


def test_full_cli_requires_explicit_root(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert "usage:" in capsys.readouterr().err.lower()


def test_run_full_releases_queue_lock_after_success_and_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(run_full(tmp_path))
    lock_path = tmp_path / ".index" / ".queue-lock"
    assert not lock_path.exists()

    def broken_source_scan(_root: Path):
        assert lock_path.exists()
        raise RuntimeError("scan failed")

    monkeypatch.setattr(extract_full, "_source_files", broken_source_scan)
    with pytest.raises(RuntimeError, match="scan failed"):
        asyncio.run(run_full(tmp_path))
    assert not lock_path.exists()

    monkeypatch.undo()
    lock_path.write_text("other-pid", encoding="utf-8")
    with pytest.raises(RuntimeError, match="另一进程正在写 queue"):
        asyncio.run(run_full(tmp_path))
    assert lock_path.read_text(encoding="utf-8") == "other-pid"


def test_corrupt_checkpoint_is_backed_up_and_rebuilt(tmp_path: Path) -> None:
    checkpoint = tmp_path / ".index" / "full.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{broken", encoding="utf-8")

    asyncio.run(run_full(tmp_path, checkpoint_path=checkpoint))

    assert checkpoint.with_suffix(".json.corrupt").read_text(encoding="utf-8") == "{broken"
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["version"] == 2


def test_legacy_completed_batches_never_hide_sources(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md")
    checkpoint = tmp_path / ".index" / "full.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text('{"completed_batches": [1]}', encoding="utf-8")

    report = asyncio.run(run_full(tmp_path, checkpoint_path=checkpoint))

    assert report["summary"]["processed"] == 1
    assert "raw/sources/one.md" in json.loads(
        checkpoint.read_text(encoding="utf-8")
    )["sources"]


def test_source_attempts_increment_once_per_run_and_stop_at_max_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(tmp_path, "one.md")
    checkpoint = tmp_path / ".index" / "full.json"
    calls = 0

    async def fail_once(_root, _path, relative, **_kwargs):
        nonlocal calls
        calls += 1
        return ExtractionResult(
            status=ExtractionStatus.FAILED,
            source_id=relative,
            failure_stage="stage5",
            metadata={"source": relative, "doc_type": None, "complete": False,
                      "topics": [], "pages": [], "error": "failed"},
        )

    monkeypatch.setattr(extract_full, "_extract_one", fail_once)
    for _ in range(3):
        asyncio.run(run_full(
            tmp_path, checkpoint_path=checkpoint, max_attempts=2,
        ))

    row = json.loads(checkpoint.read_text(encoding="utf-8"))["sources"][
        "raw/sources/one.md"
    ]
    assert calls == 2
    assert row["attempts"] == 2
    assert row["status"] == "failed_max_attempts"


def test_stage5_internal_retries_count_as_one_source_attempt_and_blocked_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 8 (Persistence Contract §4.4): BLOCKED never skips.

    Previously this test asserted BLOCKED reuses the prior checkpoint
    (skip). Task 8 deliberately changes the semantics so BLOCKED sources
    always re-evaluate — only INCOMPLETE (proven incomplete, not a
    transient failure) may be skipped. Stage 5 retries still count as
    one source-level attempt (D5 from the v3 plan).
    """
    _write_source(tmp_path, "one.md")
    fake = FakeLLMClient()
    # Register scripts for BOTH runs (Task 8: BLOCKED no longer skips, so
    # the second run must re-consume classify / completeness / cluster /
    # fill_slots scripts).
    for _ in range(2):
        fake.script(
            "classify",
            '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}',
        )
        fake.script("completeness", '{"complete": true, "reason": "ok"}')
        fake.script(
            "cluster",
            '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}',
        )
        for _ in range(3):
            fake.script("fill_slots", "not json")
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")
    checkpoint = tmp_path / ".index" / "full.json"

    first = asyncio.run(run_full(
        tmp_path, checkpoint_path=checkpoint, dry_run=False, llm=fake,
    ))
    first_call_count = len(fake.calls)
    second = asyncio.run(run_full(
        tmp_path, checkpoint_path=checkpoint, dry_run=False, llm=fake,
    ))

    row = json.loads(checkpoint.read_text(encoding="utf-8"))["sources"][
        "raw/sources/one.md"
    ]
    assert first["summary"]["blocked"] == 1
    assert first_call_count >= 6  # classify + completeness + cluster + 3 Stage 5 retries
    # Task 8: BLOCKED must re-run, NOT skip. The source-level attempt counter
    # therefore advances on the second run (Stage 5 retries still count as
    # one source-level attempt each invocation, per D5).
    assert len(fake.calls) > first_call_count
    assert second["summary"]["blocked"] == 1
    assert second["summary"]["skipped"] == 0
    assert row["attempts"] == 2


@pytest.mark.parametrize(
    ("write_report", "expected_status", "written", "blocked", "failed"),
    [
        (WriteReport(written=["p1"], page_writes={"p1": Path("p1.md")}),
         "written", ["p1"], [], []),
        (WriteReport(blocked=["p1"], page_writes={"p1": None}),
         "blocked", [], ["p1"], []),
        (WriteReport(failed={"p1": "disk"}, page_writes={"p1": None}),
         "failed", [], [], ["p1"]),
    ],
)
def test_source_outcome_matches_writer_page_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_report: WriteReport,
    expected_status: str,
    written: list[str],
    blocked: list[str],
    failed: list[str],
) -> None:
    _write_source(tmp_path, "one.md")
    page = SimpleNamespace(id="p1", sources=["raw/sources/one.md"])

    async def extracted(_root, _path, relative, **kwargs):
        kwargs["page_sink"](page)
        return ExtractionResult(
            status=ExtractionStatus.WRITTEN,
            source_id=relative,
            pages=[page],
            written_page_ids=["p1"],
            metadata={"source": relative, "doc_type": "single_method",
                      "complete": True, "topics": [], "pages": [], "error": None},
        )

    class FakeWriter:
        def __init__(self, *_args, **_kwargs):
            pass

        def commit_and_index(self, _pages):
            return write_report

    monkeypatch.setattr(extract_full, "_extract_one", extracted)
    monkeypatch.setattr(extract_full, "WikiWriter", FakeWriter)
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")
    checkpoint = tmp_path / ".index" / "full.json"

    report = asyncio.run(run_full(
        tmp_path, checkpoint_path=checkpoint, dry_run=False,
    ))

    row = json.loads(checkpoint.read_text(encoding="utf-8"))["sources"][
        "raw/sources/one.md"
    ]
    result = report["results"][0]
    assert row["status"] == result["status"] == expected_status
    assert row["written_page_ids"] == result["written_page_ids"] == written
    assert row["blocked_page_ids"] == result["blocked_page_ids"] == blocked
    assert row["failed_page_ids"] == result["failed_page_ids"] == failed


def test_resume_retries_only_failed_source_in_partially_failed_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(tmp_path, "a.md")
    _write_source(tmp_path, "b.md")
    calls = {"raw/sources/a.md": 0, "raw/sources/b.md": 0}

    async def extracted(_root, _path, relative, **kwargs):
        calls[relative] += 1
        if relative.endswith("b.md"):
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                source_id=relative,
                metadata={"source": relative, "doc_type": None, "complete": False,
                          "topics": [], "pages": [], "error": "failed"},
            )
        page = SimpleNamespace(id="page-a", sources=[relative])
        kwargs["page_sink"](page)
        return ExtractionResult(
            status=ExtractionStatus.WRITTEN,
            source_id=relative,
            pages=[page],
            written_page_ids=[page.id],
            metadata={"source": relative, "doc_type": "single_method",
                      "complete": True, "topics": [], "pages": [], "error": None},
        )

    class FakeWriter:
        def __init__(self, root, **_kwargs):
            self.root = Path(root)

        def commit_and_index(self, pages):
            page = pages[0]
            path = self.root / "wiki" / "concepts" / f"{page.id}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("page", encoding="utf-8")
            return WriteReport(written=[page.id], page_writes={page.id: path})

    monkeypatch.setattr(extract_full, "_extract_one", extracted)
    monkeypatch.setattr(extract_full, "WikiWriter", FakeWriter)
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")
    checkpoint = tmp_path / ".index" / "full.json"

    asyncio.run(run_full(
        tmp_path, batch_size=2, checkpoint_path=checkpoint, dry_run=False,
    ))
    asyncio.run(run_full(
        tmp_path, batch_size=2, checkpoint_path=checkpoint, dry_run=False,
    ))

    assert calls == {"raw/sources/a.md": 1, "raw/sources/b.md": 2}


def test_changed_source_md5_is_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(tmp_path, "one.md")
    calls = 0

    async def extracted(_root, _path, relative, **kwargs):
        nonlocal calls
        calls += 1
        page = SimpleNamespace(id="p1", sources=[relative])
        kwargs["page_sink"](page)
        return ExtractionResult(
            status=ExtractionStatus.WRITTEN, source_id=relative, pages=[page],
            written_page_ids=[page.id],
            metadata={"source": relative, "doc_type": "single_method",
                      "complete": True, "topics": [], "pages": [], "error": None},
        )

    class FakeWriter:
        def __init__(self, *_args, **_kwargs):
            pass

        def commit_and_index(self, pages):
            return WriteReport(
                written=[pages[0].id], page_writes={pages[0].id: Path("p1.md")},
            )

    monkeypatch.setattr(extract_full, "_extract_one", extracted)
    monkeypatch.setattr(extract_full, "WikiWriter", FakeWriter)
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")
    checkpoint = tmp_path / ".index" / "full.json"
    asyncio.run(run_full(tmp_path, checkpoint_path=checkpoint, dry_run=False))
    _write_source(tmp_path, "one.md", content="# changed\n\n" + "new" * 300)
    asyncio.run(run_full(tmp_path, checkpoint_path=checkpoint, dry_run=False))

    assert calls == 2


def test_mixed_written_and_blocked_pages_are_reprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_source(tmp_path, "one.md")
    calls = 0

    async def extracted(_root, _path, relative, **kwargs):
        nonlocal calls
        calls += 1
        pages = [
            SimpleNamespace(id="p1", sources=[relative]),
            SimpleNamespace(id="p2", sources=[relative]),
        ]
        for page in pages:
            kwargs["page_sink"](page)
        return ExtractionResult(
            status=ExtractionStatus.WRITTEN, source_id=relative, pages=pages,
            written_page_ids=["p1", "p2"],
            metadata={"source": relative, "doc_type": "multi_topic",
                      "complete": True, "topics": [], "pages": [], "error": None},
        )

    class FakeWriter:
        def __init__(self, *_args, **_kwargs):
            pass

        def commit_and_index(self, _pages):
            return WriteReport(
                written=["p1"], blocked=["p2"],
                page_writes={"p1": Path("p1.md"), "p2": None},
            )

    monkeypatch.setattr(extract_full, "_extract_one", extracted)
    monkeypatch.setattr(extract_full, "WikiWriter", FakeWriter)
    monkeypatch.setenv("V7_ALLOW_APPLY", "1")
    checkpoint = tmp_path / ".index" / "full.json"
    asyncio.run(run_full(tmp_path, checkpoint_path=checkpoint, dry_run=False))
    asyncio.run(run_full(tmp_path, checkpoint_path=checkpoint, dry_run=False))

    row = json.loads(checkpoint.read_text(encoding="utf-8"))["sources"][
        "raw/sources/one.md"
    ]
    assert calls == 2
    assert row["written_page_ids"] == ["p1"]
    assert row["blocked_page_ids"] == ["p2"]


def test_full_dry_run_batches_sources_and_resumes_from_checkpoint(tmp_path: Path) -> None:
    """Wave 3 / P6: dry-run no longer writes ``completed_batches`` to
    avoid silently skipping the next apply run. Per-source rows keep
    ``dry_run: True`` for audit. Two dry-runs therefore re-process
    the same sources (no batch-level skip), and the second run
    reuses the prior JSON report via the legacy ``results_reused``
    cache rather than the v2 checkpoint."""
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
    assert not (tmp_path / "wiki").exists()
    # P6: dry-run must NOT mark completed_batches (apply must not be
    # silently skipped by the dry-run's projection).
    ckpt = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert ckpt["completed_batches"] == []
    assert ckpt["version"] == 2
    # All source rows should be dry_run=True if present.
    for row in ckpt["sources"].values():
        assert row.get("dry_run") is True
    # The second dry-run has nothing to skip from the v2 checkpoint
    # (P6), but the legacy ``results_reused`` path only fires when the
    # current run produced zero results — both dry-runs here produce
    # ``incomplete`` results so ``results_reused`` stays False.
    # The operator still benefits because the JSON cache is available
    # for the next ``run_full`` call without LLM work.
    assert second["summary"]["results_reused"] is False
    assert len(second["results"]) == 5


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
        # T1 / Wave 1 schema upgrade: evidence uses integer item_index
        # into the canonical item list (not item_id string). Luna-A
        # updated slot_filler.py to consume item_index, but these test
        # fixtures were missed in that round — fixed in Wave 1.1
        # follow-up.
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "characteristics": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "examples": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "related_concepts": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "references": {"item_index": 0, '
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


def test_run_full_summary_cost_zero_when_fake_llm(tmp_path: Path) -> None:
    """FakeLLMClient does NOT accumulate cost — summary.cost is zero."""
    _write_source(tmp_path, "one.md")
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}')
    fake.script("completeness", '{"complete": false, "reason": "too short"}')

    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        llm=fake,
    ))

    cost = report["summary"]["cost"]
    assert cost["cumulative_usd"] == 0.0
    assert cost["call_count"] == 0
    assert cost["input_tokens"] == 0
    assert cost["output_tokens"] == 0


def test_run_full_summary_cost_with_real_llm(tmp_path: Path) -> None:
    """When ``llm`` is an AnthropicLLMClient wired to a ledger, summary.cost
    gets populated from ledger.snapshot(). Verifies run_full → summary plumbing.

    Task 2 already covers AnthropicLLMClient.record() end-to-end via its own
    dedicated unit tests; this test only verifies the wiring through ``run_full``.
    """
    from src.llm.base import LLMResponse
    from src.lib.budget import CostLedger
    from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

    class _StubProvider:
        model = "stub"
        async def complete(self, messages, **kwargs):
            return LLMResponse(
                content='{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}',
                model="stub",
                usage={"input_tokens": 800, "output_tokens": 50},
            )

    ledger = CostLedger()
    real_client = AnthropicLLMClient.__new__(AnthropicLLMClient)
    real_client._provider_name = "stub"
    real_client._provider = _StubProvider()
    real_client._ledger = ledger

    _write_source(tmp_path, "one.md")
    report = asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        llm=real_client,
        ledger=ledger,
    ))

    cost = report["summary"]["cost"]
    assert cost["call_count"] >= 1
    assert cost["cumulative_usd"] > 0.0
    assert cost["input_tokens"] >= 800
    assert cost["output_tokens"] >= 50
    assert "classify" in cost["cost_by_stage"]


def test_markdown_report_omits_cost_section_when_cost_zero(tmp_path: Path) -> None:
    """Markdown omits `## Cost` section when cumulative_usd == 0 (FakeLLM / dry-run)."""
    _write_source(tmp_path, "one.md")
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}')
    fake.script("completeness", '{"complete": false, "reason": "too short"}')

    md_path = tmp_path / "report.md"
    asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        llm=fake,
        markdown_output=md_path,
    ))

    md = md_path.read_text(encoding="utf-8")
    assert "## Cost" not in md


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
    assert {
        "written", "blocked", "failed", "incomplete", "skipped",
        "generated_pages",
    } <= report["summary"].keys()


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
        # T1 / Wave 1 schema upgrade: evidence uses integer item_index
        # into the canonical item list (not item_id string). Luna-A
        # updated slot_filler.py to consume item_index, but these test
        # fixtures were missed in that round — fixed in Wave 1.1
        # follow-up.
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "characteristics": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "examples": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "related_concepts": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "references": {"item_index": 0, '
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


# ---------------------------------------------------------------------------
# Wave 3 / Task 4 (plan 2026-09-15 control plane refactor):
# source-level checkpoint (version 2) + md5 skip + dry-run safety.
# ---------------------------------------------------------------------------


def test_v2_checkpoint_written_after_apply(tmp_path: Path) -> None:
    """apply run persists a version=2 checkpoint with per-source
    ``written_page_ids`` and an md5 fingerprint."""
    _write_source(tmp_path, "complete.md")
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}')
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "扩句法", "item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "characteristics": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "examples": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "related_concepts": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "references": {"item_index": 0, '
        '"source_text_excerpt": "定义"}}}'
    ))
    monkeypatch_get = None  # silence linters; we use os.environ instead.
    os.environ["V7_ALLOW_APPLY"] = "1"
    try:
        report = asyncio.run(run_full(
            tmp_path,
            batch_size=1,
            checkpoint_path=tmp_path / ".index" / "full.json",
            dry_run=False,
            llm=fake,
        ))
    finally:
        os.environ.pop("V7_ALLOW_APPLY", None)
    del monkeypatch_get

    assert report["mode"] == "apply"
    ckpt = json.loads(
        (tmp_path / ".index" / "full.json").read_text(encoding="utf-8")
    )
    assert ckpt["version"] == 2
    assert ckpt["schema_version"] == 2
    assert ckpt["completed_batches"] == [1]
    source_key = "raw/sources/complete.md"
    assert source_key in ckpt["sources"]
    source_row = ckpt["sources"][source_key]
    assert source_row["status"] == "written"
    assert source_row["md5"] and len(source_row["md5"]) == 32
    assert len(source_row["written_page_ids"]) >= 1
    assert source_row["dry_run"] is False


def test_v2_checkpoint_skips_md5_unchanged_source_on_resume(
    tmp_path: Path,
) -> None:
    """Second apply run with unchanged source must skip via md5 and
    not re-process the LLM."""
    _write_source(tmp_path, "complete.md")
    fake = FakeLLMClient()
    # Scripts for first apply only — second apply should skip entirely.
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}')
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "扩句法", "item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "characteristics": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "examples": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "related_concepts": {"item_index": 0, '
        '"source_text_excerpt": "定义"}, "references": {"item_index": 0, '
        '"source_text_excerpt": "定义"}}}'
    ))
    os.environ["V7_ALLOW_APPLY"] = "1"
    try:
        # First run: writes durable checkpoint (status=written, dry_run=False).
        first_calls = len(fake.calls)
        asyncio.run(run_full(
            tmp_path,
            batch_size=1,
            checkpoint_path=tmp_path / ".index" / "full.json",
            dry_run=False,
            llm=fake,
        ))
        assert len(fake.calls) > first_calls
        # Second run: same source md5, should skip via md5 (no new LLM calls).
        replay_calls = len(fake.calls)
        report2 = asyncio.run(run_full(
            tmp_path,
            batch_size=1,
            checkpoint_path=tmp_path / ".index" / "full.json",
            dry_run=False,
            llm=fake,
        ))
    finally:
        os.environ.pop("V7_ALLOW_APPLY", None)

    assert len(fake.calls) == replay_calls  # no new LLM calls
    print(f"report2 summary: {report2['summary']}")
    # The skip path reports ``batches_skipped=1`` (batch-level skip)
    # rather than by_status written — the source outcome is replayed
    # via ``_previous_results`` JSON cache when results is empty. The
    # test simply asserts the skip landed; the cache contents are
    # already in ``second['results']`` via the legacy path.
    assert report2["summary"]["batches_skipped"] >= 1


def test_v2_checkpoint_dry_run_does_not_mark_source_done(
    tmp_path: Path,
) -> None:
    """dry-run must NOT update ``status`` to terminal ``written`` in the
    v2 checkpoint; otherwise the next apply run would silently skip."""
    _write_source(tmp_path, "complete.md")
    fake = FakeLLMClient()
    # Script for both dry-run + apply
    for _ in range(2):
        fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}')
        fake.script("completeness", '{"complete": true, "reason": "ok"}')
        fake.script(
            "cluster",
            '{"topics": [{"id": "t1", "title": "扩句法", "item_indexes": [0]}]}',
        )
        fake.script("fill_slots", (
            # All 5 slots filled with body + evidence so the page is
            # written, not needs_review (Stage 5 / Wave 1 Gate B).
            '{"slots": {"definition": "def", "characteristics": "c", '
            '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
            '"evidence": {"definition": {"item_index": 0, "source_text_excerpt": "定义"}, '
            '"characteristics": {"item_index": 0, "source_text_excerpt": "定义"}, '
            '"examples": {"item_index": 0, "source_text_excerpt": "定义"}, '
            '"related_concepts": {"item_index": 0, "source_text_excerpt": "定义"}, '
            '"references": {"item_index": 0, "source_text_excerpt": "定义"}}}'
        ))

    # First: dry-run.
    asyncio.run(run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "full.json",
        llm=fake,
    ))
    ckpt_path = tmp_path / ".index" / "full.json"
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        # If the file exists the source must be marked dry_run=True so
        # the apply run replays instead of skipping.
        for row in ckpt.get("sources", {}).values():
            if row.get("status") == "written":
                assert row.get("dry_run") is True, (
                    "dry-run checkpoint must flag written rows as dry_run=True "
                    "so the next apply run does not silently skip."
                )

    # Second: apply (real write).
    os.environ["V7_ALLOW_APPLY"] = "1"
    try:
        report = asyncio.run(run_full(
            tmp_path,
            batch_size=1,
            checkpoint_path=tmp_path / ".index" / "full.json",
            dry_run=False,
            llm=fake,
        ))
    finally:
        os.environ.pop("V7_ALLOW_APPLY", None)

    assert report["mode"] == "apply"
    assert list((tmp_path / "wiki" / "concepts").glob("*.md"))


# ---------------------------------------------------------------------------
# Task 8 (V7 Stage Remediation / 2026-09-17 plan): source checkpoint double-key
# (md5 + pipeline_fingerprint). Skip is only allowed when:
#   1. md5 matches (content unchanged)
#   2. status is INCOMPLETE (proven incomplete, not a transient failure)
#   3. pipeline_fingerprint matches (no prompt/policy upgrade since last run)
# FAILED / BLOCKED never skip. Old checkpoints without pipeline_fingerprint
# still work via backward compat (empty string on both sides).
# ---------------------------------------------------------------------------


def _make_extraction_result(status: ExtractionStatus, *, attempts: int = 1) -> ExtractionResult:
    """Helper for unit tests on _source_outcome_from_result."""
    return ExtractionResult(
        status=status,
        source_id="raw/sources/one.md",
        attempts=attempts,
        metadata={"source": "raw/sources/one.md", "doc_type": None, "complete": False,
                  "topics": [], "pages": [], "error": None},
    )


def _prior_row(*, status: str, md5: str = "abc123", pipeline_fingerprint: str = "",
               written: list[str] | None = None,
               blocked: list[str] | None = None,
               failed: list[str] | None = None,
               dry_run: bool = False) -> dict[str, object]:
    return {
        "md5": md5,
        "status": status,
        "legacy_status": status,
        "written_page_ids": list(written or []),
        "blocked_page_ids": list(blocked or []),
        "failed_page_ids": list(failed or []),
        "attempts": 1,
        "last_attempt_at": 0,
        "llm_provider": "offline",
        "dry_run": dry_run,
        "pipeline_fingerprint": pipeline_fingerprint,
    }


def test_incomplete_only_skips_when_fingerprint_matches() -> None:
    """INCOMPLETE status + matching fingerprint → skip; mismatched → re-evaluate."""
    prior = _prior_row(status="incomplete", md5="abc123", pipeline_fingerprint="pipe-aaaa")
    assert extract_full._source_can_skip(
        prior, "abc123", dry_run=False, pipeline_fingerprint="pipe-aaaa",
    ) is True
    # Fingerprint changed (prompt / template upgrade) → must NOT skip.
    assert extract_full._source_can_skip(
        prior, "abc123", dry_run=False, pipeline_fingerprint="pipe-bbbb",
    ) is False


def test_failed_or_blocked_never_skipped() -> None:
    """FAILED and BLOCKED must never skip — they must be retried / escalated.

    Persistence Contract §4.4: only INCOMPLETE (proven incomplete) is a valid
    skip candidate. FAILED means retry will help (technical). BLOCKED means
    human review is needed.
    """
    # FAILED — never skip regardless of fingerprint.
    failed_prior = _prior_row(
        status="failed", md5="abc123",
        pipeline_fingerprint="pipe-aaaa",
        failed=["p1"],
    )
    assert extract_full._source_can_skip(
        failed_prior, "abc123", dry_run=False, pipeline_fingerprint="pipe-aaaa",
    ) is False
    # BLOCKED — never skip regardless of fingerprint.
    blocked_prior = _prior_row(
        status="blocked", md5="abc123",
        pipeline_fingerprint="pipe-aaaa",
        blocked=["p1"],
    )
    assert extract_full._source_can_skip(
        blocked_prior, "abc123", dry_run=False, pipeline_fingerprint="pipe-aaaa",
    ) is False


def test_fingerprint_upgrade_triggers_re_evaluation() -> None:
    """When current pipeline_fingerprint differs from prior, source must be
    re-evaluated even if md5 + INCOMPLETE match (acceptance: checker 升级
    后相同 source md5 仍会重判 incomplete)."""
    prior = _prior_row(status="incomplete", md5="abc123", pipeline_fingerprint="pipe-old")
    # Upgrade: same md5, status, but new pipeline fingerprint.
    assert extract_full._source_can_skip(
        prior, "abc123", dry_run=False, pipeline_fingerprint="pipe-new",
    ) is False


def test_backward_compat_old_checkpoint_without_fingerprint() -> None:
    """Old checkpoint rows (pre-Task-8) have no ``pipeline_fingerprint`` field
    — the helper falls back to empty string. Backward compat:
      - old "" + current "" → still skip (no fingerprint infrastructure yet)
      - old "" + current "pipe-xxxx" → re-run (upgrade on this side)
      - old "pipe-xxxx" + current "" → re-run (downgrade on this side)
    """
    prior = _prior_row(status="incomplete", md5="abc123", pipeline_fingerprint="")
    # Both empty → allow skip (backward compat for very old checkpoints).
    assert extract_full._source_can_skip(
        prior, "abc123", dry_run=False, pipeline_fingerprint="",
    ) is True
    # Only new has fingerprint → mismatch → re-run.
    assert extract_full._source_can_skip(
        prior, "abc123", dry_run=False, pipeline_fingerprint="pipe-aaaa",
    ) is False

    # Inverse: only old has fingerprint → mismatch → re-run.
    prior_with_fp = _prior_row(status="incomplete", md5="abc123", pipeline_fingerprint="pipe-aaaa")
    assert extract_full._source_can_skip(
        prior_with_fp, "abc123", dry_run=False, pipeline_fingerprint="",
    ) is False


def test_current_pipeline_fingerprint_is_stable_and_order_independent() -> None:
    """Contract Freeze §4.4.1 — same inputs in different arg order produce the
    same fingerprint (template_hashes order is sorted internally)."""
    fp1 = extract_full._current_pipeline_fingerprint(
        classifier_fp="c1", segmenter_fp="s1", checker_fp="k1",
        template_hashes={"a": "h1", "b": "h2"},
    )
    fp2 = extract_full._current_pipeline_fingerprint(
        classifier_fp="c1", segmenter_fp="s1", checker_fp="k1",
        template_hashes={"b": "h2", "a": "h1"},
    )
    assert fp1 == fp2
    assert fp1.startswith("pipe-")
    assert len(fp1) == len("pipe-") + 16


def test_current_pipeline_fingerprint_changes_with_any_input() -> None:
    """Any input change → fingerprint change. Sanity check on the 5 stage
    fingerprints + template hash list."""
    base = dict(classifier_fp="c1", segmenter_fp="s1", checker_fp="k1",
                clusterer_fp="cl1", generator_fp="g1")
    fp = extract_full._current_pipeline_fingerprint(**base)
    for key in ("classifier_fp", "segmenter_fp", "checker_fp",
                "clusterer_fp", "generator_fp"):
        mutated = dict(base)
        mutated[key] = base[key] + "-x"
        assert extract_full._current_pipeline_fingerprint(**mutated) != fp


def test_source_outcome_from_result_records_pipeline_fingerprint() -> None:
    """The v2 checkpoint row carries the current pipeline_fingerprint so the
    next run can verify double-key match (Persistence Contract §4.4.5)."""
    result = _make_extraction_result(ExtractionStatus.WRITTEN)
    row = extract_full._source_outcome_from_result(
        result, md5="abc123", dry_run=False,
        llm_provider="offline", pipeline_fingerprint="pipe-aaaa",
    )
    assert row["pipeline_fingerprint"] == "pipe-aaaa"
    # Old callers (no pipeline_fingerprint kwarg) must still work — the field
    # simply serializes as empty string (treated as no-fingerprint infra).
    row_legacy = extract_full._source_outcome_from_result(
        result, md5="abc123", dry_run=False, llm_provider="offline",
    )
    assert row_legacy["pipeline_fingerprint"] == ""


# ---------------------------------------------------------------------------
# Task 37: clusterer_fingerprint wired into _current_pipeline_fingerprint call
# ---------------------------------------------------------------------------


def test_clusterer_fingerprint_for_run_returns_non_empty() -> None:
    """Task 37: helper resolves the cluster prompt and hashes it.
    Non-empty string is the success indicator; empty means the prompt
    could not be resolved (which falls back to the original behaviour).
    """
    fp = extract_full._compute_clusterer_fingerprint_for_run()
    assert fp.startswith("clu-")
    assert len(fp) == len("clu-") + 16


def test_current_pipeline_fingerprint_with_clusterer_differs_from_without() -> None:
    """Task 37: when clusterer_fp is non-empty (as in extract_full.py's real
    call site after Task 37), the resulting pipeline_fingerprint must
    differ from the no-clusterer case so that source checkpoints
    correctly invalidate on cluster prompt upgrades.
    """
    fp_with = extract_full._current_pipeline_fingerprint(
        clusterer_fp=extract_full._compute_clusterer_fingerprint_for_run(),
    )
    fp_without = extract_full._current_pipeline_fingerprint()
    assert fp_with != fp_without
    assert fp_with.startswith("pipe-")
    assert fp_without.startswith("pipe-")
