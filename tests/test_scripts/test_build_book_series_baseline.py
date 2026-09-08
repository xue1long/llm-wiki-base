"""Build the deterministic book-series baseline snapshot for the real novel-wiki.

Plan: docs/superpowers/plans/2026-09-06-novel-wiki-book-series-compile-enable.md
Slice S4: scripts/build_book_series_baseline.py writes the audit trail
under .llm-wiki/book-series/baselines/<snapshot_sha[:12]>.json (gitignored).

The script re-runs ``evaluate_series_gate`` with the relaxed NOVEL_WIKI_PROFILE
plus auto-derived chapter_exit_evidence and persists a JSON snapshot that
includes the reader_profile/governance fingerprint, gate metrics, and
per-candidate decisions. It must:

* Fail closed on WikiScanError.
* Resolve project_root and wiki_root from a project_path argument (no
  implicit CWD reliance).
* Write to a gitignored location (the harness must not push the snapshot).
* Keep up to 5 historical baselines per snapshot_id stem; delete older ones.
* Be idempotent: re-running produces byte-equivalent JSON modulo timestamps.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run_script(project_path: Path, *extra_args: str,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, "-m", "scripts.build_book_series_baseline",
        "--project-root", str(project_path),
        *extra_args,
    ]
    merged_env = {
        "PYTHONPATH": str(REPO),
        "TEMP": str(REPO / ".tmp-pytest"),
        "TMP": str(REPO / ".tmp-pytest"),
        "TMPDIR": str(REPO / ".tmp-pytest"),
        # Force UTF-8 stdout on Windows so PowerShell's cp936 console does
        # not corrupt the JSON summary's non-ASCII candidate IDs.
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    if env:
        merged_env.update(env)
    # Use bytes mode so non-ASCII candidate IDs round-trip cleanly on
    # Windows (cp936) consoles.
    proc = subprocess.run(
        cmd, cwd=str(REPO), capture_output=True,
        env={**__import__("os").environ, **merged_env}, check=False,
    )
    proc.stdout = proc.stdout.decode("utf-8", errors="replace")
    proc.stderr = proc.stderr.decode("utf-8", errors="replace")
    return proc


def _write_minimal_novel_wiki(root: Path) -> None:
    """Mirror the real novel-wiki shape: writing-craft with 30 concept + 1 synthesis.

    Writes the ``primary_taxonomy`` field with raw UTF-8 bytes so the
    fixture does not depend on the host console encoding. PowerShell's
    default ``cp936`` would otherwise mojibake the CJK string when the
    test fixture is persisted via ``write_text``.
    """
    wiki = root / "wiki"
    for d in ("concepts", "entities", "synthesis"):
        (wiki / d).mkdir(parents=True, exist_ok=True)
    # UTF-8 bytes for `写作技法` (U+5199 U+4F5C U+6280 U+6CD5).
    tax = b"\xe5\x86\x99\xe4\xbd\x9c\xe6\x8a\x80\xe6\xb3\x95"
    synth_id = "wc-s0"
    for i in range(30):
        text = (
            b"---\n"
            b"id: wc-c" + str(i).encode() + b"\n"
            b"title: concept " + str(i).encode() + b"\n"
            b"type: concept\n"
            b"primary_taxonomy: " + tax + b"\n"
            b"sources:\n  - source-wc-c" + str(i).encode() + b"\n"
            b"relations:\n"
            b"  - target: " + synth_id.encode() + b"\n"
            b"    type: supports\n"
            b"---\n# H\nbody\n"
        )
        (wiki / "concepts" / f"wc-c{i}.md").write_bytes(text)
    (wiki / "synthesis" / f"{synth_id}.md").write_bytes(
        b"---\n"
        b"id: " + synth_id.encode() + b"\n"
        b"title: synthesis 0\n"
        b"type: synthesis\n"
        b"primary_taxonomy: " + tax + b"\n"
        b"sources:\n  - source-" + synth_id.encode() + b"\n"
        b"---\n# S\nbody\n"
    )
    (root / ".llm-wiki").mkdir(exist_ok=True)
    (root / ".llm-wiki" / "project.json").write_text(
        '{"id":"00000000-0000-0000-0000-000000000000","name":"novel-wiki-mini","schema_version":"v2.0"}',
        encoding="utf-8",
    )


def test_baseline_script_writes_to_gitignored_path(tmp_path: Path) -> None:
    """The script must write its snapshot under ``.llm-wiki/book-series/baselines/``,
    which is gitignored. We assert the path is excluded by checking that the
    .gitignore has the matching pattern and that the script's output dir
    lives beneath .llm-wiki.
    """
    project = tmp_path / "novel-wiki-mini"
    project.mkdir()
    _write_minimal_novel_wiki(project)

    result = _run_script(project)
    assert result.returncode == 0, (
        f"baseline script failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    baseline_dir = project / ".llm-wiki" / "book-series" / "baselines"
    assert baseline_dir.is_dir(), f"baseline dir not created: {baseline_dir}"

    files = sorted(baseline_dir.glob("*.json"))
    assert len(files) == 1, f"expected 1 baseline file, got {len(files)}: {files}"

    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["project_root"] == str(project.resolve())
    assert payload["llm_called"] is False
    assert payload["network_called"] is False
    assert payload["generation_mode"] == "rule_only"

    candidates = {c["candidate_id"]: c for c in payload["candidates"]}
    assert "写作技法" in candidates, candidates
    wc = candidates["写作技法"]
    assert wc["decision"] == "proceed", wc
    assert wc["closure_status"] == "closed", wc

    # Verify the path is gitignored
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".llm-wiki" in gitignore, ".llm-wiki must be gitignored"


def test_baseline_script_is_idempotent(tmp_path: Path) -> None:
    """Running the script twice writes a second historical baseline but
    keeps the first one. After two runs there are exactly 2 files.
    """
    project = tmp_path / "novel-wiki-mini"
    project.mkdir()
    _write_minimal_novel_wiki(project)

    first = _run_script(project)
    assert first.returncode == 0, first.stderr
    second = _run_script(project)
    assert second.returncode == 0, second.stderr

    files = sorted((project / ".llm-wiki" / "book-series" / "baselines").glob("*.json"))
    assert len(files) == 2, f"expected 2 historical baselines, got {len(files)}: {files}"


def test_baseline_script_keeps_only_five_historical_snapshots(tmp_path: Path) -> None:
    """After 7 runs the script must prune to 5 historical baselines."""
    project = tmp_path / "novel-wiki-mini"
    project.mkdir()
    _write_minimal_novel_wiki(project)

    for _ in range(7):
        result = _run_script(project)
        assert result.returncode == 0, result.stderr

    files = sorted((project / ".llm-wiki" / "book-series" / "baselines").glob("*.json"))
    assert len(files) == 5, (
        f"prune policy must cap at 5 historical baselines; got {len(files)}: {files}"
    )


def test_baseline_script_fails_closed_on_missing_wiki(tmp_path: Path) -> None:
    """When the project has no ``wiki/`` directory the script must fail
    with a non-zero exit code and write nothing under ``.llm-wiki``.
    """
    project = tmp_path / "empty-project"
    project.mkdir()
    (project / ".llm-wiki").mkdir()

    result = _run_script(project)
    assert result.returncode != 0, (
        f"expected non-zero exit; got {result.returncode}.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    llm_wiki = project / ".llm-wiki" / "book-series"
    assert not llm_wiki.exists(), (
        f"no baseline files should be written on failure; found {llm_wiki}"
    )
