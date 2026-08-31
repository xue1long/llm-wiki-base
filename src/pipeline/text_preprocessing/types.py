"""Data contracts for text preprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.kc.compiler.normalize import CanonicalDocument
from src.pipeline.extraction_types import ExtractionArtifact


class ContentKind(StrEnum):
    PROSE = "prose"
    TITLE_DEFINITION = "title_definition"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    IMAGE_OCR = "image_ocr"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class ReadinessDecision(StrEnum):
    READY = "ready"
    READY_WITH_WARNING = "ready_with_warning"
    ROUTE_SPECIALIST = "route_specialist"
    SKIP_NO_CONTENT = "skip_no_content"
    QUARANTINE_DEGRADED = "quarantine_degraded"
    UNSUPPORTED = "unsupported"


class PipelineDisposition(StrEnum):
    CONTINUE = "continue"
    SPECIALIST = "specialist"
    AUDIT_ONLY = "audit_only"


@dataclass(frozen=True)
class EvidenceCapacity:
    blocks: int
    chars: int
    units: int
    min_span_chars: int = 0
    max_span_chars: int = 0


@dataclass(frozen=True)
class ContentProfile:
    profile_id: str
    minimum_chars: int
    short_minimum_chars: int
    short_requires_structure: bool
    format: str = "md"
    extraction_method: str = "native_text"
    content_kind: ContentKind = ContentKind.PROSE
    minimum_units: int = 1
    metadata_dominance_ratio: float = 0.65
    repetition_warning_ratio: float = 0.3

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id is required")
        if not self.format or not self.extraction_method:
            raise ValueError("format and extraction_method are required")
        try:
            kind = ContentKind(self.content_kind)
        except ValueError as exc:
            raise ValueError("content_kind is unknown") from exc
        object.__setattr__(self, "content_kind", kind)
        if self.minimum_units < 0 or self.minimum_chars < 0 or self.short_minimum_chars < 0:
            raise ValueError("thresholds must be non-negative")
        if self.short_minimum_chars > self.minimum_chars:
            raise ValueError("short_minimum_chars cannot exceed minimum_chars")
        if not 0 <= self.metadata_dominance_ratio <= 1:
            raise ValueError("ratio must be between 0 and 1")
        if not 0 <= self.repetition_warning_ratio <= 1:
            raise ValueError("ratio must be between 0 and 1")


@dataclass(frozen=True)
class ReadinessPolicy:
    policy_version: str
    profiles: tuple[ContentProfile, ...]

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("policy_version is required")
        keys: set[tuple[str, str, ContentKind]] = set()
        for profile in self.profiles:
            key = (profile.format, profile.extraction_method, profile.content_kind)
            if key in keys:
                raise ValueError(f"duplicate profile key: {key}")
            keys.add(key)


@dataclass(frozen=True)
class ContentAssessment:
    assessment_version: str
    policy_version: str
    profile_id: str
    content_kind: ContentKind
    decision: ReadinessDecision
    reason_codes: tuple[str, ...]
    evidence_capacity: EvidenceCapacity
    nonempty_lines: int
    metadata_lines: int
    metadata_ratio: float
    replacement_ratio: float
    source_id: str = ""
    format: str = "md"
    extraction_method: str = "native_text"
    analyzer_called: bool = False
    provenance_complete: bool = True
    nonempty_units: int = 0
    repetition_ratio: float = 0.0
    failure_reason: str | None = None


@dataclass(frozen=True)
class ReadinessResult:
    artifact: ExtractionArtifact
    assessment: ContentAssessment
    route: str | None


@dataclass(frozen=True)
class ReplayResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    failure_reason: str | None


@dataclass(frozen=True)
class RuleApplication:
    rule_id: str
    removed_line_count: int
    removed_char_count: int


@dataclass(frozen=True)
class PromptBlockView:
    source_id: str
    block_id: str
    ordinal: int
    prompt_content: str
    removed_line_count: int


@dataclass(frozen=True)
class NoiseReport:
    version: str
    source_bytes_sha256: str | None
    input_text_sha256: str
    canonical_text_sha256: str
    prompt_text_sha256: str
    quality_score: float
    warnings: tuple[str, ...]
    should_skip_llm: bool
    metrics_scope: str
    source_chars: int
    canonical_chars: int
    prompt_chars: int
    removed_line_count: int
    removed_char_count: int
    applied_rules: tuple[RuleApplication, ...]


@dataclass(frozen=True)
class PreprocessResult:
    canonical_text: str
    canonical_document: CanonicalDocument
    prompt_text: str
    prompt_blocks: tuple[PromptBlockView, ...]
    report: NoiseReport
    content_assessment: ContentAssessment
    artifact: ExtractionArtifact | None = None
