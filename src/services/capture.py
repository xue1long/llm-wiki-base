"""Fast capture service — write wiki pages without LLM pipeline.

Bypasses Collector→Analyzer→Generator; writes pages directly via write_page.
Sub-type is marked in body HTML comment (<!-- capture-type: xxx -->),
not in page.custom_type (to avoid SchemaRegistry validation).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..lib.project import resolve_project
from ..templates.loader import load as load_bundled_template
from ..wiki.core.id_generator import generate_page_id, normalize_id_chars
from ..utils.slugify import ensure_unique_slug
from ..wiki.core.paths import WikiPaths
from ..wiki.core.types import PageType, WikiPage
from ..wiki.features.indexer import append_to_index, read_index
from ..wiki.features.logger import log_event
from ..wiki.features.tag_namespace import validate_tag_compliance
from ..wiki.storage.page_writer import page_path_for, write_page

_logger = logging.getLogger(__name__)

# Type → base PageType mapping
_TYPE_MAP = {
    "article": "source",
    "video-transcript": "source",
    "inspiration": "concept",
}

# Cached template (bundled templates don't change at runtime)
_capture_template_files: dict[str, str] | None = None


def _get_template_files() -> dict[str, str]:
    global _capture_template_files
    if _capture_template_files is None:
        _capture_template_files = load_bundled_template("capture").files
    return _capture_template_files


def _get_capture_body(type: str) -> str:
    """Read the page template body for the given capture sub-type."""
    files = _get_template_files()
    key = f".wiki-templates/{type}.md"
    if key not in files:
        raise ValueError(f"Unknown capture type: {type!r}")
    return files[key]


def _existing_slugs(paths: WikiPaths) -> list[str]:
    """Extract short slugs from index.md for ensure_unique_slug."""
    try:
        slugs = []
        for entry_id, _type, _title in read_index(paths):
            # card_<hex>_<hex>_<slug> → extract slug part
            if "_" in entry_id and entry_id.startswith("card_"):
                parts = entry_id.split("_")
                slugs.append("-".join(parts[3:]))
            else:
                slugs.append(entry_id)
        return slugs
    except Exception:
        return []


def _page_exists(paths: WikiPaths, slug: str, base_type: str) -> bool:
    """Check if a page with the given slug already exists on disk."""
    dir_map = {
        "source": paths.wiki_sources,
        "concept": paths.wiki_concepts,
        "entity": paths.wiki_entities,
        "synthesis": paths.wiki_synthesis,
    }
    target_dir = dir_map.get(base_type, paths.wiki_sources)
    if not target_dir.exists():
        return False
    # Check for any file matching the slug (with or without card_ prefix)
    for f in target_dir.glob("*.md"):
        if slug in f.stem:
            return True
    return False


def capture_page(
    project_id: str,
    type: str,
    title: str,
    content: str = "",
    url: str = "",
    tags: list[str] | None = None,
    category: str = "",
) -> dict:
    """Create a wiki page directly without LLM pipeline.

    Args:
        project_id: Project UUID or path
        type: Capture sub-type ("article", "video-transcript", "inspiration")
        title: Page title (required)
        content: Page content (empty → skeleton page)
        url: Source URL (optional)
        tags: Tag list (optional)
        category: Taxonomy category (optional, needed for strict mode)

    Returns:
        {"status": "ok"|"exists", "page_id": str, "path": str, "is_skeleton": bool}
    """
    if type not in _TYPE_MAP:
        raise ValueError(f"Invalid capture type: {type!r}. Must be one of: {list(_TYPE_MAP.keys())}")
    if not title or not title.strip():
        raise ValueError("Title is required")

    tags = tags or []
    base_type = _TYPE_MAP[type]
    ctx, paths = resolve_project(project_id, by_id_only=True)

    # Slug generation with dedup and truncation
    existing = _existing_slugs(paths)
    slug = ensure_unique_slug(normalize_id_chars(title)[:80], existing)
    page_id = generate_page_id(slug)

    # Read template body
    template_body = _get_capture_body(type)

    # Build page body
    is_skeleton = not content.strip()
    if is_skeleton:
        body = f"> ⚠️ 源文档内容为空，此页为骨架占位。\n\n{template_body}"
    else:
        body = template_body.replace("<!-- slot:summary -->", content, 1)

    # Prepend capture-type comment (sub-type marker)
    body = f"<!-- capture-type: {type} -->\n\n{body}"

    # Build WikiPage
    page = WikiPage(
        id=page_id,
        title=title.strip(),
        type=PageType(base_type),
        body=body,
        tags=tags,
    )
    page.custom_type = ""  # F1: never set custom_type
    if url:
        page.sources = [url]
    if category:
        page.category = category

    # _ko_extra persistence (F2/S1)
    page._ko_extra = {"source_status": "empty" if is_skeleton else "complete"}

    # Idempotency: check if slug already exists
    if _page_exists(paths, slug, base_type):
        page_path = page_path_for(paths, page.type, page_id)
        return {"status": "exists", "page_id": page_id, "path": str(page_path), "is_skeleton": is_skeleton}

    # Write page (skip validate_tag_compliance — capture is a quick entry,
    # mandatory UGC tags don't apply to personal captures)
    write_page(paths, page)
    page_path = page_path_for(paths, page.type, page_id)

    # Update index and log
    append_to_index(paths, [(page_id, page.type, title.strip())])
    log_event(paths, "capture", page_id, f"{type}: {title.strip()}")

    _logger.info("Captured %s page: %s (%s)", type, page_id, title.strip())
    return {"status": "ok", "page_id": page_id, "path": str(page_path), "is_skeleton": is_skeleton}
