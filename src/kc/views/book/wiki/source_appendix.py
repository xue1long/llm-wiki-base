"""Deterministic source inventory for full Wiki-to-Book releases."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .model import WikiSnapshot
from .scanner import _parse


def _normalise(value: str) -> str:
    return value.replace("\\", "/").strip()


def build_source_appendix(snapshot: WikiSnapshot) -> dict[str, Any]:
    root = Path(snapshot.wiki_root).resolve()
    source_root = root / "sources"
    pages_by_ref: dict[str, set[str]] = {}
    for page in snapshot.pages:
        for source in page.sources:
            pages_by_ref.setdefault(_normalise(source), set()).add(page.page_id)

    entries: list[dict[str, Any]] = []
    for path in sorted(source_root.rglob("*.md"), key=lambda item: item.relative_to(root).as_posix()):
        fm, _body, raw = _parse(path, None, root)
        relative = path.relative_to(root).as_posix()
        source_id = str(fm["id"])
        refs = tuple(
            _normalise(item) for item in fm.get("sources", ())
            if isinstance(item, str) and item.strip()
        )
        aliases = {relative, path.name, source_id, *refs}
        page_ids = sorted({page_id for alias in aliases for page_id in pages_by_ref.get(alias, ())})
        entries.append({
            "source_id": source_id,
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source_refs": list(refs),
            "page_ids": page_ids,
        })
    return {
        "schema_version": "book-source-appendix-v1",
        "snapshot_id": snapshot.snapshot_id,
        "source_count": len(entries),
        "sources": entries,
    }


def render_source_appendix(appendix: dict[str, Any]) -> str:
    lines = ["# Sources index", "", f"Snapshot: `{appendix['snapshot_id']}`", ""]
    for entry in appendix["sources"]:
        pages = ", ".join(entry["page_ids"]) or "未被知识页引用"
        lines.append(f"- `{entry['source_id']}` — `{entry['path']}` — `{entry['sha256']}` — pages: {pages}")
    return "\n".join(lines) + "\n"


def serialise_appendix(appendix: dict[str, Any]) -> str:
    return json.dumps(appendix, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


__all__ = ["build_source_appendix", "render_source_appendix", "serialise_appendix"]
