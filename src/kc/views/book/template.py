"""Immutable template and rendered value object for the Book view."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BookTemplate:
    template_id: str = "default_v1"
    sections: tuple[str, ...] = (
        "header", "context", "temporal_status", "knowledge_blocks",
        "conflicts", "evidence_chain", "footer",
    )
    custom_renderers: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class BookView:
    id: str
    chapter_id: str
    knowledge_unit_ids: tuple[str, ...]
    publication_version: int
    rendered_hash: str
    generated_at: int
    sections: tuple[str, ...]
    sections_content: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def markdown(self) -> str:
        return "\n\n".join(self.sections_content.get(s, "") for s in self.sections)


def compute_book_rendered_hash(
    *, book_id: str, chapter_id: str, knowledge_unit_ids: tuple[str, ...],
    sections: tuple[str, ...], sections_content: dict, publication_version: int,
    evidence_refs: tuple[tuple[str, str], ...],
) -> str:
    payload = {
        "book_id": book_id, "chapter_id": chapter_id,
        "knowledge_unit_ids": list(knowledge_unit_ids), "sections": list(sections),
        "sections_content": sections_content, "publication_version": publication_version,
        "evidence_refs": [list(ref) for ref in evidence_refs],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

