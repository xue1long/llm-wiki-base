"""Tests for OpenAIProvider truncation detection (finish_reason="length")
and max_tokens passthrough.

Regression for the batch-10 observation: the generator never sent
max_tokens, the endpoint's default cap truncated long multi-page JSON
responses mid-string, and the truncation signal (finish_reason="length")
was discarded by the provider.
"""
import asyncio

import httpx
import pytest

from src.llm.openai_provider import OpenAIProvider
from src.llm.types import ProviderConfig


def _make_provider(model: str = "gpt-4o-mini") -> OpenAIProvider:
    cfg = ProviderConfig(
        name="openai", type="openai", api_key="sk-test",
        base_url="https://api.openai.com/v1",
        default_chat_model=model,
    )
    return OpenAIProvider(cfg)


def _mock_async_client(monkeypatch, handler):
    from httpx import AsyncClient, MockTransport

    def _factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        return AsyncClient(transport=MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def test_complete_marks_truncated_when_finish_reason_length(monkeypatch):
    """finish_reason='length' → LLMResponse.truncated is True."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{
                "message": {"content": '{"pages": [{"id": "x"'},
                "finish_reason": "length",
            }],
            "model": "gpt-4o-mini",
        })

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    resp = asyncio.run(p.complete(messages=[{"role": "user", "content": "x"}]))
    assert resp.truncated is True
    assert resp.content.startswith('{"pages"')


def test_complete_not_truncated_when_finish_reason_stop(monkeypatch):
    """finish_reason='stop' → LLMResponse.truncated is False."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{
                "message": {"content": '{"pages": []}'},
                "finish_reason": "stop",
            }],
            "model": "gpt-4o-mini",
        })

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    resp = asyncio.run(p.complete(messages=[{"role": "user", "content": "x"}]))
    assert resp.truncated is False


def test_complete_not_truncated_when_finish_reason_missing(monkeypatch):
    """Endpoints that omit finish_reason → truncated stays False (no crash)."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"pages": []}'}}],
            "model": "gpt-4o-mini",
        })

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    resp = asyncio.run(p.complete(messages=[{"role": "user", "content": "x"}]))
    assert resp.truncated is False


def test_complete_forwards_max_tokens(monkeypatch):
    """max_tokens kwarg reaches the request body."""
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode()
        seen.append(body)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "model": "gpt-4o-mini",
        })

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    asyncio.run(p.complete(
        messages=[{"role": "user", "content": "x"}], max_tokens=16384,
    ))
    assert len(seen) == 1
    assert '"max_tokens":16384' in seen[0]
