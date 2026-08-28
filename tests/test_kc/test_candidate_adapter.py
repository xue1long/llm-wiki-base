"""Tests for the pipeline-candidate to KC payload adapter."""

from __future__ import annotations

import pytest

from src.kc.api import candidate_to_payload, compile_text
from src.kc.compiler.evidence import EvidenceValidationError, validate_evidence
from src.kc.compiler.verify import verify_claim
from src.kc.contracts.status import PublicationState, can_publish
from src.kc.compiler.normalize import normalize_text


def _candidate(source: str = "raw/sources/demo.md") -> dict:
    return {
        "source_id": source,
        "claims": [{"statement": "KC 统一证据适配。", "evidence_refs": [0]}],
        "evidence": [{"source_path": source, "quote": "KC 统一证据适配。"}],
        "confidence": 0.8,
    }


def test_candidate_adapter_emits_strict_claim_and_block_evidence() -> None:
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")

    payload = candidate_to_payload(_candidate(), document)

    claim = payload["claims"][0]
    evidence = claim["evidence"][0]
    assert claim["id"]
    assert claim["text"] == "KC 统一证据适配。"
    assert evidence["block_id"] == document.blocks[0].block_id
    assert evidence["quote"] == "KC 统一证据适配。"
    assert evidence["quote_hash"]


def test_candidate_adapter_rejects_source_path_mismatch() -> None:
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")
    candidate = _candidate(source="raw/sources/other.md")

    with pytest.raises(ValueError, match="source_path"):
        candidate_to_payload(candidate, document)


def test_candidate_adapter_accepts_absolute_source_under_project_root(tmp_path) -> None:
    source = tmp_path / "raw" / "sources" / "demo.md"
    source.parent.mkdir(parents=True)
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")
    candidate = _candidate(source=str(source))

    payload = candidate_to_payload(candidate, document, source_root=tmp_path)

    assert payload["claims"][0]["evidence"][0]["quote"] == "KC 统一证据适配。"


def test_candidate_adapter_rejects_bad_evidence_ref() -> None:
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")
    candidate = _candidate()
    candidate["claims"][0]["evidence_refs"] = [1]

    with pytest.raises(ValueError, match="evidence_refs"):
        candidate_to_payload(candidate, document)


def test_compile_text_builds_projection_from_valid_candidate() -> None:
    candidate = _candidate()
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")
    payload = candidate_to_payload(candidate, document)

    result = compile_text("raw/sources/demo.md", "KC 统一证据适配。", payload)

    assert result["document_id"]
    assert result["projections"][0]["body"] == "KC 统一证据适配。"
    assert result["projections"][0]["evidence_ids"]


def test_candidate_adapter_rejects_quote_matching_multiple_blocks() -> None:
    document = normalize_text(
        "重复引用内容。\n\n重复引用内容。",
        source="raw/sources/demo.md",
    )
    candidate = _candidate()
    candidate["evidence"][0]["quote"] = "重复引用内容。"

    with pytest.raises(ValueError, match="unique"):
        candidate_to_payload(candidate, document)


def test_validated_evidence_uses_structural_status() -> None:
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")
    block = document.blocks[0]

    evidence = validate_evidence(
        document,
        {
            "block_id": block.block_id,
            "quote": block.content,
        },
    )

    assert evidence.status == "structurally_verified"


def test_claim_review_returns_structural_state_not_truth_verified() -> None:
    document = normalize_text("KC 统一证据适配。", source="raw/sources/demo.md")
    evidence = validate_evidence(
        document,
        {"block_id": document.blocks[0].block_id, "quote": document.blocks[0].content},
    )

    state = verify_claim(
        {"id": "claim-1", "text": "结构声明。"},
        document,
        (evidence,),
    )

    assert state is PublicationState.STRUCTURALLY_VERIFIED
    assert can_publish(state)
    assert not can_publish(PublicationState.VERIFIED)
