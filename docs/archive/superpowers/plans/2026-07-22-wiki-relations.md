# Wiki Relations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Typed relations `[{target_id, type, weight, context}]` in WikiPage frontmatter. Bidirectional sync. 16 built-in types + user-defined x-* types. Query: list / backlinks / neighbors / path.

**Tech Stack:** Python 3.11+, dataclass, enum.

**MVP Scope** (per spec): Generator emits relations + bidirectional sync + 16 types + CLI `relations list/backlinks/neighbors/path/types/add-type`.

---

### Task 1: Relation types + bidirectional sync

**Files:** `src/wiki/relations.py` + tests

```python
# src/wiki/relations.py
"""Typed relations between wiki pages (bidirectional)."""
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class RelationType(str, Enum):
    IS_PART_OF = "is_part_of"
    CONTAINS = "contains"
    REFERENCES = "references"
    REFERENCED_BY = "referenced_by"
    CAUSES = "causes"
    CAUSED_BY = "caused_by"
    CONTRADICTS = "contradicts"     # symmetric
    SUPPORTS = "supports"
    SUPPORTED_BY = "supported_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    DEPENDS_ON = "depends_on"
    REQUIRED_BY = "required_by"
    ANALOGOUS_TO = "analogous_to"   # symmetric
    OPPOSITE_OF = "opposite_of"     # symmetric
    DERIVED_FROM = "derived_from"
    DERIVES = "derives"


# Inverse relation table
INVERSE_RELATIONS = {
    "is_part_of": "contains",
    "contains": "is_part_of",
    "references": "referenced_by",
    "referenced_by": "references",
    "causes": "caused_by",
    "caused_by": "causes",
    "contradicts": "contradicts",       # symmetric
    "supports": "supported_by",
    "supported_by": "supports",
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
    "depends_on": "required_by",
    "required_by": "depends_on",
    "analogous_to": "analogous_to",     # symmetric
    "opposite_of": "opposite_of",       # symmetric
    "derived_from": "derives",
    "derives": "derived_from",
}

USER_TYPE_PREFIX = "x-"


@dataclass
class Relation:
    target_id: str
    type: str                # RelationType.value or f"x-{name}"
    weight: float = 1.0
    context: str = ""

    def to_dict(self) -> dict:
        return {"target": self.target_id, "type": self.type,
                "weight": round(self.weight, 2), "context": self.context}

    @classmethod
    def from_dict(cls, d: dict) -> "Relation":
        return cls(
            target_id=d["target"], type=d["type"],
            weight=d.get("weight", 1.0), context=d.get("context", ""),
        )

    def inverse(self) -> Optional["Relation"]:
        inv_type = INVERSE_RELATIONS.get(self.type)
        if inv_type is None:
            return None
        return Relation(target_id="<this_page_id>", type=inv_type, weight=self.weight, context=self.context)
```

**Tests** (4): test_relation_round_trip, test_inverse_known, test_inverse_symmetric, test_user_type_prefix.

```bash
git add src/wiki/relations.py tests/test_wiki/test_relations.py
git commit -m "feat(wiki): add Relation type + 16 built-in types + inverse table"
```

---

### Task 2: RelationSync + RelationQuery

**Files:** extend `src/wiki/relations.py` + tests

```python
# Extend relations.py

@dataclass
class SyncReport:
    page_id: str
    added: list[Relation] = field(default_factory=list)
    updated: list[Relation] = field(default_factory=list)


class RelationSync:
    """Bidirectional sync of relations in wiki/."""

    @staticmethod
    def sync_page(paths, page_id: str, relations: list[Relation]) -> SyncReport:
        """Write relations to page; apply inverse relations to target pages."""
        from .page_writer import read_page, write_page
        from .page_writer import page_path_for
        from .types import PageType

        report = SyncReport(page_id=page_id)
        # Load page
        page_file = page_path_for(paths, _infer_type(paths, page_id), page_id)
        if not page_file.exists():
            return report
        page = read_page(page_file)
        # Update page's relations
        page.relations = relations
        write_page(paths, page)
        report.added = relations
        # Apply inverse to each target
        for rel in relations:
            inv = rel.inverse()
            if inv is None or rel.type in ("contradicts", "analogous_to", "opposite_of"):
                continue  # symmetric; already added
            inv.target_id = page_id
            target_file = page_path_for(paths, _infer_type(paths, rel.target_id), rel.target_id)
            if not target_file.exists():
                continue
            target_page = read_page(target_file)
            if any(r.target_id == page_id and r.type == inv.type for r in target_page.relations):
                continue  # already has inverse
            target_page.relations.append(inv)
            write_page(paths, target_page)
        return report


def _infer_type(paths, slug: str):
    """Find which subdir contains the page."""
    from .types import PageType
    for type, dir_prop in [
        (PageType.ENTITY, "wiki_entities"),
        (PageType.CONCEPT, "wiki_concepts"),
        (PageType.SOURCE, "wiki_sources"),
        (PageType.SYNTHESIS, "wiki_synthesis"),
    ]:
        if (getattr(paths, dir_prop) / f"{slug}.md").exists():
            return type
    return PageType.SOURCE


class RelationQuery:
    """Read-side queries over relations."""

    @staticmethod
    def list_relations(paths, page_id: str) -> list[Relation]:
        from .page_writer import read_page
        from .page_writer import page_path_for
        from .types import PageType
        page_file = page_path_for(paths, _infer_type(paths, page_id), page_id)
        if not page_file.exists():
            return []
        return read_page(page_file).relations

    @staticmethod
    def find_backlinks(paths, page_id: str) -> list[Relation]:
        """Scan all wiki pages for relations where target == page_id."""
        from .page_writer import read_page
        from .types import PageType
        backlinks: list[Relation] = []
        for type, dir_prop in [
            (PageType.SOURCE, "wiki_sources"),
            (PageType.ENTITY, "wiki_entities"),
            (PageType.CONCEPT, "wiki_concepts"),
            (PageType.SYNTHESIS, "wiki_synthesis"),
        ]:
            for f in getattr(paths, dir_prop).glob("*.md"):
                page = read_page(f)
                for rel in page.relations:
                    if rel.target_id == page_id:
                        backlinks.append(Relation(
                            target_id=page.id, type=rel.type, weight=rel.weight, context=rel.context
                        ))
        return backlinks

    @staticmethod
    def find_neighbors(paths, page_id: str, depth: int = 1) -> list[tuple[str, str, float]]:
        """BFS up to `depth` hops. Returns (neighbor_id, via_relation, cumulative_weight)."""
        from collections import deque
        visited = {page_id}
        queue = deque([(page_id, [], 1.0)])
        results: list[tuple[str, str, float]] = []
        while queue:
            current, path, weight = queue.popleft()
            if len(path) > depth:
                continue
            relations = RelationQuery.list_relations(paths, current)
            for rel in relations:
                if rel.target_id in visited:
                    continue
                visited.add(rel.target_id)
                results.append((rel.target_id, rel.type, weight * rel.weight))
                if len(path) + 1 < depth:
                    queue.append((rel.target_id, path + [rel], weight * rel.weight))
        return results

    @staticmethod
    def find_path(paths, source_id: str, target_id: str) -> list[tuple[str, str]]:
        """BFS shortest path. Returns [(from_id, to_id, relation_type), ...]."""
        from collections import deque
        if source_id == target_id:
            return []
        visited = {source_id}
        queue = deque([(source_id, [])])
        while queue:
            current, path = queue.popleft()
            relations = RelationQuery.list_relations(paths, current)
            for rel in relations:
                if rel.target_id in visited:
                    continue
                if rel.target_id == target_id:
                    return path + [(current, rel.target_id, rel.type)]
                visited.add(rel.target_id)
                queue.append((rel.target_id, path + [(current, rel.target_id, rel.type)]))
        return []  # no path
```

**Tests** (5): test_sync_adds_inverse, test_sync_idempotent, test_find_backlinks, test_find_neighbors, test_find_path.

```bash
git add src/wiki/relations.py tests/test_wiki/test_relations.py
git commit -m "feat(wiki): add RelationSync (bidirectional) + RelationQuery (list/backlinks/neighbors/path)"
```

---

### Task 3: Extend Generator + CLI

**Files:** modify `src/pipeline/generator.py` + `src/cli_ext/relations_cmd.py` + tests

Modify Generator's response_format to include `relations` field. Add `parse_relations_from_response()` helper.

```python
# src/cli_ext/relations_cmd.py
"""Wiki relations CLI subcommands."""
import argparse
import sys
from ..wiki.relations import (
    Relation, RelationType, INVERSE_RELATIONS, USER_TYPE_PREFIX,
    RelationSync, RelationQuery,
)
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_relations_list(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    rels = RelationQuery.list_relations(ctx.paths, args.page_id)
    for r in rels:
        print(f"  → {r.target_id}  ({r.type}, w={r.weight})  {r.context}")


def cmd_relations_backlinks(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    rels = RelationQuery.find_backlinks(ctx.paths, args.page_id)
    print(f"Backlinks to {args.page_id}:")
    for r in rels:
        print(f"  ← {r.target_id}  ({r.type}, w={r.weight})")


def cmd_relations_neighbors(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    neighbors = RelationQuery.find_neighbors(ctx.paths, args.page_id, args.depth)
    for nid, via, w in neighbors:
        print(f"  → {nid}  (via {via}, w={w:.2f})")


def cmd_relations_path(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    path = RelationQuery.find_path(ctx.paths, args.from_id, args.to_id)
    if not path:
        print(f"No path from {args.from_id} to {args.to_id}")
        sys.exit(1)
    for f, t, typ in path:
        print(f"  {f} --[{typ}]--> {t}")


def cmd_relations_types(args: argparse.Namespace) -> None:
    """List all known relation types (built-in + user-defined)."""
    print("Built-in types:")
    for t in RelationType:
        inv = INVERSE_RELATIONS.get(t.value, "(symmetric)")
        print(f"  {t.value:<25} (inverse: {inv})")
    # User-defined types from settings
    print("\nUser-defined types (x-):")
    print("  (use `relations add-type <name>` to register)")


def cmd_relations_add_type(args: argparse.Namespace) -> None:
    name = args.name
    if not name.startswith(USER_TYPE_PREFIX):
        name = USER_TYPE_PREFIX + name
    # Register in settings
    config_path = _settings_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        data = __import__("json").loads(config_path.read_text(encoding="utf-8"))
    else:
        data = {}
    types = set(data.get("user_relation_types", []))
    types.add(name)
    data["user_relation_types"] = sorted(types)
    config_path.write_text(__import__("json").dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Registered user relation type: {name}")


def _resolve(project_id):
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)


def _settings_path():
    from pathlib import Path
    from ..project.context import ProjectContext, ProjectNotFoundError
    try:
        ctx = ProjectContext.resolve(None)
        return ctx.paths.llm_wiki / "settings.json"
    except ProjectNotFoundError:
        return Path.cwd() / "settings.json"
```

**Wire in cli.py**:
```python
p_relations = subparsers.add_parser("relations", help="Manage wiki relations")
p_rel_sub = p_relations.add_subparsers(dest="relations_command")
# 6 subparsers: list / backlinks / neighbors / path / types / add-type
```

**Tests** (3): test_list, test_backlinks, test_find_path.

```bash
git add src/cli_ext/relations_cmd.py src/cli.py src/pipeline/generator.py tests/test_cli_ext/test_cmd_relations.py
git commit -m "feat(wiki): add Generator relations emission + 'relations' CLI (6 subcommands)"
```

---

## Self-Review

- [x] 16 built-in types + symmetric handling ✓
- [x] Bidirectional sync via INVERSE_RELATIONS table ✓
- [x] 4 query operations: list / backlinks / neighbors / path ✓
- [x] CLI ✓
- [x] Graph relevance scoring (4-signal) deferred to v2.1+

## Implementation order

Tasks 1-3 chain. Total: 3 tasks, ~2-3 hours.