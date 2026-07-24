"""Regression: Collector allowlist must NOT grant access to `raw/*` broadly.

Before this fix, the Collector entry included both "raw" and "raw/sources".
Because the boundary check uses PurePosixPath ancestry ("raw" is an ancestor
of "raw/sources"), the bare "raw" entry was redundant — and it also
implicitly allowed files under `raw/private/`, `raw/.draft/`, etc.,
which is broader than the documented wiki-v2 contract (CLAUDE.md says
sources live under `<project>/raw/sources/`).

After this fix the allowlist only names the documented targets. Any
caller that was relying on `raw/<other>` being writable was relying on
undocumented behaviour and should be migrated to one of the named paths.
"""
from src.permissions import (
    ALLOWED_PATHS,
    AgentType,
    Permission,
    check_permission,
)


def test_collector_cannot_read_raw_private():
    """A file under raw/<other>/ must be denied (it's not raw/sources/)."""
    result = check_permission(
        AgentType.COLLECTOR, "raw/private/secret.md", Permission.READ
    )
    assert not result.allowed, (
        "Collector must NOT have access to raw/<other>/; "
        "allowlist is broader than documented if this test fails"
    )


def test_collector_can_read_raw_sources():
    """The documented contract — raw/sources — still works."""
    result = check_permission(
        AgentType.COLLECTOR, "raw/sources/notes.md", Permission.READ
    )
    assert result.allowed


def test_collector_cannot_write_raw_private():
    """Same scoping for write."""
    result = check_permission(
        AgentType.COLLECTOR, "raw/private/secret.md", Permission.WRITE
    )
    assert not result.allowed


def test_raw_is_no_longer_in_collector_allowlist():
    """The bare "raw" entry must be gone (was redundant + over-broad)."""
    read_paths = ALLOWED_PATHS[AgentType.COLLECTOR][Permission.READ]
    write_paths = ALLOWED_PATHS[AgentType.COLLECTOR][Permission.WRITE]
    assert "raw" not in read_paths, f"raw still in READ: {read_paths}"
    assert "raw" not in write_paths, f"raw still in WRITE: {write_paths}"
    assert "raw/sources" in read_paths
    assert "raw/sources" in write_paths
