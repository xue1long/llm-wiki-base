"""Resolve wiki page templates by PageType.

Loads templates from (in priority order):
  1. <project>/.wiki-templates/<type>.md (project override)
  2. ~/.config/ruflo-kb/wiki-templates/<type>.md (user override)
  3. src/wiki/templates/bundled/<type>.md (bundled default)

v1: returns raw template text + version. Future versions add AST parsing
for slot/if/include directives (Plan 25 v2/v3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..core.types import PageType

BUNDLED_DIR = Path(__file__).parent / "bundled"
USER_TEMPLATE_DIR = Path.home() / ".config" / "ruflo-kb" / "wiki-templates"
PROJECT_TEMPLATE_DIR = ".wiki-templates"

VERSION_PATTERN = re.compile(r"<!--\s*wiki-template-version:\s*([0-9.]+)\s*-->")
TYPE_PATTERN = re.compile(r"<!--\s*wiki-template-type:\s*([a-z]+)\s*-->")


@dataclass(frozen=True)
class Template:
    type: PageType
    body_markdown: str
    version: str
    source: Literal["project", "user", "bundled"]
    path: Path


def _parse_version(raw: str) -> str:
    m = VERSION_PATTERN.search(raw)
    return m.group(1) if m else "0.0.0"


def _validate_type(raw: str, expected: PageType) -> None:
    m = TYPE_PATTERN.search(raw)
    if not m:
        raise ValueError(f"Template missing wiki-template-type header (expected {expected.value})")
    if m.group(1) != expected.value:
        raise ValueError(
            f"Template type mismatch: file says {m.group(1)!r}, expected {expected.value!r}"
        )


def resolve(page_type: PageType, project_root: Path) -> Template:
    """Load the highest-priority template for the given PageType.

    Raises FileNotFoundError if no template exists for the type
    (should not happen for bundled types; user may have deleted bundled).
    """
    candidates = [
        (project_root / PROJECT_TEMPLATE_DIR / f"{page_type.value}.md", "project"),
        (USER_TEMPLATE_DIR / f"{page_type.value}.md", "user"),
        (BUNDLED_DIR / f"{page_type.value}.md", "bundled"),
    ]
    for path, source in candidates:
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            _validate_type(raw, page_type)
            return Template(
                type=page_type,
                body_markdown=raw,
                version=_parse_version(raw),
                source=source,
                path=path,
            )
    raise FileNotFoundError(
        f"No wiki template for PageType.{page_type.value!r} "
        f"(searched project, user, bundled)"
    )


def list_available(project_root: Path) -> list[Template]:
    """List all PageTypes that have at least one resolvable template.

    Bundled should always provide all 4; the project/user layers only
    override. We iterate PageType to surface every type's template.

    Skips on two error classes:
    - FileNotFoundError: bundled file deleted (operator issue, not a
      template problem)
    - ValueError: a project/user override file has a malformed
      wiki-template-type header. The CLI surfaces this as INVALID; we
      still want a Template back so the row can be marked, so we
      attempt to construct one from the file directly.
    """
    out: list[Template] = []
    for pt in PageType:
        try:
            out.append(resolve(pt, project_root))
        except FileNotFoundError:
            continue
        except ValueError as e:
            # Surface the invalid override as a Template so list can mark INVALID.
            # Try to read the file that caused the error (project > user).
            from .resolver import _validate_type, _parse_version, BUNDLED_DIR, USER_TEMPLATE_DIR, PROJECT_TEMPLATE_DIR
            for cand in (project_root / PROJECT_TEMPLATE_DIR / f"{pt.value}.md", USER_TEMPLATE_DIR / f"{pt.value}.md"):
                if cand.is_file():
                    raw = cand.read_text(encoding="utf-8")
                    out.append(Template(
                        type=pt,
                        body_markdown=raw,
                        version=_parse_version(raw),
                        source="project" if cand.parent.name == PROJECT_TEMPLATE_DIR else "user",
                        path=cand,
                    ))
                    break
    return out
