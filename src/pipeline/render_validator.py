"""Fail-closed validation before any Writer/Index/Vector call."""
from __future__ import annotations

from dataclasses import dataclass, field
from .render_contract import RenderBundle


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def validate_bundle(bundle: RenderBundle, *, task_context=None, evidence_registry=None, wiki_index=None) -> ValidationResult:
    errors: list[str] = []
    if bundle.bundle_hash != bundle.compute_hash():
        errors.append("bundle_hash_mismatch")
    keys = [page.page_key for page in bundle.pages]
    if len(keys) != len(set(keys)):
        errors.append("duplicate_page_key")
    valid_types = {"source", "entity", "concept", "synthesis"}
    known = set(wiki_index or ())
    for page in bundle.pages:
        if not page.title.strip(): errors.append("empty_title")
        if not page.body.strip(): errors.append("empty_body")
        if page.page_type not in valid_types: errors.append("invalid_page_type")
        if any(link not in known for link in page.candidate_links): errors.append("unknown_link")
        if evidence_registry is not None:
            for block_id in page.referenced_block_ids:
                block = evidence_registry.get(block_id)
                if block is None: errors.append("invalid_evidence_block")
                elif not getattr(block, "visible", False): errors.append("hidden_block")
    return ValidationResult(not errors, tuple(dict.fromkeys(errors)))


__all__ = ["ValidationResult", "validate_bundle"]
