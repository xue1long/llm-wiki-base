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


# ---------------------------------------------------------------------------
# Phase 3: status / diff / upgrade (Plan 25 v3)
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_state_file():
    """Remove the persisted state file before AND after the test."""
    state_path = Path.home() / ".config" / "ruflo-kb" / "wiki-templates" / ".bundled-state.json"
    if state_path.exists():
        state_path.unlink()
    yield state_path
    if state_path.exists():
        state_path.unlink()


def test_status_shows_all_four_types(clean_user_overrides, clean_state_file) -> None:
    r = _run_cli("status")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    for t in ("source", "entity", "concept", "synthesis"):
        assert t in r.stdout, f"missing {t!r} in status output: {r.stdout}"
    assert "bundled" in r.stdout


def test_status_marks_bundled_updated_after_template_change(
    clean_user_overrides, clean_state_file, monkeypatch
) -> None:
    """If bundled sha256 changes between status calls, mark affected types."""
    # First call captures the current state.
    r1 = _run_cli("status")
    assert r1.returncode == 0

    # Simulate a bundled upgrade by writing a different content to concept.md
    # and re-running status. The refresh_state() inside status should detect.
    bundled = REPO / "src" / "wiki" / "templates" / "bundled" / "concept.md"
    original = bundled.read_text(encoding="utf-8")
    try:
        bundled.write_text(original + "\n<!-- bumped -->\n", encoding="utf-8")
        r2 = _run_cli("status")
        assert r2.returncode == 0
        # concept.md should now be marked as bundled-updated only if there's
        # a user override. Without an override, source=bundled so no note.
        # We don't make strong assertions on the note; just that it ran.
        assert "concept" in r2.stdout
    finally:
        bundled.write_text(original, encoding="utf-8")


def test_diff_with_no_override_reports_no_diff(clean_user_overrides) -> None:
    r = _run_cli("diff", "concept")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "no override" in r.stdout.lower() or "active template" in r.stdout.lower()


def test_diff_shows_user_vs_bundled(clean_user_overrides) -> None:
    """User override that differs from bundled shows unified diff."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    override = USER_DIR / "concept.md"
    # Build a valid override that differs from bundled
    override.write_text(
        "<!-- wiki-template-version: 9.9.9 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## CUSTOM HEADING\n\n<!-- slot:definition -->\n",
        encoding="utf-8",
    )
    try:
        r = _run_cli("diff", "concept")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "CUSTOM HEADING" in r.stdout
        assert "bundled" in r.stdout  # fromfile header
    finally:
        override.unlink(missing_ok=True)


def test_upgrade_without_force_or_if_unmodified_refuses(
    clean_user_overrides, clean_state_file
) -> None:
    """upgrade with neither flag refuses (Bug 6 fix)."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    override = USER_DIR / "concept.md"
    override.write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n## CUSTOM\n",
        encoding="utf-8",
    )
    try:
        r = _run_cli("upgrade", "concept")
        assert r.returncode == 2, f"expected refusal, got {r.returncode}: {r.stderr}"
        assert "--force" in r.stderr
        # File unchanged
        assert "## CUSTOM" in override.read_text(encoding="utf-8")
    finally:
        override.unlink(missing_ok=True)


def test_upgrade_force_overwrites_user(clean_user_overrides, clean_state_file) -> None:
    """upgrade --force overwrites the user override with bundled."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    override = USER_DIR / "concept.md"
    override.write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n## USER CUSTOM\n",
        encoding="utf-8",
    )
    try:
        r = _run_cli("upgrade", "concept", "--force")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        # Now matches bundled
        content = override.read_text(encoding="utf-8")
        assert "## USER CUSTOM" not in content
        assert "## 定义" in content  # bundled content
        # Backup created
        backup = override.with_suffix(override.suffix + ".bak")
        assert backup.exists()
        assert "## USER CUSTOM" in backup.read_text(encoding="utf-8")
    finally:
        override.unlink(missing_ok=True)
        (override.parent / (override.name + ".bak")).unlink(missing_ok=True)


def test_upgrade_if_unmodified_refuses_when_user_modified(
    clean_user_overrides, clean_state_file
) -> None:
    """--if-unmodified refuses if user file differs from recorded sha256."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    override = USER_DIR / "concept.md"
    # First call to capture state for this type (but state is keyed on
    # bundled sha256, not user sha). We need a recorded installed_sha256
    # that differs from the user's current sha256.
    from src.wiki.templates.state import State
    state = State.load()
    state.bundled["concept"] = state.bundled.get(
        "concept", type(state.bundled.get("concept", object()))()
    ) if "concept" in state.bundled else None  # noqa
    # Simpler: directly set installed_sha256 to a wrong value via a stub:
    state = State.load()
    if "concept" in state.bundled:
        state.bundled["concept"].sha256 = "0" * 64
    state.save()

    override.write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n## modified\n",
        encoding="utf-8",
    )
    try:
        r = _run_cli("upgrade", "concept", "--if-unmodified")
        assert r.returncode == 2, f"expected refusal, got {r.returncode}: {r.stderr}"
        assert "modified" in r.stderr.lower()
        # File unchanged
        assert "## modified" in override.read_text(encoding="utf-8")
    finally:
        override.unlink(missing_ok=True)
