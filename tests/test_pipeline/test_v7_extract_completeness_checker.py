"""T2.2: Stage 3 completeness_checker — pure-LLM async + P5 decoupling."""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.completeness_checker import (
    check_completeness,
    _payload_to_result,
    _resolve_completeness_template,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient


# ---------------------------------------------------------------------------
# _payload_to_result helper
# ---------------------------------------------------------------------------

def test_payload_to_result_complete_true():
    assert _payload_to_result({"complete": True, "reason": "good"}) == (True, "good")


def test_payload_to_result_complete_false():
    assert _payload_to_result({"complete": False, "reason": "no body"}) == (False, "no body")


def test_payload_to_result_defaults_reason():
    assert _payload_to_result({"complete": True}) == (True, "")


def test_payload_to_result_coerces_truthy_non_bool():
    """The LLM might return true/false as JSON — both must work."""
    assert _payload_to_result({"complete": 1, "reason": ""}) == (True, "")
    assert _payload_to_result({"complete": 0, "reason": ""}) == (False, "")


# ---------------------------------------------------------------------------
# _resolve_completeness_template helper
# ---------------------------------------------------------------------------

def test_resolve_completeness_template_uses_bundled():
    template = _resolve_completeness_template(project_root=None)
    assert template.prompt_kind == "completeness"
    assert template.source == "bundled"


# ---------------------------------------------------------------------------
# check_completeness — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_completeness_returns_true():
    fake = FakeLLMClient()
    fake.script("completeness", '{"complete": true, "reason": "substantial body"}')

    complete, reason = await check_completeness(
        "long article body here",
        doc_type_hint="single_method",
        llm=fake,
        project_root=None,
    )
    assert complete is True
    assert reason == "substantial body"


@pytest.mark.asyncio
async def test_check_completeness_returns_false():
    fake = FakeLLMClient()
    fake.script("completeness", '{"complete": false, "reason": "intro only"}')

    complete, reason = await check_completeness(
        "title\n\nshort intro",
        doc_type_hint="multi_section",
        llm=fake,
        project_root=None,
    )
    assert complete is False
    assert reason == "intro only"


# ---------------------------------------------------------------------------
# P5: doc_type_hint is SOFT — Stage 3 judges independently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p5_stage3_ignores_stage1_incomplete_hint():
    """P5: Stage 1 says 'incomplete' but Stage 3 should re-judge
    independently — the LLM might find a substantial body."""
    fake = FakeLLMClient()
    fake.script(
        "completeness",
        '{"complete": true, "reason": "actually has a body"}',
    )

    complete, _ = await check_completeness(
        "this article has a real body with content",
        doc_type_hint="incomplete",  # Stage 1 said incomplete
        llm=fake,
        project_root=None,
    )
    # Stage 3 says complete — the soft hint did not short-circuit.
    assert complete is True


# ---------------------------------------------------------------------------
# P2: failure modes — never raise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_completeness_returns_false_on_invalid_json():
    fake = FakeLLMClient()
    fake.script("completeness", "not json at all")
    fake.script("completeness", "still not json")
    fake.script("completeness", "{not even valid}")

    complete, reason = await check_completeness(
        "body", doc_type_hint="x", llm=fake, project_root=None,
    )
    assert complete is False
    assert "stage3_failed" in reason
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_check_completeness_returns_false_on_schema_violation():
    """complete is missing → LLMResponseError → retry → False."""
    fake = FakeLLMClient()
    fake.script("completeness", '{"reason": "no complete field"}')

    complete, _ = await check_completeness(
        "body", doc_type_hint="x", llm=fake, project_root=None,
    )
    assert complete is False


@pytest.mark.asyncio
async def test_check_completeness_succeeds_after_two_invalid_retries():
    fake = FakeLLMClient()
    fake.script("completeness", "")
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script("completeness", '{"complete": true, "reason": "ok"}')

    complete, _ = await check_completeness(
        "body", doc_type_hint="x", llm=fake, project_root=None,
    )
    assert complete is True
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_check_completeness_handles_llm_raising_exception():
    """An LLM provider exception must NOT propagate — P2 invariant."""
    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise RuntimeError("simulated LLM outage")

    complete, reason = await check_completeness(
        "body", doc_type_hint="x", llm=_ExplodingFake(),
        project_root=None,
    )
    assert complete is False
    assert "stage3_failed" in reason


# ---------------------------------------------------------------------------
# audit logging — one LLM call per attempt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_completeness_one_call_per_attempt():
    fake = FakeLLMClient()
    fake.script("completeness", '{"complete": true, "reason": "r"}')

    await check_completeness("body", doc_type_hint="x", llm=fake,
                             project_root=None)
    assert len(fake.calls) == 1
    assert fake.calls[0]["prompt_kind"] == "completeness"
