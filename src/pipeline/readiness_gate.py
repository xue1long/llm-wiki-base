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
from .specialists import run_specialist


_KNOWLEDGE_TYPE_TO_PAGE_TYPE = {
    "document": "source",
    "claim": "concept",
    "decision": "concept",
    "procedure": "concept",
    "event": "concept",
}


def apply_readiness_gate(artifact: ExtractionArtifact) -> ReadinessResult:
    assessment = assess_artifact(artifact)
    route = "ocr" if assessment.decision is ReadinessDecision.ROUTE_SPECIALIST and artifact.extraction_method == "ocr" else None
    return ReadinessResult(artifact=artifact, assessment=assessment, route=route)


async def resolve_specialist(result: ReadinessResult) -> ReadinessResult:
    """Run the named specialist once, then reassess its returned artifact."""
    if result.route is None:
        return result

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


def validate_page_contract(contract, page) -> list[str]:
    """Validate final page identity against the immutable template contract."""
    page_type = page.custom_type or page.type.value
    if page_type not in contract.allowed_types:
        raise ValueError(f"Wiki type {page_type!r} is not allowed by template")
    if page_type not in contract.routes:
        raise ValueError(f"Wiki type {page_type!r} has no template route")
    if not page.body.strip():
        raise ValueError(f"Wiki page {page.id!r} has an empty body")
    return []


def validate_candidate_contract(contract, candidate) -> list[str]:
    """Reject a candidate type that cannot be rendered by the pinned contract."""
    type_name = getattr(candidate, "custom_type", "") or getattr(candidate, "type", "")
    type_name = getattr(type_name, "value", type_name)
    type_name = _KNOWLEDGE_TYPE_TO_PAGE_TYPE.get(type_name, type_name)
    if type_name not in contract.allowed_types:
        raise ValueError(f"Knowledge type {type_name!r} is not allowed by template")
    if type_name not in contract.routes:
        raise ValueError(f"Knowledge type {type_name!r} has no template route")
    return []


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
