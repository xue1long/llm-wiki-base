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


# ---- CJK corruption detection ----
_CORRUPTION_MARKERS = ("????", "�")  # 4+ question marks, U+FFFD replacement char


def has_cjk_corruption(path: str) -> bool:
    """Return True if *path* looks like it has CJK encoding corruption.

    Detects the common signature: four or more consecutive ``?`` (the
    placeholder a non-UTF-8 terminal substitutes for multi-byte CJK
    characters) or the Unicode replacement character ``�`` (U+FFFD).
    """
    for marker in _CORRUPTION_MARKERS:
        if marker in path:
            return True
    return False
