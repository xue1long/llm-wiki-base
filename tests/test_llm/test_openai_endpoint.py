"""Tests for OpenAIProvider routing to chat completions endpoint (not legacy completions).

Background: OpenAIProvider.complete() previously used /v1/completions which
doesn't support chat-tuned models. It must route to /v1/chat/completions
(via client.chat.completions.create) and accept a messages list.
"""
from src.llm.openai_provider import OpenAIProvider, _strip_reasoning
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


class TestStripReasoning:
    """Unit tests for _strip_reasoning — strips <think> blocks from model output."""

    def test_strips_single_think_block(self):
        content = "<think>some reasoning here</think>\n\n{\"key\": \"value\"}"
        result = _strip_reasoning(content)
        assert result == '{"key": "value"}'

    def test_strips_multiline_think_block(self):
        content = "<think>\nLet me analyze the document.\nKey points found: 3\n</think>\n\n{\"pages\": []}"
        result = _strip_reasoning(content)
        assert result == '{"pages": []}'

    def test_no_think_block_passes_through(self):
        content = '{"pages": [{"title": "Test"}]}'
        result = _strip_reasoning(content)
        assert result == content

    def test_strips_think_block_no_trailing_newlines(self):
        content = "<think>brief</think>{\"x\": 1}"
        result = _strip_reasoning(content)
        assert result == '{"x": 1}'

    def test_empty_content(self):
        assert _strip_reasoning("") == ""

    def test_only_think_block(self):
        content = "<think>just reasoning</think>"
        result = _strip_reasoning(content)
        assert result == ""


def test_post_json_non_utf8_error_body_preserves_http_status_cause(monkeypatch):
    """GBK-encoded 5xx error body must not mask the HTTPStatusError cause.

    Regression: phase4 batch 14 — the upstream (sfkey) returned 500/502/524
    error pages whose bodies are GBK (non-UTF-8).  The old snippet line
    ``(r.text or "")[:200]`` raised UnicodeDecodeError inside the except
    handler, replacing the HTTPStatusError cause, so ``classify_error`` saw a
    bare UnicodeDecodeError → "permanent" → no retry → the raw file was
    marked permanently failed even though the failure was a transient 5xx.
    """
    import asyncio

    import httpx

    from src.llm.openai_provider import OpenAIProvider
    from src.llm.types import ProviderConfig
    from src.pipeline.retry import classify_error

    gbk_body = "服务繁忙，请稍后重试".encode("gbk")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            content=gbk_body,
            headers={"Content-Type": "text/html; charset=gbk"},
        )

    from httpx import AsyncClient, MockTransport

    def _factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        return AsyncClient(transport=MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)

    cfg = ProviderConfig(
        name="openai", type="openai", api_key="sk-test",
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    p = OpenAIProvider(cfg)

    exc = None
    try:
        asyncio.run(p._post_json("https://api.openai.com/v1/chat/completions", {"a": 1}))
    except Exception as e:  # pragma: no cover - assertion below
        exc = e
    assert exc is not None
    # The RuntimeError message must still be readable (body snippet decoded
    # with errors="replace", not a UnicodeDecodeError).
    assert str(exc).startswith("HTTP 500")
    # The HTTPStatusError must be preserved as the root cause so the retry
    # classifier treats the 5xx as transient, not permanent.
    root = exc
    while root.__cause__ is not None:
        root = root.__cause__
    assert isinstance(root, httpx.HTTPStatusError)
    assert root.response.status_code == 500
    assert classify_error(exc) == "transient"


def test_complete_undecodable_200_body_returns_truncated(monkeypatch):
    """A 2xx body cut mid-multibyte (max_tokens cap) must surface as a
    truncated LLMResponse, not raise — so the generator escalates max_tokens.

    Regression: phase4 batch 14 — 必备资料网络小说写作宝典如何做有生存能力的作者.md
    failed 4 runs because an undecodable body made complete() raise a generic
    RuntimeError (classified transient → retried with the SAME max_tokens →
    deterministic failure). Returning truncated=True lets _call_with_slot_retry
    escalate 8192 → 16384 → 32768 exactly like finish_reason="length".
    """
    import asyncio

    import httpx

    from src.llm.openai_provider import OpenAIProvider
    from src.llm.types import ProviderConfig

    # Body cut in the middle of a 3-byte CJK char: 0xe6 0x9c is an
    # incomplete sequence (needs a third byte).
    truncated_body = b'{"choices":[{"message":{"content":"\xe6\x9c"}}]}'

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=truncated_body)

    from httpx import AsyncClient, MockTransport

    def _factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        return AsyncClient(transport=MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)

    cfg = ProviderConfig(
        name="openai", type="openai", api_key="sk-test",
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    p = OpenAIProvider(cfg)

    resp = asyncio.run(p.complete([{"role": "user", "content": "hi"}]))
    assert resp.truncated is True
    assert resp.content_length > 0
