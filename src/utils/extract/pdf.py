# ruflo-kb/src/utils/extract/pdf.py
"""PDF text extraction.

Encrypted PDFs (or PDFs that pypdf cannot decrypt) are surfaced as
``EncryptedDocumentError`` rather than a confusing low-level exception
from pypdf / pycryptodome.
"""
from .exceptions import EncryptedDocumentError
from .errors import looks_like_encryption_error


def extract_pdf_text(file_path: str) -> str:
    """从 PDF 提取文本"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is optional
        raise EncryptedDocumentError(
            "pypdf is not installed; cannot extract PDF text"
        ) from exc

    try:
        reader = PdfReader(file_path)
    except Exception as exc:
        _raise_if_encrypted(exc, suffix=".pdf")
        raise

    # Some encrypted PDFs do not raise on construction but only on first
    # access. pypdf exposes ``is_encrypted``; if so, attempt a no-password
    # decrypt and surface a typed error on failure.
    if getattr(reader, "is_encrypted", False):
        try:
            result = reader.decrypt("")  # empty password
        except Exception as exc:
            raise EncryptedDocumentError(
                "PDF is encrypted and cannot be decrypted without a password"
            ) from exc
        if result == 0:
            raise EncryptedDocumentError(
                "PDF is password-protected; provide a password to extract text"
            )

    text_parts = []

    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text()
        except Exception as exc:
            _raise_if_encrypted(exc, suffix=".pdf")
            raise
        if text:
            text_parts.append(f"<!-- page: {i + 1} -->\n{text}")

    return "\n\n".join(text_parts)


def _raise_if_encrypted(exc: Exception, suffix: str) -> None:
    """Inspect the exception and raise EncryptedDocumentError if it looks
    like an encryption / decryption failure."""
    if type(exc).__name__ in ("Unknown", "PyCryptodomeWarning"):
        raise EncryptedDocumentError(
            "PDF is encrypted and cannot be decrypted (Unknown encryption algorithm)"
        ) from exc

    if looks_like_encryption_error(exc):
        raise EncryptedDocumentError(
            f"{suffix} is encrypted or password-protected"
        ) from exc
