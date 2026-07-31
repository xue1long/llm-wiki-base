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
        rel = Path(source_path).relative_to(Path(project_root))
        return rel.as_posix()
    except ValueError:
        return source_path
