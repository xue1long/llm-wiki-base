"""Tag index service — namespace-aware tag aggregation across wiki pages.

Scans all .md files under wiki/, parses YAML frontmatter ``tags`` fields,
and aggregates tag counts by namespace prefix using the controlled
vocabulary from ``src.wiki.features.tag_namespace``.
"""
from __future__ import annotations

from ..lib.project import resolve_project
from ..wiki.features.tag_namespace import TAG_PREFIXES, parse as parse_tag


def build_tag_index(project_id: str) -> dict:
    """Walk the project's wiki tree and return a namespace→tag→count index.

    Returns a dict ready for the HTTP route::

        {
            "namespaces": {
                "genre": {"label": "题材类型", "tags": [{"name": "玄幻", "count": 12}, ...]},
                ...
            }
        }
    """
    _ctx, paths = resolve_project(project_id, by_id_only=True)
    wiki_root = paths.wiki
    if not wiki_root.exists():
        return {"namespaces": {}}

    # Accumulate: {prefix: {tag_name: count}}
    ns_counts: dict[str, dict[str, int]] = {
        prefix: {} for prefix in TAG_PREFIXES
    }

    for md_file in wiki_root.rglob("*.md"):
        if not md_file.is_file():
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        try:
            import yaml
            fm = yaml.safe_load(text[4:end]) or {}
        except Exception:
            continue
        tags = fm.get("tags", [])
        if not isinstance(tags, list):
            continue
        for tag in tags:
            parsed = parse_tag(str(tag))
            if parsed is None:
                continue
            prefix, name = parsed
            if prefix in ns_counts:
                ns_counts[prefix][name] = ns_counts[prefix].get(name, 0) + 1

    namespaces = {}
    for prefix, label in TAG_PREFIXES.items():
        tag_counts = ns_counts.get(prefix, {})
        if not tag_counts:
            continue
        sorted_tags = sorted(
            [{"name": name, "count": count} for name, count in tag_counts.items()],
            key=lambda t: (-t["count"], t["name"]),
        )
        namespaces[prefix] = {"label": label, "tags": sorted_tags}

    return {"namespaces": namespaces}
