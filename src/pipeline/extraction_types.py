"""Immutable extracted text plus deterministic source provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from src.utils.extract.office import extract_office_text
from src.utils.extract.pdf import extract_pdf_text
from src.utils.text import html_to_text


_RANGE_UNITS = {"line", "paragraph", "page", "table_row", "image_region"}
_PAGE_RE = re.compile(r"^<!-- page: (\d+) -->\n?(.*)$", re.DOTALL)


@dataclass(frozen=True)
class SourceRange:
    unit: str
    start: int
    end: int
    unit_index: int


@dataclass(frozen=True)
class ExtractionArtifact:
    source_id: str
    source_bytes_sha256: str | None
    input_text: str
    input_text_sha256: str
    format: str
    extraction_method: str
    extractor_version: str
    ranges: tuple[SourceRange, ...]
    extraction_errors: tuple[str, ...]


def _decode(raw: bytes) -> tuple[str, tuple[str, ...]]:
    try:
        return raw.decode("utf-8-sig"), ()
    except UnicodeDecodeError:
        for encoding in ("gbk", "big5"):
            try:
                return raw.decode(encoding), ()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace"), ("encoding degraded",)


def _ranges(text: str, unit: str) -> tuple[SourceRange, ...]:
    values = text.splitlines() if unit == "line" else text.split("\n\n")
    return tuple(
        SourceRange(unit, 0, len(value), index)
        for index, value in enumerate(values)
        if value.strip()
    )


def _pdf_ranges(text: str) -> tuple[SourceRange, ...]:
    ranges: list[SourceRange] = []
    for index, page in enumerate(text.split("\n\n")):
        match = _PAGE_RE.match(page)
        content = match.group(2) if match else page
        if content.strip():
            ranges.append(SourceRange("page", 0, len(content), index))
    return tuple(ranges)


def _extract_ocr(file_path: Path) -> tuple[str, tuple[SourceRange, ...], tuple[str, ...]]:
    return "", (), ("OCR extractor unavailable",)


def artifact_from_text(
    input_text: str,
    *,
    source_id: str,
    format: str,
    extraction_method: str,
    source_bytes_sha256: str | None = None,
    ranges: tuple[SourceRange, ...] | None = None,
    extraction_errors: tuple[str, ...] = (),
) -> ExtractionArtifact:
    if not source_id:
        raise ValueError("source_id is required")
    if ranges is None:
        ranges = _ranges(input_text, "line")
    if input_text.strip() and not ranges and not extraction_errors:
        extraction_errors = ("missing provenance",)
    artifact = ExtractionArtifact(
        source_id=source_id,
        source_bytes_sha256=source_bytes_sha256,
        input_text=input_text,
        input_text_sha256=sha256(input_text.encode("utf-8")).hexdigest(),
        format=format,
        extraction_method=extraction_method,
        extractor_version="extraction-artifact-v1",
        ranges=tuple(ranges),
        extraction_errors=tuple(extraction_errors),
    )
    validate_artifact_ranges(artifact)
    return artifact


def collect_artifact(file_path: Path, *, source_id: str) -> ExtractionArtifact:
    """Extract one file and retain a deterministic range for each unit."""
    if not source_id:
        raise ValueError("source_id is required")
    path = Path(file_path)
    raw = path.read_bytes()
    source_hash = sha256(raw).hexdigest()
    suffix = path.suffix.lower().removeprefix(".")
    errors: list[str] = []

    if suffix in {"md", "txt"}:
        text, decode_errors = _decode(raw)
        method, ranges = "native_text", _ranges(text, "line")
        errors.extend(decode_errors)
    elif suffix in {"html", "htm"}:
        decoded, decode_errors = _decode(raw)
        text, method, ranges = html_to_text(decoded), "html_text", ()
        ranges = _ranges(text, "line")
        errors.extend(decode_errors)
    elif suffix == "pdf":
        text, method, ranges = extract_pdf_text(str(path)), "pdf_text", ()
        ranges = _pdf_ranges(text)
    elif suffix == "docx":
        text, method, ranges = extract_office_text(str(path)), "docx_text", ()
        ranges = _ranges(text, "paragraph")
    elif suffix == "xlsx":
        text, method, ranges = extract_office_text(str(path)), "xlsx_cells", ()
        ranges = _ranges(text, "table_row")
    elif suffix in {"png", "jpg", "jpeg", "webp", "tiff", "bmp"}:
        text, ranges, ocr_errors = _extract_ocr(path)
        method = "ocr"
        suffix = "image"
        errors.extend(ocr_errors)
    else:
        text, method, ranges = "", "unsupported", ()
        errors.append(f"unsupported format: {suffix or 'unknown'}")

    return artifact_from_text(
        text,
        source_id=source_id,
        source_bytes_sha256=source_hash,
        format=suffix or "unknown",
        extraction_method=method,
        ranges=tuple(ranges),
        extraction_errors=tuple(errors),
    )


def validate_artifact_ranges(artifact: ExtractionArtifact) -> None:
    if not artifact.source_id:
        raise ValueError("source_id is required")
    expected_hash = sha256(artifact.input_text.encode("utf-8")).hexdigest()
    if artifact.input_text_sha256 != expected_hash:
        raise ValueError("input_text_sha256 mismatch")
    seen: set[tuple[str, int]] = set()
    for item in artifact.ranges:
        if item.unit not in _RANGE_UNITS:
            raise ValueError("range unit is invalid")
        if item.start < 0 or item.end <= item.start or item.unit_index < 0:
            raise ValueError("range bounds are invalid")
        key = (item.unit, item.unit_index)
        if key in seen:
            raise ValueError("duplicate range")
        seen.add(key)
    if artifact.input_text.strip() and not artifact.ranges and not artifact.extraction_errors:
        raise ValueError("non-empty artifact has no source range")
