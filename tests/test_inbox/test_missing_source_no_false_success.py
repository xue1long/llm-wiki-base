# ruflo-kb/tests/test_inbox/test_missing_source_no_false_success.py
import pytest
from src.inbox.manager import InboxManager


def test_move_to_error_raises_when_missing(tmp_path):
    """move_to_error must raise FileNotFoundError when src does not exist (no false success).
    The Error directory is pre-created so that the exception is raised by the src-missing
    guard, not incidentally by `open()` failing to create the error log file.
    """
    mgr = InboxManager(tmp_path)
    (tmp_path / "Error").mkdir()
    with pytest.raises(FileNotFoundError):
        mgr.move_to_error(str(tmp_path / "in" / "ghost.md"), "boom")