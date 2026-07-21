# ruflo-kb/tests/test_utils/test_path.py
import pytest
from src.utils.path import normalize_path

def test_normalize_path():
    assert normalize_path("C:\\Users\\test\\file.md") == "C:/Users/test/file.md"
    assert normalize_path("/home/user/file.md") == "/home/user/file.md"
