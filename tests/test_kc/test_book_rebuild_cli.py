from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "kc_book_rebuild.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "book_rebuild_fixture.json"


def _run_cli(project_root: Path, snapshot: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(project_root),
            "--snapshot",
            str(snapshot),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _report(proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert proc.stdout, proc.stderr
    return json.loads(proc.stdout)


def test_cli_dry_run_parses_snapshot_and_writes_nothing(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    proc = _run_cli(project_root, FIXTURE, "--dry-run")

    assert proc.returncode == 0, proc.stderr
    report = _report(proc)
    assert report["status"] == "planned"
    assert report["book_id"] == "book-1"
    assert report["publication_version"] == 7
    assert report["rebuilt_chapter_ids"] == ["ch-1", "ch-2", "ch-3"]
    assert report["failed_chapter_ids"] == []
    assert report["reason_codes"] == []
    assert sorted(report["rendered_hashes"]) == ["ch-1", "ch-2", "ch-3"]
    assert report["output_dir"] == str(project_root / "book")
    assert not (project_root / "book").exists()


def test_cli_apply_creates_markdown_and_metadata_from_empty_book_dir(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    proc = _run_cli(project_root, FIXTURE, "--apply")

    assert proc.returncode == 0, proc.stderr
    report = _report(proc)
    assert report["status"] == "committed"

    output_dir = project_root / "book"
    for chapter_id in ("ch-1", "ch-2", "ch-3"):
        markdown_path = output_dir / f"{chapter_id}.md"
        metadata_path = output_dir / f"{chapter_id}.json"
        assert markdown_path.exists()
        assert metadata_path.exists()
        assert "publication_version: 7" in markdown_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["chapter_id"] == chapter_id
        assert metadata["rendered_hash"] == report["rendered_hashes"][chapter_id]


def test_cli_repeated_apply_keeps_rendered_hashes_stable(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    first = _run_cli(project_root, FIXTURE, "--apply")
    second = _run_cli(project_root, FIXTURE, "--apply")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_report = _report(first)
    second_report = _report(second)
    assert first_report["rendered_hashes"] == second_report["rendered_hashes"]


def test_cli_apply_with_chapter_preserves_unrelated_chapter_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    first = _run_cli(project_root, FIXTURE, "--apply")
    assert first.returncode == 0, first.stderr

    output_dir = project_root / "book"
    untouched_md = (output_dir / "ch-2.md").read_text(encoding="utf-8")
    untouched_json = (output_dir / "ch-2.json").read_text(encoding="utf-8")

    second = _run_cli(project_root, FIXTURE, "--apply", "--chapter", "ch-1")

    assert second.returncode == 0, second.stderr
    report = _report(second)
    assert report["rebuilt_chapter_ids"] == ["ch-1"]
    assert (output_dir / "ch-2.md").read_text(encoding="utf-8") == untouched_md
    assert (output_dir / "ch-2.json").read_text(encoding="utf-8") == untouched_json


def test_cli_bad_snapshot_returns_nonzero_and_structured_json_failure(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    bad_snapshot = tmp_path / "bad_snapshot.json"
    bad_snapshot.write_text(
        json.dumps(
            {
                "book": {},
                "chapters": [],
                "knowledge_units": [],
                "evidences": [],
                "publication_version": 7,
            }
        ),
        encoding="utf-8",
    )

    proc = _run_cli(project_root, bad_snapshot, "--dry-run")

    assert proc.returncode != 0
    report = _report(proc)
    assert report["status"] == "failed"
    assert report["failed_object_ids"] == ["snapshot"]
    assert any(str(code).startswith("snapshot:") for code in report["reason_codes"])
