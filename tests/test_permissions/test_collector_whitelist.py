"""Tests for the collector permission whitelist.

Wiki-v2 places source files under ``<project>/raw/sources/``; the
collector must be able to read from and write to that path. The legacy
``Inbox/{Pending,Processing,Error}`` paths are no longer allowed — the
staged-copy flow that used them was removed in 2026-07.
"""
import pytest

from src.permissions import (
    ALLOWED_PATHS,
    AgentType,
    Permission,
    check_permission,
)


def test_collector_can_read_raw_sources():
    """The wiki-v2 layout uses raw/sources/ for source files.
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
    """Collector writes a wikilink-safe trail file under raw/sources/ in
    the new flow (wiki-v2 T1 — Collector no longer stages in
    Inbox/Processing)."""
    result = check_permission(
        AgentType.COLLECTOR, "raw/sources/notes.md", Permission.WRITE
    )
    assert result.allowed, (
        f"collector should write raw/sources/; got reason: {result.reason!r}"
    )


def test_collector_denies_legacy_inbox_processing():
    """Legacy Inbox/Processing must NOT be a valid collector boundary —
    the staged-copy flow was removed in 2026-07. Back-compat is
    deliberately dropped; old projects must run ``project init`` again."""
    result = check_permission(
        AgentType.COLLECTOR, "Inbox/Processing/task-abc.md", Permission.WRITE
    )
    assert not result.allowed, (
        "Inbox/Processing should no longer be in the collector whitelist; "
        "if this test fails, check src/permissions.py ALLOWED_PATHS."
    )


def test_collector_denies_notes_and_knowledge():
    """The collector must NOT be able to read from Notes/ or Knowledge/
    (those are downstream stages)."""
    for p in ("Notes/abc.md", "Knowledge/index.md"):
        result = check_permission(AgentType.COLLECTOR, p, Permission.READ)
        assert not result.allowed, f"collector must NOT read {p}: {result.reason!r}"


def test_collector_whitelist_only_contains_raw_sources():
    """Lock down the whitelist contents: only ``raw/sources`` for the
    collector. Adding Inbox/Pending, Inbox/Processing, or anything else
    is a regression on the 2026-07 cleanup."""
    read_paths = set(ALLOWED_PATHS.get(AgentType.COLLECTOR, {}).get(Permission.READ, []))
    write_paths = set(ALLOWED_PATHS.get(AgentType.COLLECTOR, {}).get(Permission.WRITE, []))
    assert read_paths == {"raw/sources"}, (
        f"unexpected collector READ whitelist: {sorted(read_paths)!r}. "
        "The legacy Inbox/{Pending,Processing} entries should be gone."
    )
    assert write_paths == {"raw/sources"}, (
        f"unexpected collector WRITE whitelist: {sorted(write_paths)!r}. "
        "The legacy Inbox/{Pending,Processing} entries should be gone."
    )