"""Tests for state.py corruption recovery (O-5).

Bug surfaced by code review: a corrupt .bundled-state.json was
silently reset to a fresh State() with no warning, no backup. Users
would see their upgrade history vanish with no clue why.

After O-5:
- State.load() on corrupt JSON must back the file up to
  '.bundled-state.json.corrupt' before returning a fresh State.
- State.load() must log a warning naming the file and the reason.
- On OSError (e.g. permission denied), no backup is attempted — just
  log + return fresh state.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.wiki.templates.state import State


def _write_state(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_state_load_corrupt_json_creates_backup(tmp_path, caplog):
    """Corrupt JSON: backup created + fresh State returned + warning logged."""
    state_path = tmp_path / ".bundled-state.json"
    _write_state(state_path, "{not valid json[[[")

    with caplog.at_level(logging.WARNING, logger="src.wiki.templates.state"):
        s = State.load(state_path)

    # Fresh state returned
    assert s.schema_version == 1
    assert s.bundled == {}
    # Backup file created
    backup = state_path.with_suffix(".json.corrupt")
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "{not valid json[[["
    # Warning logged with both file path and parse error context
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(str(state_path) in r.getMessage() for r in warnings), (
        f"no warning mentioning the state path; got {[r.getMessage() for r in warnings]}"
    )


def test_state_load_oserror_returns_fresh_no_backup(tmp_path, caplog):
    """OSError on read (e.g. unreadable file): no backup attempted."""
    state_path = tmp_path / ".bundled-state.json"
    state_path.mkdir()  # path is a directory — read_text() will raise IsADirectoryError

    with caplog.at_level(logging.WARNING, logger="src.wiki.templates.state"):
        s = State.load(state_path)

    # Fresh state returned, no backup created
    assert s.bundled == {}
    backup = state_path.with_suffix(".json.corrupt")
    assert not backup.exists()


def test_state_load_valid_json_unchanged(tmp_path):
    """Valid JSON: no backup, state loaded intact."""
    state_path = tmp_path / ".bundled-state.json"
    _write_state(state_path, json.dumps({
        "_schema_version": 1,
        "bundled": {"concept": {"version": "1.0.0", "sha256": "abc", "captured_at": "x"}},
    }))

    s = State.load(state_path)
    assert "concept" in s.bundled
    assert s.bundled["concept"].sha256 == "abc"
    backup = state_path.with_suffix(".json.corrupt")
    assert not backup.exists()


def test_state_load_missing_file_returns_fresh(tmp_path):
    """No file at all: fresh state, no backup, no warning."""
    state_path = tmp_path / ".bundled-state.json"
    assert not state_path.exists()

    s = State.load(state_path)
    assert s.bundled == {}
    backup = state_path.with_suffix(".json.corrupt")
    assert not backup.exists()


# ---------------------------------------------------------------------------
# F-5: capture_current_bundled logs ERROR on malformed bundled files
# ---------------------------------------------------------------------------

def test_capture_current_bundled_logs_error_on_malformed(tmp_path, caplog):
    """A malformed bundled file is logged at ERROR, not silently skipped.

    Without F-5, the file would vanish from the result dict and the
    operator would see a 'type missing from bundled' with no clue.
    After F-5 the log makes the cause explicit.
    """
    from src.wiki.templates.state import capture_current_bundled

    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    # concept.md has NO version header → parser will reject
    (bundled_dir / "concept.md").write_text(
        "<!-- wiki-template-type: concept -->\n\n## 定义\n",
        encoding="utf-8",
    )
    # entity.md is well-formed — should appear in result
    (bundled_dir / "entity.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n## 基本信息\n",
        encoding="utf-8",
    )

    with caplog.at_level("ERROR", logger="src.wiki.templates.state"):
        result = capture_current_bundled(bundled_dir)

    # Malformed file excluded from result
    assert "concept" not in result
    # Well-formed file still captured
    assert "entity" in result
    # ERROR log mentions the broken file
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("concept.md" in r.getMessage() for r in errors), (
        f"no ERROR mentioning concept.md; got {[r.getMessage() for r in errors]}"
    )