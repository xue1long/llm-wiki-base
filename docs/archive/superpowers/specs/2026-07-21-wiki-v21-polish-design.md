# Wiki v2.1 Polish Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 703c92c, post-Web-Search-Deep-Research spec)

## Goal

Three small but high-value polish features on top of Wiki v2.0:

1. **Stub auto-materialization** — When wiki content changes and references a stub page (`type: stub`), a background worker promotes the stub to a real entity/concept page by running the Generator on the stub's accumulated context. Manual `cmd_stubs` CLI for override.

2. **Dedup `--auto` flag** — Extend `cmd_dedup` to auto-merge `confidence: "high"` duplicate groups without manual confirmation. Original pages archived to `.index/dedup_history/<canonical_id>/` for 30 days (recoverable).

3. **Lint semantic cache TTL** — Cache LLM-driven semantic lint results in `.index/lint_cache/` keyed by `(prompt_version, wiki_summaries_hash, index_version)`. TTL configurable (default 24h); invalidated when wiki `index_version` changes.

## Non-goals

- No manual wikilink re-resolution (stubs always auto-promote via background worker; no CLI dry-run option).
- No dedup merging for `medium` confidence groups (still require manual confirm).
- No LLM call deduplication beyond lint semantic (Analyzer / Generator caches deferred).
- No cross-project lint cache sharing.


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- Stub auto-materialization worker (background)
- Dedup `--auto` flag (high confidence auto-merge)
- Lint semantic cache TTL
- `StubMaterializerWorker`
- `DedupHistoryStore` (30-day archive)

**This spec requires from other specs**:

- **Wiki v2.0 (REQUIRED)**: stub pages + dedup foundation
- **Quality Gate (REQUIRED)**: lint semantic uses Judge LLM
- **AtomicContext (REQUIRED)**: stub materialization + dedup auto atomic commits

**Phase**: Phase 3 — Wiki Polish
**Priority**: P1 — v2.0.1

## Architecture

### Stub auto-materialization

```
Wiki page update / Generator creates new page with [[stub-foo-bar]] link
   │
   ▼
emit EventName.WIKI_PAGE_UPDATED
   │
   ▼
StubMaterializerWorker.on_page_updated(payload)
   │
   ▼
Scan wiki/_stubs/*.md for stubs referenced by updated page
   │
   ▼
For each stub:
   1. Collect context: stub frontmatter + pages referencing it
   2. Build AnalysisResult-equivalent prompt (entity/concept extraction)
   3. Call LLM (Generator path) to produce real page
   4. Write wiki/entities/<slug>.md (or concepts/<slug>.md)
   5. Remove wiki/_stubs/<slug>.md
   6. Update wiki/index.md (indexer)
   7. Emit EventName.STUB_MATERIALIZED

Concurrency: 1 stub at a time (mutex); max 20 stubs per Worker invocation.
```

### Dedup --auto

```
python -m src.cli dedup --auto [--threshold high] [--no-history]
   │
   ▼
DedupRunner.run_auto(ctx, threshold="high")
   │
   ▼
   1. extract_entity_summaries() — scan wiki/entities + wiki/concepts
   2. detect_duplicate_groups() — LLM detect
   3. Filter groups: confidence == threshold
   4. For each group:
      a. pick canonical_slug (highest pages count or first)
      b. merge_duplicate_group() — LLM body merge + code wikilink rewrite
      c. Write new canonical page (wiki/entities/<slug>.md or concepts/<slug>.md)
      d. Archive deleted pages to .index/dedup_history/<canonical_id>/<old_slug>.md
      e. Update wiki/index.md (indexer)
   5. Append operation log to .index/dedup_history/operations.log

Recovery: cmd_dedup undo <merge_id>  # restore archived pages
```

### Lint semantic cache

```
cmd_lint [--cache-ttl 24h] [--invalidate-cache] [--no-cache]
   │
   ▼
LintRunner.run(ctx, use_cache=True, cache_ttl=...)
   │
   ▼
   1. Compute cache_key = sha256(f"{prompt_version}:{wiki_summaries_hash}:{index_version}")
   2. Check .index/lint_cache/<cache_key>.json
      - exists + within TTL → reuse (skip LLM)
      - exists + expired → re-run LLM, refresh cache
      - missing → run LLM, write cache
   3. Cache invalidation:
      - index_version change (WikiIndexer writes new version) → expire ALL cache
      - prompt_versions.json update → expire ALL cache
      - Manual: cmd_lint --invalidate-cache (deletes .index/lint_cache/*.json)

Storage:
.index/lint_cache/
└── <sha256>.json
    {
      "key": "sha256...",
      "prompt_version": "2026-07-21-v1",
      "index_version": 42,
      "summaries_hash": "sha256...",
      "created_at": 1721558400000,
      "expires_at": 1721644800000,
      "findings": [...same shape as LintReport.issues...]
    }
```

## Components

### New modules

```
src/wiki/stubs.py              # StubMaterializerWorker + stub detection
src/wiki/dedup_auto.py         # DedupRunner auto mode + history archival
src/wiki/lint_cache.py         # LintSemanticCache + key derivation
src/cli_ext/stubs_cmd.py       # cmd_stubs list/promote/discard
tests/test_wiki/test_stubs.py
tests/test_wiki/test_dedup_auto.py
tests/test_wiki/test_lint_cache.py
tests/test_cli_ext/test_cmd_stubs.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/events/events.py` | `EventName.WIKI_PAGE_UPDATED`, `EventName.STUB_MATERIALIZED` |
| `src/wiki/indexer.py` | Emit `WIKI_PAGE_UPDATED` on index.md update |
| `src/cli_ext/dedup.py` | `cmd_dedup --auto` + `cmd_dedup undo <merge_id>` |
| `src/cli.py` | `stubs` subcommand dispatch |
| `src/wiki/dedup.py` | `merge_duplicate_group()` add `archive_to: Path` parameter |

## Data structures

```python
# src/wiki/stubs.py
@dataclass
class StubPage:
    slug: str
    file_path: Path
    referenced_by: list[str]                   # paths to pages with [[stub-slug]] link
    created_at: int
    materialization_attempts: int = 0         # retry counter

class StubMaterializerWorker:
    MAX_STUBS_PER_RUN = 20
    MAX_RETRIES = 2
    
    async def on_page_updated(self, payload: WIKI_PAGE_UPDATED_Payload) -> None:
        async with self._lock:
            referenced_slugs = self._scan_referenced_stubs(payload.page_path)
            for slug in referenced_slugs[:self.MAX_STUBS_PER_RUN]:
                if await self._materialize(slug):
                    event_bus.emit(EventName.STUB_MATERIALIZED, ...)
    
    async def _materialize(self, slug: str) -> bool:
        stub = self._load_stub(slug)
        if not stub:
            return False
        # 1. Build context from referring pages
        context = self._collect_context(stub)
        # 2. Call LLM via Generator.regenerate_one_page
        new_page = await self.ctx.generator.regenerate_stub(stub, context)
        # 3. Write wiki/entities/<slug>.md (or concepts/)
        new_page.write(...)
        # 4. Remove wiki/_stubs/<slug>.md
        stub.file_path.unlink()
        # 5. Update index.md (incremental)
        return True
```

```python
# src/wiki/dedup_auto.py
@dataclass
class DedupMergeRecord:
    id: str                                    # uuid
    canonical_slug: str
    merged_slugs: list[str]
    confidence: str
    merged_at: int
    expires_at: int                            # 30 days after merge
    archive_path: Path                         # .index/dedup_history/<id>/

class DedupHistoryStore:
    HISTORY_DIR = ".index/dedup_history"
    RETENTION_DAYS = 30
    
    def record(self, merge: DedupMergeRecord) -> None: ...
    def list_active(self) -> list[DedupMergeRecord]: ...    # not yet expired
    def restore(self, merge_id: str) -> None: ...           # undo merge
    def cleanup_expired(self) -> int: ...                   # runs on every cmd_dedup

class DedupAutoRunner:
    async def run_auto(self, ctx: ProjectContext, threshold: str = "high") -> list[DedupMergeRecord]:
        # 1. extract_entity_summaries
        # 2. detect_duplicate_groups (LLM)
        # 3. Filter by threshold
        # 4. merge_duplicate_group per group
        # 5. Record history
        # 6. Return merge records for CLI report
```

```python
# src/wiki/lint_cache.py
@dataclass
class LintCacheEntry:
    key: str
    prompt_version: str
    index_version: int
    summaries_hash: str
    created_at: int
    expires_at: int
    findings: list[dict]

class LintSemanticCache:
    CACHE_DIR = ".index/lint_cache"
    DEFAULT_TTL_SECONDS = 86400                # 24h
    
    def cache_key(self, prompt_version: str, summaries: list[str], index_version: int) -> str:
        h = hashlib.sha256()
        h.update(f"{prompt_version}:{index_version}:".encode())
        for s in sorted(summaries):
            h.update(s.encode())
        return h.hexdigest()
    
    def get(self, key: str) -> LintCacheEntry | None:
        """Returns entry if exists AND not expired AND index_version still current."""
        ...
    
    def put(self, entry: LintCacheEntry) -> None:
        ...
    
    def invalidate_all(self) -> int:
        """Delete all cache entries (called on index_version change or prompt upgrade)."""
        ...
    
    def cleanup_expired(self) -> int:
        """Delete expired entries."""
        ...
```

## CLI surface

```
python -m src.cli stubs list [--project <id>]
    # List all stubs + count of pages referencing each

python -m src.cli stubs promote <slug> [--project <id>]
    # Manually trigger materialization for one stub

python -m src.cli stubs discard <slug> [--project <id>]
    # Delete stub without materializing (loses any partial context)

python -m src.cli stubs show <slug> [--project <id>]
    # Print stub content + referring pages

python -m src.cli dedup --auto [--threshold high|medium] [--no-history] [--project <id>]
    # Auto-merge high-confidence duplicates; archive originals

python -m src.cli dedup undo <merge_id> [--project <id>]
    # Restore original pages from .index/dedup_history/<id>/

python -m src.cli lint --cache-ttl 24h        # default
python -m src.cli lint --cache-ttl 0          # disable cache for this run
python -m src.cli lint --invalidate-cache      # clear all cache
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Stub materialization LLM | Timeout / JSON fail | 2 retries; if all fail, leave stub in place + warning; bump `materialization_attempts` |
| Stub already materialized | Race condition | Mutex prevents; second call is no-op |
| Stub referenced by deleted page | Edge case | Continue (other pages may still reference) |
| Dedup auto LLM | Timeout / schema fail | 2 retries; skip group on failure + log |
| Dedup merge conflict | wikilink rewrite conflict | Log + skip that page; rest of merge continues |
| Dedup history cleanup | Disk full | Warning; expired entries left in place |
| Dedup undo | Merge ID not found / expired | Error + hint |
| Dedup undo | Original page now re-created | Detect + warn user before overwriting |
| Lint cache | Cache file corrupt | Skip + regenerate; warn |
| Lint cache | index_version mismatch | Skip cache + regenerate |
| Lint cache | TTL expired | Skip cache + regenerate |
| Lint cache | prompt_version mismatch | Skip cache + regenerate |
| Stub CLI | Stub file doesn't exist | Error + hint `stubs list` |

## Backwards compatibility

- `cmd_dedup` (without `--auto`): unchanged; original interactive mode preserved.
- `cmd_lint`: `--cache-ttl` defaults to 24h, transparent to existing scripts (lint output unchanged).
- `cmd_stubs`: new subcommand; no breaking change.
- Background worker `StubMaterializerWorker`: opt-out via `settings.wiki.auto_materialize_stubs = false`.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/wiki/stubs.py` | Stub detection from page references; LLM-driven materialization; archive cleanup; mutex |
| `src/wiki/dedup_auto.py` | Threshold filter; merge; archival; undo; retention cleanup |
| `src/wiki/lint_cache.py` | Key derivation; expiry; index_version mismatch; prompt_version mismatch; cleanup |
| `src/cli_ext/stubs_cmd.py` | list/promote/discard/show |

### Integration tests

```
tests/test_integration/test_stub_lifecycle.py:
    def test_stub_auto_promoted_on_ingest():
        # Ingest creates page A with [[stub-foo]] link
        # Stub exists at wiki/_stubs/foo.md
        # Wait for worker
        # Verify: wiki/entities/foo.md exists; wiki/_stubs/foo.md gone; index.md updated

tests/test_integration/test_dedup_auto.py:
    def test_dedup_auto_high():
        # 3 entity pages that LLM marks as duplicates (high confidence)
        # Run cmd_dedup --auto
        # Verify: 1 canonical page; 2 archived; history record exists

    def test_dedup_undo():
        # Run auto-merge
        # Run cmd_dedup undo <merge_id>
        # Verify: original pages restored; canonical page removed

tests/test_integration/test_lint_cache.py:
    def test_lint_uses_cache():
        # Run cmd_lint (cache miss → LLM call)
        # Run cmd_lint (cache hit → no LLM call)
        # Verify: 1 LLM call total

    def test_lint_cache_invalidated_on_index_change():
        # Run cmd_lint (cache miss → populate)
        # Ingest new source (index_version changes)
        # Run cmd_lint (cache miss → invalidate + LLM)
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P1)

- All 3 features bundled
- CLI: `stubs / dedup --auto / lint --cache-ttl`

### Polish (v2.0.1 or later)

- Stub materialization retry budget
- Dedup archive retention (default 30 days)
- Lint cache invalidation triggers (index_version change)

### Deferred (v2.1+)

- Stubs UI (click to materialize)
- Dedup --auto for medium confidence
- Lint cache cross-project sharing

## Implementation order

3 phases (each commit):

1. **Stub materialization** — `src/wiki/stubs.py` + worker + CLI + tests
2. **Dedup auto** — `src/wiki/dedup_auto.py` + history store + `cmd_dedup --auto` + tests
3. **Lint cache** — `src/wiki/lint_cache.py` + cache integration + tests

## Cost estimation

Total: ~800 lines new code + ~400 lines tests.
- Stub materialization: ~300 lines (LLM call once per stub)
- Dedup auto: ~300 lines (LLM call once per merge)
- Lint cache: ~200 lines (saves LLM calls)

Net LLM cost reduction: lint cache saves up to 50% of lint semantic calls on repeat runs.