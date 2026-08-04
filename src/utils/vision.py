"""Vision utilities — image description via vision-capable LLM.

Phase 4.1 of the Nash absorption plan.
Provides image understanding capabilities for PDFs, screenshots, and other visual content.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm.provider import LLMProvider

_logger = logging.getLogger(__name__)


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@dataclass
class ImageDescription:
    """Result of image description."""

    description: str
    confidence: float  # 0.0-1.0
    model_used: str
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "confidence": self.confidence,
            "model_used": self.model_used,
            "error": self.error,
        }


def is_image_file(path: Path) -> bool:
    """Check if file is a supported image format."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def encode_image_to_base64(path: Path) -> str:
    """Read image file and encode to base64 string.

    Args:
        path: Path to image file

    Returns:
        Base64-encoded image string

    Raises:
        ValueError: If file cannot be read
    """
    if not path.exists():
        raise ValueError(f"Image file not found: {path}")

    try:
        image_bytes = path.read_bytes()
        return base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Failed to read image: {e}") from e


def get_image_mime_type(path: Path) -> str:
    """Get MIME type for image file.

    Args:
        path: Path to image file

    Returns:
        MIME type string (e.g., "image/png")
    """
    suffix = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mime_map.get(suffix, "application/octet-stream")


async def describe_image(
    image_path: Path,
    provider: "LLMProvider",
    prompt: str | None = None,
    max_tokens: int = 500,
) -> ImageDescription:
    """Generate a text description of an image using a vision LLM.

    Args:
        image_path: Path to image file
        provider: LLM provider with vision capability
        prompt: Custom prompt (optional)
        max_tokens: Maximum tokens in response

    Returns:
        ImageDescription with generated description

    Raises:
        ValueError: If image cannot be processed or provider lacks vision support
    """
    if not is_image_file(image_path):
        return ImageDescription(
            description="",
            confidence=0.0,
            model_used="",
            error=f"Unsupported image format: {image_path.suffix}",
        )

    try:
        base64_image = encode_image_to_base64(image_path)
        mime_type = get_image_mime_type(image_path)
    except ValueError as e:
        return ImageDescription(
            description="",
            confidence=0.0,
            model_used="",
            error=str(e),
        )

    # Check if provider supports vision
    if not hasattr(provider, "complete_with_image"):
        return ImageDescription(
            description="",
            confidence=0.0,
            model_used=getattr(provider, "model", "unknown"),
            error="Provider does not support vision/image inputs",
        )

    # Default prompt for image description
    description_prompt = prompt or (
        "Describe this image in detail. Include:\n"
        "1. Main subjects/objects\n"
        "2. Setting and context\n"
        "3. Any text visible in the image\n"
        "4. Relevant details for knowledge extraction\n\n"
        "Be concise but comprehensive."
    )

    try:
        response = await provider.complete_with_image(
            prompt=description_prompt,
            image_base64=base64_image,
            image_mime_type=mime_type,
            max_tokens=max_tokens,
        )

        return ImageDescription(
            description=response,
            confidence=0.9,  # Assume high confidence on success
            model_used=getattr(provider, "model", "unknown"),
        )

    except Exception as e:
        _logger.warning(f"[vision] Failed to describe image {image_path}: {e}")
        return ImageDescription(
            description="",
            confidence=0.0,
            model_used=getattr(provider, "model", "unknown"),
            error=str(e),
        )


async def extract_images_from_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Extract images from a PDF file.

    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save extracted images

    Returns:
        List of paths to extracted image files

    Note:
        Requires pdf2image or similar library. Falls back to empty list if unavailable.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        _logger.warning("[vision] pdf2image not installed, cannot extract PDF images")
        return []

    if not pdf_path.exists():
        _logger.warning(f"[vision] PDF not found: {pdf_path}")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        images = convert_from_path(str(pdf_path), dpi=150)
        image_paths: list[Path] = []

        for i, image in enumerate(images):
            image_path = output_dir / f"{pdf_path.stem}_page{i + 1}.png"
            image.save(str(image_path), "PNG")
            image_paths.append(image_path)

        return image_paths

    except Exception as e:
        _logger.warning(f"[vision] Failed to extract PDF images: {e}")
        return []


async def describe_images_batch(
    image_paths: list[Path],
    provider: "LLMProvider",
    max_concurrent: int = 3,
) -> list[ImageDescription]:
    """Describe multiple images in parallel with concurrency limit.

    Args:
        image_paths: List of image paths
        provider: Vision-capable LLM provider
        max_concurrent: Maximum concurrent requests

    Returns:
        List of ImageDescription (same order as input)
    """
    import asyncio

    semaphore = asyncio.Semaphore(max_concurrent)

    async def describe_with_limit(path: Path) -> ImageDescription:
        async with semaphore:
            return await describe_image(path, provider)

    tasks = [describe_with_limit(p) for p in image_paths]
    return await asyncio.gather(*tasks)