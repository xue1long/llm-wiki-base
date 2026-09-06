"""Pure-rule glossary and page index builders."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .model import WikiSnapshot

@dataclass(frozen=True)
class GlossaryEntry:
    page_id: str
    title: str
    page_type: str
    taxonomy: str | None
    grade: str
    summary: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexEntry:
    page_id: str
    chapter_id: str | None
    volume_id: str | None
    page_type: str
    title: str
    taxonomy: str | None
    grade: str = "B"


@dataclass(frozen=True)
class IndexManifest:
    entries: dict[str, IndexEntry]


def build_glossary(snapshot: WikiSnapshot) -> dict[str, GlossaryEntry]:
    # Include every page so coverage is measurable; wikilinks cannot introduce
    # a fabricated entry for an unresolved target.
    return {p.page_id: GlossaryEntry(p.page_id, p.title, p.page_type, p.primary_taxonomy,
                                     getattr(p, "grade", "B"), p.summary.split(".", 1)[0].strip(),
                                     tuple(dict.fromkeys((p.title, p.page_id))))
            for p in sorted(snapshot.pages, key=lambda page: page.page_id)}


def normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def build_glossary_index(glossary: dict[str, GlossaryEntry]) -> dict[str, tuple[str, ...]]:
    index: dict[str, set[str]] = {}
    for entry in glossary.values():
        for alias in entry.aliases or (entry.title, entry.page_id):
            key = normalize_term(alias)
            if key:
                index.setdefault(key, set()).add(entry.page_id)
    return {key: tuple(sorted(ids)) for key, ids in sorted(index.items())}


def build_index(snapshot: WikiSnapshot, outlines: list[dict]) -> IndexManifest:
    locations: dict[str, tuple[str, str]] = {}
    for volume in (v for outline in outlines if isinstance(outline, dict) for v in outline.get("volumes", ()) if isinstance(v, dict)):
        vid = volume.get("volume_id")
        for chapter in volume.get("chapters", ()) if isinstance(volume.get("chapters"), list) else ():
            if not isinstance(chapter, dict):
                continue
            for item in chapter.get("page_ids", ()) if isinstance(chapter.get("page_ids"), list) else ():
                pid = item if isinstance(item, str) else item.get("page_id") if isinstance(item, dict) else None
                if pid is not None:
                    locations[pid] = (str(vid) if vid is not None else None, str(chapter.get("chapter_id")) if chapter.get("chapter_id") is not None else None)
    entries = {p.page_id: IndexEntry(p.page_id, locations.get(p.page_id, (None, None))[1], locations.get(p.page_id, (None, None))[0],
                                      p.page_type, p.title, p.primary_taxonomy, getattr(p, "grade", "B")) for p in sorted(snapshot.pages, key=lambda page: page.page_id)}
    return IndexManifest(entries)


__all__ = ["GlossaryEntry", "IndexEntry", "IndexManifest", "build_glossary", "build_glossary_index", "build_index", "normalize_term"]
