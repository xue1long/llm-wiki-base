"""Deterministic content readiness assessment before LLM analysis."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from src.pipeline.extraction_types import ExtractionArtifact, SourceRange, artifact_from_text

from .._pipeline_common import _CHROME_LINES, _FEISHU_H1_RE, _META_LINE_RES
from .policy import load_policy, select_profile
from .types import ContentAssessment, ContentKind, EvidenceCapacity, ReadinessDecision

ASSESSMENT_VERSION = "content-readiness-v1"
POLICY_VERSION = "content-policy-v1"
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_CATEGORY = re.compile(r"^\d+[_-].*")
_COMPANY = re.compile(r".*(?:公司|有限公司)$")
_SOCIAL = {"真诚点赞，手留余香", "评论(0)", "评论（0）"}
_LIST = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_PAGE_MARKER = re.compile(r"^<!-- page: \d+ -->$")
_SENTENCE_MARKS = set("。！？!?；;：:，,、.=()（）[]{}")


def _compact(value: str) -> str:
    return "".join(ch for ch in _ZERO_WIDTH.sub("", value) if ch.isalnum())


def _metadata_line(line: str, source_id: str) -> bool:
    stripped = line.strip()
    clean = _ZERO_WIDTH.sub("", stripped)
    if not clean or clean in _CHROME_LINES or clean in _SOCIAL:
        return True
    if any(pattern.match(clean) for pattern in _META_LINE_RES) or _FEISHU_H1_RE.match(clean):
        return True
    if _CATEGORY.match(clean) or _COMPANY.match(clean):
        return True
    source_stem = Path(source_id).stem
    return bool(source_stem and _compact(clean) == _compact(source_stem))


def _infer_kind(text: str, format: str, extraction_method: str) -> ContentKind:
    if format == "xlsx" or any("\t" in line for line in text.splitlines() if line.strip()):
        return ContentKind.TABLE
    if format == "image" or extraction_method == "ocr":
        return ContentKind.IMAGE_OCR
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.startswith("```") for line in lines) or (lines and all(line.startswith("    ") for line in text.splitlines() if line.strip())):
        return ContentKind.CODE
    if lines and all(_LIST.match(line) for line in lines):
        return ContentKind.LIST
    if len(lines) <= 2 and any(mark in text for mark in (":", "：", "=")):
        return ContentKind.TITLE_DEFINITION
    return ContentKind.PROSE


def _units(text: str, format: str) -> list[str]:
    if format == "pdf":
        return [line for line in text.splitlines() if line.strip() and not _PAGE_MARKER.match(line.strip())]
    return [line for line in text.splitlines() if line.strip()]


def _capacity(values: list[str]) -> EvidenceCapacity:
    lengths = [len(value) for value in values if value]
    return EvidenceCapacity(
        blocks=1 if lengths else 0,
        chars=sum(lengths),
        units=len(lengths),
        min_span_chars=min(lengths, default=0),
        max_span_chars=max(lengths, default=0),
    )


def _assessment_for_artifact(
    artifact: ExtractionArtifact,
    *,
    policy_version: str,
    forced_kind: ContentKind | None = None,
) -> ContentAssessment:
    policy = load_policy(policy_version)
    kind = forced_kind or _infer_kind(artifact.input_text, artifact.format, artifact.extraction_method)
    profile = select_profile(
        policy,
        format=artifact.format,
        extraction_method=artifact.extraction_method,
        content_kind=kind,
    )
    units = _units(artifact.input_text, artifact.format)
    metadata_flags = [_metadata_line(unit, artifact.source_id) for unit in units]
    metadata = [unit for unit, is_metadata in zip(units, metadata_flags) if is_metadata]
    content = [unit for unit, is_metadata in zip(units, metadata_flags) if not is_metadata]
    nonempty_chars = sum(len(unit) for unit in units)
    metadata_ratio = sum(len(unit) for unit in metadata) / max(nonempty_chars, 1)
    normalized = [_ZERO_WIDTH.sub("", unit).strip() for unit in content]
    counts = Counter(normalized)
    repetition_ratio = sum(count for count in counts.values() if count > 1) / max(len(normalized), 1)
    replacement_ratio = artifact.input_text.count("�") / max(len(artifact.input_text), 1)
    provenance_complete = not units or len(artifact.ranges) >= len(units)
    reasons: list[str] = []

    if artifact.extraction_method == "unsupported" or profile is None:
        reasons.append("unsupported_format")
        decision = ReadinessDecision.UNSUPPORTED
        evidence_values: list[str] = []
    elif replacement_ratio > 0.30 or any("encoding" in error.lower() for error in artifact.extraction_errors):
        reasons.append("ocr_degraded" if artifact.extraction_method == "ocr" else "encoding_degraded")
        decision = ReadinessDecision.QUARANTINE_DEGRADED
        evidence_values = []
    elif artifact.extraction_method == "ocr" and artifact.extraction_errors:
        reasons.append("ocr_degraded")
        decision = (
            ReadinessDecision.ROUTE_SPECIALIST
            if any("unavailable" in error.lower() for error in artifact.extraction_errors)
            else ReadinessDecision.QUARANTINE_DEGRADED
        )
        evidence_values = []
    elif units and not provenance_complete:
        reasons.append("missing_provenance")
        decision = ReadinessDecision.QUARANTINE_DEGRADED
        evidence_values = []
    elif not units:
        reasons.extend(("empty_input", "no_evidence_capacity"))
        decision = ReadinessDecision.SKIP_NO_CONTENT
        evidence_values = []
    else:
        evidence_values = content if kind in {ContentKind.PROSE, ContentKind.TITLE_DEFINITION} else units
        if not evidence_values:
            reasons.extend(("metadata_only", "no_evidence_capacity"))
            compact_chrome = {_compact(item) for item in _CHROME_LINES}
            if any(_compact(value) in compact_chrome for value in metadata):
                reasons.append("duplicated_navigation")
            decision = ReadinessDecision.SKIP_NO_CONTENT
        elif metadata_ratio >= profile.metadata_dominance_ratio and (
            repetition_ratio > 0
            or (len(metadata) >= 2 and sum(len(value) for value in content) < profile.minimum_chars)
        ):
            reasons.extend(("metadata_only", "no_evidence_capacity"))
            compact_chrome = {_compact(item) for item in _CHROME_LINES}
            if any(_compact(value) in compact_chrome for value in metadata):
                reasons.append("duplicated_navigation")
            decision = ReadinessDecision.SKIP_NO_CONTENT
            evidence_values = []
        else:
            chars = sum(len(value) for value in evidence_values)
            eligible_short = (
                chars >= profile.short_minimum_chars
                and (
                    not profile.short_requires_structure
                    or any(mark in artifact.input_text for mark in _SENTENCE_MARKS)
                    or not metadata
                )
            )
            enough = len(evidence_values) >= profile.minimum_units and chars >= profile.minimum_chars
            if enough:
                decision = ReadinessDecision.READY
            elif eligible_short:
                reasons.append("legitimate_short")
                decision = ReadinessDecision.READY_WITH_WARNING
            else:
                reasons.append("no_evidence_capacity")
                decision = ReadinessDecision.SKIP_NO_CONTENT
                evidence_values = []

            if repetition_ratio >= profile.repetition_warning_ratio and kind in {ContentKind.PROSE, ContentKind.TITLE_DEFINITION}:
                reasons.append("high_repetition")
                if decision is ReadinessDecision.READY:
                    decision = ReadinessDecision.READY_WITH_WARNING

    return ContentAssessment(
        assessment_version=ASSESSMENT_VERSION,
        policy_version=policy_version,
        profile_id=profile.profile_id if profile else "unknown",
        content_kind=kind,
        decision=decision,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_capacity=_capacity(evidence_values),
        nonempty_lines=len(units),
        metadata_lines=len(metadata),
        metadata_ratio=round(metadata_ratio, 4),
        replacement_ratio=round(replacement_ratio, 4),
        source_id=artifact.source_id,
        format=artifact.format,
        extraction_method=artifact.extraction_method,
        provenance_complete=provenance_complete,
        nonempty_units=len(units),
        repetition_ratio=round(repetition_ratio, 4),
        failure_reason=(reasons[0] if decision in {ReadinessDecision.QUARANTINE_DEGRADED, ReadinessDecision.UNSUPPORTED} else None),
    )


def assess_blocks(
    artifact: ExtractionArtifact, *, policy_version: str = POLICY_VERSION
) -> tuple[ContentAssessment, ...]:
    parts = [part for part in artifact.input_text.split("\n\n") if part.strip()]
    if not parts:
        return (_assessment_for_artifact(artifact, policy_version=policy_version),)
    result: list[ContentAssessment] = []
    line_offset = 0
    for index, part in enumerate(parts):
        if len(parts) == 1:
            source_range = artifact.ranges
        elif artifact.ranges and artifact.ranges[0].unit == "line":
            line_count = sum(bool(line.strip()) for line in part.splitlines())
            source_range = artifact.ranges[line_offset:line_offset + line_count]
            line_offset += line_count
        else:
            source_range = (artifact.ranges[index],) if index < len(artifact.ranges) else ()
        subartifact = artifact_from_text(
            part,
            source_id=artifact.source_id,
            format=artifact.format,
            extraction_method=artifact.extraction_method,
            source_bytes_sha256=artifact.source_bytes_sha256,
            ranges=source_range,
            extraction_errors=artifact.extraction_errors,
        )
        result.append(_assessment_for_artifact(subartifact, policy_version=policy_version))
    return tuple(result)


def assess_artifact(
    artifact: ExtractionArtifact, *, policy_version: str = POLICY_VERSION
) -> ContentAssessment:
    blocks = assess_blocks(artifact, policy_version=policy_version)
    if len(blocks) == 1:
        return blocks[0]
    kinds = {block.content_kind for block in blocks}
    has_mixed_states = any(block.decision is ReadinessDecision.SKIP_NO_CONTENT for block in blocks) and any(
        block.evidence_capacity.chars for block in blocks
    )
    decision_order = {
        ReadinessDecision.QUARANTINE_DEGRADED: 0,
        ReadinessDecision.UNSUPPORTED: 1,
        ReadinessDecision.ROUTE_SPECIALIST: 2,
        ReadinessDecision.READY: 3,
        ReadinessDecision.READY_WITH_WARNING: 3,
        ReadinessDecision.SKIP_NO_CONTENT: 4,
    }
    decision = min(blocks, key=lambda block: decision_order[block.decision]).decision
    if all(block.decision is ReadinessDecision.SKIP_NO_CONTENT for block in blocks):
        decision = ReadinessDecision.SKIP_NO_CONTENT
    reasons = list(dict.fromkeys(reason for block in blocks for reason in block.reason_codes))
    if any(block.decision is ReadinessDecision.SKIP_NO_CONTENT for block in blocks) and any(
        block.evidence_capacity.chars for block in blocks
    ):
        reasons.append("empty_subblock")
        if decision is ReadinessDecision.READY:
            decision = ReadinessDecision.READY_WITH_WARNING
    capacity_values = [block.evidence_capacity for block in blocks if block.evidence_capacity.chars]
    capacity = EvidenceCapacity(
        blocks=len(capacity_values),
        chars=sum(item.chars for item in capacity_values),
        units=sum(item.units for item in capacity_values),
        min_span_chars=min((item.min_span_chars for item in capacity_values), default=0),
        max_span_chars=max((item.max_span_chars for item in capacity_values), default=0),
    )
    first = blocks[0]
    return ContentAssessment(
        assessment_version=ASSESSMENT_VERSION,
        policy_version=policy_version,
        profile_id="mixed" if len(kinds) > 1 or has_mixed_states else first.profile_id,
        content_kind=ContentKind.MIXED if len(kinds) > 1 or has_mixed_states else first.content_kind,
        decision=decision,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evidence_capacity=capacity,
        nonempty_lines=sum(block.nonempty_lines for block in blocks),
        metadata_lines=sum(block.metadata_lines for block in blocks),
        metadata_ratio=round(sum(block.metadata_ratio for block in blocks) / len(blocks), 4),
        replacement_ratio=max(block.replacement_ratio for block in blocks),
        source_id=artifact.source_id,
        format=artifact.format,
        extraction_method=artifact.extraction_method,
        provenance_complete=all(block.provenance_complete for block in blocks if block.evidence_capacity.chars),
        nonempty_units=sum(block.nonempty_units for block in blocks),
        repetition_ratio=max(block.repetition_ratio for block in blocks),
        failure_reason=next((block.failure_reason for block in blocks if block.failure_reason), None),
    )


def assess_content(
    prompt_text: str,
    *,
    source_id: str,
    content_kind: ContentKind | str = ContentKind.PROSE,
    block_count: int = 1,
) -> ContentAssessment:
    """Compatibility wrapper for callers that only have text."""
    if not isinstance(prompt_text, str):
        raise TypeError("prompt_text must be a string")
    if block_count < 0:
        raise ValueError("block_count must be non-negative")
    try:
        kind = ContentKind(content_kind)
    except ValueError:
        kind = ContentKind.UNKNOWN
    artifact = artifact_from_text(
        prompt_text,
        source_id=source_id,
        format="md",
        extraction_method="native_text",
    )
    result = _assessment_for_artifact(artifact, policy_version=POLICY_VERSION, forced_kind=kind)
    result = ContentAssessment(
        **{**result.__dict__, "profile_id": kind.value},
    )
    if block_count != result.evidence_capacity.blocks and result.evidence_capacity.chars:
        return ContentAssessment(
            **{
                **result.__dict__,
                "evidence_capacity": EvidenceCapacity(
                    blocks=block_count,
                    chars=result.evidence_capacity.chars,
                    units=result.evidence_capacity.units,
                    min_span_chars=result.evidence_capacity.min_span_chars,
                    max_span_chars=result.evidence_capacity.max_span_chars,
                ),
            }
        )
    return result
