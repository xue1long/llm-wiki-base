# Wiki Relations (Typed Graph) Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 15e4e67, post-Vision spec)
**Inspired by:** Novel-Knowledge-Base v3.0 `relations: [{target, type, weight, context}]`

## Goal

Extend Wiki v2.0's flat wikilink graph with **typed relations**: each wiki page declares explicit typed relationships to other pages (`target` + `type` + `weight` + `context`). This transforms the wiki from a wikilink-only graph into a queryable typed knowledge graph suitable for graph algorithms, multi-hop reasoning, and weighted relevance scoring (future v2.2).

The Generator's Step 2 prompt is extended to emit `relations` alongside `body_markdown` for each page. Frontmatter parser validates and stores relations. Bidirectional sync keeps both sides consistent.

## Non-goals

- No graph visualization UI (deferred to Graph UI spec).
- No weighted graph algorithms (4-signal relevance scoring, Louvain community detection — deferred).
- No relation inference from natural language (LLM-only for now).
- No graph versioning (relations don't have their own history).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `Relation` dataclass (target / type / weight / context)
- `RelationSync` (bidirectional)
- `RelationQuery` (list / backlinks / neighbors / path)
- 16 built-in relation types
- User-defined x-* types

**This spec requires from other specs**:

- **Wiki v2.0 (REQUIRED)**: `WikiPage` extended with `relations` field
- **Schemas v3 (REQUIRED)**: v2.0 → v2.1 migration for relations field
- **src/shared/**: bidirectional sync primitives

**Phase**: Phase 3 — Wiki Polish
**Priority**: P1 — v2.1

## Architecture

```
Generator.generate() produces pages (existing)
   │
   ▼
NEW: Generator now also produces relations per page:
   - relations: list[{target_id, type, weight, context}]
   - Target must be either: existing wiki page id OR slug OR new slug to be created this turn
   │
   ▼
page_writer.write() writes frontmatter + body
   │
   ▼
NEW: relation_writer.sync_bidirectional(page_id, outgoing_relations)
   - For each (page_id, type, target_id):
     - Write outgoing relation to page_id's frontmatter (existing page)
     - Compute inverse relation (see INVERSE_RELATIONS table)
     - If inverse applies: write inverse relation to target_id's frontmatter
   - Deduplicate: if relation already exists, merge (update weight/context if different)

Backlinks = scan all wiki pages for relations where target == current page
(separate read-side query; not stored explicitly to avoid duplication)
```

## Components

### New modules

```
src/wiki/relations.py            # RelationSync + RelationQuery + INVERSE_RELATIONS table
src/cli_ext/relations_cmd.py     # cmd_relations list/show/find/path
tests/test_wiki/test_relations.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/types.py` | `WikiPage` add `relations: list[Relation] = field(default_factory=list)` |
| `src/wiki/page_writer.py` | Write `relations:` field to frontmatter; load existing frontmatter + preserve relations on update |
| `src/pipeline/processor.py` | Generator Step 2 prompt emits `relations` per page |
| `src/pipeline/prompts/generator.py` | Prompt template includes `relations` schema |
| `src/project/settings.py` | `WikiSettings` add `relation_types: list[str] = RELATION_TYPES_DEFAULT` |

## Data structures

```python
# src/types.py (additions)
@dataclass
class Relation:
    target_id: str                            # target page id (kebab-case)
    type: str                                 # from RELATION_TYPES enum
    weight: float = 1.0                      # 0.0-1.0, LLM-assigned confidence
    context: str = ""                         # ≤ 200 字上下文

    def to_frontmatter(self) -> dict:
        return {"target": self.target_id, "type": self.type, "weight": round(self.weight, 2), "context": self.context}

    @classmethod
    def from_frontmatter(cls, d: dict) -> "Relation":
        return cls(target_id=d["target"], type=d["type"], weight=d.get("weight", 1.0), context=d.get("context", ""))
```

```python
# src/wiki/relations.py
RELATION_TYPES_DEFAULT = [
    "is_part_of",          # A is_part_of B → B contains A
    "references",          # A references B → A cites B (no implication)
    "causes",              # A causes B → A leads to B (temporal)
    "contradicts",         # A contradicts B → mutually exclusive
    "supports",            # A supports B → A is evidence for B
    "supersedes",          # A supersedes B → A replaces B
    "depends_on",          # A depends_on B → A requires B
    "analogous_to",        # A analogous_to B → similar pattern
    "opposite_of",         # A opposite_of B → polarity reverse
    "derived_from",        # A derived_from B → A is computed from B
]

# Inverse relation table — when A has relation R to B, B automatically gets relation R' to A
INVERSE_RELATIONS = {
    "is_part_of":   "contains",
    "contains":      "is_part_of",
    "references":    "referenced_by",
    "referenced_by": "references",
    "causes":        "caused_by",
    "caused_by":     "causes",
    "contradicts":   "contradicts",     # symmetric
    "supports":      "supported_by",
    "supported_by":  "supports",
    "supersedes":    "superseded_by",
    "superseded_by": "supersedes",
    "depends_on":    "required_by",
    "required_by":   "depends_on",
    "analogous_to":  "analogous_to",   # symmetric
    "opposite_of":   "opposite_of",    # symmetric
    "derived_from":  "derives",        # inverse (asymmetric)
    "derives":       "derived_from",
}

USER_DEFINED_PREFIX = "x-"                 # user-defined types use prefix "x-my_type"

class RelationSync:
    """Bidirectional sync of relations in wiki/."""
    
    def sync_page(self, ctx: ProjectContext, page: WikiPage, relations: list[Relation]) -> SyncReport:
        """Update page's frontmatter.relations + apply inverse relations to target pages."""
        # 1. Load existing relations from frontmatter
        existing = self._load_existing_relations(ctx, page)
        # 2. Compute new relations
        new_relations = [r for r in relations if not self._exists(existing, r)]
        # 3. Write updated frontmatter
        self._write_relations_to_page(page, relations)
        # 4. For each new relation, write inverse to target
        for r in new_relations:
            target_page = self._load_page(ctx, r.target_id)
            if not target_page:
                continue  # target doesn't exist (will be created later?)
            inverse_type = INVERSE_RELATIONS.get(r.type)
            if not inverse_type:
                continue
            inverse = Relation(
                target_id=page.id,
                type=inverse_type,
                weight=r.weight,
                context=r.context,
            )
            target_existing = self._load_existing_relations(ctx, target_page)
            if not self._exists(target_existing, inverse):
                self._add_relation_to_page(target_page, inverse)
        return SyncReport(...)

class RelationQuery:
    """Read-side queries over relations."""
    
    def list_relations(self, ctx: ProjectContext, page_id: str) -> list[Relation]:
        """Read frontmatter.relations from page."""
        ...
    
    def find_backlinks(self, ctx: ProjectContext, page_id: str) -> list[Relation]:
        """Scan all wiki pages for relations where target == page_id."""
        ...
    
    def find_neighbors(self, ctx: ProjectContext, page_id: str, depth: int = 1) -> list[tuple[str, str, float]]:
        """BFS up to `depth` hops. Returns (neighbor_id, via_relation, cumulative_weight)."""
        ...
    
    def find_path(self, ctx: ProjectContext, source_id: str, target_id: str) -> list[tuple[str, str]]:
        """BFS shortest path. Returns [(from_id, to_id, relation_type), ...]."""
        ...
```

## Frontmatter schema

```yaml
---
id: backprop
type: concept
title: Backpropagation
sources: [raw/sources/paper-1.pdf]
created_at: 1721558400000
updated_at: 1721558600000
relations:
  - target: gradient-descent
    type: depends_on
    weight: 0.95
    context: Backprop uses gradient descent to update weights
  - target: neural-network
    type: is_part_of
    weight: 1.0
    context: Backprop is a component of neural network training
---

# Backpropagation
...
```

## Generator prompt extension

```python
# src/pipeline/prompts/generator.py
GENERATOR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "frontmatter_extra": {"type": "object"},
                    "body_markdown": {"type": "string"},
                    "relations": {                          # NEW
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_id": {"type": "string"},
                                "type": {"type": "enum", "enum": RELATION_TYPES_DEFAULT + [USER_DEFINED_PREFIX + "*"]},
                                "weight": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                "context": {"type": "string", "maxLength": 200}
                            },
                            "required": ["target_id", "type"]
                        },
                        "maxItems": 20
                    }
                },
                "required": ["id", "type", "title", "body_markdown"]
            }
        }
    }
}
```

## CLI surface

```
python -m src.cli relations list <page_id> [--project <id>]
    # List outgoing relations for page

python -m src.cli relations backlinks <page_id> [--project <id>]
    # List pages that reference this page

python -m src.cli relations neighbors <page_id> [--depth N] [--project <id>]
    # BFS 1-2 hop neighbors

python -m src.cli relations path <from_id> <to_id> [--project <id>]
    # Shortest path between two pages

python -m src.cli relations types [--project <id>]
    # List all known relation types (built-in + user-defined)

python -m src.cli relations add-type <name> --project <id>
    # Register user-defined relation type (e.g., "x-custom-relation")
```

## HTTP + MCP

```
GET    /api/v1/projects/{id}/relations/{page_id}                   # outgoing
GET    /api/v1/projects/{id}/relations/{page_id}/backlinks          # incoming
GET    /api/v1/projects/{id}/relations/{page_id}/neighbors?depth=1 # 1-hop
GET    /api/v1/projects/{id}/relations/path?from=X&to=Y             # path
POST   /api/v1/projects/{id}/relations/types                        # register user type

MCP tools:
ruflo_kb_relations_list(project_id, page_id)
ruflo_kb_relations_backlinks(project_id, page_id)
ruflo_kb_relations_neighbors(project_id, page_id, depth)
ruflo_kb_relations_path(project_id, from_id, to_id)
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Generator LLM | Unknown relation type | If starts with `x-` → accept (user-defined); else → reject + retry |
| Generator LLM | weight > 1.0 or < 0 | Clamp to [0, 1] + warning |
| Generator LLM | target_id doesn't exist in current pages | Accept (target may be created this turn); check after all pages written |
| Relation sync | Target page not in wiki/ | Skip inverse; log warning; don't fail |
| Relation sync | Circular relation (A→B→A) | Allow (e.g., "analogous_to" is symmetric) |
| Frontmatter load | relations field malformed | Skip page; log error |
| Frontmatter save | YAML serialization error | Atomic write fails; abort |
| User-defined type | No `x-` prefix | Force-add prefix |
| Bidirectional sync | Race condition (two writes simultaneously) | Use wiki mutex (existing); last write wins |
| Query: BFS depth > 5 | Performance | Cap at depth=5; warn |
| Query: cyclic graph | Infinite BFS | Track visited; standard BFS termination |
| Lint cascade | Existing wikilinks → relations | Detect + log "X pages have wikilinks but no relations" |

## Backwards compatibility

- Existing wiki pages without `relations:` field: treated as `relations: []`.
- Existing wikilinks in body: **not** auto-migrated to relations (user can run `python -m src.cli relations migrate-wikilinks` if desired).
- Frontmatter load is forward-compatible (`extra="allow"`): unknown relation types preserved as-is.
- HTTP API responses include both `relations` and `wikilinks` for compatibility.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/wiki/relations.py` | INVERSE_RELATIONS table; sync bidirectional; dedup; symmetric types; x-prefix user types |
| `src/pipeline/prompts/generator.py` | relations schema in prompt; mock LLM response with relations |
| `src/types.py::Relation` | to_frontmatter / from_frontmatter round-trip |
| `src/cli_ext/relations_cmd.py` | All subcommands |

### Integration tests

```
tests/test_integration/test_relations_e2e.py:
    def test_ingest_creates_typed_relations():
        # Ingest; verify frontmatter has relations
        # Verify inverse relations on target pages

    def test_path_query_finds_route():
        # Create 3 pages A→B→C with relations
        # path A C returns [(A,B), (B,C)]

    def test_backlinks_query():
        # Create page B with relations referring to A
        # backlinks A returns [(B, "references")]

    def test_symmetric_relation_handling():
        # A contradicts B should NOT double-write both sides with same type

    def test_x_prefix_user_type():
        # Register "x-my-type"
        # LLM emits relation with type "x-my-type"
        # Accept and persist
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P1)

- Generator emits relations per page
- Bidirectional sync via INVERSE_RELATIONS table
- 16 built-in types (is_part_of / references / causes / etc.)
- User-defined x-* types
- CLI: `relations {list,backlinks,neighbors,path,types,add-type}`

### Polish (v2.0.1 or later)

- Relation versioning
- Relation inference from prose

### Deferred (v2.1+)

- Visual graph UI
- 4-signal relevance scoring (separate spec)
- Graph algorithms (Louvain / PageRank)
- Cross-project relations

## Implementation order

5 phases:

1. **Foundation** — `Relation` dataclass + `RELATION_TYPES_DEFAULT` + `INVERSE_RELATIONS` + tests
2. **RelationSync** — bidirectional sync + dedup + tests
3. **RelationQuery** — list / backlinks / neighbors / path + tests
4. **Generator integration** — prompt schema + relations emission + tests
5. **CLI + HTTP + MCP** — `cmd_relations` + endpoints + tools + integration tests

## Cost estimation

- Per page: +5-10 tokens output (relations field)
- Per project: +~$0.001 per ingest (negligible)

## Open questions / deferred

- Relation versioning (history of relation changes).
- Relation inference from prose (LLM scans body text for "X leads to Y" patterns and suggests relations).
- Bulk relation migration from NKB (import relations from NKB v3.0 export).
- Multi-modal relations (image-to-page relations).
- Visual graph UI (sigma.js like llm_wiki-main).
- Graph algorithms (4-signal relevance, Louvain, PageRank).
- Cross-project relations (A in project X relates to B in project Y).