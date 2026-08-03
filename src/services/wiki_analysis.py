"""Wiki structure analysis: graph + lint.

Spec: FRONTEND_DESIGN.md §14.4 (graph) and §14.5 (lint).

Two endpoints consume this module:
  - GET /api/v1/projects/{id}/wiki/graph   → nodes + edges
  - GET /api/v1/projects/{id}/lint         → orphans + dangling + missing-id

We parse two link sources:
  1. Frontmatter `relations:` blocks (this wiki's primary relation format):
        relations:
        - target: writing-style
          type: supports
          weight: 0.9
  2. Markdown links of the form [text](path/to/other.md).
"""
from __future__ import annotations

import re
from typing import Any

from ..lib.project import resolve_project

# ---- frontmatter helpers ---------------------------------------------------

_FM_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?")

# `relations:` followed by "- target: X" lines (possibly nested keys).
# We scan line-by-line and accumulate (target, type, weight) tuples.
_RE_TARGET = re.compile(r"^\s+target:\s*([\w\-.]+)")
_RE_TYPE = re.compile(r"^\s+type:\s*([\w\-]+)")
_RE_WEIGHT = re.compile(r"^\s+weight:\s*([\d.]+)")
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)(?:[#?][^)]*)?\)")


def _parse_frontmatter(body: str) -> dict[str, Any]:
    """Minimal frontmatter parser: scalar keys + a `relations` list."""
    m = _FM_RE.match(body)
    if not m:
        return {}
    block = m.group(1)
    out: dict[str, Any] = {}
    relations: list[dict[str, Any]] = []
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # top-level key
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not kv:
            i += 1
            continue
        key, val = kv.group(1), kv.group(2).strip()
        if key == "relations":
            # consume indented "- ..." block(s)
            i += 1
            current: dict[str, Any] | None = None
            while i < len(lines):
                ln = lines[i]
                # A line ends the relations block only if it's a non-blank
                # line that doesn't start with space/tab/`-` (a fresh top-level
                # key, like `created_at:`).
                if ln and not (ln.startswith(" ") or ln.startswith("\t") or ln.startswith("-")):
                    break
                stripped = ln.strip()
                if not stripped:
                    i += 1
                    continue
                if stripped.startswith("- "):
                    # flush prior entry
                    if current is not None:
                        relations.append(current)
                    first = stripped[2:]
                    sub_kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", first)
                    if sub_kv and sub_kv.group(1) == "target":
                        current = {"target": sub_kv.group(2).strip(), "type": "", "weight": 1.0}
                    else:
                        current = None
                else:
                    sub_kv = re.match(r"^\s+([A-Za-z_][\w-]*)\s*:\s*(.*)$", ln)
                    if sub_kv and current is not None:
                        k, v = sub_kv.group(1), sub_kv.group(2).strip()
                        if k == "type":
                            current["type"] = v
                        elif k == "weight":
                            try:
                                current["weight"] = float(v)
                            except ValueError:
                                pass
                i += 1
            if current is not None:
                relations.append(current)
            continue
        # scalar value
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        out[key] = val
        i += 1
    if relations:
        out["relations"] = relations
    return out


def _md_links(body: str, base: str) -> list[str]:
    """Find markdown links to .md files. `base` is wiki-relative dir of source."""
    out: list[str] = []
    for _text, href in _RE_MD_LINK.findall(body):
        href = href.replace("\\", "/")
        if href.startswith(("http://", "https://", "#", "/")):
            continue
        # resolve relative to `base`
        if href.startswith("./"):
            href = href[2:]
        if base and not href.startswith("../"):
            resolved = f"{base}/{href}" if base else href
        else:
            # naive parent-relative resolution; wiki typically uses leaf links
            resolved = href
        # strip ../ and normalize
        parts: list[str] = []
        for seg in resolved.split("/"):
            if seg == "..":
                if parts: parts.pop()
            elif seg and seg != ".":
                parts.append(seg)
        out.append("/".join(parts))
    return out


# ---- public API ------------------------------------------------------------

def graph(project_id: str) -> dict:
    """Return {nodes, edges} for the project's wiki.

    Edges come from frontmatter `relations:` blocks (primary) and markdown
    `[text](path.md)` links (secondary, only when no relation exists).
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)
    wiki_root = paths.wiki

    # Pass 1: collect all nodes (must finish before resolving any links,
    # so that forward-links to later-sorted files are also resolved).
    nodes: dict[str, dict] = {}
    file_bodies: dict[str, tuple[str, str, dict]] = {}  # node_id -> (body, base_dir, fm)

    for md_path in sorted(wiki_root.rglob("*.md")):
        if "_stubs" in md_path.parts:
            continue
        rel_path = md_path.relative_to(paths.root).as_posix()  # wiki/...
        wiki_rel = md_path.relative_to(wiki_root).as_posix()   # concepts/x.md
        try:
            body = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm = _parse_frontmatter(body)
        node_id = fm.get("id") or wiki_rel.replace("/", "__").removesuffix(".md")
        nodes[node_id] = {
            "id": node_id,
            "title": fm.get("title") or wiki_rel.removesuffix(".md"),
            "type": fm.get("type", ""),
            "path": wiki_rel,
            "api_path": rel_path,
        }
        base_dir = "/".join(wiki_rel.split("/")[:-1])
        file_bodies[node_id] = (body, base_dir, fm)

    # Pass 2: resolve links using the complete nodes dict.
    edges: list[dict] = []
    for node_id, (body, base_dir, fm) in file_bodies.items():
        seen: set[tuple[str, str]] = set()
        # edges from relations
        for rel in fm.get("relations", []):
            tgt = rel.get("target")
            if not tgt:
                continue
            key = (node_id, tgt)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "source": node_id,
                "target": tgt,
                "type": rel.get("type", ""),
                "weight": rel.get("weight", 1.0),
                "kind": "relation",
            })
        # edges from markdown links
        for link in _md_links(body, base_dir):
            target_node_id = None
            for nid, n in nodes.items():
                if n["path"].endswith("/" + link) or n["path"] == link:
                    target_node_id = nid
                    break
            if target_node_id and target_node_id != node_id:
                key = (node_id, target_node_id)
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "source": node_id,
                        "target": target_node_id,
                        "type": "link",
                        "weight": 1.0,
                        "kind": "markdown",
                    })
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }


def lint(project_id: str) -> dict:
    """Heuristic wiki lint: orphans, dangling edges, missing-id pages."""
    g = graph(project_id)
    incoming: dict[str, int] = {n["id"]: 0 for n in g["nodes"]}
    for e in g["edges"]:
        if e["target"] in incoming:
            incoming[e["target"]] += 1

    orphans = [
        {"id": n["id"], "path": n["path"], "title": n["title"]}
        for n in g["nodes"] if incoming[n["id"]] == 0 and n["type"] != "system"
    ]
    node_ids = set(incoming.keys())
    dangling = [
        {"source": e["source"], "target": e["target"], "type": e["type"]}
        for e in g["edges"] if e["target"] not in node_ids
    ]
    return {
        "summary": {
            "nodes": len(g["nodes"]),
            "edges": len(g["edges"]),
            "orphans": len(orphans),
            "dangling": len(dangling),
        },
        "orphans": orphans[:50],
        "dangling": dangling[:50],
    }


# ---------------------------------------------------------------------------
# Thin service wrappers — single-line delegations to wiki/features
# ---------------------------------------------------------------------------


def get_heat_tracker(paths):
    from ..wiki.features.heat import HeatTracker
    return HeatTracker(paths)


def get_zombie_detector():
    from ..wiki.features.zombie import ZombieDetector
    return ZombieDetector


def run_dedup_auto(paths, provider, threshold="medium"):
    from ..wiki.features.dedup_auto import dedup_auto
    return dedup_auto(paths, provider, threshold=threshold)


def run_stub_promotion(paths, provider):
    import asyncio
    from ..wiki.features.stubs import StubMaterializerWorker
    return asyncio.run(StubMaterializerWorker(paths, provider).run_once())


def run_lint(paths, project_id):
    from ..wiki.features.lint import lint_wiki
    return lint_wiki(paths, project_id=project_id)


def get_relations_for_page(paths, page_id):
    from ..wiki.features.relations import RelationQuery
    return RelationQuery.list_relations(paths, page_id)


def get_backlinks_for_page(paths, page_id):
    from ..wiki.features.relations import RelationQuery
    return RelationQuery.find_backlinks(paths, page_id)


def get_neighbors(paths, page_id, depth=1):
    from ..wiki.features.relations import RelationQuery
    return RelationQuery.find_neighbors(paths, page_id, depth=depth)


def find_path_between(paths, source_id, target_id):
    from ..wiki.features.relations import RelationQuery
    return RelationQuery.find_path(paths, source_id, target_id)
