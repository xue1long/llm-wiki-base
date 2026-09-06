"""Optional, bounded LLM editorial layer. Source blocks are never rewritten."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from .aggregator import ChapterDraft
from .polish_validate import validate_polished_chapter


@dataclass(frozen=True)
class PolishedChapter:
    chapter_id: str
    block_order: tuple[str, ...]
    editorial_sections: tuple[str, ...]
    polished: bool
    failure_reason: str | None
    transition_in: str | None = None
    transition_out: str | None = None
    body: str | None = None


def _fallback(draft: ChapterDraft, reason: str) -> PolishedChapter:
    return PolishedChapter(draft.chapter_id, draft.intra_chapter_order or draft.page_ids, (), False, reason)


async def polish_chapter(
    draft: ChapterDraft,
    provider: Any,
    *,
    token_budget: int = 800,
    retries: int = 1,
) -> PolishedChapter:
    """Ask for editorial metadata only; malformed or over-budget output fails closed."""
    if token_budget <= 0:
        return _fallback(draft, "invalid_token_budget")
    prompt = json.dumps({
        "chapter_id": draft.chapter_id,
        "block_ids": list(draft.block_ids),
        "page_order": list(draft.intra_chapter_order or draft.page_ids),
        "task": "Return JSON with block_order, editorial_sections, transition_in, transition_out. Do not return body text.",
    }, ensure_ascii=False)
    response = None
    for attempt in range(retries + 1):
        try:
            response = await provider.complete([{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            content = getattr(response, "content", "")
            if getattr(response, "truncated", False) or not content.strip():
                raise ValueError("truncated_or_empty_response")
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError("response_not_object")
            result = PolishedChapter(
                draft.chapter_id,
                tuple(payload.get("block_order", ())),
                tuple(payload.get("editorial_sections", ())),
                True,
                None,
                payload.get("transition_in"),
                payload.get("transition_out"),
            )
            errors = validate_polished_chapter(draft, result)
            return result if not errors else _fallback(draft, ",".join(errors))
        except Exception as exc:
            if attempt < retries:
                await asyncio.sleep(0)
                continue
            return _fallback(draft, str(exc))
    return _fallback(draft, "llm_failed")


__all__ = ["PolishedChapter", "polish_chapter"]
