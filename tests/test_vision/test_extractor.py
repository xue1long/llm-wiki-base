"""Tests for PDF image extractor."""
import fitz

from src.vision.extractor import extract_from_pdf, ExtractedImage


def _make_test_pdf(path, with_image=True):
    """Create a minimal PDF, optionally with a single 1×1 white PNG embedded."""
    doc = fitz.open()
    page = doc.new_page()
    if with_image:
        # Draw a tiny rectangle as text-image substitute since we don't have
        # an image fixture bundled; an empty page is enough to test that the
        # extractor returns an empty list without crashing.
        page.insert_text((72, 72), "Hello PDF")
    doc.save(str(path))
    doc.close()


def test_extract_from_pdf_returns_list(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_test_pdf(pdf, with_image=False)
    images = extract_from_pdf(pdf, task_id="t1")
    assert isinstance(images, list)
    # Empty PDF (no raster images) → empty list.
    assert images == []


def test_extract_handles_missing_file(tmp_path):
    """Missing file → empty list, no exception."""
    images = extract_from_pdf(tmp_path / "nope.pdf", task_id="t1")
    assert images == []


def test_extracted_image_dataclass():
    img = ExtractedImage(
        task_id="t1", index=0, bytes=b"\x89PNG",
        mime_type="image/png",
        source_page="wiki/sources/t1.md",
        context="hello",
    )
    assert img.task_id == "t1"
    assert img.mime_type == "image/png"


def test_extract_real_pdf_with_image(tmp_path):
    """Embed a real image and verify the extractor sees it."""
    pdf = tmp_path / "img.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Insert a tiny 1×1 PNG (red pixel) by drawing then re-sampling.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1, 1), False)
    pix.clear_with(255)  # white
    page.insert_image(fitz.Rect(50, 50, 60, 60), pixmap=pix)
    doc.save(str(pdf))
    doc.close()

    images = extract_from_pdf(pdf, task_id="t2")
    assert len(images) >= 1
    img = images[0]
    assert img.task_id == "t2"
    assert img.bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    assert img.mime_type == "image/png"
