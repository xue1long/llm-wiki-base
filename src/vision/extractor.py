"""Image extraction from PDF (MVP); DOCX/PPTX/EPUB deferred to v2.0.1."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedImage:
    task_id: str
    index: int
    bytes: bytes
    mime_type: str                # "image/png" | "image/jpeg"
    source_page: str              # "wiki/sources/<task_id>.md"
    context: str                  # surrounding text from PDF (for captioning)


def extract_from_pdf(pdf_path: Path, task_id: str) -> list[ExtractedImage]:
    """Extract images from a PDF.

    Uses PyMuPDF (``fitz``) — already in the project's dependency tree.
    Walks every page, extracts every embedded raster, takes surrounding text
    as captioning context. Skips broken images silently.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            "PyMuPDF (fitz) is required for PDF image extraction. "
            "Install it with: pip install pymupdf"
        ) from e

    images: list[ExtractedImage] = []
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return images

    doc = fitz.open(str(pdf_path))
    try:
        for page_idx, page in enumerate(doc):
            page_context = page.get_text("text")[:500]
            # ``get_images(full=True)`` returns xrefs for every embedded image.
            for img_idx, img_info in enumerate(page.get_images(full=True)):
                xref = img_info[0]
                try:
                    extracted = doc.extract_image(xref)
                    data = extracted.get("image") or b""
                    fmt = (extracted.get("ext") or "png").lower()
                    mime = _fmt_to_mime(fmt)
                    images.append(ExtractedImage(
                        task_id=task_id,
                        index=len(images),
                        bytes=data,
                        mime_type=mime,
                        source_page=f"wiki/sources/{task_id}.md",
                        context=page_context,
                    ))
                except Exception:
                    # Skip broken image silently.
                    continue
    finally:
        doc.close()
    return images


def _fmt_to_mime(fmt: str) -> str:
    fmt = fmt.lower()
    if fmt in ("png", "jpeg", "jpg", "gif", "webp", "bmp", "tiff"):
        return f"image/{'jpeg' if fmt == 'jpg' else fmt}"
    return "image/png"
