"""Bounded optional LLM naming for deterministic chapter assignments."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from .model import WikiSnapshot
from .outline_validate import SCHEMA_VERSION, validate_outline


class OutlinePlanningError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, errors: tuple[str, ...] = ()):
        super().__init__(message)
        self.retryable, self.errors = retryable, errors


def _rule_chapter(snapshot: WikiSnapshot, chapter_id: str, page_ids: tuple[str, ...]) -> dict[str, Any]:
    pages = {p.page_id: p for p in snapshot.pages}
    return {"chapter_id": chapter_id, "title": " / ".join(pages[i].title for i in page_ids),
            "page_ids": list(page_ids), "overview_refs": [page_ids[0]], "confidence": 1.0}


def _transient(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    return status in (408, 429, 500, 502, 503, 504) or isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError))


async def _ask(provider: Any, prompt: str, *, retries: int = 2) -> dict[str, Any]:
    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            try:
                response = await provider.complete([{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            except (TypeError, NotImplementedError):
                response = await provider.complete([{"role": "user", "content": prompt}])
            if getattr(response, "truncated", False) or not getattr(response, "content", "").strip():
                raise OutlinePlanningError("truncated or empty outline response", retryable=True)
            payload = json.loads(response.content)
            if not isinstance(payload, dict):
                raise OutlinePlanningError("outline response must be a JSON object", retryable=True)
            return payload
        except OutlinePlanningError as exc:
            last = exc
        except Exception as exc:  # provider errors are classified without coupling to SDK types
            last = exc
            if not _transient(exc):
                raise OutlinePlanningError(str(exc), retryable=False) from exc
        if attempt < retries:
            await asyncio.sleep(0)
    raise OutlinePlanningError(str(last or "outline planning failed"), retryable=True) from last


async def plan_outline(snapshot: WikiSnapshot, chapter_chunks: dict[str, tuple[str, ...]], provider: Any, *, context_window: int, token_budget: int) -> list[dict]:
    """Name fixed chunks; malformed or unavailable LLM output fails closed."""
    if context_window <= 0 or token_budget <= 0:
        raise ValueError("context_window and token_budget must be positive")
    pages = {p.page_id: p for p in snapshot.pages}
    volumes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    spent = 0
    llm_chunks = 0
    fallback_chunks = 0
    for chapter_id in sorted(chapter_chunks):
        ids = tuple(chapter_chunks[chapter_id])
        if not ids or any(i not in pages for i in ids):
            raise OutlinePlanningError("chapter contains unknown or empty page IDs")
        volume_id = chapter_id.rsplit(":", 1)[0]
        rule = _rule_chapter(snapshot, chapter_id, ids)
        prompt = json.dumps({"chapter_id": chapter_id, "pages": [{"page_id": i, "title": pages[i].title, "summary": pages[i].summary} for i in ids]}, ensure_ascii=False)
        estimate = max(1, len(prompt) // 4)
        if spent + estimate > token_budget:
            volumes[volume_id].append(rule)
            fallback_chunks += 1
            continue
        try:
            proposed = await _ask(provider, prompt)
            if proposed.get("chapter_id") != chapter_id or proposed.get("page_ids") != list(ids):
                raise OutlinePlanningError("LLM attempted to change fixed page assignment")
            proposed["overview_refs"] = [r for r in proposed.get("overview_refs", []) if r in ids]
            if not proposed["overview_refs"]:
                raise OutlinePlanningError("overview_refs do not resolve to chunk pages")
            proposed.setdefault("title", rule["title"])
            volumes[volume_id].append(proposed)
            llm_chunks += 1
        except OutlinePlanningError:
            volumes[volume_id].append(rule)
            fallback_chunks += 1
        spent += estimate
    generation_mode = "llm" if llm_chunks and not fallback_chunks else ("llm_partial" if llm_chunks else "rule_fallback")
    outlines = [{"schema_version": SCHEMA_VERSION, "snapshot_id": snapshot.snapshot_id,
                 "generation_mode": generation_mode,
                 "fallback_chunks": fallback_chunks,
                 "volumes": [{"volume_id": vid, "title": vid, "chapters": chapters, "is_fallback": vid == "fallback"}
                              for vid, chapters in sorted(volumes.items())]}]
    report = validate_outline(snapshot, outlines)
    if not report.ok:
        raise OutlinePlanningError("generated outline failed validation", errors=tuple(e.code for e in report.errors))
    return outlines


__all__ = ["OutlinePlanningError", "plan_outline"]
