"""Tests for sync_wiki_spec.py safety (Task 2 of 9-plan-bugfixes).

The pre-commit hook runs sync_wiki_spec.py. If the spec has a YAML
parse error, the hook should NOT block unrelated commits.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
SYNC_SCRIPT = REPO / "scripts" / "sync_wiki_spec.py"
SPEC_PATH = REPO / "docs" / "guides" / "wiki-spec.md"


def _run_sync(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SYNC_SCRIPT)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )


@pytest.fixture
def restore_spec():
    """Snapshot the spec and restore after the test (defensive — tests modify it)."""
    original = SPEC_PATH.read_text(encoding="utf-8")
    yield
    SPEC_PATH.write_text(original, encoding="utf-8")
    # Also clear the .wiki-spec-md5 record so the restored spec regenerates next run
    md5 = REPO / ".wiki-spec-md5"
    if md5.exists():
        md5.unlink()


def test_sync_succeeds_on_valid_spec(restore_spec) -> None:
    r = _run_sync(REPO)
    assert r.returncode == 0, f"sync failed: {r.stderr}"


def test_sync_warns_on_yaml_error_does_not_block(restore_spec) -> None:
    """A YAML parse error must exit 0 (warn, not block)."""
    original = SPEC_PATH.read_text(encoding="utf-8")
    # Insert an unclosed bracket — clear YAML error
    bad = original.replace("rules:\n", "rules: [unclosed\n", 1)
    assert bad != original, "test setup failed: could not inject bad YAML"
    SPEC_PATH.write_text(bad, encoding="utf-8")
    # Clear MD5 so the script re-runs (it short-circuits on no-change)
    md5 = REPO / ".wiki-spec-md5"
    if md5.exists():
        md5.unlink()

    r = _run_sync(REPO)
    assert r.returncode == 0, (
        f"sync should NOT block on YAML error, but exited {r.returncode}: {r.stderr}"
    )
    assert "WARN" in r.stderr, f"expected WARN in stderr, got: {r.stderr!r}"
    assert "YAML" in r.stderr, f"expected YAML mention in stderr, got: {r.stderr!r}"


def test_sync_silent_on_no_change(restore_spec) -> None:
    """Running twice in a row should be silent on the second run (MD5 matches)."""
    r1 = _run_sync(REPO)
    assert r1.returncode == 0
    r2 = _run_sync(REPO)
    assert r2.returncode == 0
    # Second run should NOT print "Generated" (no change)
    assert "Generated" not in r2.stdout, (
        f"second run should be silent on no-change, got stdout: {r2.stdout!r}"
    )
