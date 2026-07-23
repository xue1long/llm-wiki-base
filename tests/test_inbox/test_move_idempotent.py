# ruflo-kb/tests/test_inbox/test_move_idempotent.py
from src.inbox.manager import InboxManager


def test_move_to_processing_overwrites_existing(tmp_path):
    """move_to_processing must overwrite the destination when it already exists (os.replace semantics)."""
    mgr = InboxManager(tmp_path)
    src = tmp_path / "in" / "foo.md"
    src.parent.mkdir()
    src.write_text("new", encoding="utf-8")

    (tmp_path / "Processing").mkdir()
    (tmp_path / "Processing" / "foo.md").write_text("old", encoding="utf-8")

    mgr.move_to_processing(str(src))
    assert (tmp_path / "Processing" / "foo.md").read_text(encoding="utf-8") == "new"