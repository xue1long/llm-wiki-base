from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.kc.compiler.normalize import normalize_text
from src.kc.mainline import CandidatePromoter, CandidateReviewer, finalize_bundle, recover_staged_bundles
from src.kc.publish import PublicationGate
from src.knowledge.core.candidate import KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType


def test_bundle_stays_non_current_until_vector_ready(tmp_path: Path) -> None:
    source = "raw/sources/demo.md"
    candidate = KnowledgeCandidate(
        id="candidate-pub", source_id=source, type=KnowledgeType.CONCEPT,
        title="Demo", claims=[{"statement": "Source quote", "evidence_refs": [0]}],
        confidence=.9, evidence=[{"source_path": source, "quote": "Source quote"}],
        raw_llm_output={},
    )
    document = normalize_text("Source quote", source=source)
    review = asyncio.run(CandidateReviewer().review(candidate, document))
    promotion = CandidatePromoter().promote(candidate, review, project_root=tmp_path, document=document)
    result = finalize_bundle(tmp_path, bundle_key=promotion.bundle_key, page_ids=("page-1",))
    assert result.status == "staged"
    assert PublicationGate(tmp_path / ".index" / "kc" / "publication_state.json").load().current_version == 0
    manifest = json.loads(promotion.manifest_path.read_text(encoding="utf-8"))
    assert manifest["stores"]["vector"] == "pending"


def test_vector_ready_publishes_once_and_is_idempotent(tmp_path: Path) -> None:
    source = "raw/sources/demo.md"
    candidate = KnowledgeCandidate(
        id="candidate-pub-2", source_id=source, type=KnowledgeType.CONCEPT,
        title="Demo", claims=[{"statement": "Source quote", "evidence_refs": [0]}],
        confidence=.9, evidence=[{"source_path": source, "quote": "Source quote"}],
        raw_llm_output={},
    )
    document = normalize_text("Source quote", source=source)
    review = asyncio.run(CandidateReviewer().review(candidate, document))
    promotion = CandidatePromoter().promote(candidate, review, project_root=tmp_path, document=document)
    first = finalize_bundle(tmp_path, bundle_key=promotion.bundle_key, page_ids=("page-1",), vector_ready=True)
    second = finalize_bundle(tmp_path, bundle_key=promotion.bundle_key, page_ids=("page-1",), vector_ready=True)
    assert first.status == second.status == "published"
    assert first.batch_id == second.batch_id
    assert PublicationGate(tmp_path / ".index" / "kc" / "publication_state.json").load().current_version == first.publication_version


def test_recovery_ignores_incomplete_staged_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / ".index" / "kc" / "bundles" / "broken"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "bundle_key": "broken", "status": "staged", "stores": {"vector": "pending"},
        "page_ids": ["missing-page"], "object_ids": [],
    }), encoding="utf-8")
    assert asyncio.run(recover_staged_bundles(tmp_path)) == []
