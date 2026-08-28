"""Read-only Wiki projection metadata for the C-phase seam."""

from src.knowledge.core.object import KnowledgeObject


def project_wiki(obj: KnowledgeObject, *, evidence_ids: tuple[str, ...], evidence: tuple | None = None) -> dict:
    source_paths = getattr(obj.provenance, "source_paths", None)
    return {
        "id": obj.id,
        "title": obj.title,
        "type": obj.type.value,
        "body": obj.content,
        "knowledge_object_id": obj.id,
        "evidence_ids": list(evidence_ids),
        "evidence": [
            {"document_id": item.document_id, "block_id": item.block_id, "quote": item.quote}
            for item in (evidence or ())
        ],
        "source_refs": list(source_paths or (obj.provenance.source_path,)),
        "projection_version": "kc-wiki-v1",
    }
