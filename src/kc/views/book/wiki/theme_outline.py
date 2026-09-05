"""Theme-first outline planning and summary-only Wiki placement."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any


class ThemeOutlineError(ValueError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _complete(provider: Any, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = json.dumps(payload, ensure_ascii=False)
    try:
        response = await provider.complete([{"role": "user", "content": prompt}], response_format={"type": "json_object"})
    except (TypeError, NotImplementedError):
        response = await provider.complete([{"role": "user", "content": prompt}])
    content = getattr(response, "content", "")
    if not content or getattr(response, "truncated", False):
        raise ThemeOutlineError("empty or truncated LLM outline response")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ThemeOutlineError("LLM outline response must be an object")
    return result


def _canonical_theme(payload: dict[str, Any], *, theme: str, purpose: str) -> dict[str, Any]:
    volumes = payload.get("volumes")
    if not isinstance(volumes, list) or not volumes:
        raise ThemeOutlineError("theme outline must contain at least one volume")
    result_volumes: list[dict[str, Any]] = []
    chapter_ids: set[str] = set()
    for vi, raw_volume in enumerate(volumes, 1):
        if not isinstance(raw_volume, dict) or not str(raw_volume.get("title", "")).strip():
            raise ThemeOutlineError(f"volume[{vi}] title is required")
        chapters = raw_volume.get("chapters")
        if not isinstance(chapters, list) or not chapters:
            raise ThemeOutlineError(f"volume[{vi}] must contain chapters")
        volume_id = f"v{vi:03d}"
        output_chapters: list[dict[str, Any]] = []
        for ci, raw_chapter in enumerate(chapters, 1):
            if not isinstance(raw_chapter, dict) or not str(raw_chapter.get("title", "")).strip():
                raise ThemeOutlineError(f"volume[{vi}].chapter[{ci}] title is required")
            chapter_id = f"{volume_id}-c{ci:03d}"
            if chapter_id in chapter_ids:
                raise ThemeOutlineError(f"duplicate chapter id {chapter_id}")
            chapter_ids.add(chapter_id)
            output_chapters.append({
                "chapter_id": chapter_id,
                "title": str(raw_chapter["title"]).strip(),
                "description": str(raw_chapter.get("description", "")).strip(),
                "page_ids": [],
            })
        result_volumes.append({
            "volume_id": volume_id,
            "title": str(raw_volume["title"]).strip(),
            "description": str(raw_volume.get("description", "")).strip(),
            "chapters": output_chapters,
        })
    return {
        "schema_version": "theme-outline-v1",
        "outline_id": f"theme-{_hash(theme)[:16]}",
        "theme": theme,
        "purpose_hash": _hash(purpose),
        "source_mode": "theme_only",
        "wiki_snapshot": None,
        "volumes": result_volumes,
    }


def validate_theme_outline(outline: object, *, theme: str | None = None, purpose: str | None = None) -> tuple[str, ...]:
    if not isinstance(outline, dict) or outline.get("schema_version") != "theme-outline-v1":
        return ("schema-version",)
    if outline.get("source_mode") != "theme_only" or outline.get("wiki_snapshot") is not None:
        return ("source-mode",)
    if theme is not None and outline.get("theme") != theme:
        return ("theme-mismatch",)
    if purpose is not None and outline.get("purpose_hash") != _hash(purpose):
        return ("purpose-mismatch",)
    try:
        _canonical_theme(outline, theme=str(outline.get("theme", "")), purpose="x")
    except ThemeOutlineError as exc:
        return (str(exc),)
    volume_ids: set[str] = set()
    chapter_ids: set[str] = set()
    for volume in outline.get("volumes", []):
        if not isinstance(volume.get("volume_id"), str) or not volume["volume_id"] or volume["volume_id"] in volume_ids:
            return ("invalid-volume-id",)
        volume_ids.add(volume["volume_id"])
        for chapter in volume.get("chapters", []):
            if not isinstance(chapter.get("chapter_id"), str) or not chapter["chapter_id"] or chapter["chapter_id"] in chapter_ids:
                return ("invalid-chapter-id",)
            if chapter.get("page_ids", []) not in ([], None):
                return ("page-ids-not-empty",)
            chapter_ids.add(chapter["chapter_id"])
    return ()


async def plan_theme_outline(*, theme: str, purpose: str, provider: Any) -> dict[str, Any]:
    if not theme.strip():
        raise ThemeOutlineError("theme is required")
    payload = await _complete(provider, {
        "task": "design a book volume and chapter outline from the theme only",
        "theme": theme,
        "purpose": purpose,
        "constraints": [
            "do not reference or assume any Wiki pages",
            "do not create page IDs or page assignments",
            "do not write chapter body content",
            "return JSON with volumes[].title/description and chapters[].title/description",
        ],
    })
    return _canonical_theme(payload, theme=theme, purpose=purpose)


def load_theme_outline(path: Path) -> dict[str, Any]:
    outline = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_theme_outline(outline)
    if errors:
        raise ThemeOutlineError("invalid theme outline: " + ", ".join(errors))
    return outline


def save_theme_outline(path: Path, outline: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(outline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _runtime_outline(theme_outline: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    volumes: list[dict[str, Any]] = []
    for volume in theme_outline["volumes"]:
        chapters = [{"chapter_id": chapter["chapter_id"], "title": chapter["title"],
                     "page_ids": list(chapter.get("page_ids", [])),
                     "overview_refs": list(chapter.get("page_ids", []))[:1]}
                    for chapter in volume["chapters"] if chapter.get("page_ids")]
        if chapters:
            volumes.append({"volume_id": volume["volume_id"], "title": volume["title"],
                            "chapters": chapters, "is_fallback": volume["volume_id"] == "v999"})
    return {"schema_version": "outline-v1", "snapshot_id": snapshot_id, "volumes": volumes}


async def place_page_summaries(theme_outline: dict[str, Any], snapshot: Any, provider: Any, *, batch_size: int = 40) -> dict[str, Any]:
    chapters = [chapter for volume in theme_outline["volumes"] for chapter in volume["chapters"]]
    chapter_index = {chapter["chapter_id"]: chapter for chapter in chapters}
    pages = list(snapshot.pages)
    assignments: dict[str, str] = {}
    for start in range(0, len(pages), batch_size):
        batch = pages[start:start + batch_size]
        response = await _complete(provider, {
            "task": "place Wiki page summaries into the existing book outline",
            "outline": [{"chapter_id": c["chapter_id"], "title": c["title"], "description": c.get("description", "")} for c in chapters],
            "pages": [{"page_id": p.page_id, "page_type": p.page_type, "title": p.title,
                       "taxonomy": p.primary_taxonomy, "summary": p.summary} for p in batch],
            "constraints": [
                "return assignments only; never return page body text",
                "preserve existing chapter IDs",
                "a page may be assigned at most once",
                "if no chapter fits, use chapter_id null",
            ],
        })
        for addition in response.get("additions", []) if isinstance(response.get("additions"), list) else []:
            if not isinstance(addition, dict) or not str(addition.get("title", "")).strip():
                continue
            kind = addition.get("kind")
            if kind == "volume":
                volume_id = f"v{len(theme_outline['volumes']) + 1:03d}"
                chapter_id = f"{volume_id}-c001"
                volume = {"volume_id": volume_id, "title": str(addition["title"]).strip(),
                          "description": str(addition.get("description", "")).strip(),
                          "chapters": [{"chapter_id": chapter_id, "title": "待分配内容", "description": "", "page_ids": []}]}
                theme_outline["volumes"].append(volume)
                chapter_index[chapter_id] = volume["chapters"][0]
                chapters.append(volume["chapters"][0])
            elif kind == "chapter":
                volume = next((v for v in theme_outline["volumes"] if v["volume_id"] == addition.get("parent_volume_id")), None)
                if volume is None:
                    continue
                chapter_id = f"{volume['volume_id']}-c{len(volume['chapters']) + 1:03d}"
                chapter = {"chapter_id": chapter_id, "title": str(addition["title"]).strip(),
                           "description": str(addition.get("description", "")).strip(), "page_ids": []}
                volume["chapters"].append(chapter)
                chapter_index[chapter_id] = chapter
                chapters.append(chapter)
        for item in response.get("assignments", []) if isinstance(response.get("assignments"), list) else []:
            if not isinstance(item, dict):
                continue
            page_id, chapter_id = item.get("page_id"), item.get("chapter_id")
            if page_id in {p.page_id for p in batch} and chapter_id in chapter_index and page_id not in assignments:
                assignments[page_id] = chapter_id
    fallback_volume = next((v for v in theme_outline["volumes"] if v["volume_id"] == "v999"), None)
    if fallback_volume is None:
        fallback_volume = {"volume_id": "v999", "title": "待分类", "description": "无法可靠映射的页面", "chapters": [{"chapter_id": "v999-c001", "title": "待分类页面", "description": "", "page_ids": []}]}
        theme_outline["volumes"].append(fallback_volume)
    fallback_chapter = fallback_volume["chapters"][0]
    for page in pages:
        chapter = chapter_index.get(assignments.get(page.page_id), fallback_chapter)
        chapter.setdefault("page_ids", []).append(page.page_id)
    return _runtime_outline(theme_outline, snapshot.snapshot_id)


def place_page_summaries_sync(theme_outline: dict[str, Any], snapshot: Any, provider: Any, *, batch_size: int = 40) -> dict[str, Any]:
    return asyncio.run(place_page_summaries(theme_outline, snapshot, provider, batch_size=batch_size))


__all__ = ["ThemeOutlineError", "load_theme_outline", "plan_theme_outline", "place_page_summaries", "place_page_summaries_sync", "save_theme_outline", "validate_theme_outline"]
