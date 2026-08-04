"""Wiki overview.md auto-generation.

Called after each ingest to update the global summary page that serves
as a navigation entry point for LLM agents.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.types import WikiPage
    from ..core.paths import WikiPaths


def update_overview(paths: "WikiPaths", pages: list["WikiPage"], use_llm: bool = False) -> None:
    """Generate or update wiki/overview.md based on current content.

    Args:
        paths: WikiPaths instance for the project
        pages: List of all wiki pages in the project
        use_llm: If True, use LLM to generate summary (future enhancement)
    """
    if not pages:
        return

    # Collect statistics
    stats = {
        "total_pages": len(pages),
        "by_type": {},
        "by_grade": {},
        "recent_updates": [],
    }

    for p in pages:
        # Count by type
        ptype = p.type.value if hasattr(p.type, "value") else str(p.type)
        stats["by_type"][ptype] = stats["by_type"].get(ptype, 0) + 1

        # Count by grade
        grade = getattr(p, "grade", "B") or "B"
        stats["by_grade"][grade] = stats["by_grade"].get(grade, 0) + 1

    # Sort pages by updated_at for recent updates
    sorted_pages = sorted(
        pages,
        key=lambda p: getattr(p, "updated_at", "") or "",
        reverse=True,
    )[:10]
    stats["recent_updates"] = [
        {"id": p.id, "title": p.title, "type": p.type.value if hasattr(p.type, "value") else str(p.type)}
        for p in sorted_pages
    ]

    # Generate content
    content = _generate_overview_content(stats, pages)

    # Write to wiki/overview.md
    overview_path = paths.wiki_root / "overview.md"
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.write_text(content, encoding="utf-8")


def _generate_overview_content(stats: dict, pages: list["WikiPage"]) -> str:
    """Generate overview.md content from statistics."""
    lines = [
        "# Wiki Overview",
        "",
        f"> Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Statistics",
        "",
        f"- **Total pages**: {stats['total_pages']}",
        "",
        "### By Type",
        "",
    ]

    for ptype, count in sorted(stats["by_type"].items()):
        lines.append(f"- {ptype}: {count}")

    lines.append("")
    lines.append("### By Grade")
    lines.append("")

    for grade, count in sorted(stats["by_grade"].items()):
        lines.append(f"- {grade}: {count}")

    if stats["recent_updates"]:
        lines.append("")
        lines.append("## Recent Updates")
        lines.append("")
        for p in stats["recent_updates"]:
            lines.append(f"- [[{p['id']}]] ({p['type']})")

    # Add quick navigation section
    lines.extend([
        "",
        "## Quick Navigation",
        "",
        "### Entities",
        "",
    ])

    entities = [p for p in pages if getattr(p, "type", None).__class__.__name__ == "PageType"
                and str(getattr(p.type, "value", "")) == "entity"][:10]
    for e in entities:
        lines.append(f"- [[{e.id}]] — {e.title}")

    lines.extend([
        "",
        "### Concepts",
        "",
    ])

    concepts = [p for p in pages if getattr(p, "type", None).__class__.__name__ == "PageType"
                and str(getattr(p.type, "value", "")) == "concept"][:10]
    for c in concepts:
        lines.append(f"- [[{c.id}]] — {c.title}")

    lines.append("")
    return "\n".join(lines)


def collect_all_pages(paths: "WikiPaths") -> list["WikiPage"]:
    """Collect all wiki pages from the project."""
    from ..storage.page_writer import read_page
    from ..core.types import PageType

    pages = []
    type_dirs = [
        (paths.wiki_sources, PageType.SOURCE),
        (paths.wiki_entities, PageType.ENTITY),
        (paths.wiki_concepts, PageType.CONCEPT),
        (paths.wiki_synthesis, PageType.SYNTHESIS),
    ]

    for dir_path, ptype in type_dirs:
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            try:
                page = read_page(md_file)
                pages.append(page)
            except Exception:
                # Skip unreadable files
                continue

    return pages