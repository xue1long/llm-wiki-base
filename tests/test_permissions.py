"""Task 0.2 — verify each AgentType's allowed and rejected paths."""
import pytest

from src.permissions import (
    AgentType,
    Permission,
    ALLOWED_PATHS,
    check_permission,
    enforce_permission,
    PermissionDenied,
)


# ---------------------------------------------------------------------------
# Whitelist structure
# ---------------------------------------------------------------------------

def test_collector_has_read_and_write():
    assert Permission.READ in ALLOWED_PATHS[AgentType.COLLECTOR]
    assert Permission.WRITE in ALLOWED_PATHS[AgentType.COLLECTOR]


def test_processor_has_read_and_write():
    assert Permission.READ in ALLOWED_PATHS[AgentType.PROCESSOR]
    assert Permission.WRITE in ALLOWED_PATHS[AgentType.PROCESSOR]


def test_librarian_has_read_and_write():
    assert Permission.READ in ALLOWED_PATHS[AgentType.LIBRARIAN]
    assert Permission.WRITE in ALLOWED_PATHS[AgentType.LIBRARIAN]


def test_searcher_has_read_only():
    assert Permission.READ in ALLOWED_PATHS[AgentType.SEARCHER]
    assert Permission.WRITE not in ALLOWED_PATHS[AgentType.SEARCHER]


# ---------------------------------------------------------------------------
# Allowed paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("agent,path,perm", [
    (AgentType.COLLECTOR, "raw/sources/doc.md", Permission.READ),
    (AgentType.COLLECTOR, "raw/sources/doc.md", Permission.WRITE),
    (AgentType.PROCESSOR, "raw/sources/doc.md", Permission.READ),
    (AgentType.PROCESSOR, "wiki/concepts/page.md", Permission.READ),
    (AgentType.PROCESSOR, "wiki/concepts/page.md", Permission.WRITE),
    (AgentType.PROCESSOR, ".index/lancedb/foo", Permission.WRITE),
    (AgentType.LIBRARIAN, "wiki/entities/e.md", Permission.READ),
    (AgentType.LIBRARIAN, "wiki/sources/s.md", Permission.WRITE),
    (AgentType.LIBRARIAN, ".index/staging/x", Permission.WRITE),
    (AgentType.SEARCHER, "wiki/concepts/c.md", Permission.READ),
    (AgentType.SEARCHER, ".index/lancedb/data", Permission.READ),
])
def test_allowed(agent, path, perm):
    result = check_permission(agent, path, perm)
    assert result.allowed, f"{agent.value} {perm.value} {path} should be allowed"


# ---------------------------------------------------------------------------
# Rejected paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("agent,path,perm", [
    (AgentType.COLLECTOR, "wiki/concepts/page.md", Permission.READ),
    (AgentType.COLLECTOR, ".index/lancedb/foo", Permission.WRITE),
    (AgentType.PROCESSOR, "../etc/passwd", Permission.READ),
    (AgentType.LIBRARIAN, "raw/sources/doc.md", Permission.READ),
    (AgentType.SEARCHER, "wiki/concepts/new.md", Permission.WRITE),
    (AgentType.SEARCHER, "raw/sources/doc.md", Permission.READ),
])
def test_rejected(agent, path, perm):
    result = check_permission(agent, path, perm)
    assert not result.allowed, f"{agent.value} {perm.value} {path} should be rejected"


# ---------------------------------------------------------------------------
# Enforce raises
# ---------------------------------------------------------------------------

def test_enforce_raises_permission_denied():
    with pytest.raises(PermissionDenied):
        enforce_permission(AgentType.SEARCHER, "wiki/concepts/new.md", Permission.WRITE)


def test_enforce_passes_for_allowed():
    enforce_permission(AgentType.COLLECTOR, "raw/sources/doc.md", Permission.READ)


# ---------------------------------------------------------------------------
# Orchestrator always passes
# ---------------------------------------------------------------------------

def test_orchestrator_always_allowed():
    result = check_permission(AgentType.ORCHESTRATOR, "any/random/path", Permission.WRITE)
    assert result.allowed


def test_orchestrator_not_in_whitelist():
    assert AgentType.ORCHESTRATOR not in ALLOWED_PATHS
