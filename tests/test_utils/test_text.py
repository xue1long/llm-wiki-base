# ruflo-kb/tests/test_utils/test_text.py
from src.utils.text import trim_text, html_to_text, chunk_markdown

def test_trim_text():
    assert trim_text("  hello  ") == "hello"
    assert trim_text("hello\n\n\n\nworld") == "hello\n\nworld"

def test_html_to_text():
    assert html_to_text("<p>Hello <strong>World</strong></p>") == "Hello World"
    assert html_to_text("<script>alert(1)</script>Hello") == "Hello"

def test_chunk_markdown():
    result = chunk_markdown("short content")
    assert result == ["short content"]

    long_content = "A" * 600
    result = chunk_markdown(long_content, chunk_size=500)
    assert len(result) > 1
