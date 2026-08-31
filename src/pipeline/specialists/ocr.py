"""Validate OCR-shaped artifacts without invoking a provider."""

from __future__ import annotations

from src.pipeline.extraction_types import ExtractionArtifact, validate_artifact_ranges

from . import SpecialistError


async def run_ocr(artifact: ExtractionArtifact) -> ExtractionArtifact:
    if artifact.extraction_method != "ocr":
        raise SpecialistError("ocr", "artifact extraction method is not ocr")
    if artifact.extraction_errors:
        raise SpecialistError("ocr", "; ".join(artifact.extraction_errors))
    if not artifact.input_text.strip() or not artifact.ranges:
        raise SpecialistError("ocr", "OCR output has no text or image region")
    try:
        validate_artifact_ranges(artifact)
    except ValueError as exc:
        raise SpecialistError("ocr", str(exc)) from exc
    return artifact
