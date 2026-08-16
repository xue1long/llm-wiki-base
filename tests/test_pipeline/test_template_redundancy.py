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
    """examples fallback must be demoted to a last resort, not a lazy out.

    Phase 3 实测修复：examples 无例子时的 fallback 统一为
    ``来源未详述此方面``（与 ALL OTHERS 一致，不在 lint 占位符列表），
    消除 M4 占位符 ERROR 与 generator fallback 的冲突。
    """
    assert "来源未详述此方面" in UNIFIED_PROMPT
    assert "来源未提供具体例子" not in UNIFIED_PROMPT
    assert "only when the source truly" in UNIFIED_PROMPT.lower() \
        or "仅在源文档确实没有" in UNIFIED_PROMPT


def test_generator_prompt_examples_last_resort():
    """The GENERATOR_PROMPT (two-step path) gets the same demotion."""
    assert "来源未详述此方面" in GENERATOR_PROMPT
    assert "来源未提供具体例子" not in GENERATOR_PROMPT
    assert "truly" in GENERATOR_PROMPT.lower() or "确实没有" in GENERATOR_PROMPT
