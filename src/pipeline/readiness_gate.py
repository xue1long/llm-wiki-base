"""Shared pre-Analyzer readiness gate."""

from __future__ import annotations

from dataclasses import replace

from src.pipeline.extraction_types import ExtractionArtifact
from src.pipeline.text_preprocessing import assess_artifact
from src.pipeline.text_preprocessing.types import (
    PipelineDisposition,
    ReadinessDecision,
    ReadinessResult,
)


def apply_readiness_gate(artifact: ExtractionArtifact) -> ReadinessResult:
    assessment = assess_artifact(artifact)
    route = "ocr" if assessment.decision is ReadinessDecision.ROUTE_SPECIALIST and artifact.extraction_method == "ocr" else None
    return ReadinessResult(artifact=artifact, assessment=assessment, route=route)


async def resolve_specialist(result: ReadinessResult) -> ReadinessResult:
    """Run the named specialist once, then reassess its returned artifact."""
    if result.route is None:
        return result
    from .specialists import run_specialist

    try:
        artifact = await run_specialist(result.route, result.artifact)
    except Exception as exc:
        reason_codes = tuple(dict.fromkeys((*result.assessment.reason_codes, "specialist_failed")))
        assessment = replace(
            result.assessment,
            decision=ReadinessDecision.QUARANTINE_DEGRADED,
            reason_codes=reason_codes,
            failure_reason=str(exc),
        )
        return ReadinessResult(artifact=result.artifact, assessment=assessment, route=None)
    return apply_readiness_gate(artifact)


async def route_after_readiness(
    result: ReadinessResult,
    *,
    provider: object,
    paths,
    task_id: str,
) -> PipelineDisposition:
    del provider, paths, task_id
    if result.assessment.decision in {ReadinessDecision.READY, ReadinessDecision.READY_WITH_WARNING}:
        return PipelineDisposition.CONTINUE
    if result.assessment.decision is ReadinessDecision.ROUTE_SPECIALIST:
        return PipelineDisposition.SPECIALIST
    return PipelineDisposition.AUDIT_ONLY
