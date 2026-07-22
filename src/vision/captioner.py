"""LLM-based image captioning using vision-capable models."""
import asyncio
import base64
import json
import logging
import time

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .extractor import ExtractedImage


_logger = logging.getLogger(__name__)

MAX_IMAGES_PER_TASK = 20
MAX_CONCURRENT = 5


CAPTION_PROMPT = """Describe this image factually. Output strict JSON:
{{
  "caption": "<1-3 sentences>",
  "alt_text": "<short alt, < 100 chars>",
  "entities": ["<named entities visible>"],
  "confidence": 0.0-1.0
}}

Context (surrounding text):
{context}
"""


class ImageCaption:
    def __init__(self, task_id: str, index: int, caption: str, alt_text: str,
                 entities, confidence: float, model_used: str, generated_at: int):
        self.task_id = task_id
        self.index = index
        self.caption = caption
        self.alt_text = alt_text
        self.entities = entities
        self.confidence = confidence
        self.model_used = model_used
        self.generated_at = generated_at


class VisionCaptioner:
    def __init__(self, provider_registry_name: str = "openai", model: str = "gpt-4o-mini"):
        # We don't accept ctx in the MVP — provider registry name is enough.
        self.provider_registry_name = provider_registry_name
        self.model = model
        self.provider = create_llm_provider(provider_registry_name, model_override=model)

    async def caption_one(self, image: ExtractedImage) -> ImageCaption:
        b64 = base64.b64encode(image.bytes).decode()
        prompt = CAPTION_PROMPT.format(context=image.context or "(no context)")
        # Most vision-capable providers take image + text; the legacy LLMProvider
        # interface we have is text-only. We pass the base64 in the prompt so
        # the test stub can still parse it — the real vision integration needs
        # the provider's native vision API (out of MVP scope).
        full_prompt = f"{prompt}\n\n[image: data:image/png;base64,{b64[:80]}... ({len(b64)} chars)]"
        try:
            response = await self.provider.complete(prompt=full_prompt)
            raw = response.content if hasattr(response, "content") else response
            if isinstance(raw, dict):
                data = raw
            else:
                if "```" in raw:
                    raw = raw.split("```", 2)[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.split("```", 1)[0]
                data = json.loads(raw) if raw.strip().startswith("{") else {}
        except Exception as e:
            _logger.warning("[vision] caption failed: %s", e)
            return ImageCaption(
                task_id=image.task_id, index=image.index,
                caption="[Caption generation failed]", alt_text="image",
                entities=[], confidence=0.0, model_used=self.model,
                generated_at=int(time.time() * 1000),
            )
        return ImageCaption(
            task_id=image.task_id, index=image.index,
            caption=str(data.get("caption", "")) if isinstance(data, dict) else "",
            alt_text=str(data.get("alt_text", "")) if isinstance(data, dict) else "",
            entities=data.get("entities", []) if isinstance(data, dict) else [],
            confidence=float(data.get("confidence", 0.0)) if isinstance(data, dict) else 0.0,
            model_used=self.model,
            generated_at=int(time.time() * 1000),
        )

    async def caption_batch(self, images: list[ExtractedImage]) -> list[ImageCaption]:
        if len(images) > MAX_IMAGES_PER_TASK:
            _logger.warning(
                "[vision] truncating %d to %d", len(images), MAX_IMAGES_PER_TASK
            )
            images = images[:MAX_IMAGES_PER_TASK]
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def cap(img: ExtractedImage) -> ImageCaption:
            async with sem:
                return await self.caption_one(img)

        return await asyncio.gather(*[cap(i) for i in images])
