"""WikiPage <-> KnowledgeObject adapter — bidirectional conversion with _ko_extra.

Round-trip guarantee: wp == knowledge_object_to_wiki_page(wiki_page_to_knowledge_object(wp)).
"""

from __future__ import annotations

from .object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
)
from src.wiki.core.types import WikiPage, PageType


# ---------------------------------------------------------------------------
# Type mapping helpers (source <-> document)
# ---------------------------------------------------------------------------

_PAGETYPE_TO_KNOWLEDGETYPE: dict[PageType, KnowledgeType] = {
    PageType.SOURCE: KnowledgeType.DOCUMENT,
    PageType.ENTITY: KnowledgeType.ENTITY,
    PageType.CONCEPT: KnowledgeType.CONCEPT,
    PageType.CLAIM: KnowledgeType.CLAIM,
    PageType.DECISION: KnowledgeType.DECISION,
    PageType.PROCEDURE: KnowledgeType.PROCEDURE,
    PageType.EVENT: KnowledgeType.EVENT,
    PageType.SYNTHESIS: KnowledgeType.SYNTHESIS,
}

_KNOWLEDGETYPE_TO_PAGETYPE: dict[KnowledgeType, PageType] = {
    KnowledgeType.DOCUMENT: PageType.SOURCE,
    KnowledgeType.ENTITY: PageType.ENTITY,
    KnowledgeType.CONCEPT: PageType.CONCEPT,
    KnowledgeType.CLAIM: PageType.CLAIM,
    KnowledgeType.DECISION: PageType.DECISION,
    KnowledgeType.PROCEDURE: PageType.PROCEDURE,
    KnowledgeType.EVENT: PageType.EVENT,
    KnowledgeType.SYNTHESIS: PageType.SYNTHESIS,
}


# ---------------------------------------------------------------------------
# _ko_extra serialization helpers
# ---------------------------------------------------------------------------

def _provenance_to_dict(p: Provenance) -> dict:
    return {
        "source_path": p.source_path,
        "source_paths": list(p.source_paths),
        "page": p.page,
        "quote": p.quote,
        "ingested_at": p.ingested_at,
        "ingestor_version": p.ingestor_version,
    }


def _provenance_from_dict(d: dict) -> Provenance:
    return Provenance(
        source_path=d.get("source_path", ""),
        source_paths=tuple(d.get("source_paths", ()) or ()),
        page=d.get("page"),
        quote=d.get("quote", ""),
        ingested_at=d.get("ingested_at", 0),
        ingestor_version=d.get("ingestor_version", ""),
    )


def _version_ref_to_dict(v: VersionRef) -> dict:
    return {
        "version_id": v.version_id,
        "timestamp": v.timestamp,
        "change_description": v.change_description,
    }


def _version_ref_from_dict(d: dict) -> VersionRef:
    return VersionRef(
        version_id=d.get("version_id", ""),
        timestamp=d.get("timestamp", 0),
        change_description=d.get("change_description", ""),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def wiki_page_to_knowledge_object(page: WikiPage) -> KnowledgeObject:
    """Convert a WikiPage to a KnowledgeObject.

    Reads ``_ko_extra`` from the page's instance attribute (set by
    ``knowledge_object_to_wiki_page``) or falls back to the frontmatter dict.
    Missing keys are filled with safe defaults so that old pages without any
    ``_ko_extra`` data can still be converted.
    """
    # Read existing _ko_extra (may be an instance attribute or in frontmatter)
    ko_extra: dict = _get_ko_extra(page)

    # Extract KO-specific fields with defaults
    lifecycle_raw = ko_extra.get("lifecycle", "created")
    try:
        lifecycle = LifecycleState(lifecycle_raw)
    except ValueError:
        lifecycle = LifecycleState.CREATED

    confidence = float(ko_extra.get("confidence", 0.0))

    p_dict = ko_extra.get("provenance", None)
    provenance = _provenance_from_dict(p_dict) if isinstance(p_dict, dict) else Provenance(source_path="")

    v_list = ko_extra.get("versions", None)
    versions = [_version_ref_from_dict(v) for v in v_list] if isinstance(v_list, list) else []

    # Build the KnowledgeObject
    ko = KnowledgeObject(
        id=page.id,
        type=_PAGETYPE_TO_KNOWLEDGETYPE[page.type],
        title=page.title,
        content=page.body,
        lifecycle=lifecycle,
        confidence=confidence,
        provenance=provenance,
        grade=page.grade,
        heat=page.heat,
        relations=list(page.relations),
        versions=versions,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )
    ko.evidence_refs = list(page.evidence_refs)  # type: ignore[attr-defined]
    for field_name in (
        "knowledge_mode",
        "context",
        "validity",
        "publication_version",
        "version",
        "closure_report",
    ):
        if field_name in ko_extra:
            setattr(ko, field_name, ko_extra[field_name])

    # Augment _ko_extra with WP-only fields so the reverse conversion can
    # restore them exactly.
    ko_extra["sources"] = list(page.sources)
    ko_extra["processing_depth"] = page.processing_depth
    ko_extra["is_immutable"] = page.is_immutable
    ko_extra["last_used_at"] = page.last_used_at
    ko_extra["zombie_since"] = page.zombie_since
    ko_extra["tags"] = list(page.tags)
    ko_extra["category"] = page.category
    ko_extra["taxonomy_sub"] = page.taxonomy_sub

    # Attach the augmented _ko_extra to the KO for round-trip preservation
    ko._ko_extra = ko_extra  # type: ignore[attr-defined]

    return ko


def knowledge_object_to_wiki_page(obj: KnowledgeObject) -> WikiPage:
    """Convert a KnowledgeObject to a WikiPage.

    KO-specific fields (lifecycle, confidence, provenance, versions) are
    packed into an ``_ko_extra`` instance attribute on the returned WikiPage.
    WP-only fields are restored from the same ``_ko_extra`` dict (when
    available, e.g. after a ``wiki_page_to_knowledge_object`` call).
    """
    # Read _ko_extra if available (set by wiki_page_to_knowledge_object)
    ko_extra: dict = _get_ko_extra(obj)

    # ---- Build _ko_extra for the resulting WikiPage ----
    new_extra: dict = dict(ko_extra)

    # KO-specific fields
    new_extra["lifecycle"] = obj.lifecycle.value
    new_extra["confidence"] = obj.confidence
    new_extra["provenance"] = _provenance_to_dict(obj.provenance)
    new_extra["versions"] = [_version_ref_to_dict(v) for v in obj.versions]

    # WP-only fields restored from incoming ko_extra (if any)
    new_extra["sources"] = list(ko_extra.get("sources", []))
    # Seed all sources from provenance when not already present
    source_paths = obj.provenance.source_paths or (obj.provenance.source_path,)
    for source_path in source_paths:
        if source_path and source_path not in new_extra["sources"]:
            new_extra["sources"].append(source_path)
    new_extra["processing_depth"] = ko_extra.get("processing_depth", "concept")
    new_extra["is_immutable"] = bool(ko_extra.get("is_immutable", False))
    new_extra["last_used_at"] = int(ko_extra.get("last_used_at", 0))
    new_extra["zombie_since"] = ko_extra.get("zombie_since")
    new_extra["tags"] = list(ko_extra.get("tags", []))
    new_extra["category"] = ko_extra.get("category", "")
    new_extra["taxonomy_sub"] = ko_extra.get("taxonomy_sub", "")
    for field_name in (
        "knowledge_mode",
        "context",
        "validity",
        "publication_version",
        "version",
        "closure_report",
    ):
        if hasattr(obj, field_name):
            new_extra[field_name] = getattr(obj, field_name)

    # ---- Build the WikiPage ----
    wp = WikiPage(
        id=obj.id,
        title=obj.title,
        type=_KNOWLEDGETYPE_TO_PAGETYPE[obj.type],
        sources=new_extra["sources"],
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        body=obj.content,
        relations=list(obj.relations),
        grade=obj.grade,
        processing_depth=new_extra["processing_depth"],
        is_immutable=new_extra["is_immutable"],
        heat=obj.heat,
        last_used_at=new_extra["last_used_at"],
        zombie_since=new_extra["zombie_since"],
        tags=new_extra["tags"],
        category=new_extra["category"],
        taxonomy_sub=new_extra["taxonomy_sub"],
        evidence_refs=list(getattr(obj, "evidence_refs", ())),
    )

    # Attach _ko_extra for downstream use (future frontmatter serialization)
    wp._ko_extra = new_extra  # type: ignore[attr-defined]

    return wp


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_ko_extra(obj: WikiPage | KnowledgeObject) -> dict:
    """Read ``_ko_extra`` from an instance attribute.

    For WikiPage we also check ``to_frontmatter_dict()`` as a fallback for
    pages that were loaded from disk with ``_ko_extra`` embedded in the
    frontmatter YAML (future support).
    """
    extra = getattr(obj, "_ko_extra", None)
    if isinstance(extra, dict):
        return extra

    # Fallback: check frontmatter (WikiPage only)
    if isinstance(obj, WikiPage):
        fm = obj.to_frontmatter_dict()
        fm_extra = fm.get("_ko_extra", None)
        if isinstance(fm_extra, dict):
            return fm_extra

    return {}
