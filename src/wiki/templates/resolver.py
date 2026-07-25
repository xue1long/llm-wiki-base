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
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from src.wiki.core.types import PageType

from .types import (
    Template,
    PROJECT_TEMPLATE_DIRNAME,
    USER_TEMPLATE_DIR,
    BUNDLED_DIR,
    MAX_INCLUDE_DEPTH,
)

if TYPE_CHECKING:
    pass


def resolve(page_type: PageType, project_root: Path) -> Template:
    """Load the highest-priority template for the given PageType.

    Raises FileNotFoundError if no template exists at any priority
    level. (Bundled ships with all 4 PageTypes; a missing file here
    indicates the bundled dir has been tampered with.)
    """
    candidates: list[tuple[Path, str]] = [
        (project_root / PROJECT_TEMPLATE_DIRNAME / f"{page_type.value}.md", "project"),
        (USER_TEMPLATE_DIR / f"{page_type.value}.md", "user"),
        (BUNDLED_DIR / f"{page_type.value}.md", "bundled"),
    ]

    for path, source in candidates:
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            _validate_type(raw, page_type)  # raises ValueError on mismatch
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


_TYPE_HEADER_RE = re.compile(
    r"^<!--\s*wiki-template-type:\s*([a-z]+)\s*-->\s*$",
    re.MULTILINE,
)


def _validate_type(raw: str, expected: PageType) -> None:
    """Raise ValueError if the template's type header doesn't match.

    Mirrors the parser's strict check so user-level templates (which
    don't go through parser.py) are also validated. Tests rely on this.
    """
    m = _TYPE_HEADER_RE.search(raw)
    if not m:
        raise ValueError(
            f"Template missing wiki-template-type header (expected {expected.value})"
        )
    if m.group(1) != expected.value:
        raise ValueError(
            f"Template type mismatch: file says {m.group(1)!r}, expected {expected.value!r}"
        )


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

        if not target.is_file():
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

    For ValueError raised by an INVALID user/project override (missing or
    mismatched type header), still returns a Template so the CLI can mark
    it INVALID — the operator can then fix it.
    """
    out: list[Template] = []
    for pt in PageType:
        try:
            out.append(resolve(pt, project_root))
        except FileNotFoundError:
            continue
        except ValueError:
            # Surface the invalid override as a Template so list can mark INVALID.
            from .types import PROJECT_TEMPLATE_DIRNAME
            from .resolver import BUNDLED_DIR, USER_TEMPLATE_DIR
            for cand in (
                project_root / PROJECT_TEMPLATE_DIRNAME / f"{pt.value}.md",
                USER_TEMPLATE_DIR / f"{pt.value}.md",
            ):
                if cand.is_file():
                    raw = cand.read_text(encoding="utf-8")
                    out.append(Template(
                        type=pt,
                        body_markdown=raw,
                        version=_extract_version(raw),
                        source="project" if cand.parent.name == PROJECT_TEMPLATE_DIRNAME else "user",
                        path=cand,
                    ))
                    break
    return out


# Backwards-compat alias (existing tests import this name).
list_available = list_resolved