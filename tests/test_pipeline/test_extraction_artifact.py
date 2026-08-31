"""Tests for immutable extraction artifacts and source ranges."""

from __future__ import annotations

from hashlib import sha256

import pytest

from src.pipeline.extraction_types import (
    ExtractionArtifact,
    SourceRange,
    collect_artifact,
    validate_artifact_ranges,
)


def test_native_text_artifact_keeps_byte_hash_and_line_ranges(tmp_path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"alpha\r\nbeta\n")

    artifact = collect_artifact(path, source_id="raw/sources/notes.md")

    assert artifact.format == "md"
    assert artifact.extraction_method == "native_text"
    assert artifact.source_bytes_sha256 == sha256(path.read_bytes()).hexdigest()
    assert artifact.input_text_sha256 == sha256(artifact.input_text.encode()).hexdigest()
    assert artifact.source_bytes_sha256 == sha256(b"alpha\r\nbeta\n").hexdigest()
    assert [item.unit for item in artifact.ranges] == ["line", "line"]
    assert [item.unit_index for item in artifact.ranges] == [0, 1]
    validate_artifact_ranges(artifact)


@pytest.mark.parametrize(
    ("suffix", "method", "unit"),
    [(".pdf", "pdf_text", "page"), (".docx", "docx_text", "paragraph"), (".xlsx", "xlsx_cells", "table_row")],
)
def test_document_formats_record_mapped_units(
    tmp_path, monkeypatch, suffix: str, method: str, unit: str
) -> None:
    path = tmp_path / f"source{suffix}"
    path.write_bytes(b"original bytes")
    if suffix == ".pdf":
        monkeypatch.setattr(
            "src.pipeline.extraction_types.extract_pdf_text",
            lambda _: "<!-- page: 1 -->\npage one\n\n<!-- page: 2 -->\npage two",
        )
    else:
        monkeypatch.setattr(
            "src.pipeline.extraction_types.extract_office_text",
            lambda _: "row one\n\nrow two" if suffix == ".docx" else "a\tb\nc\td",
        )

    artifact = collect_artifact(path, source_id=f"raw/sources/source{suffix}")

    assert artifact.extraction_method == method
    assert all(item.unit == unit for item in artifact.ranges)
    assert artifact.extraction_errors == ()
    validate_artifact_ranges(artifact)


def test_html_and_ocr_shape_are_explicit(tmp_path, monkeypatch) -> None:
    html = tmp_path / "page.html"
    html.write_text("<h1>Title</h1><p>Body</p>", encoding="utf-8")
    artifact = collect_artifact(html, source_id="raw/sources/page.html")
    assert artifact.format == "html"
    assert artifact.extraction_method == "html_text"
    assert artifact.ranges

    image = tmp_path / "scan.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        "src.pipeline.extraction_types._extract_ocr",
        lambda _: ("recognized", (SourceRange("image_region", 0, 10, 0),), ()),
    )
    ocr = collect_artifact(image, source_id="raw/sources/scan.png")
    assert ocr.format == "image"
    assert ocr.extraction_method == "ocr"
    assert ocr.ranges[0].unit == "image_region"
    validate_artifact_ranges(ocr)


def test_unmappable_and_invalid_ranges_fail_closed(tmp_path) -> None:
    path = tmp_path / "unknown.bin"
    path.write_bytes(b"bytes")
    artifact = collect_artifact(path, source_id="raw/sources/unknown.bin")

    assert artifact.extraction_errors == ("unsupported format: bin",)
    assert artifact.ranges == ()

    invalid = ExtractionArtifact(
        source_id="raw/sources/x.md",
        source_bytes_sha256=None,
        input_text="x",
        input_text_sha256=sha256(b"x").hexdigest(),
        format="md",
        extraction_method="native_text",
        extractor_version="test",
        ranges=(SourceRange("line", 2, 1, 0),),
        extraction_errors=(),
    )
    with pytest.raises(ValueError, match="range"):
        validate_artifact_ranges(invalid)
