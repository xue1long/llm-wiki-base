"""Reference-only TutorialPath validation for a compiled Book."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PATH_SCHEMA_VERSION = "tutorial-path-v1"
PATH_STATUSES = frozenset({"active", "draft", "archived"})


@dataclass(frozen=True)
class PathStep:
    chapter_id: str
    section_id: str | None = None
    task: str | None = None
    checkpoint: str | None = None


@dataclass(frozen=True)
class TutorialPath:
    path_id: str
    title: str
    steps: tuple[PathStep, ...]
    status: str = "draft"
    goal: str | None = None


def _outline_sections(outline: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    volumes = outline.get("volumes", ())
    for volume in volumes if isinstance(volumes, list) else ():
        if not isinstance(volume, Mapping):
            continue
        chapters = volume.get("chapters", ())
        for chapter in chapters if isinstance(chapters, list) else ():
            if not isinstance(chapter, Mapping):
                continue
            chapter_id = chapter.get("chapter_id")
            if not isinstance(chapter_id, str) or not chapter_id:
                continue
            sections = chapter.get("sections", ())
            section_ids = {
                section.get("section_id")
                for section in sections if isinstance(sections, list) and isinstance(section, Mapping)
                if isinstance(section.get("section_id"), str) and section.get("section_id")
            }
            result[chapter_id] = section_ids
    return result


def validate_tutorial_paths(
    paths: Mapping[str, Any],
    outline: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate navigation references without mutating the Book outline."""
    errors: list[str] = []
    if paths.get("schema_version") not in (None, PATH_SCHEMA_VERSION):
        errors.append("paths-schema-version")
    rows = paths.get("paths")
    if not isinstance(rows, list):
        return ("paths-list",)
    chapters = _outline_sections(outline)
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("path-type")
            continue
        path_id = row.get("path_id")
        path_key = path_id if isinstance(path_id, str) and path_id else "<missing>"
        if not isinstance(path_id, str) or not path_id:
            errors.append("path-id")
        elif path_id in seen:
            errors.append(f"duplicate-path-id:{path_id}")
        else:
            seen.add(path_id)
        if "body" in row or "chapter_body" in row or "content" in row:
            errors.append(f"path-body-forbidden:{path_key}")
        status = row.get("status", "draft")
        if status not in PATH_STATUSES:
            errors.append(f"path-status:{path_key}")
        steps = row.get("steps")
        if not isinstance(steps, list):
            errors.append(f"steps-list:{path_key}")
            continue
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                errors.append(f"step-type:{path_key}:{index}")
                continue
            chapter_id = step.get("chapter_id")
            if chapter_id not in chapters:
                errors.append(f"unknown-chapter:{path_key}:{index}")
                continue
            section_id = step.get("section_id")
            if section_id is not None and section_id not in chapters[chapter_id]:
                errors.append(f"section-chapter-mismatch:{path_key}:{index}")
    return tuple(sorted(set(errors)))


__all__ = [
    "PATH_SCHEMA_VERSION",
    "PATH_STATUSES",
    "PathStep",
    "TutorialPath",
    "validate_tutorial_paths",
]
