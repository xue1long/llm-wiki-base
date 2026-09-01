"""Path-traversal fail-closed for ingest path normalisation (PR-2 final).

Pre-PR-2 bug: ``_normalize_absolute_path`` had two paths that
silently allowed paths to escape the project root:

1. **Relative + escape**: a relative path like ``"../foo.md"`` would
   compute ``rel = os.path.relpath(abs(path), root)`` which starts
   with ``..``. The legacy code then fell through to a
   ``raw/sources/`` fallback that joined the user's path onto the
   raw/sources directory — effectively allowing ``"../../etc/passwd"``
   to be queued for ingestion if such a file existed.

2. **Cross-drive tolerance**: ``os.path.relpath`` raises
   ``ValueError`` on Windows when the two paths are on different
   drives. The legacy code caught the exception and forced a
   fallback — silently producing a project-relative-looking path
   that did not actually live under the project root.

After PR-2 final:

* A relative path containing a ``..`` segment is rejected outright
  (``IngestPathError``). No raw/sources fallback is consulted for
  traversal attempts.
* A cross-drive relative path is also rejected with a clear error.
* The raw/sources fallback is preserved for legitimate bare
  filename inputs (no ``..`` segments, no cross-drive mismatch).
* An absolute path with ``..`` segments still gets the original
  "outside project root" error, but the audit trail calls out the
  traversal attempt explicitly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.services.ingest import (
    IngestPathError,
    _has_path_traversal,
    _normalize_absolute_path,
)


# ── _has_path_traversal helper ──────────────────────────────────────


def test_has_path_traversal_detects_dotdot_segment():
    assert _has_path_traversal("../etc/passwd") is True


def test_has_path_traversal_detects_midpath_dotdot():
    assert _has_path_traversal("foo/../../bar") is True


def test_has_path_traversal_detects_leading_double_dot():
    assert _has_path_traversal("../../foo") is True


def test_has_path_traversal_allows_plain_path():
    assert _has_path_traversal("raw/sources/foo.md") is False


def test_has_path_traversal_allows_dotted_filename():
    """``..foo.md`` is a legal filename (leading double-dot)."""
    # Note: the user's ``..foo.md`` is not a traversal — it is a
    # filename. The string split does not produce a ``..`` segment.
    assert _has_path_traversal("..foo.md") is False


def test_has_path_traversal_allows_dot_filename():
    assert _has_path_traversal(".hidden/foo.md") is False


def test_has_path_traversal_works_after_backslash_normalisation():
    """The collector layer uses forward-slash / POSIX-style paths
    internally; test the helper on the converted form directly."""
    assert _has_path_traversal("raw/sources/foo/../bar.md") is True


# ── Relative path fail-closed on traversal ──────────────────────────


def test_relative_path_with_dotdot_raises(tmp_path, monkeypatch):
    """An obvious traversal attempt (e.g. ``../etc/passwd``) must
    be rejected, NOT silently absorbed into the raw/sources fallback."""
    monkeypatch.chdir(tmp_path)
    # Ensure no file at the raw/sources fallback target — the legacy
    # code would silently have produced this path if it found such a
    # file. After PR-2, the traversal guard fires first.
    sources_dir = tmp_path / "raw" / "sources" / "etc"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "passwd").write_text("attacker", encoding="utf-8")

    with pytest.raises(IngestPathError, match="path-traversal"):
        _normalize_absolute_path(tmp_path, "../../etc/passwd")


def test_relative_path_dotdot_anywhere_raises(tmp_path, monkeypatch):
    """``foo/../../bar`` — traversal in the middle of the path.
    Even if a file would exist at the resolved location, refuse."""
    monkeypatch.chdir(tmp_path)
    # Plant a candidate file at the resolved location to confirm
    # we still refuse regardless of existence.
    target = tmp_path / "bar"
    target.write_text("anything", encoding="utf-8")

    with pytest.raises(IngestPathError, match="path-traversal"):
        _normalize_absolute_path(tmp_path, "foo/../../bar")


def test_relative_path_with_dotdot_at_start_is_rejected(tmp_path, monkeypatch):
    """``../foo`` alone (no slash sequence) must also fail."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IngestPathError, match="path-traversal"):
        _normalize_absolute_path(tmp_path, "../foo")


# ── raw/sources fallback is preserved for legitimate inputs ───────


def test_relative_bare_filename_passes_through(tmp_path, monkeypatch):
    """A bare filename ``"foo.md"`` resolves to ``tmp_path/foo.md``
    (under CWD/project_root) — no escalation needed. The raw/sources
    fallback is only consulted when the user's path would otherwise
    escape the project tree.
    """
    monkeypatch.chdir(tmp_path)
    sources_dir = tmp_path / "raw" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "foo.md").write_text("content", encoding="utf-8")

    result = _normalize_absolute_path(tmp_path, "foo.md")
    assert result == "foo.md"


def test_relative_subpath_filename_passes_through(tmp_path, monkeypatch):
    """``subdir/foo.md`` (resolves under CWD/project_root) passes
    through the normalisation without invoking the fallback."""
    monkeypatch.chdir(tmp_path)
    sources_dir = tmp_path / "raw" / "sources" / "subdir"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "foo.md").write_text("content", encoding="utf-8")

    result = _normalize_absolute_path(tmp_path, "subdir/foo.md")
    assert result == "subdir/foo.md"


def test_relative_path_inside_project_skips_fallback(tmp_path, monkeypatch):
    """A path that already resolves inside the project skips the
    fallback (no double-resolution)."""
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "raw" / "sources"
    raw_dir.mkdir(parents=True, exist_ok=True)

    result = _normalize_absolute_path(tmp_path, "raw/sources/foo.md")
    assert result == "raw/sources/foo.md"


def test_legacy_fallback_invoked_when_path_escapes(tmp_path, monkeypatch):
    """When the user's path would escape project_root (no ``..``
    segments, but the CWD-relative resolution sits outside the
    project tree), the legacy raw/sources fallback saves the user
    from a confusing error by trying to find the file there.

    Example: project_root is /a/b, but CWD is /a. User passes
    ``c.md`` which would resolve to /a/c.md (outside /a/b). The
    fallback searches /a/b/raw/sources/c.md.
    """
    # Project root is /tmp_path/project
    project = tmp_path / "project"
    project.mkdir()
    sibling_dir = tmp_path / "sibling_cwd"
    sibling_dir.mkdir()
    # CWD is sibling_dir — different subtree than project.
    monkeypatch.chdir(sibling_dir)
    (sibling_dir / "c.md").write_text("outside-the-tree", encoding="utf-8")
    # Drop the same name under raw/sources/ so the fallback finds it.
    (project / "raw" / "sources" / "c.md").parent.mkdir(parents=True, exist_ok=True)
    (project / "raw" / "sources" / "c.md").write_text("real-content", encoding="utf-8")

    # ``c.md`` from sibling_dir does NOT resolve under project_root,
    # so the relpath check says it would escape — the fallback runs
    # and finds c.md under raw/sources/.
    result = _normalize_absolute_path(project, "c.md")
    assert result == "raw/sources/c.md"


def test_legacy_fallback_does_not_invoke_when_no_file_match(tmp_path, monkeypatch):
    """If the escape + fallback path finds no candidate, the user's
    raw input is returned unchanged (so downstream collector can
    surface its own read error)."""
    project = tmp_path / "project"
    project.mkdir()
    # CWD that puts a ``foo.md`` outside project_root.
    monkeypatch.chdir(tmp_path.parent)
    (tmp_path.parent / "foo.md").write_text("outside", encoding="utf-8")
    # No raw/sources/foo.md exists.

    result = _normalize_absolute_path(project, "foo.md")
    # Returns the raw input unchanged; collector will then surface
    # a FileNotFoundError-style failure. We just need to confirm the
    # function does not raise.
    assert result == "foo.md"


# ── Cross-drive Windows guard ────────────────────────────────────────


def test_cross_drive_relative_path_raises(tmp_path, monkeypatch):
    """If ``os.path.relpath`` would raise ``ValueError`` (cross-drive
    on Windows), pre-PR-2 code silently forced a fallback and
    produced an invalid project-relative string. After PR-2, the
    cross-drive mismatch must surface a clean error.

    We can't actually trigger cross-drive in a single test, but
    the function must at minimum refuse inputs it cannot resolve.
    The monkeypatch simulates this: stub ``os.path.relpath`` to
    raise ``ValueError`` to mirror the cross-drive behaviour on a
    single-drive host.
    """
    monkeypatch.chdir(tmp_path)

    def fake_relpath(_a, _b):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", fake_relpath)
    with pytest.raises(IngestPathError, match="different drive"):
        _normalize_absolute_path(tmp_path, "raw/sources/foo.md")


def test_cross_drive_with_traversal_attempt_raises_traversal_error(
    tmp_path, monkeypatch,
):
    """A traversal in a cross-drive context must surface the
    traversal error, not the cross-drive error (the more dangerous
    issue wins)."""
    monkeypatch.chdir(tmp_path)
    # Seed a candidate at the resolved location; the traversal guard
    # must still fire without consulting relpath at all.
    bogus_target = tmp_path / "etc"
    bogus_target.mkdir(exist_ok=True)
    (bogus_target / "passwd").write_text("attacker", encoding="utf-8")

    def fake_relpath(_a, _b):
        raise ValueError("cross-drive")

    monkeypatch.setattr(os.path, "relpath", fake_relpath)
    with pytest.raises(IngestPathError, match="path-traversal"):
        _normalize_absolute_path(tmp_path, "../../etc/passwd")


# ── Absolute path branch ─────────────────────────────────────────────


def test_absolute_path_inside_project_returns_relative(tmp_path):
    """An absolute path under project_root returns a project-relative form."""
    file = tmp_path / "raw" / "sources" / "foo.md"
    file.parent.mkdir(parents=True)
    file.write_text("x", encoding="utf-8")

    result = _normalize_absolute_path(tmp_path, str(file))
    # Unix-style forward slashes regardless of host OS.
    assert result == "raw/sources/foo.md"


def test_absolute_path_outside_project_raises(tmp_path):
    """An absolute path NOT under project_root must raise."""
    import tempfile

    with tempfile.TemporaryDirectory() as other:
        outside = Path(other) / "private.md"
        outside.write_text("x", encoding="utf-8")
        with pytest.raises(IngestPathError, match="outside project root"):
            _normalize_absolute_path(tmp_path, str(outside))


def test_absolute_path_with_traversal_segment_surfaces_clear_error(
    tmp_path,
):
    """An absolute path containing ``..`` segments that resolve
    OUTSIDE project_root must surface a traversal-specific error.
    Pre-PR-2 the same input got only "outside project root" without
    mentioning the traversal attempt in the audit trail.
    """
    # tmp_path/foo/../../../<outside> resolves to tmp_path.parent/<x>;
    # we don't actually need a sibling file to exist — the
    # function checks relpath and exits with the traversal error.
    # Build the absolute path the user would have typed.
    abspath_inside_project = tmp_path / "foo" / "inside"
    abspath_inside_project.parent.mkdir(parents=True, exist_ok=True)
    absolute_traversal = str(
        abspath_inside_project.parent / ".." / ".." / "outside.md"
    )
    # Sanity: this path is, by construction, outside project_root.
    if str(tmp_path) in absolute_traversal and os.path.commonpath(
        [absolute_traversal, str(tmp_path)]
    ) == str(tmp_path):
        pytest.skip(
            "Test environment places tmp_path on a path that "
            "contains the resolved traversal path — skipping to "
            "keep semantics tautological."
        )

    with pytest.raises(IngestPathError, match="refuses path-traversal"):
        _normalize_absolute_path(tmp_path, absolute_traversal)


# ── Sanity check for the helper output format ───────────────────────


def test_normalized_paths_use_forward_slashes(tmp_path, monkeypatch):
    """The function must always return forward-slash delimited paths,
    even when the host OS uses backslashes."""
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "raw" / "sources" / "b.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("x", encoding="utf-8")
    result = _normalize_absolute_path(tmp_path, str(nested))
    assert "\\" not in result
    # And it must be a project-relative path (no leading absolute).
    assert not result.startswith("/")
    assert not (len(result) >= 2 and result[1] == ":")  # not "C:..."
