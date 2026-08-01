# ruflo-kb/src/utils/path.py
"""Path utilities — safe from CJK encoding corruption on Windows.

``Path.resolve()`` on Windows calls ``GetFinalPathNameByHandleW`` which can
corrupt CJK characters in certain edge cases (the Win32 API normalises the
path through the filesystem, and non-ASCII segments may be mangled). Use
``safe_resolve()`` and ``safe_resolve_str()`` instead — they are pure
string-manipulation equivalents that never touch the Win32 path resolution
APIs.
"""
import os
from pathlib import Path


def normalize_path(p: str) -> str:
    """跨平台路径标准化（Windows 反斜杠转正斜杠）"""
    return p.replace("\\", "/")


def safe_resolve(path: str | Path) -> Path:
    """Absolute, normalised path — no Win32 ``GetFinalPathNameByHandleW``.

    Uses ``os.path.abspath`` + ``os.path.normpath`` (pure string ops) instead
    of ``Path.resolve()``, which can corrupt CJK characters on Windows.

    >>> safe_resolve(Path("foo/bar"))
    Path('/abs/path/to/foo/bar')
    """
    return Path(os.path.normpath(os.path.abspath(str(path))))


def safe_resolve_str(path: str | Path) -> str:
    """Same as ``safe_resolve()`` but returns a plain ``str``.

    Use this when you need a canonical string form for equality checks,
    dict keys, or serialisation — no ``Path`` garbage-collection edge
    cases.
    """
    return os.path.normpath(os.path.abspath(str(path)))


def safe_resolve_posix(path: str | Path) -> str:
    """``safe_resolve_str`` with forward slashes for cross-platform comparison.

    Equivalent to the problematic ``Path(path).resolve().as_posix()`` pattern
    but without the CJK-corrupting Win32 API call.
    """
    return safe_resolve_str(path).replace("\\", "/")


def resolve_stored_path(stored: str | Path | None, root: str | Path) -> Path | None:
    """Resolve a persisted (possibly legacy-absolute) path against *root*.

    Returns the normalized absolute :class:`Path` only if it is inside
    *root*; ``None`` when *stored* is blank, escapes root (``..``
    traversal), or is a foreign absolute path (different drive / device
    move) that cannot be mapped onto the current root. Use this on the
    read side when a stored path from a vector row / JSON blob may be
    absolute, relative, or stale.

    Path resolution is lexical (``os.path.abspath`` + ``normpath``, no
    Win32 API), so CJK segments are safe and the file need not exist.

    Note: ``is_relative_to`` is a textual comparison — a symlink inside
    root pointing outside would still pass (same as the rest of the
    codebase). Do not add ``expanduser`` here: ``~`` is a new escape
    vector.
    """
    if stored is None:
        return None
    s = str(stored).strip()
    if not s:
        return None
    root_resolved = safe_resolve(root)
    if Path(s).is_absolute():
        candidate = safe_resolve(s)
    else:
        candidate = safe_resolve(os.path.join(str(root_resolved), s))
    try:
        return candidate if candidate.is_relative_to(root_resolved) else None
    except (ValueError, AttributeError):
        return None


def migrate_state_paths(state: dict, root: str | Path) -> dict:
    """Rewrite ``ingested``/``archived``/``failed`` state keys to project-relative form.

    Absolute keys inside *root* are relativized (via
    :func:`normalize_source_path` semantics); already-relative keys are
    kept (backslashes normalized to ``/``); foreign absolute keys
    (different device) are DROPPED — their content is re-derived on the
    next run. Returns a NEW dict; values (content digests / error text)
    are preserved and the input is not mutated.

    Keys are classified as *absolute-like* when ``os.path.isabs`` OR the
    path starts with ``/`` (POSIX-absolute seen on Windows) OR matches a
    drive-letter prefix ``C:/...`` (Windows-absolute seen on POSIX) — a
    plain ``os.path.isabs`` miss on the opposite platform. This matters
    because :func:`normalize_source_path` falls back to the input
    unchanged on ``ValueError``, which is indistinguishable from an
    already-relative key.
    """
    def _is_absolute_like(k: str) -> bool:
        if os.path.isabs(k) or k.startswith("/"):
            return True
        return len(k) >= 3 and k[1] == ":" and k[2] == "/"  # drive-letter (C:/...)

    out: dict = {}
    for section, value in state.items():
        if not isinstance(value, dict):
            out[section] = value
            continue
        new_map: dict = {}
        for key, val in value.items():
            k = str(key).replace("\\", "/")
            if not _is_absolute_like(k):
                new_map[k] = val  # already relative -> keep (slashes normalized)
                continue
            try:
                new_map[Path(k).relative_to(Path(root)).as_posix()] = val
            except ValueError:
                continue  # foreign absolute -> drop
        out[section] = new_map
    return out


def normalize_source_path(source_path: str, project_root: str | Path) -> str:
    """Convert *source_path* to canonical ``raw/sources/<relpath>`` form.

    The ingest pipeline receives source paths as absolute strings
    (e.g. ``D:\\...\\knowledge\\novel-wiki\\raw\\sources\\01_新手入门\\foo.md``).
    This function converts them to the stable project-relative form::

        raw/sources/01_新手入门/foo.md

    with forward slashes.  Falls back to *source_path* unchanged when the
    path does not live under *project_root*.

    >>> normalize_source_path(
    ...     "D:\\\\...\\\\knowledge\\\\novel-wiki\\\\raw\\\\sources\\\\01_新手入门\\\\foo.md",
    ...     "D:\\\\...\\\\knowledge\\\\novel-wiki",
    ... )
    'raw/sources/01_新手入门/foo.md'
    """
    try:
        source = Path(source_path)
        root = Path(project_root)
        # Resolve relative paths against project_root so the
        # relativization always succeeds regardless of whether
        # source_path is absolute or relative.  This also ensures
        # the output is canonical (forward slashes) on Windows.
        if not source.is_absolute():
            source = root / source
        rel = source.relative_to(root)
        return rel.as_posix()
    except ValueError:
        return source_path
