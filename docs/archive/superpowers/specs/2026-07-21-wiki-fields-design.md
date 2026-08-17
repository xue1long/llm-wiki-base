# Wiki Fields Design Spec (v2.2)

**Date:** 2026-07-22
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 6eff137, post-Atomic-Budgeted spec)
**Inspired by:** Novel-Knowledge-Base v3.0 wiki page fields

## Goal

Extend Wiki v2.0's wiki page fields with eight new fields borrowed from NKB:

| Field | Type | Purpose |
|---|---|---|
| `id` | string (26 chars) | UUID v7-style sortable identifier with creation time prefix |
| `grade` | enum | Source quality A/B/C; combined with `processing_depth` controls Generator routing |
| `processing_depth` | enum | `concept` (full wiki) or `memory` (mini-wiki) |
| `use_context` | string | AI retrieval hint: when to use this page |
| `maturity` | enum | `draft` / `in_review` / `verified` |
| `workflow_state` | enum | Workflow state: `draft` / `reviewing` / `approved` / `archived` |
| `is_immutable` | bool | True = permanent reference, protected from auto-edit |
| `tag_namespace` | enum-prefixed | Tags with controlled prefixes (`genre/`, `func/`, etc.) |

These fields form a **L0-L3 layered validation** (NKB pattern): L0 (always required: id/title/type/sources), L1 (extended required: schema_version/created_at/updated_at/grade/processing_depth), L2 (concept-only: use_context/maturity/workflow_state), L3 (per-type conditional).

## Non-goals

- No breaking changes to existing wiki pages (new fields default to safe values via Schemas v3 migration).
- No new page types (existing source/entity/concept/.../stub types unchanged).
- No tag validator CLI in this spec (deferred to Quality Gate v2.x lint extension).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- L0-L3 layered field validation
- `FieldsValidator`
- `TagNamespace` validator (8 prefixes)
- `GradeRouter` (grade A/B/C → processing_depth concept/memory)
- UUID v7 page IDs (`card_<13hex>_<8hex>_<slug>`)
- `WikiPage` extended with 8 new fields

**This spec requires from other specs**:

- **Wiki v2.0 (REQUIRED)**: `WikiPage` base structure
- **Schemas v3 (REQUIRED)**: v2.0 → v2.2 migration
- **Health Check (REQUIRED)**: H4 ID format uses `ID_PATTERN`

**Phase**: Phase 3 — Wiki Polish
**Priority**: P1 — v2.0.1

## Architecture

```
Wiki page frontmatter (after this spec):
---
id: card_01j7xyz_stable-slug     # 26-char UUID v7 + slug suffix
schema_version: v2.2
title: 林风
type: entity

# L0 (always required)
sources: [raw/sources/novel-1.pdf]
created_at: 1721558400000
updated_at: 1721558600000

# L1 (extended required)
grade: A                           # source quality: A | B | C
processing_depth: concept         # concept | memory
use_context: "Character main hero"  # AI retrieval hint (free-form, ≤ 200 chars)
maturity: verified                # draft | in_review | verified
workflow_state: approved          # draft | reviewing | approved | archived
is_immutable: false               # true = protected from auto-edit

# L2 (typed-conditional)
tag_namespace:                    # controlled prefixes
  genre: [genre/玄幻]
  func: [func/人设]
  char: [char/男主]
relations: []                     # from Wiki Relations spec (v2.1)
pool: pool_3                      # from Heat 5-Pool spec
heat: 50                          # from Heat 5-Pool spec
---

# 林风
...
```

## Components

### New modules

```
src/wiki/fields.py                # L0-L3 validator + GradeRouter + TagNamespaceValidator
src/wiki/id_generator.py          # UUID v7 + slug suffix
src/wiki/grade_router.py          # Grade A/B/C → processing_depth concept/memory
src/wiki/tag_namespace.py         # Allowed prefixes + validation
src/schemas/migrations/v2_1_to_v2_2.py  # Migration: add new fields to existing pages
tests/test_wiki/test_fields.py
tests/test_wiki/test_id_generator.py
tests/test_wiki/test_grade_router.py
tests/test_wiki/test_tag_namespace.py
tests/test_schemas/test_v2_1_to_v2_2.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/types.py` | `WikiPage` adds: `grade`, `processing_depth`, `use_context`, `maturity`, `workflow_state`, `is_immutable`, `tag_namespace: dict[str, list[str]]` |
| `src/pipeline/processor.py` | Generator Step 2 prompt includes new fields; `GradeRouter` selects depth |
| `src/pipeline/analyzer.py` | Analyzer Step 1 includes `grade` in prompt; classifies A/B/C |
| `src/wiki/templates.py` | `render_*` templates inject new fields |
| `src/orchestrator/audit_hard.py` | L0-L3 validation |
| `src/wiki/templates.py` | `render_concept_page` and `render_memory_page` (mini-wiki, single section) |
| `src/schemas/registry.py` | Schema bumped to v2.2 |

## Data structures

```python
# src/types.py (additions)
class SourceGrade(str, Enum):
    A = "A"           # High quality: official docs, well-edited articles, peer-reviewed
    B = "B"           # Medium: blog posts, general articles
    C = "C"           # Low quality: social media, forum posts, snippets

class ProcessingDepth(str, Enum):
    CONCEPT = "concept"     # Full wiki page (all sections)
    MEMORY = "memory"       # Mini-wiki (1-2 sections, condensed)

class Maturity(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"

class WorkflowState(str, Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    ARCHIVED = "archived"

@dataclass
class WikiPage:
    # ... existing v2.0 fields ...
    id: str                          # NEW: 26-char UUID v7 + slug
    grade: SourceGrade = SourceGrade.B
    processing_depth: ProcessingDepth = ProcessingDepth.CONCEPT
    use_context: str = ""
    maturity: Maturity = Maturity.DRAFT
    workflow_state: WorkflowState = WorkflowState.DRAFT
    is_immutable: bool = False
    tag_namespace: dict[str, list[str]] = field(default_factory=dict)
```

```python
# src/wiki/id_generator.py
import time
import secrets

def generate_page_id(slug: str) -> str:
    """Generate 26-char ID: card_<13hex_millis>_<8hex_random>.
    
    Example: card_018f3a8e2b1c4_a3f9d12c
    
    - 13 hex chars = millisecond timestamp (sortable)
    - 8 hex chars = random suffix (collision resistance)
    - slug appended for human readability
    """
    millis = int(time.time() * 1000) & 0x1FFFFFFFFFFFF  # 13 hex chars
    random_suffix = secrets.token_hex(4)               # 8 hex chars
    return f"card_{millis:013x}_{random_suffix}_{slug}"

def is_valid_id(id_str: str) -> bool:
    """Validate format: card_<13hex>_<8hex>_<slug>"""
    import re
    return bool(re.match(r"^card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+$", id_str))
```

```python
# src/wiki/grade_router.py
class GradeRouter:
    """Routes sources to processing_depth based on grade."""
    
    DEFAULT_DEPTH = ProcessingDepth.CONCEPT
    
    def route(self, grade: SourceGrade) -> ProcessingDepth:
        """A/B → concept; C → memory. Defaults to concept."""
        if grade == SourceGrade.C:
            return ProcessingDepth.MEMORY
        return ProcessingDepth.CONCEPT
    
    def should_auto_promote(self, grade: SourceGrade) -> bool:
        """Whether memory pages can be promoted to concept on update."""
        return grade in (SourceGrade.A, SourceGrade.B)
```

```python
# src/wiki/tag_namespace.py
TAG_PREFIXES = {
    "genre":        "题材类型（玄幻/都市/科幻...）",
    "func":         "功能类型（人设/桥段/伏笔/章节卡）",
    "char":         "角色类型（男主/反派/配角）",
    "event":        "事件类型（打脸/升级/暧昧）",
    "mood":         "情绪氛围（热血/虐恋/甜宠）",
    "entity":       "What — 是什么（实体分类）",
    "scene_phase":  "When — 何时用（场景阶段）",
    "status":       "生命周期（高频复用/草稿沉淀）",
}

class TagNamespace:
    @staticmethod
    def is_valid(tag: str) -> bool:
        """Check if tag uses a known prefix."""
        for prefix in TAG_PREFIXES:
            if tag.startswith(prefix + "/"):
                return True
        return False
    
    @staticmethod
    def parse(tag: str) -> tuple[str, str] | None:
        """Returns (prefix, name) or None if invalid."""
        if "/" not in tag:
            return None
        prefix, _, name = tag.partition("/")
        if prefix in TAG_PREFIXES:
            return (prefix, name)
        return None
    
    @staticmethod
    def validate_page_tags(tags: list[str]) -> list[str]:
        """Returns list of invalid tags (must be empty)."""
        return [t for t in tags if not TagNamespace.is_valid(t)]
```

```python
# src/wiki/fields.py
LAYER_REQUIREMENTS = {
    # L0: always required (any page type)
    "L0": ["id", "title", "type", "sources", "created_at", "updated_at"],
    # L1: extended required
    "L1": ["schema_version", "grade", "processing_depth"],
    # L2: concept-depth pages only
    "L2_concept": ["use_context", "maturity", "workflow_state"],
    # L2: memory-depth pages (lighter requirements)
    "L2_memory": [],
    # L3: per-type conditional
    "L3_entity": [],
    "L3_concept": [],
    "L3_source": [],
    "L3_synthesis": [],
}

class FieldsValidator:
    def validate(self, page: WikiPage) -> ValidationResult:
        errors = []
        
        # L0
        for field_name in LAYER_REQUIREMENTS["L0"]:
            if not getattr(page, field_name, None):
                errors.append(f"L0 missing required: {field_name}")
        
        # L1
        for field_name in LAYER_REQUIREMENTS["L1"]:
            if getattr(page, field_name, None) is None:
                errors.append(f"L1 missing required: {field_name}")
        
        # L2 (depth-conditional)
        l2 = LAYER_REQUIREMENTS[f"L2_{page.processing_depth.value}"]
        for field_name in l2:
            if getattr(page, field_name, None) is None:
                errors.append(f"L2 missing required: {field_name}")
        
        # Tag namespace validation
        invalid_tags = TagNamespace.validate_page_tags(page.tags)
        if invalid_tags:
            errors.append(f"Invalid tag namespace: {invalid_tags}")
        
        return ValidationResult(valid=len(errors) == 0, errors=errors)
```

## Frontmatter examples

### Concept page (full wiki)

```yaml
---
id: card_018f3a8e2b1c4_a3f9d12c_lin-feng
schema_version: v2.2
title: 林风
type: entity

# L0
sources: [raw/sources/novel-1.pdf]
created_at: 1721558400000
updated_at: 1721558600000

# L1
grade: A
processing_depth: concept

# L2 (concept-only)
use_context: "Male protagonist; tech entrepreneur; lin family heir"
maturity: verified
workflow_state: approved
is_immutable: false

# Tags (validated namespace)
tags: [genre/玄幻, func/人设, char/男主]

# Cross-spec fields
relations: [{target: "lin-family", type: "is_part_of", weight: 1.0}]
pool: pool_3
heat: 75
---

# 林风

## 背景
...
```

### Memory page (mini-wiki, C-grade source)

```yaml
---
id: card_018f3a8f12345_b9d8e7f0_chapter-3-note
schema_version: v2.2
title: 第3章场景笔记
type: memory

# L0
sources: [raw/sources/weibo-screenshot.png]
created_at: 1721558700000
updated_at: 1721558700000

# L1
grade: C                           # low quality
processing_depth: memory           # mini-wiki
use_context: "Quick reference for chapter 3 scene"
maturity: draft
workflow_state: draft
is_immutable: false

tags: [status/草稿沉淀]

relations: []
pool: pool_2
heat: 30
---

# 第3章场景笔记

简短摘要 + 关键引用 + 待整理。
```

## Pipeline integration

```python
# src/pipeline/processor.py (modified)
async def generate(ctx, analysis):
    # Analyzer already determined grade in Step 1
    # GradeRouter picks processing_depth
    depth = GradeRouter().route(analysis.grade)
    
    # Generator prompt includes depth hint
    prompt = build_generator_prompt(analysis, depth_hint=depth)
    
    # Generate pages with depth-appropriate template
    pages = await llm_call(prompt, response_format=GENERATOR_SCHEMA)
    for page in pages:
        page.processing_depth = depth     # force-set from grade
        page.id = generate_page_id(page.slug)
        page.tag_namespace = parse_tag_namespace(page.tags)
        page_writer.write(page)
```

```python
# src/wiki/templates.py (additions)
def render_memory_page(page: WikiPage) -> str:
    """Mini-wiki template for grade-C sources. 1-2 sections only."""
    return f"""---
{frontmatter_yaml(page)}
---

# {page.title}

## 简短摘要
{page.summary}

## 关键引用
{page.body_markdown}
"""
```

## CLI surface

```
python -m src.cli fields validate <page_id> [--project <id>]
    # Run L0-L3 validation on one page; report missing/invalid fields

python -m src.cli fields validate-all [--project <id>]
    # Validate all wiki pages; exit 1 if any invalid

python -m src.cli fields show-schema
    # Print L0/L1/L2/L3 layer requirements

python -m src.cli fields migrate-id [--dry-run] [--project <id>]
    # Migrate old slug-based IDs to UUID v7 format

python -m src.cli tags validate <page_id> [--project <id>]
    # Validate tags against namespace prefixes

python -m src.cli tags audit [--project <id>]
    # Report all invalid tags across wiki; suggest fixes

python -m src.cli tags list-prefixes
    # List allowed prefixes
```

## HTTP + MCP

```
GET    /api/v1/projects/{id}/fields/schema          # L0-L3 layer definitions
GET    /api/v1/projects/{id}/fields/validate/{page_id}
POST   /api/v1/projects/{id}/fields/validate-all
GET    /api/v1/projects/{id}/tags/prefixes

MCP tools:
ruflo_kb_fields_validate(project_id, page_id)
ruflo_kb_fields_validate_all(project_id)
ruflo_kb_tags_validate(project_id, page_id)
ruflo_kb_tags_audit(project_id)
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| ID generation | Slug contains invalid chars | Sanitize (replace spaces with -, strip non-ascii) + warn |
| ID generation | Collision (extremely rare) | Append extra 4 random hex + warn |
| Grade routing | Unknown grade | Default to concept |
| Tag validation | Tag without prefix | TagNamespace validator lists as invalid |
| Tag validation | Unknown prefix | TagNamespace validator lists as invalid |
| L0-L3 validation | Missing required field | Error with field name + layer |
| L2 concept → memory downgrade | Grade changed A→C | Manual downgrade required (no auto) |
| Memory → concept promotion | Grade changed C→B | Auto-promote on next ingest; preserve content |
| Frontmatter load | Unknown new field | Schemas v3 extra="allow" preserves |
| Migration v2.1→v2.2 | Old ID format | Auto-convert slug → UUID v7 + slug suffix |
| Migration v2.1→v2.2 | Frontmatter parse error | Skip page; log; continue with others |
| Validation | Invalid maturity / workflow_state enum | Error |

## Backwards compatibility

- Existing wiki pages (v2.1) get new fields via `v2_1_to_v2_2` migration:
  - `grade`: default "B"
  - `processing_depth`: default "concept"
  - `use_context`: default ""
  - `maturity`: default "draft"
  - `workflow_state`: default "draft"
  - `is_immutable`: default false
  - `tag_namespace`: parsed from existing `tags:` field; invalid tags kept but flagged
  - `id`: converted from slug → `card_<millis>_<random>_<old_slug>`
- Existing tag format `tags: [玄幻, 人设]` (no prefix) treated as invalid per new namespace rules; migration keeps them but audit warns.
- CLI commands are additive.
- HTTP endpoints are additive.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/wiki/id_generator.py` | Format validation; millis sortability; collision resistance |
| `src/wiki/grade_router.py` | A/B/C routing; defaults |
| `src/wiki/tag_namespace.py` | Parse; validate; invalid prefix detection |
| `src/wiki/fields.py` | L0/L1/L2 validation; per-type; tag namespace |
| `src/schemas/migrations/v2_1_to_v2_2.py` | Up/down/preview; idempotency |
| `src/wiki/templates.py` | Memory page mini-wiki template |

### Integration tests

```
tests/test_integration/test_wiki_fields_e2e.py:
    def test_ingest_concept_page():
        # Ingest PDF (grade A)
        # Verify: page has processing_depth=concept, full template rendered

    def test_ingest_memory_page():
        # Ingest Weibo screenshot (grade C)
        # Verify: page has processing_depth=memory, mini template rendered

    def test_id_is_sortable_by_creation():
        # Create 10 pages with 100ms delays
        # Verify: IDs sort by creation time

    def test_tag_audit():
        # Create pages with invalid tags
        # Run tags audit
        # Verify: invalid tags listed + suggested prefix
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P1)

- 4 fields: id (UUID v7) / grade / processing_depth / is_immutable
- Tag namespace validation (8 prefixes)
- Migration v2.0 → v2.2
- CLI: `fields validate / tags validate`

### Polish (v2.0.1 or later)

- Remaining 4 fields: use_context / maturity / workflow_state
- L3 per-type conditional fields
- Tag audit CLI

### Deferred (v2.1+)

- Auto-promote memory → concept
- Tag auto-suggestion
- Per-namespace tag color/icon

## Implementation order

5 phases:

1. **Foundation** — type extensions + UUID v7 generator + TagNamespace + tests
2. **GradeRouter + memory template** — route by grade + render memory pages + tests
3. **L0-L3 validator** — FieldsValidator + audit_hard integration + tests
4. **Migration v2.1 → v2.2** — add new fields + convert IDs + tests
5. **CLI + HTTP + MCP** — `cmd_fields` + `cmd_tags` + endpoints + integration tests

## Cost estimation

- New code: ~800 lines
- New tests: ~400 lines
- Migration cost: O(N existing pages) — for 1000 pages: ~5 seconds

## Open questions / deferred

- Auto-promote memory → concept on grade upgrade (current: manual).
- Per-namespace tag color/icon (Obsidian-specific).
- Tag co-occurrence analysis (which tags cluster).
- Tag auto-suggestion (LLM proposes tags during ingest).
- L3 per-type required fields (e.g., entity needs 阵营 / concept needs 来源 etc.).
- Card ID migration is one-way (down_fn can't reverse to slug IDs).