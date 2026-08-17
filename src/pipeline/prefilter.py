"""D3: Rule-based document pre-filtering.

Runs early in the ingest pipeline, before any LLM work, to decide
whether a document should be processed, skipped, or downgraded.

Rules (evaluated in order — first match wins):

1. **File < 100 bytes** → ``skip`` (empty / placeholder files)
2. **sanitizer score < 0.3** (when ``RUFLO_SANITIZER_SKIP_LLM=1``) → ``source_only``
3. **List-lines ratio > 80%** → ``reference_list`` (C3 reference-list mode)
4. **No Chinese characters** → ``skip``, metadata ``{"language": "en"}``
   (English prompts are not yet supported)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class PrefilterResult:
    """Outcome of the prefilter decision.

    Attributes
    ----------
    action:
        Recommended action for the ingest pipeline.
    reason:
        Human-readable explanation of the decision.
    metadata:
        Auxiliary data (e.g. ``{"language": "en"}``, ``{"list_density": 0.85}``).
    """
    action: Literal["process", "skip", "source_only", "reference_list"]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


# Chinese character ranges: CJK Unified Ideographs (U+4E00–U+9FFF) and
# CJK Unified Ideographs Extension A (U+3400–U+4DBF).
_CHINESE_RE = re.compile(r"[一-鿿㐀-䶿]")


def _has_chinese(text: str) -> bool:
    """Return True when *text* contains at least one Chinese character."""
    return bool(_CHINESE_RE.search(text))


def prefilter(
    source_text: str,
    file_size: int,
    sanitizer_score: float | None = None,
) -> PrefilterResult:
    """Apply rule-based pre-filtering to decide how to handle a source document.

    Parameters
    ----------
    source_text:
        The (sanitized) source text. Used for list-density and language
        detection.
    file_size:
        Raw file size in bytes (before sanitization).
    sanitizer_score:
        Quality score from :func:`~.sanitizer.sanitize` (0.0–1.0), or
        ``None`` when the caller has not yet run the sanitizer.  Rules
        that depend on this value are skipped when it is ``None``.

    Returns
    -------
    PrefilterResult
        The recommended action and associated metadata.
    """
    from src.config import settings
    from .stub_quality import detect_reference_list_density

    # Rule 1: skip empty or placeholder files (< 100 bytes).
    if file_size < 100:
        return PrefilterResult(
            action="skip",
            reason=f"File too small ({file_size} bytes < 100 minimum)",
        )

    # Rule 2: when SKIP_LLM is enabled, downgrade low-quality sources
    # to source-only (no LLM analysis).
    if (
        sanitizer_score is not None
        and sanitizer_score < 0.3
        and settings().sanitizer_skip_llm
    ):
        return PrefilterResult(
            action="source_only",
            reason=(
                f"Sanitizer score {sanitizer_score:.2f} below 0.3 threshold"
                " (RUFLO_SANITIZER_SKIP_LLM enabled)"
            ),
            metadata={"sanitizer_score": sanitizer_score},
        )

    # Rule 3: detect reference-list documents (> 80% list lines).
    # Reuses the existing ``detect_reference_list_density`` from C3.
    list_density = detect_reference_list_density(source_text)
    if list_density > 0.8:
        return PrefilterResult(
            action="reference_list",
            reason=(
                f"List density {list_density:.2f} exceeds 0.8 threshold"
            ),
            metadata={"list_density": list_density},
        )

    # Rule 4: pure English documents (no Chinese characters) —
    # English prompts are not yet supported.
    if source_text.strip() and not _has_chinese(source_text):
        return PrefilterResult(
            action="skip",
            reason="English-only document (Chinese prompt not yet supported)",
            metadata={"language": "en"},
        )

    return PrefilterResult(
        action="process",
        reason="Document passed all prefilter checks",
    )
