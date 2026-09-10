"""Export v2 entity aliases in the ruflo-kb forward registry format."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ...lib.write_hooks import safe_write


def _pairs(registry: Mapping[str, str] | Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return list(registry.items()) if isinstance(registry, Mapping) else list(registry)


def extract_aliases(file_stem: str, frontmatter: Mapping[str, Any]) -> dict[str, str]:
    if frontmatter.get("type") != "entity":
        return {}
    aliases = frontmatter.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    result: dict[str, str] = {}
    for alias in aliases if isinstance(aliases, Iterable) else ():
        if not isinstance(alias, str) or not alias.strip():
            continue
        result.setdefault(alias.strip(), file_stem)
    return result


def extract_alias_records(file_stem: str, frontmatter: Mapping[str, Any]) -> list[dict[str, str]]:
    aliases = extract_aliases(file_stem=file_stem, frontmatter=frontmatter)
    return [
        {"alias": alias, "canonical": canonical, "original": alias}
        for alias, canonical in sorted(aliases.items())
    ]


def write_alias_registry(
    registry: Mapping[str, str] | Iterable[tuple[str, str]],
    path: str | Path,
) -> Path:
    """Write a SlugAliasRegistry-compatible JSON file.

    First-writer-wins is intentional: an alias collision is reported and the
    existing canonical target is never silently replaced.
    """
    aliases: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    for alias, canonical in _pairs(registry):
        if not isinstance(alias, str) or not isinstance(canonical, str):
            continue
        if not alias.strip() or not canonical.strip():
            continue
        alias = alias.strip()
        canonical = canonical.strip()
        existing = aliases.get(alias)
        if existing is None:
            aliases[alias] = canonical
        elif existing != canonical:
            conflicts.append({"alias": alias, "existing": existing, "incoming": canonical})

    # Stable JSON key order also stabilises SlugAliasRegistry's rebuilt
    # reverse index (the registry intentionally preserves file order).
    aliases = dict(sorted(aliases.items()))
    reverse: dict[str, list[str]] = {}
    for alias, canonical in aliases.items():
        reverse.setdefault(canonical, []).append(alias)
    for canonical in reverse:
        reverse[canonical].sort()
    payload: dict[str, Any] = {
        "version": 1,
        "aliases": aliases,
        "aliases_rev": reverse,
    }
    if conflicts:
        payload["conflicts"] = conflicts
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_write(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target
