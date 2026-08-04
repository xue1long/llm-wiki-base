"""Ebook text extraction — EPUB and MOBI support.

Phase 1.7 of the Nash absorption plan.
"""
from pathlib import Path


def extract_epub(path: Path) -> str:
    """Extract text content from EPUB file.

    Args:
        path: Path to .epub file

    Returns:
        Extracted text content with chapter separators

    Raises:
        ImportError: If ebooklib is not installed
        ValueError: If file cannot be parsed
    """
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        raise ImportError(
            "ebooklib is required for EPUB parsing. "
            "Install with: pip install ebooklib>=0.18"
        )

    if not path.exists():
        raise ValueError(f"EPUB file not found: {path}")

    try:
        book = epub.read_epub(str(path))
    except Exception as e:
        raise ValueError(f"Failed to parse EPUB: {e}") from e

    texts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            content = item.get_content()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            # Strip HTML tags for plain text (basic extraction)
            text = _strip_html(content)
            if text.strip():
                texts.append(text.strip())

    return "\n\n---\n\n".join(texts)


def extract_mobi(path: Path) -> str:
    """Extract text content from MOBI file.

    Args:
        path: Path to .mobi file

    Returns:
        Extracted text content

    Raises:
        ImportError: If mobi library is not installed
        ValueError: If file cannot be parsed
    """
    try:
        import mobi
    except ImportError:
        raise ImportError(
            "mobi is required for MOBI parsing. "
            "Install with: pip install mobi>=0.3"
        )

    if not path.exists():
        raise ValueError(f"MOBI file not found: {path}")

    try:
        # mobi module extracts to a temp directory
        result = mobi.read(str(path))
        if result is None:
            raise ValueError("MOBI extraction returned no content")
        # mobi.read returns the raw HTML content
        text = _strip_html(result)
        return text.strip()
    except Exception as e:
        raise ValueError(f"Failed to parse MOBI: {e}") from e


def _strip_html(html_content: str) -> str:
    """Basic HTML stripping for ebook content extraction.

    This is a simple implementation. For better results, consider
    using BeautifulSoup or html2text.
    """
    import re

    # Remove scripts and styles
    html_content = re.sub(r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE)

    # Convert common block elements to newlines
    html_content = re.sub(r"<br\s*/?>", "\n", html_content, flags=re.IGNORECASE)
    html_content = re.sub(r"</p>", "\n\n", html_content, flags=re.IGNORECASE)
    html_content = re.sub(r"</div>", "\n", html_content, flags=re.IGNORECASE)
    html_content = re.sub(r"</h[1-6]>", "\n\n", html_content, flags=re.IGNORECASE)

    # Remove remaining tags
    html_content = re.sub(r"<[^>]+>", "", html_content)

    # Decode HTML entities
    import html
    html_content = html.unescape(html_content)

    # Clean up whitespace
    html_content = re.sub(r"\n{3,}", "\n\n", html_content)
    html_content = re.sub(r" {2,}", " ", html_content)

    return html_content.strip()


def extract_ebook(path: Path) -> str:
    """Extract text from ebook (EPUB or MOBI).

    Auto-detects format based on file extension.

    Args:
        path: Path to ebook file

    Returns:
        Extracted text content

    Raises:
        ValueError: If format is not supported
    """
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return extract_epub(path)
    elif suffix == ".mobi":
        return extract_mobi(path)
    else:
        raise ValueError(f"Unsupported ebook format: {suffix}")


def is_ebook_file(path: Path) -> bool:
    """Check if file is a supported ebook format."""
    return path.suffix.lower() in {".epub", ".mobi"}