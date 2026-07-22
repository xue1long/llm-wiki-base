"""Store extracted images as MediaPage in wiki/media/.

Decoupled from the (not-yet-implemented) wiki module: takes a project root
Path and writes a markdown caption page with frontmatter directly.
"""
from pathlib import Path

from .captioner import ImageCaption
from .extractor import ExtractedImage


MEDIA_DIR = "wiki/media"


def _build_frontmatter(page_id: str, caption: ImageCaption, image_path: str,
                       task_id: str) -> str:
    return (
        "---\n"
        f"id: {page_id}\n"
        f"title: Image from {task_id}\n"
        f"type: media\n"
        f"sources: [raw/sources/{task_id}.pdf]\n"
        f"caption: {caption.caption}\n"
        f"alt_text: {caption.alt_text}\n"
        f"entities: {caption.entities}\n"
        f"confidence: {caption.confidence}\n"
        f"image: {image_path}\n"
        f"created_at: {caption.generated_at}\n"
        f"updated_at: {caption.generated_at}\n"
        "---\n"
    )


def _build_body(caption: ImageCaption, image_rel_path: str) -> str:
    return (
        f"![{caption.alt_text}]({image_rel_path})\n\n"
        f"{caption.caption}\n"
    )


class MediaPage:
    @staticmethod
    def write(project_root, image: ExtractedImage, caption: ImageCaption) -> Path:
        """Write image binary + caption markdown under ``<root>/wiki/media/``."""
        media_dir = Path(project_root) / MEDIA_DIR
        media_dir.mkdir(parents=True, exist_ok=True)
        ext = image.mime_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        image_filename = f"{image.task_id}_{image.index}.{ext}"
        image_path = media_dir / image_filename
        # safe_write is text-only in the current lib; fall back to direct writes.
        image_path.write_bytes(image.bytes)
        page_id = image_filename.rsplit(".", 1)[0]
        page_filename = f"{page_id}.md"
        page_path = media_dir / page_filename
        image_rel = f"media/{image_filename}"
        fm = _build_frontmatter(page_id, caption, image_rel, image.task_id)
        body = _build_body(caption, image_rel)
        page_path.write_text(fm + body, encoding="utf-8")
        return page_path
