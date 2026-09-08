"""Small immutable records shared by the Wiki-to-Book compiler stages."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentBlock:
    block_id: str
    page_id: str
    heading: str | None
    body: str
    ordinal: int


@dataclass(frozen=True)
class PageRecord:
    page_id: str
    title: str
    page_type: str
    path: str
    primary_taxonomy: str | None
    summary: str
    content_blocks: tuple[ContentBlock, ...]
    relation_targets: tuple[tuple[str, str], ...]
    content_sha256: str
    char_count: int
    token_count: int | None
    custom_type: str = ""
    # V4 disk contract keeps source provenance in frontmatter; retain it in
    # the compiler snapshot so chapters and manifests can expose traceability.
    sources: tuple[str, ...] = ()
    task_type: str | None = None
    sensitivity: str = ""


@dataclass(frozen=True)
class WikiSnapshot:
    snapshot_id: str
    wiki_root: str
    schema_version: str
    pages: tuple[PageRecord, ...]
    excluded_sources: tuple[str, ...]
