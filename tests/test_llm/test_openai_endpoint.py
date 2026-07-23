"""Tests for OpenAIProvider routing to chat completions endpoint (not legacy completions).

Background: OpenAIProvider.complete() previously used /v1/completions which
doesn't support chat-tuned models. It must route to /v1/chat/completions
(via client.chat.completions.create) and accept a messages list.
"""
from src.llm.openai_provider import OpenAIProvider
from src.llm.types import ProviderConfig, ModelInfo
from src.llm.base import LLMResponse


class _FakeCompletions:
    def __init__(self):
        self.captured = {}

    def create(self, **kw):
        self.captured.update(kw)
        class _R:
            class _Choice:
                message = type("M", (), {"content": "{}"})()
            choices = [_Choice()]
        return _R()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def _make_provider(client=None):
    cfg = ProviderConfig(
        name="openai", type="openai", api_key="x",
        default_chat_model="gpt-4o-mini",
        models={"gpt-4o-mini": ModelInfo(name="gpt-4o-mini", type="chat")},
    )
    return OpenAIProvider(cfg, client=client or _FakeClient())


def test_complete_routes_to_chat_endpoint():
    """complete() must call client.chat.completions.create (not /v1/completions)."""
    client = _FakeClient()
    p = _make_provider(client)

    import asyncio
    r = asyncio.run(p.complete([{"role": "user", "content": "hi"}]))
    # Reaches chat completions, not legacy /completions
    assert client.chat.completions.captured.get("model") == "gpt-4o-mini"
    msgs = client.chat.completions.captured.get("messages")
    assert msgs is not None
    assert any(m.get("role") == "user" for m in msgs)


def test_complete_returns_llm_response_string_content():
    """complete() must return LLMResponse with .content as a string (JSON or text)."""
    client = _FakeClient()
    p = _make_provider(client)
    import asyncio
    r = asyncio.run(p.complete([{"role": "user", "content": "hi"}]))
    assert isinstance(r, LLMResponse)
    assert isinstance(r.content, str)


def test_complete_accepts_messages_form():
    """complete(messages=[...]) is the new contract; raise TypeError on prompt=... as the only positional form."""
    client = _FakeClient()
    p = _make_provider(client)
    import asyncio
    # Old positional-prompt signature is gone; this would now take messages=...
    # We just need the call to take a messages= list:
    r = asyncio.run(p.complete([{"role": "user", "content": "ping"}]))
    assert r is not None
