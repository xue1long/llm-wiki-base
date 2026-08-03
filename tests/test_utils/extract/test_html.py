# ruflo-kb/tests/test_utils/extract/test_html.py
from src.utils.extract.html import convert_html_tables_to_markdown, html_img_tags_to_markdown

def test_convert_html_tables():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    result = convert_html_tables_to_markdown(html)
    assert "| A | B |" in result
    assert "| 1 | 2 |" in result

def test_html_img_to_markdown():
    html = '<img src="test.png" alt="test image">'
    result = html_img_tags_to_markdown(html)
    assert result == "![test image](test.png)"
