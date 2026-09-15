"""T3.3: review_queue_cli (D8) tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_queue(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_cli(*args: str, queue_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts" / "review_queue_cli.py"),
            "--queue-path", str(queue_path),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_list_shows_all_items(tmp_path: Path) -> None:
    items = [
        {"id": "r1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": None},
        {"id": "r2", "source": "generator", "failure_stage": "filter",
         "reason": "y", "resolved_at": None},
    ]
    queue = tmp_path / "queue.json"
    _write_queue(queue, items)

    result = _run_cli("list", queue_path=queue)
    assert result.returncode == 0
    assert "r1" in result.stdout
    assert "r2" in result.stdout


def test_list_filters_by_source_v7(tmp_path: Path) -> None:
    items = [
        {"id": "r1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": None},
        {"id": "r2", "source": "generator", "failure_stage": "filter",
         "reason": "y", "resolved_at": None},
    ]
    queue = tmp_path / "queue.json"
    _write_queue(queue, items)

    result = _run_cli("list", "--source=v7_extract", queue_path=queue)
    assert result.returncode == 0
    assert "r1" in result.stdout
    assert "r2" not in result.stdout


def test_list_filters_open_items(tmp_path: Path) -> None:
    items = [
        {"id": "open1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": None},
        {"id": "resolved1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": 1726000000000},
    ]
    queue = tmp_path / "queue.json"
    _write_queue(queue, items)

    result = _run_cli("list", "--open", queue_path=queue)
    assert result.returncode == 0
    assert "open1" in result.stdout
    assert "resolved1" not in result.stdout


def test_list_json_output(tmp_path: Path) -> None:
    items = [
        {"id": "r1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": None},
    ]
    queue = tmp_path / "queue.json"
    _write_queue(queue, items)

    result = _run_cli("list", "--json", queue_path=queue)
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["id"] == "r1"


def test_resolve_marks_resolved(tmp_path: Path) -> None:
    items = [
        {"id": "r1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": None},
        {"id": "r2", "source": "generator", "failure_stage": "filter",
         "reason": "y", "resolved_at": None},
    ]
    queue = tmp_path / "queue.json"
    _write_queue(queue, items)

    result = _run_cli("resolve", "r1", "--action=promoted", queue_path=queue)
    assert result.returncode == 0
    assert "resolved r1" in result.stdout

    updated = json.loads(queue.read_text(encoding="utf-8"))["items"]
    r1 = next(it for it in updated if it["id"] == "r1")
    assert r1["resolution"] == "promoted"
    assert r1["resolved_at"] is not None
    # r2 unchanged
    r2 = next(it for it in updated if it["id"] == "r2")
    assert r2["resolved_at"] is None


def test_resolve_unknown_id_fails(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    _write_queue(queue, [])

    result = _run_cli("resolve", "nonexistent", "--action=promoted", queue_path=queue)
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_stats_groups_by_source_and_stage(tmp_path: Path) -> None:
    items = [
        {"id": "r1", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": None},
        {"id": "r2", "source": "v7_extract", "failure_stage": "stage5",
         "reason": "x", "resolved_at": None},
        {"id": "r3", "source": "v7_extract", "failure_stage": "stage1",
         "reason": "x", "resolved_at": 1726000000000},
        {"id": "r4", "source": "generator", "failure_stage": "filter",
         "reason": "y", "resolved_at": None},
    ]
    queue = tmp_path / "queue.json"
    _write_queue(queue, items)

    result = _run_cli("stats", queue_path=queue)
    assert result.returncode == 0
    assert "Total: 4" in result.stdout
    assert "Open: 3" in result.stdout
    # By source
    assert "v7_extract" in result.stdout
    assert "generator" in result.stdout
    # By stage
    assert "stage1" in result.stdout
    assert "stage5" in result.stdout


def test_list_empty_queue(tmp_path: Path) -> None:
    queue = tmp_path / "queue.json"
    _write_queue(queue, [])
    result = _run_cli("list", queue_path=queue)
    assert result.returncode == 0
    assert "empty" in result.stdout.lower() or result.stdout.strip() == ""
