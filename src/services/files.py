"""File listing + content reading for a project's wiki tree.

Extracted from src/server/routes/files.py. Routes now call these and
map domain exceptions (FileNotFoundError, PathTraversalError,
FileTooLargeError, PathIsDirectoryError) to HTTP status codes.
"""
from __future__ import annotations

import hashlib
import json
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


class BookWikiUnavailableError(Exception):
    """The project has no integrity-verified active Wiki-to-Book release."""


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


def _verified_book_release(book_dir: Path, version: str) -> tuple[Path, dict]:
    if not version or Path(version).name != version or version in {".", ".."}:
        raise BookWikiUnavailableError("Invalid book-wiki version")
    release = book_dir / ".releases" / version
    manifest_path = release / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files") or {}
        if not isinstance(files, dict):
            raise ValueError("files must be an object")
        for name, digest in files.items():
            relative = Path(str(name))
            if relative.is_absolute() or ".." in relative.parts or relative.name != str(name):
                raise ValueError("invalid release file path")
            target = release / relative
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("release file hash mismatch")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise BookWikiUnavailableError("Book release is unreadable or failed integrity checks") from exc
    return release, manifest


def _book_outline_metadata(release: Path) -> tuple[list[dict], dict[str, dict]]:
    """Read optional volume/chapter labels from the compiled outline."""
    try:
        raw = json.loads((release / "outline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return [], {}
    outlines = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    volumes, chapters = [], {}
    for outline in outlines:
        if not isinstance(outline, dict):
            continue
        for volume in outline.get("volumes") or []:
            if not isinstance(volume, dict):
                continue
            volume_id = str(volume.get("volume_id") or "").strip()
            volume_title = str(volume.get("title") or volume_id).strip()
            if not volume_id:
                continue
            volumes.append({"id": volume_id, "title": volume_title})
            for chapter in volume.get("chapters") or []:
                if not isinstance(chapter, dict) or not chapter.get("chapter_id"):
                    continue
                chapters[str(chapter["chapter_id"])] = {
                    "title": str(chapter.get("title") or chapter["chapter_id"]),
                    "volume_id": volume_id,
                    "volume_title": volume_title,
                }
    return volumes, chapters


def _active_book_wiki(project_id: str, version: str | None = None) -> tuple[Path, dict]:
    """Return the verified active Book release and its manifest."""
    import json
    from ..kc.views.book.wiki.compiler import resolve_active_version

    ctx, _paths = resolve_project(project_id, by_id_only=True)
    book_dir = ctx.path / "book-wiki"
    if version is None:
        active = resolve_active_version(book_dir)
        if active is None:
            raise BookWikiUnavailableError("No active book-wiki release")
        version = active.name
    release, verified_manifest = _verified_book_release(book_dir, version)
    manifest_path = release / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BookWikiUnavailableError("Active book-wiki manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise BookWikiUnavailableError("Active book-wiki manifest is invalid")
    return release, verified_manifest


def book_wiki_versions(project_id: str) -> dict:
    """Return integrity-verified releases, newest first, for Book preview."""
    from ..kc.views.book.wiki.compiler import resolve_active_version

    ctx, _paths = resolve_project(project_id, by_id_only=True)
    book_dir = ctx.path / "book-wiki"
    active = resolve_active_version(book_dir)
    versions = []
    releases_dir = book_dir / ".releases"
    if releases_dir.is_dir():
        for candidate in sorted((p for p in releases_dir.iterdir() if p.is_dir()),
                                key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                release, manifest = _verified_book_release(book_dir, candidate.name)
            except BookWikiUnavailableError:
                continue
            versions.append({
                "version": candidate.name,
                "active": active is not None and release == active,
                "chapter_count": int(manifest.get("chapter_count", 0) or 0),
                "page_count": int(manifest.get("page_count", 0) or 0),
                "created_at": candidate.stat().st_mtime,
            })
    return {"versions": versions}


def book_wiki_manifest(project_id: str, version: str | None = None) -> dict:
    """Describe the active Wiki-to-Book release for the reader UI."""
    release, manifest = _active_book_wiki(project_id, version=version)
    from ..kc.views.book.wiki.acceptance import (
        derive_book_freshness, load_release_acceptance_report,
    )
    derived_freshness, freshness_reason = derive_book_freshness(release.parents[2], manifest)
    acceptance = load_release_acceptance_report(release)
    if acceptance is not None:
        acceptance = {
            **acceptance,
            "current_freshness": derived_freshness,
            "current_freshness_reason": freshness_reason,
        }
    chapter_sources = manifest.get("chapter_sources") or {}
    section_source_ids = manifest.get("section_source_ids") or {}
    tutorial_paths = []
    paths_file = release / "editorial" / "paths.json"
    if paths_file.is_file():
        try:
            payload = json.loads(paths_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("paths"), list):
                tutorial_paths = payload["paths"]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            tutorial_paths = []
    files = manifest.get("files") or {}
    outline_volumes, outline_chapters = _book_outline_metadata(release)
    chapters = []
    for name in sorted(files):
        if not name.endswith(".md") or name in {"index.md", "glossary.md"}:
            continue
        path = release / name
        if not path.is_file():
            continue
        chapter_id = path.stem
        outline_id = chapter_id.split("__", 1)[-1]
        chapter_meta = outline_chapters.get(outline_id, outline_chapters.get(chapter_id, {}))
        sources = chapter_sources.get(name, chapter_sources.get(chapter_id, []))
        chapters.append({
            "path": name,
            "chapter_id": chapter_id,
            "outline_id": outline_id,
            "title": chapter_meta.get("title") or chapter_id.replace("__", " / "),
            "volume_id": chapter_meta.get("volume_id"),
            "volume_title": chapter_meta.get("volume_title"),
            "order": len(chapters) + 1,
            "size": path.stat().st_size,
            "sources": list(sources) if isinstance(sources, list) else [],
            "section_source_ids": section_source_ids.get(name, {}),
        })
    return {
        "version": manifest.get("run_id"),
        "snapshot_id": manifest.get("snapshot_id"),
        "page_count": manifest.get("page_count", 0),
        "chapter_count": manifest.get("chapter_count", len(chapters)),
        "total_relations": manifest.get("total_relations", 0),
        "unresolved": manifest.get("unresolved", 0),
        "unresolved_ratio": manifest.get("unresolved_ratio", 0),
        "reading_experience_mode": manifest.get("reading_experience_mode", "rule_only"),
        "generation_mode": manifest.get("generation_mode", "rule_only"),
        "release_status": manifest.get("release_status", "complete"),
        "book_freshness": derived_freshness,
        "book_freshness_reason": freshness_reason,
        "wiki_snapshot_hash": manifest.get("wiki_snapshot_hash", manifest.get("snapshot_id")),
        "editorial_state_hash": manifest.get("editorial_state_hash"),
        "release_manifest_hash": manifest.get("release_manifest_hash"),
        "tutorial_paths": tutorial_paths,
        "acceptance": acceptance,
        "volumes": [
            {**volume, "chapter_count": sum(1 for chapter in chapters if chapter["volume_id"] == volume["id"])}
            for volume in outline_volumes
        ],
        "chapters": chapters,
    }


def book_wiki_series_manifest(project_id: str) -> dict:
    """Read a verified series manifest, with anonymous single-book fallback."""
    import json
    from ..kc.views.book.wiki.series_validate import read_legacy_manifest, validate_series_manifest

    release, manifest = _active_book_wiki(project_id)
    series_path = release / "series-manifest.json"
    if series_path.is_file():
        expected = (manifest.get("files") or {}).get("series-manifest.json")
        actual = hashlib.sha256(series_path.read_bytes()).hexdigest()
        if not expected or expected != actual:
            raise BookWikiUnavailableError("Series manifest failed integrity checks")
        try:
            payload = json.loads(series_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BookWikiUnavailableError("Series manifest is unreadable") from exc
        report = validate_series_manifest(payload)
        if not report["ok"]:
            raise BookWikiUnavailableError("Series manifest failed validation")
        def public_id(value):
            if not isinstance(value, str) or not value or Path(value).is_absolute() or "/" in value or "\\" in value or ".." in value:
                raise BookWikiUnavailableError("Series manifest contains an unsafe public identifier")
            return value

        public_books = []
        for book in payload.get("books", []):
            if not isinstance(book, dict):
                raise BookWikiUnavailableError("Series manifest contains an invalid book")
            public = {key: book[key] for key in (
                "book_id", "required", "status", "outline_id",
                "hard_dependencies", "soft_dependencies") if key in book}
            public_id(public_id(public.get("book_id")))
            if public.get("outline_id") is not None:
                public_id(public_id(public["outline_id"]))
            for key in ("hard_dependencies", "soft_dependencies"):
                public[key] = [public_id(value) for value in public.get(key, [])]
            public_books.append(public)
        return {"series_id": public_id(payload["series_id"]), "release_id": public_id(payload["release_id"]),
                "status": payload["status"], "books": public_books}
    legacy = read_legacy_manifest(manifest)
    legacy["books"] = [{"book_id": None, "required": True,
                         "status": legacy["status"], "outline_id": None,
                         "hard_dependencies": [], "soft_dependencies": []}]
    legacy["release_id"] = None
    return legacy


def read_book_wiki_content(project_id: str, path: str, version: str | None = None) -> dict:
    """Read one chapter from the verified active Book release."""
    release, manifest = _active_book_wiki(project_id, version=version)
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    if normalized != name:
        raise PathTraversalError(f"Path escapes active book-wiki release: {path!r}")
    files = manifest.get("files") or {}
    if name not in files or not name.endswith(".md"):
        raise FileNotFoundError(f"No such book-wiki chapter: {path!r}")
    candidate = safe_resolve(release / name)
    try:
        candidate.relative_to(release.resolve())
    except ValueError as exc:
        raise PathTraversalError(f"Path escapes active book-wiki release: {path!r}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"No such book-wiki chapter: {path!r}")
    size = candidate.stat().st_size
    if size > MAX_FILE_BYTES:
        raise FileTooLargeError(f"File too large (>{MAX_FILE_BYTES} bytes): {path!r}")
    return {
        "path": name,
        "content": candidate.read_text(encoding="utf-8"),
        "size": size,
        "version": manifest.get("run_id"),
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

    # Build raw_path → wiki page frontmatter map for quality info
    raw_to_wiki_page: dict[str, dict] = {}
    if paths.wiki_sources.exists():
        for md_file in paths.wiki_sources.iterdir():
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
                    key = str(s).replace("\\", "/")
                    raw_to_wiki_page[key] = fm

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

        # quality = grade from the wiki source page frontmatter
        quality = None
        if ingested and rel in raw_to_wiki_page:
            wp = raw_to_wiki_page[rel]
            quality = wp.get("grade", "B")  # default B = "未质检"

        files.append({
            "path": rel,
            "name": f.name,
            "ext": ext,
            "size": f.stat().st_size,
            "created_at": int(f.stat().st_ctime * 1000),
            "ingested": ingested,
            "quality": quality,
        })

    files.sort(key=lambda f: f["name"])
    return {"files": files}


class UnsupportedFileTypeError(Exception):
    """Uploaded file's extension is not in the supported ingest set."""


def upload_file(project_id: str, filename: str, content: bytes) -> dict:
    """Persist an uploaded raw file to ``raw/sources/``.

    The filename is sanitised to a bare basename (no path separators or
    traversal) and written under ``<project>/raw/sources/`` so the existing
    ingest pipeline — which resolves paths relative to that directory — can
    pick it up unchanged.

    Args:
        project_id: validated project (ProjectNotFound if absent).
        filename: original upload filename; only its basename is used.
        content: raw file bytes.

    Returns:
        {"path": "raw/sources/<name>", "size": int, "name": str}

    Raises:
        UnsupportedFileTypeError: extension not in ``_RAW_EXTS``.
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)

    name = Path(filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in _RAW_EXTS:
        raise UnsupportedFileTypeError(
            f"unsupported file type {ext!r}; supported: {sorted(_RAW_EXTS)}"
        )

    # R2: defensive size cap at the service layer (the HTTP route also
    # streams with a chunk limit, so a hostile client cannot force the
    # whole payload into memory before this check runs).
    from ..config import settings
    max_bytes = settings().max_upload_bytes
    if len(content) > max_bytes:
        raise FileTooLargeError(
            f"upload exceeds limit of {max_bytes} bytes ({name})"
        )

    raw_dir = paths.root / "raw" / "sources"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / name
    dest.write_bytes(content)

    rel = f"raw/sources/{name}"
    return {"path": rel, "size": len(content), "name": name}
