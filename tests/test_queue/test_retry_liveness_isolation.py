"""Regression test for retry-liveness queue state isolation."""

import json
import os
from pathlib import Path
import subprocess
import sys


_QUEUE_SEED = {
    "id": "stale-queue-task",
    "source": "stale.txt",
    "source_type": "file",
    "status": "pending",
    "task_hash": "stale-queue-hash",
    "created_at": 0,
    "updated_at": 0,
    "retry_count": 0,
    "error": None,
    "raw_path": None,
    "note_path": None,
    "knowledge_path": None,
    "project_id": None,
}


def test_retry_liveness_module_can_run_twice_without_queue_contamination(tmp_path):
    """A stale persisted task must not poison either consecutive module run."""
    repo_root = Path(__file__).resolve().parents[2]
    queue_file = tmp_path / ".kb-queue.json"
    retry_module = Path(__file__).with_name("test_queue_retry_liveness.py")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment.pop("PYTEST_CURRENT_TEST", None)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(repo_root), environment.get("PYTHONPATH", "")) if part
    )

    queue_file.write_text(json.dumps([_QUEUE_SEED]), encoding="utf-8")
    try:
        results = [
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--import-mode=importlib",
                    "-q",
                    "--basetemp",
                    str(tmp_path / f"child-{run_number}"),
                    str(retry_module),
                ],
                cwd=tmp_path,
                env=environment,
                capture_output=True,
                text=True,
            )
            for run_number in range(1, 3)
        ]
    finally:
        queue_file.unlink(missing_ok=True)

    for run_number, result in enumerate(results, start=1):
        assert result.returncode == 0, (
            f"retry-liveness run {run_number} failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
