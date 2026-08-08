"""Tests for OpenAIProvider.check_response_format() and its health_check integration.

Uses httpx.MockTransport to simulate provider responses, following the
pattern in test_ollama_provider.py. The provider constructs its own
httpx.AsyncClient internally, so we monkeypatch `httpx.AsyncClient` to
return a mock-transport client.
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
    """Patch httpx.AsyncClient so provider-internal clients use a mock transport."""
    from httpx import AsyncClient, MockTransport

    def _factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        return AsyncClient(transport=MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def test_response_format_accepted(monkeypatch):
    """Provider returns 200 → response_format check passes."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    result = asyncio.run(p.check_response_format())
    assert result["ok"] is True
    assert "accepted" in result["detail"]


def test_response_format_rejected_400(monkeypatch):
    """Provider returns 400 'invalid response_format' → check fails."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text='{"error": "invalid response_format, should be json_object/json_schema/text/url/b64_json"}',
        )

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    result = asyncio.run(p.check_response_format())
    assert result["ok"] is False
    assert "HTTP 400" in result["detail"]
    assert "empty stub pages" in result["detail"]


def test_response_format_400_other_reason(monkeypatch):
    """400 for an unrelated reason (e.g. bad api key) → check passes (not a response_format issue)."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"error": "invalid api key"}')

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    result = asyncio.run(p.check_response_format())
    assert result["ok"] is True


def test_response_format_connection_error(monkeypatch):
    """Connection error → check fails with detail message."""
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    result = asyncio.run(p.check_response_format())
    assert result["ok"] is False


def test_health_check_includes_response_format_ok(monkeypatch):
    """health_check() reports response_format_ok=True when probe accepts the schema."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    result = asyncio.run(p.health_check())
    assert result["ok"] is True
    assert result["response_format_ok"] is True
    assert "response_format_detail" in result


def test_health_check_reports_response_format_rejected(monkeypatch):
    """health_check() reports response_format_ok=False when the probe returns 400."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})
        return httpx.Response(400, text='{"error": "invalid response_format"}')

    _mock_async_client(monkeypatch, handler)
    p = _make_provider()
    result = asyncio.run(p.health_check())
    assert result["ok"] is True
    assert result["response_format_ok"] is False