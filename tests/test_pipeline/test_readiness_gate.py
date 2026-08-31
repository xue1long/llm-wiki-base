"""The readiness gate is shared and fail-closed before Analyzer."""

from __future__ import annotations

import pytest

from src.pipeline.extraction_types import SourceRange, artifact_from_text
from src.events.events import CollectorDonePayload
from src.pipeline.ports import PipelineContext
from src.pipeline.stages.analyzer import AnalyzerStage
from src.types import SourceType
from src.pipeline.readiness_gate import (
    apply_readiness_gate,
    resolve_specialist,
    route_after_readiness,
)
from src.pipeline.text_preprocessing import PipelineDisposition, ReadinessDecision
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


class ProviderMustNotBeCalled:
    def __getattr__(self, name):
        raise AssertionError(f"provider called for blocking readiness: {name}")


def test_gate_blocks_no_content_and_returns_audit_only() -> None:
    result = apply_readiness_gate(
        artifact_from_text(
            "登录/注册\n登录/注册",
            source_id="raw/sources/navigation.md",
            format="md",
            extraction_method="native_text",
        )
    )

    assert result.assessment.decision is ReadinessDecision.SKIP_NO_CONTENT
    assert result.route is None


@pytest.mark.asyncio
async def test_blocking_dispositions_never_require_a_provider() -> None:
    result = apply_readiness_gate(
        artifact_from_text(
            "�" * 20,
            source_id="raw/sources/degraded.md",
            format="md",
            extraction_method="native_text",
        )
    )

    assert await route_after_readiness(
        result,
        provider=ProviderMustNotBeCalled(),
        paths=None,
        task_id="gate-test",
    ) is PipelineDisposition.AUDIT_ONLY


@pytest.mark.asyncio
async def test_unavailable_ocr_is_routed_to_one_specialist_attempt() -> None:
    result = apply_readiness_gate(
        artifact_from_text(
            "",
            source_id="raw/sources/scan.png",
            format="image",
            extraction_method="ocr",
            extraction_errors=("OCR extractor unavailable",),
        )
    )

    assert result.assessment.decision is ReadinessDecision.ROUTE_SPECIALIST
    assert result.route == "ocr"
    assert await route_after_readiness(
        result, provider=ProviderMustNotBeCalled(), paths=None, task_id="ocr-route"
    ) is PipelineDisposition.SPECIALIST


@pytest.mark.asyncio
async def test_failed_specialist_becomes_quarantine_terminal_state() -> None:
    result = apply_readiness_gate(
        artifact_from_text(
            "",
            source_id="raw/sources/scan-failed.png",
            format="image",
            extraction_method="ocr",
            extraction_errors=("OCR extractor unavailable",),
        )
    )

    resolved = await resolve_specialist(result)

    assert resolved.route is None
    assert resolved.assessment.decision is ReadinessDecision.QUARANTINE_DEGRADED
    assert resolved.assessment.reason_codes == ("ocr_degraded", "specialist_failed")
    assert resolved.assessment.failure_reason.startswith("specialist_failed:")


@pytest.mark.asyncio
async def test_successful_specialist_is_reassessed_before_continuation() -> None:
    result = apply_readiness_gate(
        artifact_from_text(
            "识别结果",
            source_id="raw/sources/scan-success.png",
            format="image",
            extraction_method="ocr",
            ranges=(SourceRange("image_region", 0, 4, 0),),
        )
    )

    resolved = await resolve_specialist(result)

    assert resolved.artifact is result.artifact
    assert resolved.assessment.decision is ReadinessDecision.READY_WITH_WARNING
    assert resolved.assessment.reason_codes == ("legitimate_short",)


@pytest.mark.asyncio
async def test_generate_ingest_blocking_gate_returns_no_source_page(tmp_path) -> None:
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    source = paths.raw_sources / "navigation.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    text = "登录/注册\n登录/注册\n05_题材专题"
    source.write_text(text, encoding="utf-8")

    from src.pipeline.ingest import generate_ingest

    pages, extras, meta = await generate_ingest(
        paths=paths,
        source_path=source,
        source_text=text,
        provider=ProviderMustNotBeCalled(),
        task_id="gate-source-page-test",
    )

    assert pages == []
    assert extras == []
    assert meta["source_page_id"] is None
    assert meta["content_assessment"]["decision"] == "skip_no_content"


@pytest.mark.asyncio
async def test_analyzer_stage_blocks_collector_artifact_before_provider() -> None:
    text = "登录/注册\n登录/注册"
    ctx = PipelineContext(
        task_id="stage-gate-test",
        source="raw/sources/navigation.md",
        source_type=SourceType.FILE,
        collector_result=CollectorDonePayload(
            task_id="stage-gate-test",
            raw_path="raw/sources/navigation.md",
            content=text,
            artifact=artifact_from_text(
                text,
                source_id="raw/sources/navigation.md",
                format="md",
                extraction_method="native_text",
            ),
        ),
        provider=ProviderMustNotBeCalled(),
    )

    result = await AnalyzerStage().run(ctx, None)

    assert result.success is False
    assert result.payload.assessment.decision is ReadinessDecision.SKIP_NO_CONTENT
