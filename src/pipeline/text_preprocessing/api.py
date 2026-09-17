"""Deterministic, evidence-preserving source preprocessing."""

from __future__ import annotations

import re
from collections import Counter
from hashlib import sha256

from src.kc.compiler.normalize import normalize_text
from src.pipeline.extraction_types import artifact_from_text

from .._pipeline_common import (
    _CHROME_LINES,
    _FEISHU_H1_RE,
    _META_LINE_RES,
)
from .types import NoiseReport, PreprocessResult, PromptBlockView, RuleApplication
from .readiness import assess_artifact

PREPROCESSING_VERSION = "text-preprocess-v1"
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def chunk_prompt_blocks(
    blocks: tuple[PromptBlockView, ...], *, max_chars: int
) -> tuple[tuple[PromptBlockView, ...], ...]:
    """Pack whole prompt blocks without merging or truncating their content.

    V7 personal-KB mode: when a single block is bigger than ``max_chars``
    (e.g. a tutorial document with one giant paragraph), split it on
    sentence/line boundaries and yield sub-block views instead of raising.
    This is the same soft-fail posture as the KC review soft-fail — LLM
    extraction rarely produces verbatim quotes for these long prose blocks,
    so losing the literal block_id boundary is acceptable; we keep the
    ordinal prefix so downstream `supported_by` relations still work.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    chunks: list[tuple[PromptBlockView, ...]] = []
    current: list[PromptBlockView] = []
    current_chars = 0

    def _flush() -> None:
        nonlocal current, current_chars
        if current:
            chunks.append(tuple(current))
        current = []
        current_chars = 0

    for block in blocks:
        content = block.prompt_content
        block_chars = len(content)

        if block_chars <= max_chars:
            # Normal path: pack whole block.
            separator = 2 if current else 0
            if current and current_chars + separator + block_chars > max_chars:
                _flush()
                separator = 0
            current.append(block)
            current_chars += separator + block_chars
            continue

        # Oversized single block — flush current accumulator first, then
        # split this block into sub-block views. Splitting prefers sentence
        # boundaries ("。" "！" "？" ".\n" etc.) and falls back to hard line
        # splits if no boundary fits within max_chars.
        _flush()
        sub_views = _split_oversized_block(block, max_chars)
        if not sub_views:
            # Last resort: keep as a single chunk even though it overflows.
            chunks.append((block,))
            continue
        sub_chunk: list[PromptBlockView] = []
        sub_chars = 0
        for sv in sub_views:
            sv_chars = len(sv.prompt_content)
            sep = 2 if sub_chunk else 0
            if sub_chunk and sub_chars + sep + sv_chars > max_chars:
                chunks.append(tuple(sub_chunk))
                sub_chunk = []
                sub_chars = 0
                sep = 0
            sub_chunk.append(sv)
            sub_chars += sep + sv_chars
        if sub_chunk:
            chunks.append(tuple(sub_chunk))

    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _split_oversized_block(
    block: PromptBlockView, max_chars: int
) -> list[PromptBlockView]:
    """Split one oversized block into sub-block views on sentence/line boundaries.

    Each sub-view inherits the parent block's source_id and shares a
    derived block_id (`<parent.block_id>#sub-<n>`) so any downstream
    reference still points back to the original block.
    """
    content = block.prompt_content
    # Prefer Chinese sentence boundaries, then ASCII sentence boundaries,
    # then paragraph boundaries, then hard line splits.
    boundary_re = re.compile(r"(?<=[。！？!?\n])\s*")
    pieces = [p for p in boundary_re.split(content) if p]

    # If splitting produced pieces still larger than max_chars (e.g. a
    # single 30k-char run-on sentence), hard-split on lines instead.
    refined: list[str] = []
    for p in pieces:
        if len(p) <= max_chars:
            refined.append(p)
            continue
        # Hard split on newlines first.
        for line in p.split("\n"):
            if not line:
                continue
            if len(line) <= max_chars:
                refined.append(line)
            else:
                # Last resort: chunk into max_chars-sized slices.
                for i in range(0, len(line), max_chars):
                    refined.append(line[i:i + max_chars])

    if not refined:
        return []
    return [
        PromptBlockView(
            source_id=block.source_id,
            block_id=f"{block.block_id}#sub-{idx}",
            ordinal=block.ordinal,
            prompt_content=piece,
            removed_line_count=0,
        )
        for idx, piece in enumerate(refined)
        if piece
    ]


def _sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _quality(text: str) -> tuple[float, tuple[str, ...], bool]:
    lines = text.splitlines()
    total = len(text)
    replacement_ratio = text.count("�") / max(total, 1)
    blank_ratio = sum(not line.strip() for line in lines) / max(len(lines), 1)
    counts = Counter(lines)
    repeated_lines = sum(count for count in counts.values() if count > 5)
    repeat_ratio = repeated_lines / max(len(lines), 1)

    score = 1.0
    if replacement_ratio > 0.01:
        score -= 0.4
    if replacement_ratio > 0.05:
        score -= 0.3
    if blank_ratio > 0.6:
        score -= 0.3
    if blank_ratio > 0.85:
        score -= 0.3
    if repeat_ratio > 0.3:
        score -= 0.3
    if repeat_ratio > 0.6:
        score -= 0.3
    score = max(score, 0.0)

    warnings: list[str] = []
    if replacement_ratio > 0.01:
        warnings.append("has_replacement_chars")
    if replacement_ratio > 0.05:
        warnings.append("garbled")
    if blank_ratio > 0.6:
        warnings.append("mostly_blank")
    if repeat_ratio > 0.3:
        warnings.append("high_repetition")
    if score < 0.3:
        warnings.append("low_quality")

    degraded = (
        len(text.strip()) < 5
        or replacement_ratio > 0.3
        or (len(text.strip()) < 20 and blank_ratio > 0.9)
    )
    return score, tuple(warnings), degraded


def _prompt_view(content: str) -> tuple[str, tuple[RuleApplication, ...]]:
    lines = content.splitlines()
    applications: dict[str, list[int]] = {}

    if _FRONTMATTER_RE.match(content):
        frontmatter = _FRONTMATTER_RE.match(content)
        assert frontmatter is not None
        removed = frontmatter.group(0)
        lines = content[len(removed):].splitlines()
        applications["frontmatter"] = [len(removed.splitlines()), len(removed)]

    kept: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        rule_id = ""
        if stripped in _CHROME_LINES:
            rule_id = "platform_chrome"
        elif any(pattern.match(stripped) for pattern in _META_LINE_RES):
            rule_id = "source_metadata"
        elif _FEISHU_H1_RE.match(stripped):
            rule_id = "feishu_h1_artifact"
        if rule_id:
            counts = applications.setdefault(rule_id, [0, 0])
            counts[0] += 1
            counts[1] += len(line) + 1
            continue
        kept.append(line)

    prompt = "\n".join(kept).strip()
    applications_tuple = tuple(
        RuleApplication(rule_id, counts[0], counts[1])
        for rule_id, counts in applications.items()
    )
    return prompt, applications_tuple


def preprocess_source(
    source_text: str,
    *,
    source_id: str = "",
    source_bytes_sha256: str | None = None,
    skip_llm_on_degraded: bool = False,
    format: str = "md",
    extraction_method: str = "native_text",
) -> PreprocessResult:
    """Build one canonical document and a deterministic prompt view."""
    if not isinstance(source_text, str):
        raise TypeError("source_text must be a string")
    if not source_id:
        raise ValueError("source_id is required")

    quality_score, warnings, degraded = _quality(source_text)
    document = normalize_text(source_text, source=source_id)
    canonical_text = document.content

    prompt_blocks: list[PromptBlockView] = []
    applications: dict[str, list[int]] = {}
    for block in document.blocks:
        prompt_content, block_rules = _prompt_view(block.content)
        for rule in block_rules:
            counts = applications.setdefault(rule.rule_id, [0, 0])
            counts[0] += rule.removed_line_count
            counts[1] += rule.removed_char_count
        if prompt_content:
            prompt_blocks.append(
                PromptBlockView(
                    source_id=source_id,
                    block_id=block.block_id,
                    ordinal=block.ordinal,
                    prompt_content=prompt_content,
                    removed_line_count=sum(
                        rule.removed_line_count for rule in block_rules
                    ),
                )
            )

    prompt_text = "\n\n".join(block.prompt_content for block in prompt_blocks)
    artifact = artifact_from_text(
        source_text,
        source_id=source_id,
        format=format,
        extraction_method=extraction_method,
        source_bytes_sha256=source_bytes_sha256,
    )
    content_assessment = assess_artifact(artifact)
    applied_rules = tuple(
        RuleApplication(rule_id, counts[0], counts[1])
        for rule_id, counts in applications.items()
    )
    removed_line_count = sum(rule.removed_line_count for rule in applied_rules)
    removed_char_count = sum(rule.removed_char_count for rule in applied_rules)
    report = NoiseReport(
        version=PREPROCESSING_VERSION,
        source_bytes_sha256=source_bytes_sha256,
        input_text_sha256=_sha256(source_text),
        canonical_text_sha256=_sha256(canonical_text),
        prompt_text_sha256=_sha256(prompt_text),
        quality_score=quality_score,
        warnings=warnings,
        should_skip_llm=bool(skip_llm_on_degraded and degraded),
        metrics_scope="full_input_text",
        source_chars=len(source_text),
        canonical_chars=len(canonical_text),
        prompt_chars=len(prompt_text),
        removed_line_count=removed_line_count,
        removed_char_count=removed_char_count,
        applied_rules=applied_rules,
    )
    return PreprocessResult(
        canonical_text=canonical_text,
        canonical_document=document,
        prompt_text=prompt_text,
        prompt_blocks=tuple(prompt_blocks),
        report=report,
        content_assessment=content_assessment,
        artifact=artifact,
    )
