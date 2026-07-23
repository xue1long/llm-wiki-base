"""Regression tests for audit finding C-13 follow-up: permissions whitelist
must cover the new wiki-v2 layout, not just the legacy Inbox/ layout.

The wiki-v2 project layout (per CLAUDE.md) places source files under
``<project>/raw/sources/``. The collector must be able to read from that
path; otherwise every new-style ingest is denied.
"""
import pytest

from src.permissions import (
    ALLOWED_PATHS,
    AgentType,
    Permission,
    check_permission,
)


def test_collector_can_read_raw_sources():
    """The new wiki-v2 layout uses raw/sources/ for source files.
    Collector must be allowed to read from there."""
    result = check_permission(
        AgentType.COLLECTOR, "raw/sources/notes.md", Permission.READ
    )
    assert result.allowed, (
        f"collector should read raw/sources/; got reason: {result.reason!r}. "
        "Update src/permissions.py ALLOWED_PATHS[COLLECTOR][READ] to "
        "include the new wiki-v2 layout path."
    )


def test_collector_can_write_raw_sources():
    """Collector writes the staged content to raw/sources/ in the new flow
    (wiki-v2 T1 — Collector no longer moves to Inbox/Processing)."""
    result = check_permission(
        AgentType.COLLECTOR, "raw/sources/notes.md", Permission.WRITE
    )
    assert result.allowed, (
        f"collector should write raw/sources/; got reason: {result.reason!r}"
    )


def test_collector_can_read_legacy_inbox_pending():
    """Legacy Inbox/Pending must still be allowed (back-compat)."""
    result = check_permission(
        AgentType.COLLECTOR, "Inbox/Pending/old-doc.md", Permission.READ
    )
    assert result.allowed, (
        "legacy Inbox/Pending must remain allowed for back-compat"
    )


def test_collector_can_write_legacy_inbox_processing():
    """Legacy Inbox/Processing write must still be allowed (back-compat)."""
    result = check_permission(
        AgentType.COLLECTOR, "Inbox/Processing/task-abc.md", Permission.WRITE
    )
    assert result.allowed


def test_collector_still_denies_notes_and_knowledge():
    """Even with the new whitelist, collector must NOT be able to read
    from Notes/ or Knowledge/ (those are downstream stages)."""
    for p in ("Notes/abc.md", "Knowledge/index.md"):
        result = check_permission(AgentType.COLLECTOR, p, Permission.READ)
        assert not result.allowed, f"collector must NOT read {p}: {result.reason!r}"