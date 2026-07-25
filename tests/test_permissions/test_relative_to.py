"""C-13 regression: permission boundary uses PurePath.is_relative_to semantics.

The previous implementation relied on `str.startswith(allowed_path)` after
`Path(path).resolve()`. Two problems:

1. `resolve()` is CWD-dependent: if the user chdir's into a directory that
   happens to start with "Inbox", unrelated paths can match.
2. `startswith("Inbox")` matches `InboxEvil/secret.md` because there's no
   trailing separator.

This module pins the new contract:
- `check_permission` accepts `allowed_paths=[...]` per-call; defaults to
  the project-config ALLOWED_PATHS map when not provided.
- Boundary check uses PurePath semantics (no resolve(), no CWD dependence,
  no spurious prefix match).
"""
from src.permissions import check_permission, AgentType, Permission


def test_inbox_does_not_match_inboxevil():
    """C-13 regression: 'InboxEvil/secret.md' must NOT match allowed='Inbox'.

    The old `startswith("Inbox")` check matched because there was no
    trailing separator on the boundary. After the fix, only paths inside
    the allowed dir (or one of its descendants) match.
    """
    res = check_permission(
        AgentType.COLLECTOR,
        "InboxEvil/secret.md",
        Permission.WRITE,
        allowed_paths=["Inbox"],
    )
    assert not res.allowed


def test_inbox_processing_matches():
    """'Inbox/Processing/foo.txt' must match allowed='Inbox/Processing'."""
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox/Processing/foo.txt",
        Permission.WRITE,
        allowed_paths=["Inbox/Processing"],
    )
    assert res.allowed


def test_inbox_processing_does_not_match_inbox_pending():
    """'Inbox/Pending/foo.txt' must NOT match allowed='Inbox/Processing'.

    The allowed dir must be a real boundary, not a name prefix.
    """
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox/Pending/foo.txt",
        Permission.WRITE,
        allowed_paths=["Inbox/Processing"],
    )
    assert not res.allowed


def test_check_permission_is_cwd_independent(tmp_path, monkeypatch):
    """C-13 regression: CWD must not affect the boundary check.

    Previous implementation called `Path(path).resolve()`; the resolved
    form depended on `os.getcwd()`. After monkeypatching chdir to a
    tmp dir, the check must still pass for an Inbox-relative path.
    """
    monkeypatch.chdir(tmp_path)
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox/Processing/foo.txt",
        Permission.WRITE,
        allowed_paths=["Inbox/Processing"],
    )
    assert res.allowed


def test_default_allowed_paths_still_apply_when_not_provided():
    """Backwards-compat: with no `allowed_paths` arg, falls back to the
    module-level ALLOWED_PATHS map.

    The default Collector WRITE allowlist is ``['raw/sources']`` after
    the 2026-07 cleanup; ``Inbox/Processing`` is no longer permitted
    by default (back-compat was dropped intentionally).
    """
    # Default whitelist: raw/sources is allowed
    res = check_permission(
        AgentType.COLLECTOR,
        "raw/sources/foo.txt",
        Permission.WRITE,
    )
    assert res.allowed

    # Legacy Inbox/Processing is no longer in the default whitelist
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox/Processing/foo.txt",
        Permission.WRITE,
    )
    assert not res.allowed, (
        "Inbox/Processing should not be in the default collector whitelist "
        "after the 2026-07 cleanup."
    )


def test_url_path_returns_allowed_for_collector_read():
    """T4 carry-over: URL sources are gated by `_check_url_allowlisted`,
    not by the Inbox/Notes/Knowledge boundary check. A URL passed to
    `check_permission` for Collector READ must be allowed so the URL
    gate (T4) is the single source of truth for SSRF / DNS checks.
    """
    res = check_permission(
        AgentType.COLLECTOR,
        "https://example.com/foo",
        Permission.READ,
    )
    assert res.allowed


def test_dotdot_traversal_blocked():
    """C-13 follow-up: '..' segments must not escape the allowed dir.

    `PurePosixPath.is_relative_to` is purely lexical — it does not
    normalise parent references. Without explicit handling, a path like
    ``Inbox/Processing/../../secret.txt`` slips through the boundary
    check, even though filesystem access resolves it outside the
    allowed directory. This regression pins the contract that such
    traversal is rejected.
    """
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox/Processing/../../secret.txt",
        Permission.WRITE,
        allowed_paths=["Inbox/Processing"],
    )
    assert not res.allowed


def test_backslash_traversal_blocked():
    """C-13 follow-up: '..' segments with backslash separators must
    also be blocked.

    On Windows, callers sometimes pass backslash-separated paths. The
    normalisation step must convert them to forward slashes first, then
    reject the resulting traversal.
    """
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox\\..\\secret.txt",
        Permission.WRITE,
        allowed_paths=["Inbox"],
    )
    assert not res.allowed


def test_normalized_within_root_allowed():
    """C-13 follow-up: legitimate nested paths inside the allowed dir
    must still be allowed.

    The normalisation must only block traversal, not legitimate descent
    into sub-directories of the allowed root.
    """
    res = check_permission(
        AgentType.COLLECTOR,
        "Inbox/Processing/sub/file.md",
        Permission.WRITE,
        allowed_paths=["Inbox/Processing"],
    )
    assert res.allowed