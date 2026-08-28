"""Minimal atomic projection writer using the existing Wiki writer."""

from __future__ import annotations

from src.kc.adapters.legacy_write_guard import require_write_authority
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.page_writer import write_page


def write_projection(paths: WikiPaths, projection: dict, *, verified: bool = True, expected_version: int = 1, current_version: int = 1) -> None:
    source_refs = tuple(projection.get("source_refs", ()))
    require_write_authority(
        verified=verified,
        source_id=projection.get("knowledge_object_id", ""),
        expected_version=expected_version,
        current_version=current_version,
    )
    if not source_refs or not projection.get("projection_version"):
        raise ValueError("projection requires source_refs and projection_version")
    page = WikiPage(
        id=str(projection["id"]),
        title=str(projection["title"]),
        type=PageType.CLAIM,
        sources=list(source_refs),
        body=str(projection.get("body", "")),
        workflow_state="verified",
    )
    page._ko_extra = {
        "knowledge_object_id": projection["knowledge_object_id"],
        "document_id": projection.get("document_id", ""),
        "evidence": list(projection.get("evidence", ())),
        "evidence_ids": list(projection.get("evidence_ids", ())),
        "projection_version": projection["projection_version"],
    }
    write_page(paths, page)
