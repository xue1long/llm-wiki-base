"""Small JSON state file for resumable chapter batches."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .polish_llm import GeneratedChapter, GeneratedSection


class BatchStateError(ValueError):
    pass


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        Path(name).replace(path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _chapter_to_dict(chapter: GeneratedChapter) -> dict[str, Any]:
    return {
        "chapter_id": chapter.chapter_id,
        "content_status": chapter.content_status,
        "failure_reason": chapter.failure_reason,
        "failure_code": chapter.failure_code,
        "editorial_markers": list(chapter.editorial_markers),
        "prompt_hash": chapter.prompt_hash,
        "sections": [{
            "section_id": section.section_id,
            "title": section.title,
            "body": section.body,
            "source_page_ids": list(section.source_page_ids),
            "status": section.status,
        } for section in chapter.sections],
    }


def chapter_from_dict(payload: dict[str, Any]) -> GeneratedChapter:
    if not isinstance(payload, dict) or not isinstance(payload.get("chapter_id"), str):
        raise BatchStateError("invalid completed chapter")
    return GeneratedChapter(
        payload["chapter_id"],
        tuple(GeneratedSection(
            str(item["section_id"]), str(item["title"]), str(item["body"]),
            tuple(str(page_id) for page_id in item["source_page_ids"]), str(item.get("status", "normal")),
        ) for item in payload.get("sections", ()) if isinstance(item, dict)),
        str(payload.get("content_status", "")),
        payload.get("failure_reason"), str(payload.get("failure_code", "")),
        tuple(str(item) for item in payload.get("editorial_markers", ())),
        payload.get("prompt_hash"),
    )


def load_or_create(
    path: Path,
    *,
    snapshot_id: str,
    chapter_ids: tuple[str, ...],
    batch_size: int,
    max_attempts: int,
    max_llm_calls: int,
    resume: bool,
) -> dict[str, Any]:
    if resume and path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise BatchStateError(f"batch state unreadable: {path}") from exc
        if not isinstance(state, dict) or state.get("snapshot_id") != snapshot_id:
            raise BatchStateError("batch state snapshot mismatch")
        if tuple(state.get("chapter_ids", ())) != chapter_ids:
            raise BatchStateError("batch state chapter plan mismatch")
        if not isinstance(state.get("chapters"), dict):
            raise BatchStateError("batch state chapters missing")
        return state
    state = {
        "schema_version": "book-batch-state-v1",
        "snapshot_id": snapshot_id,
        "chapter_ids": list(chapter_ids),
        "batch_size": batch_size,
        "max_attempts": max_attempts,
        "budget": {
            "minimum_calls": len(chapter_ids),
            "configured_max_calls": len(chapter_ids) * (1 + max_attempts),
            "max_llm_calls": max_llm_calls,
            "actual_calls": 0,
        },
        "chapters": {},
    }
    _write(path, state)
    return state


def save(path: Path, state: dict[str, Any]) -> None:
    _write(path, state)


def record(path: Path, state: dict[str, Any], chapter: GeneratedChapter, *, input_hash: str, calls: int) -> None:
    state["chapters"][chapter.chapter_id] = {
        "status": chapter.content_status,
        "input_hash": input_hash,
        "calls": calls,
        "result": _chapter_to_dict(chapter),
    }
    state["budget"]["actual_calls"] = calls
    save(path, state)


__all__ = ["BatchStateError", "chapter_from_dict", "load_or_create", "record", "save"]
