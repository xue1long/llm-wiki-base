# ruflo-kb/tests/test_utils/test_extract_doc_guard.py
"""Verify extract_office_text rejects legacy .doc files.

Legacy .doc (binary OLE Compound File) is NOT supported by python-docx.
Without the guard, callers get a confusing PackageNotFoundError / zipfile error.
"""
import pytest

from src.utils.extract.office import extract_office_text
from src.utils.extract import UnsupportedFormat


def test_legacy_doc_raises_unsupported_format(tmp_path):
    fake = tmp_path / "legacy.doc"
    fake.write_bytes(b"\xd0\xcf\x11\xe0")  # OLE Compound File magic
    with pytest.raises(UnsupportedFormat):
        extract_office_text(str(fake))


def test_docx_extension_still_supported(tmp_path):
    # Just verify the guard doesn't accidentally reject .docx
    fake = tmp_path / "ok.docx"
    fake.write_bytes(b"")  # empty; python-docx is stubbed in tests
    # We expect either UnsupportedFormat (corrupt) or some normal extraction error,
    # but NOT an UnsupportedFormat about ".doc" being legacy.
    try:
        extract_office_text(str(fake))
    except UnsupportedFormat as e:
        assert "legacy" not in str(e).lower()
    except Exception:
        # any other error is fine — the guard did not fire on .docx
        pass
