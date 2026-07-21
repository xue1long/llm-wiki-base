# Wiki Heat + 5-Pool Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ fe95f79, post-Schemas-v3 spec)
**Inspired by:** Novel-Knowledge-Base v3.0 5-Pool + Heat system

## Goal

Add two complementary systems that make AI retrieval over the wiki intelligent:

1. **5-Pool scope** — every wiki page declares which "pool" it belongs to (hard constraint / atmosphere / causal / narrative / commons / drift). AI retrieval is routed by pool priority.

2. **Heat decay** — every page has a `heat: 0-100` score that decays over time (-10/30 days unused) and grows on use (+5 per AI retrieval). Pages with heat=0 for 30 consecutive days are flagged as "zombie" and an auto-staging draft is generated.

These systems transform the wiki from a flat dump of pages into a self-curating knowledge base that surfaces relevant content and self-prunes stale entries.

## Non-goals

- No user-defined pool types (fixed enum for v1).
- No heat-based auto-deletion (only warning + staging draft).
- No graph-based heat propagation (heat doesn't propagate via relations in v1).
- No UI for heat/pool visualization (CLI + HTTP only).

## Architecture

### 5-Pool routing

```
AI retrieval (Search / Chat / Agent):
  1. Get candidates from hybrid search (existing vector + keyword)
  2. Group by pool:
     pool_1 (hard constraints) → ALWAYS included
     pool_2 (atmosphere)      → included for creative tasks
     pool_3 (causal graph)    → included for factual reasoning
     pool_4 (narrative)       → included for writing tasks
     ccd (commons)            → included for project context
     drift (unclassified)     → NEVER included unless --include-drift
  3. Within each pool: rank by heat (high → low)
  4. Take top-K from each pool, merge into final ranking

Heat-aware filtering:
  - heat >= 60: HOT (top 50% of pool, always retrieved)
  - 30 <= heat < 60: WARM (normal ranking)
  - heat < 30: COLD (skip unless --include-cold)
```

### Heat update flow

```
AI retrieval hits page P:
  1. heat_tracker.increment(P, +5)
  2. Persist heat to P's frontmatter (debounced, batched)
  3. Log to .index/heat_events.log

Daily background task (or on cmd_heat_decay):
  1. Scan all wiki pages
  2. For each page P: if last_used_at > 30 days ago → heat -= 10
  3. If heat < 0 → clamp to 0
  4. If heat == 0 for 30 consecutive days:
     - Generate staging draft (.index/staging/<P.id>-<ts>.md)
     - Append to .index/zombie_review.json
     - Emit EventName.ZOMBIE_DETECTED
```

## Components

### New modules

```
src/wiki/pool_router.py          # PoolRouter: classify + priority
src/wiki/heat_tracker.py         # HeatTracker: increment + decay + zombie detection
src/wiki/zombie_detector.py      # ZombieDetector + staging draft generator
src/cli_ext/heat_cmd.py          # cmd_heat show/decay/zombies/pool-stats
tests/test_wiki/test_pool_router.py
tests/test_wiki/test_heat_tracker.py
tests/test_wiki/test_zombie_detector.py
tests/test_cli_ext/test_cmd_heat.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/types.py` | `WikiPage` add `pool: str = "drift"` + `heat: int = 50` + `last_used_at: int = 0` + `zombie_since: int | None = None` |
| `src/wiki/templates.py` | `render_source_page` add pool/heat fields |
| `src/pipeline/processor.py` | Generator Step 2 prompt includes pool + heat initialization |
| `src/searcher/hybrid_search.py` | `hybrid_search` calls `heat_tracker.increment(page, +5)` per result |
| `src/chat_agent/runtime.py` | Agent loop calls `heat_tracker.increment` per wiki tool result |
| `src/schemas/migrations/` | New v2.0→v2.1 migration adds pool/heat to existing pages (default: pool=drift, heat=50) |
| `src/project/settings.py` | `WikiSettings` add `pool_priorities: dict[str, int]` + `heat_decay_days: int = 30` + `heat_decay_amount: int = 10` + `heat_increment_amount: int = 5` |

## Data structures

```python
# src/types.py (additions)
class Pool(str, Enum):
    POOL_1 = "pool_1"            # 硬约束（世界观铁律、不可变设定）
    POOL_2 = "pool_2"            # 氛围弹药（金句、场景切片）
    POOL_3 = "pool_3"            # 因果图谱（伏笔链、事件节拍）
    POOL_4 = "pool_4"            # 叙事语法（技法、转场公式）
    CCD = "ccd"                  # 创作公约数（项目上下文）
    DRIFT = "drift"              # 漂流（未分类）

@dataclass
class WikiPage:
    # ... existing fields ...
    pool: Pool = Pool.DRIFT
    heat: int = 50                          # 0-100
    last_used_at: int = 0                   # unix ms
    zombie_since: int | None = None         # unix ms when heat hit 0
```

```python
# src/wiki/pool_router.py
POOL_DESCRIPTIONS = {
    Pool.POOL_1: "Hard constraints: world rules, immutable lore",
    Pool.POOL_2: "Atmosphere: quotes, scene fragments",
    Pool.POOL_3: "Causal graph: foreshadows, event beats",
    Pool.POOL_4: "Narrative syntax: techniques, transition formulas",
    Pool.CCD: "Creative commons: project context",
    Pool.DRIFT: "Drift: unclassified",
}

DEFAULT_POOL_PRIORITIES = {
    Pool.POOL_1: 100,    # always
    Pool.POOL_2: 60,
    Pool.POOL_3: 80,
    Pool.POOL_4: 70,
    Pool.CCD: 90,
    Pool.DRIFT: 0,       # never (unless --include-drift)
}

class PoolRouter:
    """Routes AI retrieval through pool priorities."""
    
    def __init__(self, settings: WikiSettings):
        self.priorities = settings.pool_priorities or DEFAULT_POOL_PRIORITIES
    
    def rank_by_pool(self, candidates: list[tuple[WikiPage, float]]) -> list[tuple[WikiPage, float]]:
        """Re-rank candidates by pool priority * similarity."""
        return sorted(
            candidates,
            key=lambda c: self.priorities[c[0].pool] * c[1],
            reverse=True,
        )
    
    def filter_pools(self, candidates: list[WikiPage], include_cold: bool = False, include_drift: bool = False) -> list[WikiPage]:
        """Filter out cold / drift pages by default."""
        filtered = []
        for p in candidates:
            if p.heat < 30 and not include_cold:
                continue
            if p.pool == Pool.DRIFT and not include_drift:
                continue
            filtered.append(p)
        return filtered
```

```python
# src/wiki/heat_tracker.py
@dataclass
class HeatEvent:
    page_id: str
    delta: int                          # +5 (use) or -10 (decay)
    reason: str                         # "ai_retrieval" | "daily_decay" | "manual"
    at: int

class HeatTracker:
    HEAT_LOG_PATH = ".index/heat_events.log"
    HEAT_DEBOUNCE_MS = 5000             # batch writes within 5s window
    
    def __init__(self, ctx: ProjectContext):
        self.ctx = ctx
        self._pending_writes: dict[str, int] = {}  # page_id → new heat
        self._last_write_ms: int = 0
    
    def increment(self, page_id: str, delta: int = 5, reason: str = "ai_retrieval") -> None:
        """Called when AI retrieves a page."""
        page = self._load_page(page_id)
        new_heat = min(100, max(0, page.heat + delta))
        self._pending_writes[page_id] = new_heat
        page.heat = new_heat
        page.last_used_at = int(time.time() * 1000)
        page.zombie_since = None  # reset zombie
        self._log_event(page_id, delta, reason)
        self._maybe_flush()
    
    def decay(self) -> list[HeatEvent]:
        """Run decay for all wiki pages. Returns list of decayed events."""
        events = []
        now = int(time.time() * 1000)
        threshold_ms = now - self.ctx.settings.wiki.heat_decay_days * 86400 * 1000
        
        for page in self._all_wiki_pages():
            if page.last_used_at > 0 and page.last_used_at < threshold_ms:
                new_heat = max(0, page.heat - self.ctx.settings.wiki.heat_decay_amount)
                old_heat = page.heat
                page.heat = new_heat
                page.frontmatter_update()  # persist
                events.append(HeatEvent(page_id=page.id, delta=new_heat - old_heat, reason="daily_decay", at=now))
                if new_heat == 0 and page.zombie_since is None:
                    page.zombie_since = now
                    self._on_zombie_detected(page)
        return events
    
    def _on_zombie_detected(self, page: WikiPage) -> None:
        """Generate staging draft for zombie page."""
        zombie_detector.generate_staging_draft(page)
```

```python
# src/wiki/zombie_detector.py
class ZombieDetector:
    STAGING_DIR = ".index/staging"
    ZOMBIE_LOG_PATH = ".index/zombie_review.json"
    
    def generate_staging_draft(self, page: WikiPage) -> Path:
        """Generate a .md draft summarizing page state + last-used info."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        draft_path = self.STAGING_DIR / f"{page.id}-{timestamp}.md"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft = f"""# Staging: {page.title} (zombie)

- **page_id**: {page.id}
- **last_used_at**: {datetime.fromtimestamp(page.last_used_at / 1000).isoformat()}
- **days_since_use**: {(time.time() * 1000 - page.last_used_at) / 86400000:.1f}
- **pool**: {page.pool}
- **heat**: {page.heat}

## Question for human review

This page has not been retrieved by AI in {self.ctx.settings.wiki.heat_decay_days} days.

Choose one:
1. **Keep**: Mark as `is_immutable: true` (permanent reference); heat reset to 100.
2. **Archive**: Move to `wiki/_archive/<page.id>.md`; remove from active retrieval.
3. **Update**: Ingest new content; page will be regenerated.
"""
        draft_path.write_text(draft, encoding="utf-8")
        self._append_zombie_log(page)
        return draft_path
    
    def list_zombies(self) -> list[ZombieRecord]: ...
    def restore_page(self, page_id: str) -> None: ...  # heat = 100, is_immutable
    def archive_page(self, page_id: str) -> None: ...    # move to wiki/_archive/
```

## CLI surface

```
python -m src.cli heat show <page_id> [--project <id>]
    # Show heat, last_used_at, pool, decay history

python -m src.cli heat top [--pool pool_1] [--limit N] [--project <id>]
    # Top hot pages in pool (default: all pools)

python -m src.cli heat cold [--pool pool_1] [--limit N] [--project <id>]
    # Cold pages (heat < 30)

python -m src.cli heat decay [--dry-run] [--project <id>]
    # Run heat decay once; show what would change
    # Add to cron for daily execution

python -m src.cli heat zombies [--project <id>]
    # List all zombie pages

python -m src.cli heat restore <page_id> [--project <id>]
    # Mark page as warm (heat=100, is_immutable=true)

python -m src.cli heat archive <page_id> [--project <id>]
    # Move zombie to wiki/_archive/

python -m src.cli heat pool-stats [--project <id>]
    # Per-pool stats: count, avg heat, top pages
```

## HTTP + MCP

```
GET    /api/v1/projects/{id}/heat/{page_id}
GET    /api/v1/projects/{id}/heat/top?pool=pool_1&limit=10
GET    /api/v1/projects/{id}/heat/cold?pool=pool_1&limit=10
POST   /api/v1/projects/{id}/heat/decay  # trigger decay run
GET    /api/v1/projects/{id}/heat/zombies
POST   /api/v1/projects/{id}/heat/{page_id}/restore
POST   /api/v1/projects/{id}/heat/{page_id}/archive

MCP tools:
ruflo_kb_heat_show / heat_top / heat_cold / heat_decay / heat_zombies / heat_restore / heat_archive
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Heat increment | Page not in registry | Skip + log |
| Heat persistence | Disk full | Log; keep in-memory state; retry next increment |
| Decay | Page last_used_at = 0 (never used) | Skip decay (not yet evaluated) |
| Zombie detection | Staging dir not writable | Log + skip; emit alert event |
| Staging draft | LLM call fails | Write stub staging with placeholders |
| Restore | Page doesn't exist | Error |
| Archive | Page is_immutable=true | Error + refuse |
| Archive | wiki/_archive/ already has page | Overwrite (idempotent) |
| Pool re-rank | Page has unknown pool | Treat as drift (lowest priority) |
| Background decay | Lock contention with ingest | Use wiki mutex; skip if held |

## Backwards compatibility

- Existing wiki pages without `pool:` field: default to `pool: drift`.
- Existing wiki pages without `heat:` field: default to `heat: 50` (WARM).
- Search without pool routing: existing behavior unchanged (just lower-quality ranking).
- `--include-drift` / `--include-cold` flags opt-in to expanded results.
- Schemas migration: `v2_to_v3` migration adds pool/heat defaults to all existing pages.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/wiki/pool_router.py` | Ranking order; priority * similarity; cold/drift filtering |
| `src/wiki/heat_tracker.py` | Increment / decay; debounced flush; threshold detection |
| `src/wiki/zombie_detector.py` | Staging draft generation; log append; restore / archive |

### Integration tests

```
tests/test_integration/test_heat_e2e.py:
    def test_heat_increments_on_ai_retrieval():
        # Search hits page A
        # Verify: page A's heat incremented by 5

    def test_heat_decay_after_30_days():
        # Mock clock to 31 days later
        # Run cmd_heat decay
        # Verify: unused pages' heat dropped by 10

    def test_zombie_detected_after_30_days_at_zero():
        # Mock clock + force heat to 0
        # Wait 30 days
        # Verify: zombie_since set; staging draft created

    def test_pool_routing_search():
        # Create pages in pool_1 + pool_4 + drift
        # Search without --include-drift
        # Verify: drift page excluded
```

## Implementation order

5 phases:

1. **Foundation** — Pool enum + WikiPage fields + PoolRouter + tests
2. **Heat tracker** — increment + decay + persistence + tests
3. **Zombie detector** — staging draft + log + restore/archive + tests
4. **Generator integration** — pool/heat initialization in Step 2 prompt + tests
5. **CLI + HTTP + MCP** — `cmd_heat` + endpoints + tools + integration tests

## Cost estimation

- Heat increment: free (in-memory update + debounced write)
- Heat decay: O(N) per scan; ~1000 pages in 1 second
- Zombie detection: O(Z) staging draft generation; typically <10 zombies at a time
- LLM staging draft: ~500 tokens per zombie page; ~$0.005 per draft
- Per-project daily decay cost: ~$0.05 if 10 zombies detected

## Open questions / deferred

- Heat propagation via relations (heat of related pages also increases).
- Auto-archive vs manual review (current: always manual).
- Pool inheritance (sub-pages inherit parent's pool).
- Heat as graph algorithm input (PageRank-style).
- UI visualization (heat maps, pool pie chart).
- Custom decay policies (per-pool decay rates).
- Bulk re-heat on ingest (new pages get heat=50; touch related pages).