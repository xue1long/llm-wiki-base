"""Bounded, provider-free specialist routes for degraded extraction."""

from __future__ import annotations

from dataclasses import dataclass

from src.pipeline.extraction_types import ExtractionArtifact


@dataclass(frozen=True)
class SpecialistError(ValueError):
    route: str
    reason: str
    attempts: int = 1

    def __str__(self) -> str:
        return f"specialist_failed: {self.route}: {self.reason}"


_ATTEMPTS: set[tuple[str, str]] = set()

from .ocr import run_ocr
from .table import run_table


async def run_specialist(route: str, artifact: ExtractionArtifact) -> ExtractionArtifact:
    key = (artifact.source_id, route)
    if key in _ATTEMPTS:
        raise SpecialistError(route, "one attempt per source and route", attempts=2)
    _ATTEMPTS.add(key)
    if route == "ocr":
        return await run_ocr(artifact)
    if route == "table":
        return await run_table(artifact)
    if route == "image":
        return await run_ocr(artifact)
    raise SpecialistError(route, "unknown route")


__all__ = ["SpecialistError", "run_specialist"]
