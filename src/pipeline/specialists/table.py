"""Validate table-shaped artifacts without invoking a provider."""

from __future__ import annotations

from src.pipeline.extraction_types import ExtractionArtifact, validate_artifact_ranges

from . import SpecialistError


async def run_table(artifact: ExtractionArtifact) -> ExtractionArtifact:
    if artifact.extraction_method not in {"xlsx_cells", "pdf_text"}:
        raise SpecialistError("table", "artifact extraction method is not table-capable")
    if not artifact.input_text.strip() or not artifact.ranges:
        raise SpecialistError("table", "table output has no rows or ranges")
    if not any("\t" in line or "|" in line for line in artifact.input_text.splitlines()):
        raise SpecialistError("table", "table output has no deterministic column boundary")
    if not all(item.unit == "table_row" for item in artifact.ranges):
        raise SpecialistError("table", "table output has non-row provenance")
    try:
        validate_artifact_ranges(artifact)
    except ValueError as exc:
        raise SpecialistError("table", str(exc)) from exc
    return artifact
