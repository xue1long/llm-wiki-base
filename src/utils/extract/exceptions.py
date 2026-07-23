# ruflo-kb/src/utils/extract/exceptions.py
"""Typed exceptions raised by the document text extractors.

These distinguish "the file is encrypted / corrupt / not actually an Office
document" (caller may want to surface a specific UI message) from generic
exceptions that callers cannot meaningfully differentiate.
"""


class UnsupportedFormat(Exception):
    """Raised when the file extension is recognised but the format itself
    is not supported by this extractor.

    Example: legacy ``.doc`` (binary OLE Compound File) is not supported by
    ``python-docx``; callers should convert to ``.docx`` first.
    """


class EncryptedDocumentError(Exception):
    """Raised when the file appears to be encrypted, password-protected, or
    is not a valid document of its declared type.

    Wraps the underlying exceptions raised by ``pypdf`` (``cryptocode.Unknown``,
    decryption errors), ``python-docx`` / ``zipfile.BadZipFile`` (corrupt
    DOCX/XLSX), and ``docx.opc.exceptions.PackageNotFoundError``.
    """
