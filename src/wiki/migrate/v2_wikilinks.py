"""Deterministic conversion of v2 wikilinks into relation dictionaries."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ...utils.slugify import slugify


_WIKILINK_RE = re.compile(r"\[\[([^\[\]\r\n]+?)\]\]")
_BVID_RE = re.compile(r"^BV[0-9A-Za-z]+$")
_NUMERIC_RE = re.compile(r"^\d+$")


def _normalise_target(value: str) -> str:
    value = value.strip()
    if _BVID_RE.fullmatch(value) or _NUMERIC_RE.fullmatch(value):
        return value
    return slugify(value) or value


def _items(body: str) -> tuple[list[dict[str, Any]], int]:
    matches = list(_WIKILINK_RE.finditer(body or ""))
    malformed = len(re.findall(r"\[\[(?![^\[\]\r\n]+\]\])", body or ""))
    items: list[dict[str, Any]] = []
    for match in matches:
        raw = match.group(0)
        inner = match.group(1).strip()
        target = inner.split("|", 1)[0].strip()
        if not target:
            malformed += 1
            continue
        items.append({"raw": raw, "target": _normalise_target(target)})
    return items, malformed


def extract_relations(body: str, *, current_page_id: str) -> list[dict[str, str]]:
    """Return one ``references`` relation per non-self target, in source order."""
    current = _normalise_target(current_page_id)
    relations: list[dict[str, str]] = []
    seen: set[str] = set()
    links, _ = _items(body)
    for link in links:
        target = link["target"]
        if target == current or target in seen:
            continue
        seen.add(target)
        relations.append({"target": target, "type": "references"})
    return relations


def extract_link_ledger(
    body: str,
    *,
    current_page_id: str,
    known_targets: Iterable[str] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return an auditable link ledger without inventing missing targets."""
    known = {_normalise_target(str(target)) for target in (known_targets or ())}
    alias_map = {
        _normalise_target(str(alias)): _normalise_target(str(canonical))
        for alias, canonical in (aliases or {}).items()
    }
    current = _normalise_target(current_page_id)
    links: list[dict[str, str]] = []
    resolved = unresolved = self_references = 0
    parsed, parse_errors = _items(body)
    for link in parsed:
        target = link["target"]
        canonical = alias_map.get(target, target)
        if canonical == current:
            status = "self_reference"
            self_references += 1
        elif canonical in known:
            status = "resolved"
            resolved += 1
        else:
            status = "unresolved"
            unresolved += 1
        links.append({"raw": link["raw"], "target": target, "status": status})
    return {
        "total": len(parsed),
        "resolved": resolved,
        "unresolved": unresolved,
        "self_references": self_references,
        "parse_errors": parse_errors,
        "links": links,
    }
