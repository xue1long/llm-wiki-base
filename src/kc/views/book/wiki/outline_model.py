"""Versioned, JSON-shaped outline records used by the wiki compiler."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageAssignment:
    page_id: str
    volume_id: str
    chapter_id: str
    role: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    context: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    errors: tuple[ValidationError, ...] = ()


__all__ = ["PageAssignment", "ValidationError", "ValidationReport"]
