import asyncio

from src.kc.contracts.candidate_v2 import CandidateV2, ClaimV2
from src.kc.mainline import CandidateReviewer
from src.pipeline.evidence_registry import EvidenceBlockRegistry
from src.pipeline.text_preprocessing.api import preprocess_source
from src.pipeline.ingest import _resolve_evidence_contract
from src.config import settings


def test_all_providers_default_to_v1_evidence_contract(monkeypatch):
    monkeypatch.delenv("RUFLO_EVIDENCE_CONTRACT", raising=False)
    assert _resolve_evidence_contract() == "v1"


def test_explicit_evidence_contract_override_is_preserved(monkeypatch):
    monkeypatch.setenv("RUFLO_EVIDENCE_CONTRACT", "v1")
    assert _resolve_evidence_contract() == "v1"


def test_task_contract_version_defaults_to_v1(monkeypatch):
    monkeypatch.delenv("RUFLO_TASK_CONTRACT_VERSION", raising=False)
    assert settings().task_contract_version == "v1"


def test_queued_ingest_snapshot_uses_canonical_v1(monkeypatch):
    from src.services.ingest import create_ingest_snapshot

    monkeypatch.setattr("src.services.ingest.resolve_project", lambda *args, **kwargs: (type("C", (), {"id": "p", "path": "p"})(), None))
    monkeypatch.setattr("src.project.identity.resolve_project_template", lambda *args, **kwargs: (type("T", (), {"template_id": "t", "template_version": "1", "template_hash": "h", "contract_hash": "c", "snapshot_path": "s"})(), None))
    assert create_ingest_snapshot("p", "raw/a.md").pipeline_contract_version == "v1"


def test_reviewer_isolates_invalid_v2_claims():
    prepared = preprocess_source(
        "正文证据。\n\n来源：https://example.test/source",
        source_id="raw/sources/a.md",
    )
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    visible = next(iter(registry.visible_block_ids()))
    hidden = next(block.block_id for block in registry.blocks() if not block.visible)
    candidate = CandidateV2(
        source_id="raw/sources/a.md",
        type="concept",
        title="标题",
        claims=(
            ClaimV2("有效", 0.9, (visible,)),
            ClaimV2("隐藏", 0.9, (hidden,)),
            ClaimV2("未知", 0.9, ("missing",)),
        ),
    )

    result = asyncio.run(CandidateReviewer().review(
        candidate, prepared.canonical_document, registry=registry
    ))

    assert result.status == "validated"
    assert result.valid_claim_count == 1
    assert len(result.rejected_claims) == 2
    assert result.generator_candidate is not None
    assert len(result.projections) == 1


def test_reviewer_requires_human_when_no_v2_claim_has_valid_evidence():
    prepared = preprocess_source("正文证据。", source_id="raw/sources/a.md")
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    candidate = CandidateV2(
        source_id="raw/sources/a.md",
        type="concept",
        title="标题",
        claims=(ClaimV2("无效", 0.9, ("missing",)),),
    )

    result = asyncio.run(CandidateReviewer().review(
        candidate, prepared.canonical_document, registry=registry
    ))

    assert result.status == "review_required"
    assert result.valid_claim_count == 0
    assert not result.projections
