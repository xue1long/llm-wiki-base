from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.extract_full import run_full


def _write_source(root: Path, name: str, content: str = "# 标题\n\n" + "正文。" * 300) -> None:
    path = root / "raw" / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_full_dry_run_batches_sources_and_resumes_from_checkpoint(tmp_path: Path) -> None:
    for index in range(5):
        _write_source(tmp_path, f"source-{index}.md")
    checkpoint = tmp_path / ".index" / "full.json"
    report_path = tmp_path / "report.json"

    first = run_full(tmp_path, batch_size=2, checkpoint_path=checkpoint, json_output=report_path)
    second = run_full(tmp_path, batch_size=2, checkpoint_path=checkpoint, json_output=report_path)

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

    report = run_full(
        tmp_path,
        batch_size=1,
        checkpoint_path=tmp_path / ".index" / "checkpoint.json",
        json_output=json_path,
        markdown_output=markdown_path,
    )

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert "# V7 Extract Full Dry-Run Report" in markdown_path.read_text(encoding="utf-8")


def test_full_apply_is_fail_closed_before_pilot_approval(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md")

    with pytest.raises(RuntimeError, match="spot-check"):
        run_full(tmp_path, dry_run=False)
