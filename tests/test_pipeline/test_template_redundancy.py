"""Tests for S6 template-redundancy prompt guidance.

batch-50/audit findings:
- entity pages duplicate `basic_info` and `summary` (LLM sees no distinction)
- concept `examples` lazily filled with "来源未提供具体例子" even when the
  source has concrete examples

The fix is prompt-level: slot-purpose notes distinguishing adjacent slots and
demoting the examples fallback to a true last resort.
"""
from src.pipeline.generator import GENERATOR_PROMPT, UNIFIED_PROMPT


def test_unified_prompt_distinguishes_entity_slots():
    """basic_info vs summary must be told apart, else the LLM duplicates them."""
    assert "basic_info" in UNIFIED_PROMPT
    assert "summary" in UNIFIED_PROMPT
    assert "NOT repeat" in UNIFIED_PROMPT or "NO duplicate" in UNIFIED_PROMPT


def test_unified_prompt_examples_last_resort():
    """examples fallback must be demoted to a last resort, not a lazy out."""
    assert "来源未提供具体例子" in UNIFIED_PROMPT
    assert "only when the source truly" in UNIFIED_PROMPT.lower() \
        or "仅在源文档确实没有" in UNIFIED_PROMPT


def test_generator_prompt_examples_last_resort():
    """The GENERATOR_PROMPT (two-step path) gets the same demotion."""
    assert "来源未提供具体例子" in GENERATOR_PROMPT
    assert "truly" in GENERATOR_PROMPT.lower() or "确实没有" in GENERATOR_PROMPT
