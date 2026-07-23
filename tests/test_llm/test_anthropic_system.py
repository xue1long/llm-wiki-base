"""Test: Anthropic system messages are lifted to top-level 'system' field.

Background: AnthropicProvider.chat() previously stripped system-role messages
silently (data loss). The Anthropic API supports a top-level 'system' field
which is the canonical place for system instructions; messages array must NOT
contain role='system' entries.
"""
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.types import ProviderConfig, ModelInfo
from src.llm.base import LLMResponse


class _FakeMessages:
    def __init__(self):
        self.captured = {}

    def create(self, **kw):
        self.captured.update(kw)
        class _R:
            content = [type("C", (), {"text": "{}"})()]
        return _R()


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _make_provider(client=None):
    cfg = ProviderConfig(
        name="anthropic", type="anthropic", api_key="x",
        default_chat_model="claude-3-5-sonnet",
        models={"claude-3-5-sonnet": ModelInfo(name="claude-3-5-sonnet", type="chat")},
    )
    return AnthropicProvider(cfg, client=client or _FakeClient())


def test_system_message_promoted_to_top_level():
    """A system-role message in `messages` must be lifted into top-level `system`."""
    client = _FakeClient()
    p = _make_provider(client)
    import asyncio
    r = asyncio.run(p.complete([
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ]))
    # Top-level system field set
    assert client.messages.captured.get("system") == "be terse"
    # No system-role messages leaked into messages array
    msgs = client.messages.captured.get("messages", [])
    assert all(m["role"] != "system" for m in msgs)
    assert isinstance(r, LLMResponse)


def test_multiple_system_messages_joined():
    """Multiple system-role messages must be joined with double-newline into `system`."""
    client = _FakeClient()
    p = _make_provider(client)
    import asyncio
    r = asyncio.run(p.complete([
        {"role": "system", "content": "be terse"},
        {"role": "system", "content": "no code"},
        {"role": "user", "content": "hi"},
    ]))
    assert client.messages.captured.get("system") == "be terse\n\nno code"
    msgs = client.messages.captured.get("messages", [])
    assert all(m["role"] != "system" for m in msgs)


def test_no_system_message_no_top_level_field():
    """When no system message is present, do not add a system field (or set None)."""
    client = _FakeClient()
    p = _make_provider(client)
    import asyncio
    r = asyncio.run(p.complete([{"role": "user", "content": "hi"}]))
    # The 'system' key may be absent; if present must be falsy / None / empty string.
    assert client.messages.captured.get("system") in (None, "")
    msgs = client.messages.captured.get("messages", [])
    assert all(m["role"] != "system" for m in msgs)
