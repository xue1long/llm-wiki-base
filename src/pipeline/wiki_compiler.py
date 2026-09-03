"""Deterministic conversion from render candidates to trusted page records."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from .render_contract import RenderBundle


@dataclass(frozen=True)
class CompiledPage:
    id: str
    title: str
    page_type: str
    body: str
    sources: tuple[str, ...]
    tags: tuple[str, ...]
    evidence: tuple[object, ...]
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class WikiBundle:
    task_id: str
    source_id: str
    pages: tuple[CompiledPage, ...]
    bundle_hash: str


def _page_id(bundle: RenderBundle, page) -> str:
    return hashlib.sha256(f"{bundle.source_id}:{page.page_key}".encode()).hexdigest()[:24]


def compile_bundle(bundle, knowledge_object=None, evidence_registry=None, wiki_index=None) -> WikiBundle:
    keys = [page.page_key for page in bundle.pages]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_page_key")
    now = int(time.time() * 1000)
    compiled = []
    for page in bundle.pages:
        evidence = []
        for block_id in page.referenced_block_ids:
            block = evidence_registry.get(block_id) if evidence_registry else None
            if block is None or not getattr(block, "visible", False):
                raise ValueError(f"invalid_evidence_block:{block_id}")
            evidence.append(block)
        compiled.append(CompiledPage(
            id=_page_id(bundle, page), title=page.title, page_type=page.page_type,
            body=page.body, sources=(bundle.source_id,), tags=page.candidate_tags,
            evidence=tuple(evidence), created_at=now, updated_at=now,
        ))
    return WikiBundle(bundle.task_id, bundle.source_id, tuple(compiled), bundle.bundle_hash)
