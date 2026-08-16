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


def test_complete_reasoning_consumed_all_budget_sets_content_length(monkeypatch):
    """Phase 4 缺陷 F（thinking 占满预算）：glm-5.2 等 reasoning 模型返回
    reasoning_content 但 content 为空且 finish_reason=length → provider 应基
   于 reasoning_content 长度设置 content_length > 0，避免下游调用方
    （_call_with_slot_retry）误判为 0-char 空截断而不升级 max_tokens。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": "",
                    "reasoning_content": "思考中思考中思考中" * 100,
                },
                "finish_reason": "length",
            }],
            "model": "glm-5.2",
        })

    _mock_async_client(monkeypatch, handler)
    p = _make_provider(model="glm-5.2")
    resp = asyncio.run(p.complete(messages=[{"role": "user", "content": "x"}]))
    assert resp.truncated is True
    assert resp.content == ""
    assert resp.content_length > 0, (
        "content_length must be >0 when reasoning_content consumed the budget"
    )


def test_complete_reasoning_not_truncated_ignores_content_length(monkeypatch):
    """reasoning_content 存在但 finish_reason=stop（thinking 正常产出）→
    content_length 保持 0（不干扰正常调用）。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": "{\"key\": \"value\"}",
                    "reasoning_content": "思考过程",
                },
                "finish_reason": "stop",
            }],
            "model": "glm-5.2",
        })

    _mock_async_client(monkeypatch, handler)
    p = _make_provider(model="glm-5.2")
    resp = asyncio.run(p.complete(messages=[{"role": "user", "content": "x"}]))
    assert resp.truncated is False
    assert resp.content_length == 0  # 正常响应，不覆写
