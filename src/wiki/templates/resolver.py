"""Resolve wiki page templates by PageType.

Three-level priority (Bug 3 fix):
  1. ``<project>/.wiki-templates/<type>.md`` (project override)
  2. ``~/.config/ruflo-kb/wiki-templates/<type>.md`` (user override)
  3. ``src/wiki/templates/bundled/<type>.md`` (defaults)

`<!-- include:PATH -->` directives are expanded with cycle detection
(Bug 1/15 fix):
  - Path must be a bare filename (no `/`, `\\`, or `..`)
  - Resolved relative to the template's containing directory
  - visited-set prevents any cycle

The resolved `Template.body_markdown` keeps `<!-- slot:NAME -->` markers
intact — the generator prompt is told to fill those slots.

Caching (O-4): ``resolve()`` is mtime-keyed via an in-process LRU. The
``Generator`` calls it for every generated wiki page, so re-reading the
4 bundled files + expanding includes on every call was wasteful.
``clear_cache()`` is exposed for tests and for explicit invalidation.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from src.wiki import PageType

from .parser import validate_type_header
from .types import (
    Template,
    PROJECT_TEMPLATE_DIRNAME,
    USER_TEMPLATE_DIR,
    BUNDLED_DIR,
    MAX_INCLUDE_DEPTH,
)

if TYPE_CHECKING:
    pass


def _iter_candidates(
    page_type: PageType, project_root: Path
) -> "list[tuple[Path, str]]":
    """Yield (path, source) candidates in priority order.

    Centralised so resolve() and list_resolved() share one source of truth
    for the candidate ordering. Add a new priority level here and both
    call sites pick it up.
    """
    return [
        (project_root / PROJECT_TEMPLATE_DIRNAME / f"{page_type.value}.md", "project"),
        (USER_TEMPLATE_DIR / f"{page_type.value}.md", "user"),
        (BUNDLED_DIR / f"{page_type.value}.md", "bundled"),
    ]


def _safe_is_file(path: Path) -> bool:
    """Treat unreadable optional overrides as unavailable candidates."""
    try:
        return path.is_file()
    except OSError:
        return False


def _candidate_mtime_signature(
    page_type: PageType, project_root: Path
) -> tuple[int, ...]:
    """Compute a tuple of file mtimes (ns) over the candidate paths.

    Returns an empty tuple when no candidate file exists — this matches
    the FileNotFoundError path and ensures exceptions are never cached.
    """
    sig: list[int] = []
    for path, _source in _iter_candidates(page_type, project_root):
        if _safe_is_file(path):
            try:
                sig.append(path.stat().st_mtime_ns)
            except OSError:
                # Permission denied / file vanished — treat as missing
                sig.append(-1)
    return tuple(sig)


@lru_cache(maxsize=64)
def _resolve_cached(
    page_type_value: str, project_root_str: str, mtime_sig: tuple
) -> Template:
    """LRU-cached inner resolve. Keys: (page_type, project_root, mtime_sig).

    The mtime signature auto-invalidates when any candidate file is
    edited (mtime_ns changes). Exceptions are NOT cached because
    ``@lru_cache`` only stores successful return values.
    """
    return _resolve_uncached(
        PageType(page_type_value), Path(project_root_str)
    )


def _resolve_uncached(page_type: PageType, project_root: Path) -> Template:
    for path, source in _iter_candidates(page_type, project_root):
        if _safe_is_file(path):
            raw = path.read_text(encoding="utf-8")
            validate_type_header(raw, page_type)  # raises TemplateParseError on mismatch
            version = _extract_version(raw)
            body = _expand_includes(raw, base_dir=path.parent)
            return Template(
                type=page_type,
                body_markdown=body,
                version=version,
                source=source,  # type: ignore[arg-type]
                path=path,
            )

    raise FileNotFoundError(
        f"No wiki template for PageType.{page_type.value!r} "
        f"(searched project, user, bundled)"
    )


def resolve(page_type: PageType, project_root: Path) -> Template:
    """Load the highest-priority template for the given PageType.

    Cached in-process via an mtime-keyed LRU. The cache invalidates
    automatically when any candidate file's mtime changes; call
    ``clear_cache()`` to force a flush (tests, after manual file ops
    that don't bump mtime, after deploy).

    Raises FileNotFoundError if no template exists at any priority
    level. (Bundled ships with all 4 PageTypes; a missing file here
    indicates the bundled dir has been tampered with.)
    """
    mtime_sig = _candidate_mtime_signature(page_type, project_root)
    return _resolve_cached(
        page_type.value,
        str(project_root),
        mtime_sig,
    )


def clear_cache() -> None:
    """Drop all cached resolve() results.

    Intended for tests and for callers that have just performed a
    file operation that didn't bump mtime (e.g. os.replace, atomic
    rename). Normal usage does not need this — the mtime signature
    auto-invalidates on file edits.

    Cache key limitation: keys do NOT include the global
    ``USER_TEMPLATE_DIR`` / ``BUNDLED_DIR`` paths (they're treated as
    module-level constants). In production these are immutable after
    import, so this is fine. In tests that monkeypatch these
    constants, you **must** call ``clear_cache()`` first or the cached
    result will point at the original (pre-patch) directory.
    """
    _resolve_cached.cache_clear()


# ---------------------------------------------------------------------------
# Include expansion (Bug 1/15 fix)
# ---------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r"<!--\s*include:\s*([^>\s]+)\s*-->")
_VERSION_RE = re.compile(
    r"^<!--\s*wiki-template-version:\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*-->\s*$",
    re.MULTILINE,
)


def _extract_version(raw: str) -> str | None:
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else None


def _validate_type(raw: str, expected: PageType) -> None:
    """Deprecated thin wrapper — delegates to ``validate_type_header``.

    Kept for any external callers that historically relied on this name.
    Raises ``TemplateParseError`` (a ``ValueError`` subclass) on failure,
    matching the parser's behaviour exactly.
    """
    validate_type_header(raw, expected)


def _safe_include_path(inc_path: str, base_dir: Path) -> Path:
    """Bug 1 fix: enforce bare-filename includes (no path traversal)."""
    if "/" in inc_path or "\\" in inc_path:
        raise ValueError(
            f"include path must be a bare filename, got {inc_path!r} "
            "(no '/' or '\\\\' allowed)"
        )
    if inc_path in (".", "..") or inc_path.startswith(".."):
        raise ValueError(f"unsafe include path: {inc_path!r}")
    if len(inc_path) >= 2 and inc_path[1] == ":":
        raise ValueError(f"include path must not contain drive letter: {inc_path!r}")
    return base_dir / inc_path


def _expand_includes(
    raw: str,
    base_dir: Path,
    depth: int = 0,
    visited: frozenset[Path] = frozenset(),
) -> str:
    """Expand `<!-- include:PATH -->` directives recursively.

    Bug 15 fix: visited set tracks every expanded path; revisiting raises
    RecursionError. Combined with depth limit as defence-in-depth.
    """
    if depth > MAX_INCLUDE_DEPTH:
        raise RecursionError(
            f"include depth exceeded (>{MAX_INCLUDE_DEPTH}) in {base_dir}"
        )

    out: list[str] = []
    pos = 0
    for m in _INCLUDE_RE.finditer(raw):
        out.append(raw[pos:m.start()])

        inc_path = m.group(1).strip()
        target = _safe_include_path(inc_path, base_dir)

        if target in visited:
            raise RecursionError(
                f"circular include detected: {target} already expanded"
            )

        if not _safe_is_file(target):
            # Leave marker in place + warning; don't silently drop.
            out.append(m.group(0))
        else:
            included_raw = target.read_text(encoding="utf-8")
            included_expanded = _expand_includes(
                included_raw,
                base_dir=target.parent,
                depth=depth + 1,
                visited=visited | {target},
            )
            out.append(included_expanded)

        pos = m.end()

    out.append(raw[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Listing helpers (used by CLI)
# ---------------------------------------------------------------------------

def list_resolved(project_root: Path) -> list[Template]:
    """Return resolved templates for all 4 PageTypes (in enum order).

    Skips types where resolve() raises FileNotFoundError (which should
    only happen if bundled files are missing).

    For ``TemplateParseError`` raised by an INVALID user/project override
    (missing or mismatched type header), still returns a Template so the
    CLI can mark it INVALID — the operator can then fix it. Other
    ValueErrors (e.g. unsafe include path) propagate to the caller.
    """
    from .parser import TemplateParseError

    out: list[Template] = []
    for pt in PageType:
        try:
            out.append(resolve(pt, project_root))
        except FileNotFoundError:
            continue
        except TemplateParseError:
            # Surface the invalid override as a Template so list can mark INVALID.
            # Walk candidates in priority order — first hit is the invalid file.
            for cand, source in _iter_candidates(pt, project_root):
                if _safe_is_file(cand):
                    raw = cand.read_text(encoding="utf-8")
                    out.append(Template(
                        type=pt,
                        body_markdown=raw,
                        version=_extract_version(raw),
                        source=source,  # type: ignore[arg-type]
                        path=cand,
                    ))
                    break
    return out


# Backwards-compat alias removed in O-3 cleanup — callers should use
# list_resolved directly. (No remaining external callers after the
# generator.py and cli_ext/wiki_templates_cmd.py migrations.)
