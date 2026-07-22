"""File listing + content reading for a project's wiki tree.

Extracted from src/server/routes/files.py. Routes now call these and
map domain exceptions (FileNotFoundError, PathTraversalError,
FileTooLargeError, PathIsDirectoryError) to HTTP status codes.
"""
from __future__ import annotations

from pathlib import Path

from ..lib.project import resolve_project


# 2 MB — matches the previous inline limit in src/server/routes/files.py
MAX_FILE_BYTES = 2_000_000


class FileNotFoundError(Exception):
    """Requested file does not exist within the project's wiki root."""


class PathTraversalError(Exception):
    """Requested path escapes the project's wiki root."""


class PathIsDirectoryError(Exception):
    """Requested path is a directory, not a file."""


class FileTooLargeError(Exception):
    """Requested file exceeds the MAX_FILE_BYTES size limit."""


def _resolve_root(paths, root: str) -> Path:
    """Map an API `root` string to a concrete directory under the project.

    - ``root == "wiki"``    -> ``paths.wiki``
    - ``root == "sources"`` -> ``paths.sources``
    - anything else         -> subdirectory under ``paths.wiki``

    Prevents the previous ``getattr(paths, f"wiki_{root.rstrip('s')}...")``
    bug that produced ``wiki_wiki`` for ``root="wiki"``.
    """
    if root == "wiki":
        return paths.wiki
    if root == "sources":
        return paths.sources
    return paths.wiki / root


def list_files(
    project_id: str,
    root: str = "wiki",
    recursive: bool = True,
    max_files: int = 2000,
) -> dict:
    """List markdown files under the project's `root` directory.

    Returns a dict ready to be returned from an HTTP route:
        {"files": [{"path": ..., "isDir": False, "size": ...}, ...],
         "truncated": bool, "totalCount": int}
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)
    base = _resolve_root(paths, root)
    if not base.exists():
        return {"files": [], "truncated": False, "totalCount": 0}

    files = list(base.rglob("*.md")) if recursive else list(base.glob("*.md"))
    total_count = len(files)
    truncated = total_count > max_files
    files = files[:max_files]
    return {
        "files": [
            {
                # as_posix() normalises to forward slashes for cross-platform API
                "path": f.relative_to(ctx.path).as_posix(),
                "isDir": False,
                "size": f.stat().st_size,
            }
            for f in files
        ],
        "truncated": truncated,
        "totalCount": total_count,
    }


def read_file_content(project_id: str, path: str) -> dict:
    """Read the text content of a file within the project's wiki root.

    Raises:
        PathTraversalError: if the resolved path escapes the wiki root.
        FileNotFoundError:   if no file exists at the resolved path.

    Returns:
        {"path": str, "content": str, "size": int}
    """
    _ctx, paths = resolve_project(project_id, by_id_only=True)
    base = _resolve_root(paths, "wiki")
    candidate = (base / path).resolve()

    # Path-traversal guard: resolved file must remain under the wiki root.
    try:
        candidate.relative_to(base)
    except ValueError as e:
        raise PathTraversalError(
            f"Path escapes wiki root: {path!r} -> {candidate}"
        ) from e

    if not candidate.is_file():
        if candidate.is_dir():
            raise PathIsDirectoryError(f"Path is a directory: {path!r}")
        raise FileNotFoundError(f"No such file: {path!r}")

    size = candidate.stat().st_size
    if size > MAX_FILE_BYTES:
        raise FileTooLargeError(f"File too large (>{MAX_FILE_BYTES} bytes): {path!r}")

    return {
        # as_posix() for cross-platform API consistency
        "path": candidate.relative_to(paths.root).as_posix(),
        "content": candidate.read_text(encoding="utf-8"),
        "truncated": False,
        "size": size,
    }
