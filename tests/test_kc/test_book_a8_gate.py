from __future__ import annotations

import json
from pathlib import Path
from subprocess import run
import sys

import pytest


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "book_rebuild_fixture.json"
SCRIPT = ROOT / "scripts" / "kc_book_a8_accept.py"


def _run(fixture: Path = FIXTURE):
    return run([sys.executable, str(SCRIPT), "--fixture", str(fixture)], cwd=ROOT, capture_output=True, text=True)


def test_a8_acceptance_fixture_passes() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert len(payload["checks"]) == 8


@pytest.mark.parametrize("mutation", ["missing", "invalid_json", "empty"])
def test_a8_acceptance_rejects_non_evaluable_fixture(tmp_path: Path, mutation: str) -> None:
    target = tmp_path / "fixture.json"
    if mutation == "missing":
        target = tmp_path / "missing.json"
    elif mutation == "invalid_json":
        target.write_text("not json", encoding="utf-8")
    else:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["book"]["chapter_ids"] = []
        payload["chapters"] = []
        target.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(target)
    assert result.returncode != 0


def test_a8_acceptance_reports_snapshot_validation_error(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["chapters"].append(dict(payload["chapters"][0]))
    target = tmp_path / "duplicate.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(target)
    assert result.returncode != 0
    assert "duplicate_id" in result.stdout
