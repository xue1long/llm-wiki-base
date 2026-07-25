"""Tests for wiki-templates CLI (Plan 25 v1 follow-up / P3 fix)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).parent.parent.parent
USER_DIR = Path.home() / ".config" / "ruflo-kb" / "wiki-templates"


def _run_cli(*args, cwd=None, env=None) -> subprocess.CompletedProcess:
    base_env = {**os.environ, "PYTHONPATH": str(REPO)}
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "src.cli", "wiki-templates", *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        env=base_env,
    )


@pytest.fixture
def clean_user_overrides():
    """Remove any user-level template overrides before AND after the test."""
    if USER_DIR.exists():
        for f in USER_DIR.glob("*.md"):
            f.unlink()
        for f in USER_DIR.glob("*.md.bak"):
            f.unlink()
    yield
    if USER_DIR.exists():
        for f in USER_DIR.glob("*.md"):
            f.unlink()
        for f in USER_DIR.glob("*.md.bak"):
            f.unlink()


def test_list_shows_all_four_types(clean_user_overrides) -> None:
    r = _run_cli("list")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "source" in r.stdout
    assert "entity" in r.stdout
    assert "concept" in r.stdout
    assert "synthesis" in r.stdout
    assert "bundled" in r.stdout


def test_list_marks_invalid_template(clean_user_overrides, tmp_path) -> None:
    """A user override with a missing/malformed type header is marked INVALID."""
    # Create a bogus override
    USER_DIR.mkdir(parents=True, exist_ok=True)
    bogus = USER_DIR / "concept.md"
    bogus.write_text("<!-- wiki-template-version: 1.0.0 -->\nbody without type header\n", encoding="utf-8")
    try:
        r = _run_cli("list")
        assert r.returncode == 0
        assert "INVALID" in r.stdout, f"expected INVALID marker, got: {r.stdout}"
    finally:
        bogus.unlink(missing_ok=True)


def test_show_concept_prints_template_body(clean_user_overrides) -> None:
    r = _run_cli("show", "concept")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "## 定义" in r.stdout or "## Definition" in r.stdout
    assert "<!-- slot:definition -->" in r.stdout


def test_show_unknown_type_errors_gracefully(clean_user_overrides) -> None:
    r = _run_cli("show", "nonsense")
    assert r.returncode == 2
    assert "Unknown type" in r.stderr


def test_edit_no_open_copies_to_user_dir(clean_user_overrides) -> None:
    r = _run_cli("edit", "concept", "--no-open")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    dest = USER_DIR / "concept.md"
    assert dest.exists(), f"concept.md not created in {USER_DIR}"
    content = dest.read_text(encoding="utf-8")
    assert "DO NOT EDIT" in content
    assert "wiki-template-type: concept" in content
    # Version is also there
    assert "wiki-template-version:" in content


def test_edit_skips_overwrite(clean_user_overrides) -> None:
    """If user override already exists, edit does NOT overwrite."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    existing = USER_DIR / "concept.md"
    existing.write_text("<!-- existing user content -->\n", encoding="utf-8")
    try:
        r = _run_cli("edit", "concept", "--no-open")
        assert r.returncode == 0
        # File should be UNCHANGED
        assert existing.read_text(encoding="utf-8") == "<!-- existing user content -->\n"
    finally:
        existing.unlink(missing_ok=True)


def test_reset_requires_yes_in_non_tty(clean_user_overrides) -> None:
    """reset without --yes in a non-interactive environment must refuse (exit 2)."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    target = USER_DIR / "concept.md"
    target.write_text("<!-- to be removed -->\n", encoding="utf-8")
    try:
        r = _run_cli("reset", "concept", env={**os.environ, "RUFO_NONINTERACTIVE": "1"})
        # Non-interactive without --yes should refuse
        assert r.returncode == 2, f"expected refusal (exit 2), got {r.returncode}: {r.stderr}"
        assert "--yes" in r.stderr
        # File should still exist
        assert target.exists()
    finally:
        target.unlink(missing_ok=True)


def test_reset_with_yes_removes_and_backs_up(clean_user_overrides) -> None:
    """reset --yes removes the file and creates a .bak backup."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    target = USER_DIR / "concept.md"
    target.write_text("<!-- custom override -->\n", encoding="utf-8")
    try:
        r = _run_cli("reset", "concept", "--yes")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert not target.exists(), "target should be removed"
        backup = target.with_suffix(target.suffix + ".bak")
        assert backup.exists(), "backup should be created"
        assert backup.read_text(encoding="utf-8") == "<!-- custom override -->\n"
    finally:
        target.with_suffix(target.suffix + ".bak").unlink(missing_ok=True)
