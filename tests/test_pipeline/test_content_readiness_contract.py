"""Frozen vocabulary and fixture contract for content readiness."""

from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.text_preprocessing import ContentKind, ReadinessDecision


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "content_readiness" / "golden.json"
REASON_CODES = {
    "empty_input",
    "metadata_only",
    "duplicated_navigation",
    "no_evidence_capacity",
    "legitimate_short",
    "high_repetition",
    "encoding_degraded",
    "ocr_degraded",
    "missing_provenance",
    "unsupported_format",
    "oversized_block",
    "empty_subblock",
    "specialist_failed",
    "policy_violation",
}
DECISIONS = {item.value for item in ReadinessDecision}
CONTENT_KINDS = {item.value for item in ContentKind}


def test_golden_manifest_freezes_content_readiness_contract() -> None:
    manifest = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "content-readiness-v1"
    assert manifest["reason_codes"] == sorted(REASON_CODES)
    assert set(manifest["decisions"]) == DECISIONS
    assert set(manifest["content_kinds"]) == CONTENT_KINDS
    assert "metadata_only" not in manifest["content_kinds"]
    assert "readiness_decision" not in manifest["audit_keys"]
    assert len(manifest["fixtures"]) >= 14

    source_ids = set()
    for fixture in manifest["fixtures"]:
        assert fixture["source_id"] not in source_ids
        source_ids.add(fixture["source_id"])
        assert fixture["label"]
        assert fixture["content_kind"] in CONTENT_KINDS
        assert fixture["decision"] in DECISIONS
        assert set(fixture["reason_codes"]) <= REASON_CODES
