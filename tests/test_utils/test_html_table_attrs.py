# ruflo-kb/tests/test_utils/test_html_table_attrs.py
"""Verify convert_html_tables_to_markdown preserves table attributes.

Before the fix, the function used `result.replace(f"<table>{table}</table>", md_table, 1)`
which only matched tables without attributes. A table like
`<table class="data">...</table>` would be silently skipped.
"""
from src.utils.extract.html import convert_html_tables_to_markdown


def test_table_with_class_is_converted():
    src = '<table class="data"><tr><td>1</td></tr></table>'
    out = convert_html_tables_to_markdown(src)
    assert "| 1 |" in out
    assert "<table" not in out


def test_table_with_id_is_converted():
    src = '<table id="t1"><tr><th>A</th></tr><tr><td>x</td></tr></table>'
    out = convert_html_tables_to_markdown(src)
    assert "| A |" in out
    assert "| x |" in out
    assert "<table" not in out


def test_table_with_multiple_attributes_is_converted():
    src = '<table class="grid" id="main" data-x="y"><tr><td>v</td></tr></table>'
    out = convert_html_tables_to_markdown(src)
    assert "| v |" in out
    assert "<table" not in out
