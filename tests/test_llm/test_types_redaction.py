"""Tests for ProviderConfig.to_dict(redact=True) — API key masking.

Plan 19 — Task 10: I-llm-12 (API key plaintext persistence + unredacted display).
The masking strategy is "***" + last 4 chars (matches AWS / Stripe convention).
Keys shorter than 4 chars fall back to "***" (no info leak).
"""
from src.llm.types import ProviderConfig


def test_to_dict_redacts_api_key_long():
    c = ProviderConfig(name="openai", type="openai", api_key="sk-abc1234567890XYZ")
    d = c.to_dict(redact=True)
    assert d["api_key"].startswith("***")
    # Consecutive 4+ chars from the middle of the key must not appear.
    assert "abc1234567890XYZ" not in d["api_key"]
    # Last 4 chars of the key should appear (UX convention).
    assert d["api_key"].endswith("0XYZ")


def test_to_dict_redacts_api_key_short():
    c = ProviderConfig(name="openai", type="openai", api_key="sk-x")
    d = c.to_dict(redact=True)
    assert d["api_key"] == "***"


def test_to_dict_redacts_api_key_empty():
    c = ProviderConfig(name="openai", type="openai", api_key="")
    d = c.to_dict(redact=True)
    # Empty key remains empty; no point masking nothing.
    assert d["api_key"] == ""


def test_to_dict_default_includes_key_for_internal_use():
    c = ProviderConfig(name="openai", type="openai", api_key="sk-x")
    d = c.to_dict()
    assert d["api_key"] == "sk-x"  # internal callers may need it


def test_to_dict_default_explicit_false_includes_key():
    c = ProviderConfig(name="openai", type="openai", api_key="sk-explicit")
    d = c.to_dict(redact=False)
    assert d["api_key"] == "sk-explicit"


def test_to_dict_redact_preserves_other_fields():
    c = ProviderConfig(
        name="anthropic",
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-secret-1234567890",
        default_chat_model="claude-haiku-4-5",
    )
    d = c.to_dict(redact=True)
    assert d["name"] == "anthropic"
    assert d["type"] == "anthropic"
    assert d["base_url"] == "https://api.anthropic.com"
    assert d["default_chat_model"] == "claude-haiku-4-5"
    # Secret body must not leak.
    assert "secret" not in d["api_key"]
    assert "ant-secret" not in d["api_key"]
