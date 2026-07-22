"""Tests for MediaPage.write."""
from src.vision.captioner import ImageCaption
from src.vision.extractor import ExtractedImage
from src.vision.storage import MediaPage


def _image(task_id="t1"):
    return ExtractedImage(
        task_id=task_id, index=0, bytes=b"\x89PNG\r\n\x1a\nFAKE_BYTES",
        mime_type="image/png",
        source_page=f"wiki/sources/{task_id}.md",
        context="context",
    )


def _caption(task_id="t1", ts=12345):
    return ImageCaption(
        task_id=task_id, index=0,
        caption="Caption text here.",
        alt_text="caption",
        entities=["X", "Y"],
        confidence=0.85,
        model_used="gpt-4o-mini",
        generated_at=ts,
    )


def test_media_page_write_creates_files(tmp_path):
    img = _image("t1")
    cap = _caption("t1")
    page_path = MediaPage.write(tmp_path, img, cap)
    assert page_path.exists()
    content = page_path.read_text(encoding="utf-8")
    assert "id: t1_0" in content
    assert "type: media" in content
    assert "Caption text here." in content
    assert "media/t1_0.png" in content
    # Image binary next to the markdown
    img_path = tmp_path / "wiki" / "media" / "t1_0.png"
    assert img_path.exists()
    assert img_path.read_bytes().startswith(b"\x89PNG")


def test_media_page_write_jpeg_extension(tmp_path):
    img = ExtractedImage(
        task_id="t2", index=1, bytes=b"\xff\xd8\xff",
        mime_type="image/jpeg",
        source_page="wiki/sources/t2.md",
        context="x",
    )
    cap = _caption("t2")
    page_path = MediaPage.write(tmp_path, img, cap)
    # jpeg → .jpg extension
    assert (tmp_path / "wiki" / "media" / "t2_1.jpg").exists()
    assert page_path.exists()
