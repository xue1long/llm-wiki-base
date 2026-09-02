from dataclasses import asdict

from src.kc.contracts.candidate_v2 import CandidateV2, ClaimV2
from src.pipeline.evidence_registry import EvidenceBlockRegistry
from src.pipeline.shadow import compare_evidence_contracts
from src.pipeline.text_preprocessing.api import preprocess_source


def test_shadow_compares_one_parsed_candidate_without_llm_calls():
    prepared = preprocess_source("正文证据。", source_id="raw/sources/a.md")
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    block_id = next(iter(registry.visible_block_ids()))
    candidate = CandidateV2(
        source_id="raw/sources/a.md",
        type="concept",
        title="标题",
        claims=(ClaimV2("正文证据。", 0.9, (block_id,)),),
    )

    report = compare_evidence_contracts(
        candidate, prepared.canonical_document, registry, "task-1"
    )

    assert report["llm_calls"] == 0
    assert report["v2"]["claim_count"] == 1
    assert "differences" in report
