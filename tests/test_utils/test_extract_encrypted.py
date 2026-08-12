# ruflo-kb/tests/test_utils/test_extract_encrypted.py
"""Verify encrypted / corrupt files raise a typed EncryptedDocumentError.

Wraps pypdf + python-docx + openpyxl exceptions that indicate the file is
encrypted, password-protected, or otherwise not a valid Office document.
"""
import zipfile
import pytest

from src.utils.extract import EncryptedDocumentError
from src.utils.extract.errors import looks_like_encryption_error


@pytest.mark.parametrize(
    "exc",
    [Exception("password required"), Exception("document is encrypted"), type("Unknown", (Exception,), {})()],
)
def test_shared_encryption_classifier_detects_known_signals(exc):
    assert looks_like_encryption_error(exc)


def test_shared_encryption_classifier_rejects_unrelated_error():
    assert not looks_like_encryption_error(ValueError("invalid header"))


def test_shared_encryption_classifier_does_not_match_bare_password_text():
    assert not looks_like_encryption_error(ValueError("invalid password field"))


def test_encrypted_zipfile_raises_typed_error(tmp_path, monkeypatch):
    """Simulate python-docx raising zipfile.BadZipFile on a corrupt .docx."""
    from src.utils.extract import office

    fake = tmp_path / "corrupt.docx"
    fake.write_bytes(b"not a zip")

    # Patch Document to raise zipfile.BadZipFile (what python-docx does internally)
    def _raise(*a, **kw):
        raise zipfile.BadZipFile("File is not a zip file")

    monkeypatch.setattr(office, "Document", _raise, raising=False)
    # Inject Document into the module
    import docx as _docx_mod
    monkeypatch.setattr(_docx_mod, "Document", _raise)

    with pytest.raises(EncryptedDocumentError):
        office.extract_docx_text(str(fake))


def test_corrupt_xlsx_raises_typed_error(tmp_path, monkeypatch):
    """Simulate openpyxl raising zipfile.BadZipFile on a corrupt .xlsx."""
    from src.utils.extract import office

    fake = tmp_path / "corrupt.xlsx"
    fake.write_bytes(b"not a zip")

    def _raise(*a, **kw):
        raise zipfile.BadZipFile("File is not a zip file")

    import openpyxl as _oxl
    monkeypatch.setattr(_oxl, "load_workbook", _raise)

    with pytest.raises(EncryptedDocumentError):
        office.extract_xlsx_text(str(fake))


def test_encrypted_pdf_raises_typed_error(tmp_path, monkeypatch):
    """Simulate pypdf raising on an encrypted PDF."""
    from src.utils.extract import pdf

    fake = tmp_path / "encrypted.pdf"
    fake.write_bytes(b"%PDF-1.4\n")

    class _FakeReader:
        def __init__(self, *a, **kw):
            raise Exception("File has not been decrypted")

    import pypdf as _pypdf_mod
    monkeypatch.setattr(_pypdf_mod, "PdfReader", _FakeReader)

    with pytest.raises(EncryptedDocumentError):
        pdf.extract_pdf_text(str(fake))
