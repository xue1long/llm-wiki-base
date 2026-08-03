"""Flat-file adjacency index for wiki relations.

Writes to ``.index/relations/outgoing/{source_id}.json`` and
``.index/relations/backlinks/{target_id}.json`` so that O(n) scans of all wiki
pages are avoided for common graph queries.
"""
from __future__ import annotations

import json

from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths


def _outgoing_dir(paths: WikiPaths):
    d = paths.index / "relations" / "outgoing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _backlinks_dir(paths: WikiPaths):
    d = paths.index / "relations" / "backlinks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_outgoing(paths: WikiPaths, source_id: str, relations: list[dict]) -> None:
    """Persist the outgoing edge list for *source_id*."""
    payload = {"source": source_id, "relations": relations}
    safe_write(
        _outgoing_dir(paths) / f"{source_id}.json",
        json.dumps(payload, ensure_ascii=False),
    )


def write_backlinks_for_source(
    paths: WikiPaths, source_id: str, relations: list[dict]
) -> None:
    """For each target in *relations*, add/update an entry in its backlinks file."""
    bl_dir = _backlinks_dir(paths)
    for rel in relations:
        target_id = rel["target"]
        bl_path = bl_dir / f"{target_id}.json"
        if bl_path.exists():
            try:
                data = json.loads(bl_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"target": target_id, "backlinks": []}
        else:
            data = {"target": target_id, "backlinks": []}
        # Remove existing entry from this source (idempotent upsert)
        data["backlinks"] = [
            b for b in data["backlinks"] if b.get("source") != source_id
        ]
        data["backlinks"].append(
            {
                "source": source_id,
                "type": rel["type"],
                "weight": rel.get("weight", 1.0),
                "context": rel.get("context", ""),
            }
        )
        safe_write(bl_path, json.dumps(data, ensure_ascii=False))


def read_outgoing(paths: WikiPaths, source_id: str) -> list[dict]:
    """Return outgoing relation dicts for *source_id*, or [] if missing."""
    path = _outgoing_dir(paths) / f"{source_id}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("relations", [])
    except (json.JSONDecodeError, OSError):
        return []


def read_backlinks(paths: WikiPaths, target_id: str) -> list[dict]:
    """Return backlink dicts for *target_id*, or [] if missing."""
    path = _backlinks_dir(paths) / f"{target_id}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("backlinks", [])
    except (json.JSONDecodeError, OSError):
        return []


def remove_source_from_index(paths: WikiPaths, source_id: str) -> None:
    """Remove outgoing index + all backlink references for *source_id*."""
    # Remove outgoing
    out_path = _outgoing_dir(paths) / f"{source_id}.json"
    if out_path.exists():
        out_path.unlink()

    # Remove references from every backlinks file
    bl_dir = _backlinks_dir(paths)
    if not bl_dir.exists():
        return
    for bl_path in bl_dir.glob("*.json"):
        try:
            data = json.loads(bl_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        before = len(data.get("backlinks", []))
        data["backlinks"] = [
            b for b in data.get("backlinks", []) if b.get("source") != source_id
        ]
        if len(data["backlinks"]) != before:
            safe_write(bl_path, json.dumps(data, ensure_ascii=False))


def rebuild_index(paths: WikiPaths) -> int:
    """Full rebuild from wiki pages. Returns count of indexed pages."""
    from ..core.types import PageType
    from ..storage.page_writer import read_page

    # Clear existing
    import shutil

    od = _outgoing_dir(paths)
    bd = _backlinks_dir(paths)
    if od.exists():
        shutil.rmtree(od)
    if bd.exists():
        shutil.rmtree(bd)

    count = 0
    for type_, dir_prop in [
        (PageType.SOURCE, "wiki_sources"),
        (PageType.ENTITY, "wiki_entities"),
        (PageType.CONCEPT, "wiki_concepts"),
        (PageType.SYNTHESIS, "wiki_synthesis"),
    ]:
        for f in getattr(paths, dir_prop).glob("*.md"):
            page = read_page(f)
            if not page.relations:
                continue
            rel_dicts = [r.to_dict() for r in page.relations]
            write_outgoing(paths, page.id, rel_dicts)
            write_backlinks_for_source(paths, page.id, rel_dicts)
            count += 1
    return count
