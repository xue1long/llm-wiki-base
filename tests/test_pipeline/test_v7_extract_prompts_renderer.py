"""T1.3: render_prompt + parse_llm_response + schema validation tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.v7_extract.prompts.ast import PromptTemplate
from src.pipeline.v7_extract.prompts.renderer import (
    LLMResponseError,
    PromptSlotMissingError,
    compute_prompt_fill_status,
    parse_llm_response,
    render_prompt,
)


def _tpl(user_template: str, output_schema=None) -> PromptTemplate:
    return PromptTemplate(
        prompt_kind="x",
        version="1.0",
        system_section="SYS",
        user_template=user_template,
        output_schema=output_schema,
        source="bundled",
        path=Path("/tmp/x.toml"),
    )


# ---------------------------------------------------------------------------
# render_prompt
# ---------------------------------------------------------------------------

def test_render_substitutes_simple_slots():
    tpl = _tpl("Classify this: {content}")
    sys_p, user_p = render_prompt(tpl, {"content": "hello"})
    assert sys_p == "SYS"
    assert user_p == "Classify this: hello"


def test_render_substitutes_multiple_slots():
    tpl = _tpl("File: {filename_hint} Body: {content}")
    sys_p, user_p = render_prompt(tpl, {
        "filename_hint": "x.md",
        "content": "hello",
    })
    assert "File: x.md" in user_p
    assert "Body: hello" in user_p


def test_render_substitutes_repeated_slot():
    tpl = _tpl("Slot: {x} and again {x}")
    user_p = render_prompt(tpl, {"x": "42"})[1]
    assert user_p == "Slot: 42 and again 42"


def test_render_missing_required_raises():
    tpl = _tpl("Body: {content}")
    with pytest.raises(PromptSlotMissingError, match="content"):
        render_prompt(tpl, {})


def test_render_ignores_extra_slots():
    """Extra slot values are silently ignored (matches compute_slot_fill_status)."""
    tpl = _tpl("Body: {content}")
    sys_p, user_p = render_prompt(tpl, {"content": "x", "extra": "y"})
    assert user_p == "Body: x"


def test_render_coerces_non_string_values():
    tpl = _tpl("Limit: {limit}")
    user_p = render_prompt(tpl, {"limit": 4096})[1]
    assert user_p == "Limit: 4096"


# ---------------------------------------------------------------------------
# compute_prompt_fill_status
# ---------------------------------------------------------------------------

def test_fill_status_reports_missing_and_extra():
    tpl = _tpl("A: {a} B: {b}")
    status = compute_prompt_fill_status(tpl, {"a": "1", "c": "3"})
    assert status["missing"] == ["b"]
    assert status["extra"] == ["c"]


def test_fill_status_clean_when_all_provided():
    tpl = _tpl("A: {a}")
    status = compute_prompt_fill_status(tpl, {"a": "1"})
    assert status["missing"] == []
    assert status["extra"] == []


# ---------------------------------------------------------------------------
# parse_llm_response — fence stripping
# ---------------------------------------------------------------------------

def test_parse_accepts_plain_json():
    payload = parse_llm_response('{"a": 1}', None)
    assert payload == {"a": 1}


def test_parse_strips_json_fence():
    payload = parse_llm_response('```json\n{"a": 1}\n```', None)
    assert payload == {"a": 1}


def test_parse_strips_plain_fence():
    payload = parse_llm_response('```\n{"a": 1}\n```', None)
    assert payload == {"a": 1}


def test_parse_empty_string_raises():
    with pytest.raises(LLMResponseError, match="empty"):
        parse_llm_response("", None)


def test_parse_whitespace_only_raises():
    with pytest.raises(LLMResponseError, match="empty"):
        parse_llm_response("   \n  ", None)


def test_parse_none_raises():
    with pytest.raises(LLMResponseError, match="None"):
        parse_llm_response(None, None)


def test_parse_invalid_json_raises():
    with pytest.raises(LLMResponseError, match="not valid JSON"):
        parse_llm_response("not json at all", None)


def test_parse_top_level_array_rejected():
    """Stage 5 expects a JSON object — arrays are not accepted."""
    with pytest.raises(LLMResponseError, match="expected object"):
        parse_llm_response("[1, 2, 3]", None)


def test_parse_top_level_string_rejected():
    with pytest.raises(LLMResponseError, match="expected object"):
        parse_llm_response('"just a string"', None)


# ---------------------------------------------------------------------------
# parse_llm_response — schema validation
# ---------------------------------------------------------------------------

def test_parse_required_key_missing_raises():
    schema = {"type": "json", "required": ["doc_type", "confidence"]}
    with pytest.raises(LLMResponseError, match="doc_type"):
        parse_llm_response('{"confidence": 0.9}', schema)


def test_parse_required_keys_present_passes():
    schema = {"type": "json", "required": ["doc_type", "confidence"]}
    payload = parse_llm_response(
        '{"doc_type": "single_method", "confidence": 0.9}',
        schema,
    )
    assert payload == {"doc_type": "single_method", "confidence": 0.9}


def test_parse_enum_violation_raises():
    schema = {
        "type": "json",
        "required": ["doc_type"],
        "enum": {"doc_type": ["single_method", "multi_section"]},
    }
    with pytest.raises(LLMResponseError, match="not in allowed enum"):
        parse_llm_response('{"doc_type": "pwned"}', schema)


def test_parse_enum_match_passes():
    schema = {
        "type": "json",
        "required": ["doc_type"],
        "enum": {"doc_type": ["single_method", "multi_section"]},
    }
    payload = parse_llm_response('{"doc_type": "single_method"}', schema)
    assert payload["doc_type"] == "single_method"


def test_parse_range_below_min_raises():
    schema = {"range": {"confidence": [0.0, 1.0]}}
    with pytest.raises(LLMResponseError, match="out of range"):
        parse_llm_response('{"confidence": -0.1}', schema)


def test_parse_range_above_max_raises():
    schema = {"range": {"confidence": [0.0, 1.0]}}
    with pytest.raises(LLMResponseError, match="out of range"):
        parse_llm_response('{"confidence": 1.5}', schema)


def test_parse_range_within_bounds_passes():
    schema = {"range": {"confidence": [0.0, 1.0]}}
    payload = parse_llm_response('{"confidence": 0.0}', schema)
    assert payload["confidence"] == 0.0
    payload = parse_llm_response('{"confidence": 1.0}', schema)
    assert payload["confidence"] == 1.0


def test_parse_range_non_numeric_raises():
    schema = {"range": {"confidence": [0.0, 1.0]}}
    with pytest.raises(LLMResponseError, match="not numeric"):
        parse_llm_response('{"confidence": "high"}', schema)


def test_parse_no_schema_returns_payload_directly():
    payload = parse_llm_response('{"anything": true}', None)
    assert payload == {"anything": True}


def test_parse_empty_schema_dict_passes():
    payload = parse_llm_response('{"a": 1}', {})
    assert payload == {"a": 1}
