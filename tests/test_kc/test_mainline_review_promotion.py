from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.kc.compiler.normalize import normalize_text
from src.kc.mainline import CandidatePromoter, CandidateReviewer
from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType


def _candidate(source: str = "raw/sources/demo.md", *, quote: str = "Source quote") -> KnowledgeCandidate:
    return KnowledgeCandidate(
        id="candidate-1", source_id=source, type=KnowledgeType.CONCEPT,
        title="Demo", claims=[{"statement": quote, "evidence_refs": [0]}],
        confidence=0.9, evidence=[{"source_path": source, "quote": quote}],
        raw_llm_output={},
    )


def test_reviewer_rejects_unanchored_evidence() -> None:
    candidate = _candidate(quote="missing")
    document = normalize_text("Source quote", source="raw/sources/demo.md")
    result = asyncio.run(CandidateReviewer().review(candidate, document))
    assert result.status == "rejected"
    assert candidate.status == CandidateStatus.REJECTED


def test_reviewer_promoter_persists_validated_bundle(tmp_path: Path) -> None:
    candidate = _candidate()
    document = normalize_text("Source quote", source="raw/sources/demo.md")
    review = asyncio.run(CandidateReviewer().review(candidate, document))
    assert review.status == "validated"
    promoted = CandidatePromoter().promote(candidate, review, project_root=tmp_path, document=document)
    assert candidate.status == CandidateStatus.PROMOTED
    manifest = json.loads(promoted.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "staged"
    assert manifest["stores"]["knowledge_object"] == "ready"
    assert manifest["stores"]["wiki"] == "pending"
    assert len(manifest["object_ids"]) == 1


def test_promoter_is_fail_closed_for_rejected_candidate(tmp_path: Path) -> None:
    candidate = _candidate()
    document = normalize_text("Source quote", source="raw/sources/demo.md")
    review = asyncio.run(CandidateReviewer().review(candidate, document))
    candidate.status = CandidateStatus.REJECTED
    try:
        CandidatePromoter().promote(candidate, review, project_root=tmp_path, document=document)
    except ValueError as exc:
        assert "validated" in str(exc)
    else:
        raise AssertionError("rejected candidates must not be promoted")
