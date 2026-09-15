"""Tests for scripts/extract_pilot.py — v3.0 (async run_pilot)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.extract_pilot import run_pilot
from src.pipeline.v7_extract.llm_client import FakeLLMClient


@pytest.fixture(autouse=True)
def _scrub_d9_temp_whitelist(monkeypatch):
    """D9: the resolver rejects tmp_path (which lives under %TEMP%) unless
    we clear the temp env vars. Pilot tests always pass a tmp_path as
    project_root, so this scrub is required."""
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TMP", raising=False)


def _write_source(root: Path, name: str, content: str) -> None:
    path = root / "raw" / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_run_pilot_selects_deterministic_sources_and_never_writes_wiki(
    tmp_path: Path,
) -> None:
    for index in range(4):
        _write_source(
            tmp_path,
            f"source-{index}.md",
            f"# 主题 {index}\n\n这是一个足够长的来源正文。" * 120,
        )

    report = asyncio.run(run_pilot(tmp_path, count=3, seed=7))

    assert report["mode"] == "dry-run"
    assert report["summary"]["selected"] == 3
    assert len(report["sources"]) == 3
    assert report["sources"] == asyncio.run(
        run_pilot(tmp_path, count=3, seed=7)
    )["sources"]
    assert not (tmp_path / "wiki").exists()
    assert not (tmp_path / ".index").exists()


def test_run_pilot_reports_classification_and_pages(tmp_path: Path) -> None:
    """v3: doc_type is now a plain string (was DocType.value)."""
    # Long enough to pass Stage 3 completeness heuristic (was 800 chars)
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    _write_source(tmp_path, "short.md", "# 只有标题\n\n简介")

    fake = FakeLLMClient()
    fake.script(
        "classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}'
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "Topic 1", "item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": '
        '{"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": '
        '{"definition": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"characteristics": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"examples": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"related_concepts": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"references": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}}}'
    ))

    report = asyncio.run(run_pilot(tmp_path, count=10, seed=1, llm=fake))
    by_name = {item["source"]: item for item in report["results"]}

    # doc_type is a string, not an enum
    assert by_name["raw/sources/short.md"]["doc_type"] == "incomplete"
    assert by_name["raw/sources/short.md"]["pages"] == []


def test_write_report_emits_json_and_markdown_without_wiki_writes(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    report = asyncio.run(run_pilot(
        tmp_path,
        count=1,
        seed=1,
        json_output=json_path,
        markdown_output=markdown_path,
    ))

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# V7 Extract Pilot Report" in markdown
    assert "dry-run" in markdown
    assert not (tmp_path / "wiki").exists()


def test_direct_script_entrypoint_bootstraps_repo_imports(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)
    json_path = tmp_path / "direct.json"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts" / "extract_pilot.py"),
            "--root",
            str(tmp_path),
            "--count",
            "1",
            "--json-out",
            str(json_path),
            "--markdown-out",
            str(tmp_path / "direct.md"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json_path.exists()


def test_run_pilot_records_llm_enabled_when_injected(tmp_path: Path) -> None:
    """The report's `llm_enabled` flag reflects whether an LLM was injected."""
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)

    without_llm = asyncio.run(run_pilot(tmp_path, count=1, seed=1))
    assert without_llm["llm_enabled"] is False

    fake = FakeLLMClient()
    fake.script(
        "classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}'
    )
    fake.script("completeness", '{"complete": false, "reason": "too short"}')
    with_llm = asyncio.run(run_pilot(tmp_path, count=1, seed=1, llm=fake))
    assert with_llm["llm_enabled"] is True
    assert fake.calls, "FakeLLMClient should have been invoked for at least one prompt_kind"


def test_run_pilot_broken_llm_keeps_pipeline_running(tmp_path: Path) -> None:
    """v3 (P2): a broken LLM doesn't crash the pilot — classification
    falls back to INCOMPLETE, no pages are written, error is recorded."""
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    fake = FakeLLMClient()
    # queue garbage for every prompt kind
    for kind in ("classify", "completeness", "cluster", "fill_slots"):
        for _ in range(5):
            fake.script(kind, "this is not json")

    report = asyncio.run(run_pilot(tmp_path, count=1, seed=1, llm=fake))
    assert report["llm_enabled"] is True
    by_name = {item["source"]: item for item in report["results"]}
    page = by_name["raw/sources/complete.md"]
    # No pages because LLM failed every retry
    assert page["pages"] == []
    # doc_type is "incomplete" because classify_doc returned fallback
    assert page["doc_type"] == "incomplete"
    # completeness is False because Stage 3 LLM also failed
    assert page["complete"] is False
    # No exception propagated up — the pilot ran to completion (P2)
    assert all("error" in item for item in report["results"])
