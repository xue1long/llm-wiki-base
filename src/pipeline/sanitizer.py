"""Source text quality gate between Collector and Analyzer.

Computes noise metrics (replacement chars, blank lines, repetition),
scores quality on a 0.0–1.0 scale, and normalises the text before it
enters the LLM prompt.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass

from ._pipeline_common import _ZERO_WIDTH_RE, _MULTI_BLANK_RE

SANITIZER_MAX_CHARS = 50_000


@dataclass
class SanitizerResult:
    text: str                # cleaned text
    quality_score: float     # 0.0–1.0, 1.0 = clean
    warnings: list[str]      # warning keys for logging / diagnostics
    should_skip_llm: bool    # True when the text is too degraded for LLM


def _detect_repeat_ratio(text: str) -> float:
    """Lines appearing >5 times as a fraction of total lines. 0.0 = no repetition."""
    lines = text.splitlines()
    if len(lines) < 3:
        return 0.0
    counts = Counter(lines)
    repeated = sum(c for _line, c in counts.items() if c > 5)
    return repeated / len(lines)


def _normalize(text: str) -> str:
    """Apply all normalization rules. Operates on the FULL text (not truncated)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    text = unicodedata.normalize("NFC", text)

    # Collapse repeated lines (>10 occurrences -> keep first only)
    lines = text.splitlines()
    counts = Counter(lines)
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if counts[line] > 10:
            if line in seen:
                continue
            seen.add(line)
        result.append(line)
    return "\n".join(result)


def sanitize(source_text: str) -> SanitizerResult:
    """Analyse and clean source text before it enters the LLM prompt.

    Quality scoring only penalises objective noise (garbled chars,
    excessive blank lines, extreme repetition).  Length is NEVER
    penalised — a short but clean quote is fine.
    """
    # Step 1 — compute quality metrics (on the raw text)
    _raw = source_text[:SANITIZER_MAX_CHARS]
    total = len(_raw)

    # Replacement character ratio (U+FFFD)
    replacement_ratio = _raw.count("�") / max(total, 1)

    # Blank line noise ratio
    _lines = _raw.splitlines()
    blank_lines = sum(1 for line in _lines if line.strip() == "")
    blanks_ratio = blank_lines / max(len(_lines), 1)

    # Repeated line ratio
    repeat_ratio = _detect_repeat_ratio(_raw)

    # Step 2 — quality score
    score = 1.0

    if replacement_ratio > 0.01:
        score -= 0.4
    if replacement_ratio > 0.05:
        score -= 0.3  # cumulative -0.7
    if blanks_ratio > 0.6:
        score -= 0.3
    if blanks_ratio > 0.85:
        score -= 0.3  # cumulative -0.6
    if repeat_ratio > 0.3:
        score -= 0.3
    if repeat_ratio > 0.6:
        score -= 0.3  # cumulative -0.6

    score = max(score, 0.0)

    # should_skip_llm — conservative, only skip when there's essentially no content
    should_skip = (
        len(source_text.strip()) < 5
        or replacement_ratio > 0.3
        or (len(source_text.strip()) < 20 and blanks_ratio > 0.9)
    )

    # Step 3 — normalise (AFTER scoring, so metrics are on the raw text)
    cleaned_text = _normalize(source_text)

    # Step 4 — assemble warnings
    warnings: list[str] = []
    if replacement_ratio > 0.01:
        warnings.append("has_replacement_chars")
    if replacement_ratio > 0.05:
        warnings.append("garbled")
    if blanks_ratio > 0.6:
        warnings.append("mostly_blank")
    if repeat_ratio > 0.3:
        warnings.append("high_repetition")
    if score < 0.3:
        warnings.append("low_quality")

    return SanitizerResult(
        text=cleaned_text,
        quality_score=score,
        warnings=warnings,
        should_skip_llm=should_skip,
    )
