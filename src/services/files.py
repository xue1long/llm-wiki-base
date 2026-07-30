"""File listing + content reading for a project's wiki tree.

Extracted from src/server/routes/files.py. Routes now call these and
map domain exceptions (FileNotFoundError, PathTraversalError,
FileTooLargeError, PathIsDirectoryError) to HTTP status codes.
"""
from __future__ import annotations

from pathlib import Path

from ..utils.path import safe_resolve, safe_resolve_posix, safe_resolve_str

import yaml

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

    - ``root == "wiki"``       -> ``paths.wiki``
    - ``root == "sources"``    -> ``paths.wiki_sources``
    - anything else            -> subdirectory under ``paths.wiki``

    Prevents the previous ``getattr(paths, f"wiki_{root.rstrip('s')}...")``
    bug that produced ``wiki_wiki`` for ``root="wiki"``.
    """
    if root == "wiki":
        return paths.wiki
    if root == "sources":
        return paths.wiki_sources
    return paths.wiki / root


def list_files(
    project_id: str,
    root: str = "wiki",
    recursive: bool = True,
    max_files: int = 2000,
    include_tags: bool = False,
) -> dict:
    """List markdown files under the project's `root` directory.

    Returns a dict ready to be returned from an HTTP route:
        {"files": [{"path": ..., "isDir": False, "size": ..., "tags": [...]}, ...],
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
    result = []
    for f in files:
        entry = {
            "path": f.relative_to(ctx.path).as_posix(),
            "isDir": False,
            "size": f.stat().st_size,
        }
        if include_tags:
            entry["tags"] = _extract_tags_from_file(f)
        result.append(entry)
    return {
        "files": result,
        "truncated": truncated,
        "totalCount": total_count,
    }


def _extract_tags_from_file(filepath: Path) -> list[str]:
    """Extract tags from a markdown file's YAML frontmatter."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return []
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---", 4)
    if end < 0:
        return []
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return []
    tags = fm.get("tags", [])
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return []


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
    candidate = safe_resolve(base / path)

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


# Extensions considered "raw source" files for the raw file browser.
_RAW_EXTS = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".txt", ".md", ".html", ".xml", ".json"}


def _load_batch_state(paths) -> dict:
    """Load .index/batch_build_state.json if it exists."""
    state_file = paths.root / ".index" / "batch_build_state.json"
    if state_file.exists():
        import json
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _collect_referenced_raw_paths(wiki_sources_dir: Path) -> set:
    """Parse frontmatter of every wiki/sources page and return a set of
    normalized (forward-slash) raw-source paths referenced by their
    ``sources`` field.

    Wiki pages use generated IDs as filenames (e.g. ``kb-20260726-xxxx.md``),
    so filename-stem matching against raw files is unreliable.  We must read
    the YAML frontmatter to know which raw files were actually ingested.
    """
    if not wiki_sources_dir.exists():
        return set()

    referenced: set = set()
    for md_file in wiki_sources_dir.iterdir():
        if not md_file.suffix == ".md" or not md_file.is_file():
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        try:
            fm = yaml.safe_load(text[4:end]) or {}
        except yaml.YAMLError:
            continue
        sources = fm.get("sources", [])
        if isinstance(sources, list):
            for s in sources:
                # Normalize Windows backslashes to forward slashes so
                # comparison with Path.as_posix() works cross-platform.
                referenced.add(str(s).replace("\\", "/"))
    return referenced


def list_raw_files(project_id: str) -> dict:
    """List files under raw/sources/ for the project.

    Returns a dict:
        {"files": [{"path": ..., "name": ..., "ext": ..., "size": ..., "ingested": bool}, ...]}
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)
    raw_dir = paths.root / "raw" / "sources"
    if not raw_dir.exists():
        return {"files": []}

    state = _load_batch_state(paths)
    ingested_set = set(state.get("ingested", {}).keys())

    # Resolve ingestion status by reading wiki page frontmatter, NOT by
    # filename-stem matching.  Wiki pages use generated IDs as filenames
    # (e.g. kb-20260726-xxxx.md) that never match raw file names.
    referenced_paths = _collect_referenced_raw_paths(paths.wiki_sources)

    files = []
    for f in raw_dir.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in _RAW_EXTS:
            continue
        rel = f.relative_to(paths.root).as_posix()
        # Use safe_resolve_str (no Win32 CJK corruption) for comparison
        # with ingested_set (which stores forward slashes).
        resolved_posix = safe_resolve_posix(f)

        # ingested = True when a wiki/sources page references this raw file
        # in its frontmatter ``sources`` field AND batch_build_state does
        # not explicitly contradict it.
        wiki_page_exists = rel in referenced_paths
        batch_match = (
            rel in ingested_set
            or safe_resolve_str(f) in ingested_set
            or resolved_posix in ingested_set
        )
        ingested = wiki_page_exists and (
            not ingested_set  # no batch state at all → trust wiki page
            or batch_match     # batch state exists and confirms this file
        )

        files.append({
            "path": rel,
            "name": f.name,
            "ext": ext,
            "size": f.stat().st_size,
            "created_at": int(f.stat().st_ctime * 1000),
            "ingested": ingested,
        })

    files.sort(key=lambda f: f["name"])
    return {"files": files}
