# ruflo-kb/tests/test_inbox/test_error_log_unique.py
from src.inbox.manager import InboxManager


def test_error_log_uses_full_filename(tmp_path):
    """move_to_error writes the error log as {src.name}.error.log (full filename, not just stem)."""
    mgr = InboxManager(tmp_path)
    (tmp_path / "Error").mkdir()

    src = tmp_path / "in" / "report.docx"
    src.parent.mkdir()
    src.write_text("content")

    mgr.move_to_error(str(src), "boom")
    assert (tmp_path / "Error" / "report.docx.error.log").exists()