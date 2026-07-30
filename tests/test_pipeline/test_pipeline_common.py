"""Tests for _escape_string_controls in _pipeline_common.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline._pipeline_common import (
    _escape_string_controls,
    _repair_json,
    parse_llm_json,
)


class TestEscapeStringControls:
    """Unit tests for _escape_string_controls."""

    def test_escapes_newline_inside_string(self):
        text = '{"body": "line1\nline2"}'
        result = _escape_string_controls(text)
        assert result == '{"body": "line1\\nline2"}'

    def test_escapes_tab_inside_string(self):
        text = '{"body": "col1\tcol2"}'
        result = _escape_string_controls(text)
        assert result == '{"body": "col1\\tcol2"}'

    def test_escapes_carriage_return_inside_string(self):
        text = '{"body": "line1\r\nline2"}'
        result = _escape_string_controls(text)
        assert result == '{"body": "line1\\r\\nline2"}'

    def test_preserves_already_escaped_newline(self):
        text = '{"body": "line1\\nline2"}'
        result = _escape_string_controls(text)
        assert result == '{"body": "line1\\nline2"}'

    def test_preserves_already_escaped_tab(self):
        text = '{"body": "col1\\tcol2"}'
        result = _escape_string_controls(text)
        assert result == '{"body": "col1\\tcol2"}'

    def test_preserves_newline_outside_string(self):
        # Whitespace between JSON tokens is allowed.
        text = '{\n  "key": "value"\n}'
        result = _escape_string_controls(text)
        assert result == '{\n  "key": "value"\n}'

    def test_escapes_multiple_strings(self):
        text = '{"a": "x\ny", "b": "p\tq"}'
        result = _escape_string_controls(text)
        assert result == '{"a": "x\\ny", "b": "p\\tq"}'

    def test_handles_empty_string(self):
        assert _escape_string_controls("") == ""

    def test_handles_no_strings(self):
        assert _escape_string_controls('[1, 2, 3]') == '[1, 2, 3]'

    def test_escaped_backslash_before_quote(self):
        # \\" — backslash escapes the quote, so quote doesn't toggle in_string.
        text = '{"body": "say \\"hello\\"\nworld"}'
        result = _escape_string_controls(text)
        assert result == '{"body": "say \\"hello\\"\\nworld"}'


class TestParseLlmJsonWithNewlines:
    """Integration tests: parse_llm_json handles literal newlines in strings."""

    def test_markdown_table_with_newlines_parses(self):
        """Simulate LLM output with a markdown table containing literal newlines."""
        content = '''```json
{
  "pages": [
    {
      "title": "Test",
      "body": "## Table
| Col1 | Col2 |
|------|------|
| a    | b    |
"
    }
  ]
}
```'''
        result = parse_llm_json(content)
        assert result["pages"][0]["title"] == "Test"
        # After json.loads, \\n is decoded back to actual newline.
        assert "\n" in result["pages"][0]["body"]
        assert "| Col1 | Col2 |" in result["pages"][0]["body"]

    def test_multiline_prose_with_newlines_parses(self):
        content = '''{
  "summary": "Paragraph one.
Paragraph two.
Paragraph three."
}'''
        result = parse_llm_json(content)
        assert "Paragraph one." in result["summary"]
        assert "Paragraph two." in result["summary"]

    def test_mixed_newlines_and_wikilinks(self):
        """Literal newlines + bare wikilinks — both repaired."""
        content = '''```json
{
  "related": [
    [[feishu-yunwendang]],
    [[xieren-rumen]]
  ],
  "body": "line1
line2"
}
```'''
        result = parse_llm_json(content)
        assert result["related"] == ["[[feishu-yunwendang]]", "[[xieren-rumen]]"]
        # After json.loads, \\n is decoded back to actual newline.
        assert "\n" in result["body"]
