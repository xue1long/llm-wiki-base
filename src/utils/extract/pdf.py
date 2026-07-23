# ruflo-kb/src/utils/extract/pdf.py
"""PDF text extraction.

Encrypted PDFs (or PDFs that pypdf cannot decrypt) are surfaced as
``EncryptedDocumentError`` rather than a confusing low-level exception
from pypdf / pycryptodome.
"""
from .exceptions import EncryptedDocumentError


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

    for page in reader.pages:
        try:
            text = page.extract_text()
        except Exception as exc:
            _raise_if_encrypted(exc, suffix=".pdf")
            raise
        if text:
            text_parts.append(text)

    return "\n\n".join(text_parts)


def _raise_if_encrypted(exc: Exception, suffix: str) -> None:
    """Inspect the exception and raise EncryptedDocumentError if it looks
    like an encryption / decryption failure."""
    name = type(exc).__name__
    msg = str(exc).lower()

    # Cryptocode / pycryptodome raise Unknown when the PDF claims to be
    # encrypted but we cannot decrypt it (wrong / missing password).
    if name in ("Unknown", "PyCryptodomeWarning"):
        raise EncryptedDocumentError(
            "PDF is encrypted and cannot be decrypted (Unknown encryption algorithm)"
        ) from exc

    if any(token in msg for token in ("decrypt", "password", "encrypted", "not been decrypted")):
        raise EncryptedDocumentError(
            f"{suffix} is encrypted or password-protected"
        ) from exc
