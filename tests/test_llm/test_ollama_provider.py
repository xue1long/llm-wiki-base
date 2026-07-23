"""Tests for OllamaProvider using a fake httpx transport."""
import httpx

from src.llm.types import ProviderConfig
from src.llm.ollama_provider import OllamaProvider


def _fake_transport(handler):
    """Wrap a sync handler into an httpx.MockTransport."""
    return httpx.MockTransport(handler)


def test_complete_returns_content():
    cfg = ProviderConfig(
        name="o", type="ollama", base_url="http://x", default_chat_model="m",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/chat"
        return httpx.Response(200, json={
            "message": {"content": "hi"},
            "prompt_eval_count": 3,
            "eval_count": 7,
        })

    p = OllamaProvider(cfg)
    p.client = httpx.AsyncClient(transport=_fake_transport(handler))
    import asyncio
    r = asyncio.run(p.complete("hello"))
    assert r.content == "hi"
    assert r.usage["prompt_tokens"] == 3
    assert r.usage["completion_tokens"] == 7
    asyncio.run(p.close())


def test_complete_uses_json_mode():
    cfg = ProviderConfig(
        name="o", type="ollama", base_url="http://x", default_chat_model="m",
    )

    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={"message": {"content": "{}"}})

    p = OllamaProvider(cfg)
    p.client = httpx.AsyncClient(transport=_fake_transport(handler))
    import asyncio
    asyncio.run(p.complete("hello", response_format={"type": "object"}))
    asyncio.run(p.close())
    assert captured["body"].get("format") == "json"


def test_health_check_reachable():
    cfg = ProviderConfig(name="o", type="ollama", base_url="http://x", default_chat_model="m")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "0.5.0"})

    p = OllamaProvider(cfg)
    p.client = httpx.AsyncClient(transport=_fake_transport(handler))
    import asyncio
    h = asyncio.run(p.health_check())
    asyncio.run(p.close())
    # Audit I2: standardised dict shape {"ok": bool, "detail": str, "version": str|None}.
    assert h["ok"] is True
    assert h["version"] == "0.5.0"


def test_health_check_unreachable():
    cfg = ProviderConfig(name="o", type="ollama", base_url="http://nonexistent", default_chat_model="m")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, text="fail")

    p = OllamaProvider(cfg)
    p.client = httpx.AsyncClient(transport=_fake_transport(handler))
    import asyncio
    h = asyncio.run(p.health_check())
    asyncio.run(p.close())
    # Audit I2: standardised dict shape — `ok` not `reachable`.
    assert h["ok"] is False
