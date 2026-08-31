"""Data contracts for text preprocessing."""

from __future__ import annotations

from dataclasses import dataclass

from src.kc.compiler.normalize import CanonicalDocument


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
