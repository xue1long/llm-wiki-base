"""Pure conversion helpers for v2 frontmatter and Markdown bodies."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ..core.types import _coerce_ts_ms


_PAGE_TYPES = {"source", "entity", "concept", "synthesis"}
_VIDEO_PLATFORMS = {"B站", "哔哩哔哩", "抖音", "小红书", "快手", "YouTube", "TikTok"}
_CANONICAL_FIELDS = {
    "id", "title", "type", "sources", "created_at", "updated_at", "tags",
    "processing_depth", "source_grade", "platform", "category", "taxonomy_sub",
    "use_context", "workflow_state", "capture_type", "v2_origin", "custom_type",
}
_AUDIT_FIELDS = {"version", "author", "maturity", "summary", "aliases", "instance_of",
                 "bv", "video_id", "note_id", "uid", "source", "invalid_reason",
                 "uploader", "video_published_at"}


def _timestamp(value: Any, field: str, errors: list[str]) -> int:
    result = _coerce_ts_ms(value)
    if result == 0 and value not in (None, "", 0):
        errors.append(f"invalid {field}: {value!r}")
    return result


def _normalise_tags(value: Any) -> list[str]:
    """Keep v2 tags usable without rejecting its free-form vocabulary.

    The migration boundary maps only the legacy English prefixes. Values are
    deliberately not domain-validated here; the complete original list is
    retained in ``_ko_extra`` for replay and later review.
    """
    if not isinstance(value, (list, tuple)):
        value = [] if value in (None, "") else [value]
    legacy = {
        "genre": "题材", "func": "功能", "char": "角色", "event": "事件",
        "mood": "情绪", "entity": "实体", "scene_phase": "场景阶段", "status": "状态",
    }
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            continue
        tag = raw.strip()
        prefix, separator, suffix = tag.partition("/")
        if separator and prefix in legacy:
            tag = f"{legacy[prefix]}/{suffix}"
        if tag not in result:
            result.append(tag)
    return result


def _capture_type(frontmatter: Mapping[str, Any], page_type: str, source_kind: str | None) -> str:
    explicit = frontmatter.get("capture_type")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if source_kind in {"seed", "inspiration", "fragment"}:
        return "inspiration"
    if source_kind in {"article", "article-excerpt"}:
        return "article"
    content_kind = str(frontmatter.get("content_type") or frontmatter.get("source_type") or "").lower()
    if content_kind in {"article", "文章", "article-excerpt"}:
        return "article"
    if page_type == "entity":
        return ""
    if frontmatter.get("platform") in _VIDEO_PLATFORMS or any(
        frontmatter.get(key) for key in ("bv", "video_id")
    ):
        return "video-transcript"
    # v2 concepts are the video-note corpus unless the source explicitly says
    # otherwise; this is the D9a default.
    return "video-transcript" if page_type == "concept" else ""


def convert_frontmatter(
    value: Mapping[str, Any] | None,
    *,
    file_stem: str,
    source_kind: str | None = None,
) -> dict[str, Any]:
    """Convert one v2 frontmatter mapping into a replayable V6-shaped dict."""
    original = copy.deepcopy(dict(value or {}))
    errors: list[str] = []
    title = original.get("title")
    title = title.strip() if isinstance(title, str) else ""
    title = title or file_stem
    page_type = original.get("type")
    page_type = page_type if page_type in _PAGE_TYPES else "concept"

    output: dict[str, Any] = {
        "id": file_stem,
        "title": title,
        "type": page_type,
        "sources": [],
        "created_at": _timestamp(original.get("created"), "created", errors),
        "updated_at": _timestamp(original.get("updated"), "updated", errors),
        "tags": _normalise_tags(original.get("tags")),
        "processing_depth": original.get("processing_depth", "concept"),
        "source_grade": original.get("source_grade", original.get("grade", "B")),
        "platform": original.get("platform", ""),
        "category": original.get("category", ""),
        "taxonomy_sub": original.get("taxonomy_sub", ""),
        "use_context": original.get("use_context", ""),
        "workflow_state": original.get("workflow_state", "draft"),
        "capture_type": _capture_type(original, page_type, source_kind),
        "v2_origin": True,
    }

    url = original.get("url")
    if isinstance(url, (list, tuple)):
        output["sources"] = list(url)
    elif url not in (None, ""):
        output["sources"] = [url]
    elif original.get("sources") not in (None, ""):
        value = original["sources"]
        output["sources"] = list(value) if isinstance(value, (list, tuple)) else [value]

    if original.get("instance_of") not in (None, ""):
        output["custom_type"] = original["instance_of"]

    extra: dict[str, Any] = {}
    for key in _AUDIT_FIELDS:
        if key in original:
            extra[key] = copy.deepcopy(original[key])
    if "instance_of" in original:
        extra["custom_type"] = copy.deepcopy(original["instance_of"])
    if "url" in original:
        extra["v2_url"] = copy.deepcopy(original["url"])
    if "created" in original:
        extra["v2_created"] = copy.deepcopy(original["created"])
    if "updated" in original:
        extra["v2_updated"] = copy.deepcopy(original["updated"])
    if "tags" in original:
        extra["_v2_tags_original"] = copy.deepcopy(original["tags"])

    known = _CANONICAL_FIELDS | _AUDIT_FIELDS | {"url", "created", "updated", "tags", "grade"}
    unknown = {key: copy.deepcopy(raw) for key, raw in original.items() if key not in known}
    if unknown:
        extra["_v2_unknown_fields"] = unknown
    if errors:
        extra["_migration_errors"] = [error.split(":", 1)[0] for error in errors]
    extra["_v2_frontmatter_original"] = original
    output["_ko_extra"] = extra
    return output


def convert_frontmatter_and_body(
    value: Mapping[str, Any] | None,
    *,
    file_stem: str,
    body: str,
    source_kind: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Convert frontmatter and add the D9a marker exactly once."""
    frontmatter = convert_frontmatter(value, file_stem=file_stem, source_kind=source_kind)
    body = body or ""
    marker = f"<!-- capture-type: {frontmatter['capture_type']} -->"
    if frontmatter["type"] == "concept" and frontmatter["capture_type"] == "video-transcript":
        if marker not in body:
            body = marker + "\n" + body
    return frontmatter, body
