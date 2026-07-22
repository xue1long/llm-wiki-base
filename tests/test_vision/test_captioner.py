"""Tests for VisionCaptioner."""
import asyncio
import json

from src.llm.base import LLMResponse
from src.vision.captioner import VisionCaptioner
from src.vision.extractor import ExtractedImage


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def complete(self, prompt, **kwargs):
        self.calls += 1
        return LLMResponse(content=json.dumps(self.payload), model="fake", usage={})

    async def close(self):
        pass


def _img(task_id="t", idx=0, png_bytes=b"\x89PNG\r\n\x1a\n"):
    return ExtractedImage(
        task_id=task_id, index=idx, bytes=png_bytes,
        mime_type="image/png",
        source_page=f"wiki/sources/{task_id}.md",
        context="page context text",
    )


def test_caption_one_returns_caption(monkeypatch):
    payload = {
        "caption": "A diagram showing the relationship between X and Y.",
        "alt_text": "diagram",
        "entities": ["X", "Y"],
        "confidence": 0.95,
    }
    provider = FakeProvider(payload)
    # VisionCaptioner imports create_llm_provider as a name; patch it at module level.
    from src.llm import provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name, model_override=None: provider)
    from src.vision import captioner as cap_mod
    monkeypatch.setattr(cap_mod, "create_llm_provider", lambda name, model_override=None: provider)

    captioner = VisionCaptioner("openai", "fake-model")
    cap = asyncio.run(captioner.caption_one(_img("a", 0)))
    assert cap.caption.startswith("A diagram")
    assert cap.alt_text == "diagram"
    assert "X" in cap.entities
    assert cap.confidence == 0.95
    assert cap.generated_at > 0


def test_caption_batch_concurrent(monkeypatch):
    payload = {
        "caption": "c", "alt_text": "a",
        "entities": [], "confidence": 0.5,
    }
    provider = FakeProvider(payload)
    from src.llm import provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name, model_override=None: provider)
    from src.vision import captioner as cap_mod
    monkeypatch.setattr(cap_mod, "create_llm_provider", lambda name, model_override=None: provider)

    captioner = VisionCaptioner("openai", "fake-model")
    images = [_img("t", i) for i in range(5)]
    captions = asyncio.run(captioner.caption_batch(images))
    assert len(captions) == 5
    assert provider.calls == 5


def test_caption_one_handles_bad_payload(monkeypatch):
    """Non-JSON content → caption falls back without raising."""
    class BadProvider(FakeProvider):
        async def complete(self, prompt, **kwargs):
            self.calls += 1
            return LLMResponse(content="not json", model="x", usage={})
    provider = BadProvider({})
    from src.llm import provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name, model_override=None: provider)
    from src.vision import captioner as cap_mod
    monkeypatch.setattr(cap_mod, "create_llm_provider", lambda name, model_override=None: provider)
    captioner = VisionCaptioner("openai", "fake-model")
    cap = asyncio.run(captioner.caption_one(_img("a", 0)))
    assert cap.caption == ""
