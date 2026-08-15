"""Tests for parse_llm_json truncation detection.

Regression for the batch-10 observation: 11/11 JSON parse failures were
truncated responses (unterminated string near the end), but parse_llm_json
reported the misleading "no JSON object/array found: line 1 column 1".
"""
import json

import pytest

from src.llm.base import LLMResponse
from src.llm.types import TruncatedResponseError
from src.pipeline._pipeline_common import parse_llm_json


def test_parse_raises_truncated_when_response_marked():
    """LLMResponse.truncated=True is the exact signal → TruncatedResponseError."""
    resp = LLMResponse(
        content='{"pages": [{"id": "x", "title": "未完成',
        model="glm-5.2",
        truncated=True,
    )
    with pytest.raises(TruncatedResponseError):
        parse_llm_json(resp)


def test_parse_raises_truncated_on_tail_unterminated_string():
    """A JSON object whose string never terminates near the end = truncation."""
    content = '{"pages": [{"id": "x", "title": "abc'
    with pytest.raises(TruncatedResponseError) as excinfo:
        parse_llm_json(content)
    assert "truncated" in str(excinfo.value).lower()


def test_parse_raises_truncated_on_tail_missing_delimiter():
    """JSON cut right after a value (Expecting ',' at the very end) = truncation."""
    content = '{"pages": [{"id": "x"}]'
    with pytest.raises(TruncatedResponseError):
        parse_llm_json(content)


def test_parse_generic_error_on_mid_json_syntax_error():
    """A genuine mid-content syntax error (missing comma) is NOT truncation.

    (The pre-existing lenient strategies may extract a balanced fragment or
    raise a generic JSONDecodeError — either is fine; the important contract
    is that mid-content errors are never misclassified as truncation.)
    """
    content = '{"pages": [{"id": "x"}] "oops": 1}'
    try:
        result = parse_llm_json(content)
        # Fragment extraction may return a partial list — acceptable legacy
        # behavior, but it must not be a TruncatedResponseError.
        assert not isinstance(result, Exception)
    except TruncatedResponseError:
        pytest.fail("mid-content syntax error must not be classified as truncation")
    except json.JSONDecodeError:
        pass  # also acceptable


def test_parse_valid_json_still_parses():
    content = '{"pages": [{"id": "x", "title": "ok"}]}'
    result = parse_llm_json(content)
    assert result["pages"][0]["id"] == "x"


def test_parse_markdown_fenced_json_still_parses():
    content = '```json\n{"pages": []}\n```'
    result = parse_llm_json(content)
    assert result == {"pages": []}
