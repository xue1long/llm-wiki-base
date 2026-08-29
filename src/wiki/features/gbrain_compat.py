"""Canonical Markdown conventions shared with GBrain's importer."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence


_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)([^\]]*)\]\]")
_RELATIONS_MARKER = "<!-- gbrain:relations -->"


def gbrain_slug_for_path(paths, page_path) -> str:
    """Return the slash-qualified slug GBrain derives from a wiki file."""
    return page_path.relative_to(paths.wiki).with_suffix("").as_posix()


def build_target_slugs(paths, page_paths: Iterable[tuple[str, object]] = ()) -> dict[str, str]:
    """Build the unambiguous page-id → path-slug map used on write."""
    from ..schema_registry import SchemaRegistry

    result: dict[str, str] = {}
    ambiguous: set[str] = set()
    registry = SchemaRegistry.from_project(paths.root)
    directories = registry.iter_page_dirs(paths)
    for directory in directories:
        if not directory or not directory.exists():
            continue
        for path in directory.glob("*.md"):
            _add_target(result, ambiguous, path.stem, gbrain_slug_for_path(paths, path))
    for page_id, path in page_paths:
        _add_target(result, ambiguous, page_id, gbrain_slug_for_path(paths, path))
    for page_id in ambiguous:
        result.pop(page_id, None)
    return result


def _add_target(result: dict[str, str], ambiguous: set[str], page_id: str, slug: str) -> None:
    if page_id in result and result[page_id] != slug:
        ambiguous.add(page_id)
    elif page_id not in ambiguous:
        result[page_id] = slug


def rewrite_wikilinks(body: str, target_slugs: Mapping[str, str]) -> str:
    """Qualify known ruflo page IDs while preserving aliases/fragments."""
    def replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        qualified = target_slugs.get(target)
        return f"[[{qualified}{match.group(2)}]]" if qualified else match.group(0)

    return _WIKILINK_RE.sub(replace, body)


def materialize_relations(body: str, relations: Sequence[object], target_slugs: Mapping[str, str]) -> str:
    """Add an idempotent Markdown relation section for GBrain link extraction."""
    if not relations:
        return body
    lines = []
    for relation in relations:
        target = target_slugs.get(getattr(relation, "target_id", ""))
        if target:
            lines.append(f"- {getattr(relation, 'type', 'related')}: [[{target}]]")
    if not lines:
        return body
    prefix = body.split("\n## Related pages\n", 1)[0].rstrip()
    return f"{prefix}\n\n## Related pages\n\n{_RELATIONS_MARKER}\n" + "\n".join(lines) + "\n"


__all__ = [
    "build_target_slugs", "gbrain_slug_for_path", "materialize_relations",
    "rewrite_wikilinks",
]
