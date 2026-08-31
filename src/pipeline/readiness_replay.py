"""Independent, fail-closed replay of readiness audit evidence."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from typing import Any

from src.kc.compiler.evidence import canonical_quote
from src.kc.compiler.normalize import normalize_text
from src.pipeline.extraction_types import ExtractionArtifact
from src.pipeline.text_preprocessing.types import (
    ContentAssessment,
    NoiseReport,
    ReplayResult,
)


def _failure(reason: str) -> ReplayResult:
    return ReplayResult(False, ("policy_violation",), reason)


def replay_evidence(record: dict[str, Any], artifact: ExtractionArtifact) -> ReplayResult:
    if record.get("source_id") != artifact.source_id:
        return _failure("source_id_mismatch")
    if record.get("input_text_sha256") != artifact.input_text_sha256:
        return _failure("input_text_hash_mismatch")
    if record.get("source_bytes_sha256") not in {None, artifact.source_bytes_sha256}:
        return _failure("source_bytes_hash_mismatch")

    document = normalize_text(artifact.input_text, source=artifact.source_id)
    canonical_hash = sha256(document.content.encode("utf-8")).hexdigest()
    if record.get("canonical_text_sha256") != canonical_hash:
        return _failure("canonical_text_hash_mismatch")

    evidence = record.get("evidence", [])
    if not isinstance(evidence, list):
        return _failure("evidence_not_a_list")
    blocks = {block.block_id: block for block in document.blocks}
    for item in evidence:
        if not isinstance(item, dict):
            return _failure("evidence_item_invalid")
        item_source = item.get("source_id", item.get("source_path"))
        if item_source != artifact.source_id:
            return _failure("source_id_mismatch")
        block_id = item.get("block_id")
        if not isinstance(block_id, str) or not block_id:
            return _failure("block_id_missing")
        block = blocks.get(block_id)
        if block is None:
            return _failure("block_id_mismatch")
        quote = item.get("quote", item.get("exact_quote"))
        if not isinstance(quote, str) or not quote:
            return _failure("quote_missing")
        quote = canonical_quote(quote)
        if quote not in block.content:
            return _failure("quote_not_in_declared_block")
        if item.get("quote_hash") != sha256(quote.encode("utf-8")).hexdigest():
            return _failure("quote_hash_mismatch")
    return ReplayResult(True, (), None)


def serialize_audit(
    assessment: ContentAssessment,
    report: NoiseReport,
    *,
    analyzer_called: bool,
    failure_reason: str | None,
) -> dict[str, Any]:
    return {
        "assessment_version": assessment.assessment_version,
        "policy_version": assessment.policy_version,
        "source_id": assessment.source_id,
        "format": assessment.format,
        "extraction_method": assessment.extraction_method,
        "content_kind": assessment.content_kind.value,
        "decision": assessment.decision.value,
        "reason_codes": list(assessment.reason_codes),
        "analyzer_called": analyzer_called,
        "evidence_capacity": asdict(assessment.evidence_capacity),
        "failure_reason": failure_reason or assessment.failure_reason,
        "preprocessing_version": report.version,
        "source_bytes_sha256": report.source_bytes_sha256,
        "input_text_sha256": report.input_text_sha256,
        "canonical_text_sha256": report.canonical_text_sha256,
        "prompt_text_sha256": report.prompt_text_sha256,
        "evidence": [],
    }
