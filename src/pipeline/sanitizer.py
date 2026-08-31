"""Compatibility wrapper for the evidence-preserving text preprocessor."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from .text_preprocessing import preprocess_source

SANITIZER_MAX_CHARS = 50_000
_ZERO_WIDTH_RE = re.compile(r'[​‌‍﻿]')


@dataclass
class SanitizerResult:
    text: str                # cleaned text
    quality_score: float     # 0.0–1.0, 1.0 = clean
    warnings: list[str]      # warning keys for logging / diagnostics
    should_skip_llm: bool    # True when the text is too degraded for LLM


def sanitize(source_text: str) -> SanitizerResult:
    """Preserve the historical return type while using the shared module."""
    result = preprocess_source(
        source_text,
        source_id="legacy/sanitizer",
        skip_llm_on_degraded=True,
    )
    # Compatibility only: callers of the old sanitizer historically received
    # zero-width removal and repeated-line collapse.  The new ingest path
    # consumes ``preprocess_source`` directly and never uses this fallback.
    lines = _ZERO_WIDTH_RE.sub("", result.prompt_text).splitlines()
    counts = Counter(lines)
    seen: set[str] = set()
    legacy_lines: list[str] = []
    for line in lines:
        if counts[line] > 10:
            if line in seen:
                continue
            seen.add(line)
        legacy_lines.append(line)
    return SanitizerResult(
        text="\n".join(legacy_lines),
        quality_score=result.report.quality_score,
        warnings=list(result.report.warnings),
        should_skip_llm=result.report.should_skip_llm,
    )
