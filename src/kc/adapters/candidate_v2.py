"""Adapters between the v2 block-reference contract and the KC payload."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict
from typing import Any

from src.kc.contracts.candidate_v2 import (
    AdaptationResult,
    CandidateV2,
    ClaimV2,
    RejectedClaim,
)
from src.kc.compiler.normalize import CanonicalDocument
from src.knowledge.core.candidate import KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType
from src.pipeline.evidence_registry import EvidenceBlockRegistry
from src.kc.compiler.evidence import quote_matches_content


def _as_v2(candidate: CandidateV2 | dict[str, Any], document: CanonicalDocument) -> CandidateV2:
    if isinstance(candidate, CandidateV2):
        return candidate
    evidence = candidate.get("evidence", [])
    claims = []
    for item in candidate.get("claims", []):
        if not isinstance(item, dict) or not isinstance(item.get("statement"), str):
            continue
        block_ids = item.get("evidence_block_ids")
        if not isinstance(block_ids, list):
            refs = item.get("evidence_refs", [])
            block_ids = [
                evidence[ref].get("block_id", "")
                for ref in refs
                if isinstance(ref, int)
                and 0 <= ref < len(evidence)
                and isinstance(evidence[ref], dict)
            ]
            if not block_ids:
                quote = next(
                    (evidence[ref].get("quote") for ref in refs
                     if isinstance(ref, int) and 0 <= ref < len(evidence)
                     and isinstance(evidence[ref], dict)),
                    "",
                )
                matches = [
                    block.block_id for block in document.blocks
                    if isinstance(quote, str) and quote_matches_content(quote, block.content)
                ]
                block_ids = matches if len(matches) == 1 else []
        claims.append(ClaimV2(
            statement=str(item["statement"]),
            confidence=float(item.get("confidence", 0.0)),
            evidence_block_ids=tuple(value for value in block_ids if isinstance(value, str)),
        ))
    return CandidateV2(
        source_id=str(candidate.get("source_id", "")),
        type=str(candidate.get("type", "concept")),
        title=str(candidate.get("title", "")),
        claims=tuple(claims),
    )


def adapt_candidate(
    candidate: CandidateV2 | dict[str, Any],
    document: CanonicalDocument,
    registry: EvidenceBlockRegistry,
    source_root=None,
):
    candidate_v2 = _as_v2(candidate, document)
    payload_claims: list[dict[str, Any]] = []
    generator_claims: list[dict[str, Any]] = []
    generator_evidence: list[dict[str, Any]] = []
    rejected: list[RejectedClaim] = []
    for index, claim in enumerate(candidate_v2.claims):
        bound = registry.bind_claim(claim.statement, claim.evidence_block_ids)
        if isinstance(bound, RejectedClaim):
            rejected.append(bound)
            continue
        claim_id = hashlib.sha256(
            f"{candidate_v2.source_id}:{index}:{claim.statement}".encode("utf-8")
        ).hexdigest()[:16]
        evidence = [
            {
                "source_path": document.source,
                "block_id": item.block_id,
                "quote": item.quote,
                "quote_hash": item.quote_hash,
                "confidence": claim.confidence,
            }
            for item in bound.evidence
        ]
        payload_claims.append({"id": claim_id, "text": claim.statement.strip(), "evidence": evidence})
        refs = list(range(len(generator_evidence), len(generator_evidence) + len(evidence)))
        generator_evidence.extend(evidence)
        generator_claims.append({
            "statement": claim.statement,
            "confidence": claim.confidence,
            "evidence_refs": refs,
        })
    payload = {"claims": payload_claims}
    generator_candidate = KnowledgeCandidate(
        id=f"cand_{uuid.uuid4().hex[:12]}",
        source_id=candidate_v2.source_id,
        type=KnowledgeType(candidate_v2.type) if candidate_v2.type in {item.value for item in KnowledgeType} else KnowledgeType.CONCEPT,
        title=candidate_v2.title,
        claims=generator_claims,
        confidence=max((claim.confidence for claim in candidate_v2.claims), default=0.0),
        evidence=generator_evidence,
        raw_llm_output=asdict(candidate_v2),
    )
    return AdaptationResult(
        candidate_v2=candidate_v2,
        payload=payload,
        generator_candidate=generator_candidate,
        rejected_claims=tuple(rejected),
        valid_claim_count=len(payload_claims),
    )
