# ruflo-kb/tests/test_inbox.py
import pytest
import tempfile
import os
from pathlib import Path
from src.inbox.manager import InboxManager

@pytest.fixture
def temp_inbox():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield InboxManager(tmpdir)

def test_ensure_dirs(temp_inbox):
    temp_inbox.ensure_dirs()
    assert temp_inbox.pending_path.exists()
    assert temp_inbox.processing_path.exists()
    assert temp_inbox.error_path.exists()

def test_move_to_processing(temp_inbox):
    temp_inbox.ensure_dirs()

    # 创建测试文件
    test_file = temp_inbox.pending_path / "test.txt"
    test_file.write_text("content")

    # 移动到 Processing
    new_path = temp_inbox.move_to_processing(str(test_file))

    assert new_path == temp_inbox.processing_path / "test.txt"
    assert not test_file.exists()
    assert new_path.exists()

def test_move_to_error(temp_inbox):
    temp_inbox.ensure_dirs()

    # 创建测试文件
    test_file = temp_inbox.processing_path / "test.txt"
    test_file.write_text("content")

    # 移动到 Error
    new_path = temp_inbox.move_to_error(str(test_file), "Test error message")

    assert new_path == temp_inbox.error_path / "test.txt"
    assert new_path.exists()
    assert (temp_inbox.error_path / "test.txt.error.log").exists()

def test_scan_pending(temp_inbox):
    temp_inbox.ensure_dirs()

    # 创建测试文件
    (temp_inbox.pending_path / "file1.txt").write_text("1")
    (temp_inbox.pending_path / "file2.md").write_text("2")
    (temp_inbox.pending_path / ".hidden").write_text("3")  # 隐藏文件应被忽略

    files = temp_inbox.scan_pending()
    assert len(files) == 2
    assert all(f.name in ["file1.txt", "file2.md"] for f in files)
