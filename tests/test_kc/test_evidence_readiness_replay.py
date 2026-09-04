"""Independent replay tests for readiness audit evidence."""

from __future__ import annotations

from hashlib import sha256

from src.pipeline.extraction_types import artifact_from_text
from src.pipeline.readiness_replay import replay_evidence, serialize_audit
from src.pipeline.text_preprocessing import assess_artifact
from src.pipeline.text_preprocessing.types import NoiseReport
from src.pipeline.text_preprocessing.api import PREPROCESSING_VERSION


def _fixture():
    artifact = artifact_from_text(
        "第一段证据。\n\n第二段证据。",
        source_id="raw/sources/replay.md",
        format="md",
        extraction_method="native_text",
    )
    assessment = assess_artifact(artifact)
    report = NoiseReport(
        version=PREPROCESSING_VERSION,
        source_bytes_sha256=artifact.source_bytes_sha256,
        input_text_sha256=artifact.input_text_sha256,
        canonical_text_sha256=sha256(artifact.input_text.encode()).hexdigest(),
        prompt_text_sha256=sha256(artifact.input_text.encode()).hexdigest(),
        quality_score=1.0,
        warnings=(),
        should_skip_llm=False,
        metrics_scope="full_input_text",
        source_chars=len(artifact.input_text),
        canonical_chars=len(artifact.input_text),
        prompt_chars=len(artifact.input_text),
        removed_line_count=0,
        removed_char_count=0,
        applied_rules=(),
    )
    block = __import__("src.kc.compiler.normalize", fromlist=["normalize_text"]).normalize_text(
        artifact.input_text, source=artifact.source_id
    ).blocks[0]
    return artifact, assessment, report, block


def test_replay_accepts_exact_source_block_quote_and_hash() -> None:
    artifact, assessment, report, block = _fixture()
    quote_hash = sha256("第一段证据。".encode()).hexdigest()
    record = serialize_audit(assessment, report, analyzer_called=True, failure_reason=None)
    record["evidence"] = [{
        "source_id": artifact.source_id,
        "block_id": block.block_id,
        "quote": "第一段证据。",
        "quote_hash": quote_hash,
    }]

    result = replay_evidence(record, artifact)

    assert result.accepted is True
    assert result.failure_reason is None


def test_replay_rejects_source_or_block_mismatch_without_relocation() -> None:
    artifact, assessment, report, block = _fixture()
    record = serialize_audit(assessment, report, analyzer_called=True, failure_reason=None)
    record["evidence"] = [{
        "source_id": "raw/sources/other.md",
        "block_id": block.block_id,
        "quote": "第一段证据。",
        "quote_hash": sha256("第一段证据。".encode()).hexdigest(),
    }]

    result = replay_evidence(record, artifact)

    assert result.accepted is False
    assert result.failure_reason == "source_id_mismatch"


def test_replay_rejects_modified_quote_and_hash() -> None:
    artifact, assessment, report, block = _fixture()
    record = serialize_audit(assessment, report, analyzer_called=True, failure_reason=None)
    record["evidence"] = [{
        "source_id": artifact.source_id,
        "block_id": block.block_id,
        "quote": "改写后的证据。",
        "quote_hash": sha256("改写后的证据。".encode()).hexdigest(),
    }]

    result = replay_evidence(record, artifact)

    assert result.accepted is False
    assert result.failure_reason == "quote_not_in_declared_block"


def test_audit_schema_uses_decision_and_recomputable_hash_fields() -> None:
    artifact, assessment, report, _ = _fixture()
    record = serialize_audit(
        assessment,
        report,
        analyzer_called=False,
        failure_reason="skip_no_content",
    )

    assert record["decision"] == assessment.decision.value
    assert "readiness_decision" not in record
    assert record["source_id"] == artifact.source_id
    assert record["input_text_sha256"] == artifact.input_text_sha256
    assert record["evidence"] == []
