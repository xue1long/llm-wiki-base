"""Projection seam into the existing KnowledgeObject model."""

from __future__ import annotations

from src.knowledge.core.object import KnowledgeObject, KnowledgeType, LifecycleState, Provenance
from src.kc.compiler.normalize import CanonicalDocument
from src.kc.compiler.verify import verify_claim
from src.kc.contracts.evidence import Evidence


def compile_claim(claim: dict, document: CanonicalDocument, evidence: tuple[Evidence, ...]) -> KnowledgeObject:
    verify_claim(claim, document, evidence)
    quote = evidence[0].quote
    return KnowledgeObject(
        id=claim["id"],
        type=KnowledgeType.CLAIM,
        title=claim["text"][:120],
        content=claim["text"],
        lifecycle=LifecycleState.PROCESSING,
        confidence=max(item.confidence for item in evidence),
        provenance=Provenance(
            source_path=document.source,
            source_paths=document.sources,
            quote=quote,
            ingestor_version=document.parser_version,
        ),
    )
