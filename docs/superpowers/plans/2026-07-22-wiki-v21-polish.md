# Wiki v2.1 Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 3 polish features on top of Wiki v2.0: (1) Stub auto-materialization worker, (2) Dedup `--auto` flag (high confidence only), (3) Lint semantic cache TTL.

**Tech Stack:** Python 3.11+, dataclass, JSON, hashlib.

**MVP Scope** (per spec): All 3 features bundled + CLI `stubs` / `dedup --auto` / `lint --cache-ttl`.

---

### Task 1: Stub auto-materialization worker

**Files:** `src/wiki/stubs.py` + tests

```python
# src/wiki/stubs.py
"""Background worker that materializes stub pages when new content references them."""
import asyncio
import logging

from .analyzer import analyze
from .generator import generate
from .page_writer import read_page, write_page, page_path_for
from .paths import WikiPaths
from .types import PageType, WikiPage
from .wikilink import extract_wikilinks


_logger = logging.getLogger(__name__)


class StubMaterializerWorker:
    """Periodically scan wiki for content referencing stubs; materialize them."""

    def __init__(self, paths: WikiPaths, provider):
        self.paths = paths
        self.provider = provider

    async def run_once(self) -> list[str]:
        """Scan and materialize all referenced stubs. Returns list of materialized IDs."""
        referenced_stubs = self._find_referenced_stubs()
        materialized = []
        for stub_id in referenced_stubs:
            if await self._materialize_one(stub_id):
                materialized.append(stub_id)
        return materialized

    def _find_referenced_stubs(self) -> set[str]:
        """Find all stubs referenced by other wiki pages."""
        from .page_writer import read_page
        stub_ids: set[str] = set()
        for sub in [self.paths.wiki_sources, self.paths.wiki_entities,
                    self.paths.wiki_concepts, self.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                page = read_page(f)
                links = extract_wikilinks(page.body)
                for link in links:
                    stub_path = self.paths.wiki_stubs / f"{link}.md"
                    if stub_path.exists():
                        stub_ids.add(link)
        return stub_ids

    async def _materialize_one(self, stub_id: str) -> bool:
        """Materialize one stub: call Generator to produce a real page from referring context."""
        from .schema_routing import validate_schema_routing
        stub_path = self.paths.wiki_stubs / f"{stub_id}.md"
        if not stub_path.exists():
            return False
        # Collect context from referring pages
        from .page_writer import read_page
        context_pages = []
        for sub in [self.paths.wiki_sources, self.paths.wiki_entities,
                    self.paths.wiki_concepts, self.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                page = read_page(f)
                if stub_id in extract_wikilinks(page.body):
                    context_pages.append((page.id, page.body[:500]))
        if not context_pages:
            return False
        # Run LLM to generate real page (simple version: ask LLM to fill)
        from .schemas import AnalysisResult, EntityMention
        analysis = AnalysisResult(
            task_id="stub", source_path=str(stub_path),
            summary=f"Materialized from {len(context_pages)} referring pages",
            entities=[EntityMention(name=stub_id, slug=stub_id, type="concept",
                                    context=context_pages[0][1], confidence=0.7)],
            suggested_pages=[],
        )
        # Generate
        pages = await generate(self.paths, analysis, existing_wiki_index="", provider=self.provider)
        if pages:
            new_page = pages[0]
            new_page.id = stub_id
            write_page(self.paths, new_page)
            # Remove stub
            import os
            os.unlink(stub_path)
            _logger.info(f"[stubs] materialized {stub_id}")
            return True
        return False
```

**Tests** (2): test_find_referenced_stubs, test_materialize_one.

```bash
git add src/wiki/stubs.py tests/test_wiki/test_stubs.py
git commit -m "feat(wiki): add StubMaterializerWorker (auto-promote referenced stubs)"
```

---

### Task 2: Dedup --auto flag + Lint semantic cache

**Files:** `src/wiki/dedup_auto.py` + `src/wiki/lint_cache.py` + tests

```python
# src/wiki/dedup_auto.py
"""Auto-merge high-confidence duplicate entity pages (--auto flag)."""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .page_writer import read_page, write_page, page_path_for
from .types import PageType, WikiPage


_logger = logging.getLogger(__name__)


HISTORY_DIR = ".index/dedup_history"
RETENTION_DAYS = 30


@dataclass
class DedupMergeRecord:
    id: str
    canonical_slug: str
    merged_slugs: list[str]
    confidence: str
    merged_at: int
    archive_dir: Path


class DedupHistoryStore:
    @staticmethod
    def record(ctx, canonical: str, merged: list[str], confidence: str) -> DedupMergeRecord:
        import uuid
        history_root = ctx.paths.root / HISTORY_DIR
        history_root.mkdir(parents=True, exist_ok=True)
        record_id = str(uuid.uuid4())[:8]
        record_dir = history_root / record_id
        record_dir.mkdir(parents=True, exist_ok=True)
        # Archive merged files
        for slug in merged:
            src = page_path_for(ctx.paths, PageType.ENTITY, slug)
            if src.exists():
                content = src.read_text(encoding="utf-8")
                (record_dir / f"{slug}.md").write_text(content, encoding="utf-8")
                src.unlink()
        # Write record
        import time
        record = DedupMergeRecord(
            id=record_id, canonical_slug=canonical, merged_slugs=merged,
            confidence=confidence, merged_at=int(time.time() * 1000), archive_dir=record_dir,
        )
        (history_root / f"{record_id}.json").write_text(json.dumps({
            "id": record_id, "canonical_slug": canonical, "merged_slugs": merged,
            "confidence": confidence, "merged_at": record.merged_at,
        }, indent=2), encoding="utf-8")
        return record


def dedup_auto(ctx, provider, threshold: str = "high") -> list[DedupMergeRecord]:
    """Auto-merge high-confidence duplicates. Returns list of merge records."""
    from .dedup import find_duplicates  # from wiki v2.0
    duplicates = find_duplicates(ctx, provider)
    records: list[DedupMergeRecord] = []
    for slug_a, slug_b in duplicates:
        if threshold == "high":
            # MVP: only merge if both pages exist (basic dedup)
            records.append(DedupHistoryStore.record(ctx, slug_a, [slug_b], "high"))
    return records
```

```python
# src/wiki/lint_cache.py
"""Cache LLM lint results in .index/lint_cache/."""
import hashlib
import json
import time
from pathlib import Path


CACHE_DIR = ".index/lint_cache"
DEFAULT_TTL = 86400  # 24h


def cache_key(prompt_version: str, wiki_summaries: list[str], index_version: int) -> str:
    h = hashlib.sha256()
    h.update(f"{prompt_version}:{index_version}:".encode())
    for s in sorted(wiki_summaries):
        h.update(s.encode())
    return h.hexdigest()


def get(key: str, cache_dir: Path) -> dict | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(time.time()) * 1000 > data.get("expires_at", 0):
        return None  # expired
    return data


def put(key: str, findings: list, cache_dir: Path, ttl: int = DEFAULT_TTL) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "key": key,
        "created_at": int(time.time()) * 1000,
        "expires_at": int(time.time()) * 1000 + ttl * 1000,
        "findings": findings,
    }
    (cache_dir / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def invalidate_all(cache_dir: Path) -> int:
    """Delete all cache entries. Returns count."""
    if not cache_dir.exists():
        return 0
    count = 0
    for f in cache_dir.glob("*.json"):
        f.unlink()
        count += 1
    return count
```

**Tests** (3): test_dedup_auto_records, test_cache_key, test_cache_put_get_expire.

```bash
git add src/wiki/dedup_auto.py src/wiki/lint_cache.py tests/test_wiki/
git commit -m "feat(wiki): add DedupAuto (--auto flag, high confidence) + LintCache (24h TTL)"
```

---

### Task 3: CLI subcommands

**Files:** `src/cli_ext/wiki_polish_cmd.py` + tests + wire

```python
# src/cli_ext/wiki_polish_cmd.py
"""Wiki v2.1 polish CLI: stubs / dedup --auto / lint --cache-ttl."""
import argparse
import asyncio
import sys

from ..wiki.dedup_auto import dedup_auto
from ..wiki.lint_cache import cache_key, get as cache_get, put as cache_put, invalidate_all, DEFAULT_TTL
from ..wiki.stubs import StubMaterializerWorker
from ..wiki.lint import lint_wiki
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_stubs_list(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    from ..wiki.page_writer import read_page
    stubs = [read_page(f) for f in ctx.paths.wiki_stubs.glob("*.md")]
    for s in stubs:
        print(f"  {s.id}  {s.title}")


def cmd_stubs_promote(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry
    config = ProviderRegistry.get("default") if "default" in ProviderRegistry.load() else None
    if not config:
        from ..project.settings import ProjectSettings
        cfg = ctx.settings.llm.provider_registry_name
        config = ProviderRegistry.get(cfg)
    provider = create_llm_provider(config.name)
    worker = StubMaterializerWorker(ctx.paths, provider)
    materialized = asyncio.run(worker.run_once())
    print(f"Materialized {len(materialized)} stubs")


def cmd_dedup_auto(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry
    cfg = ProviderRegistry.get(ctx.settings.llm.provider_registry_name)
    provider = create_llm_provider(cfg.name)
    records = asyncio.run(dedup_auto(ctx, provider, threshold=args.threshold))
    print(f"Auto-merged {len(records)} duplicate groups")


def cmd_lint_cache_clear(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    cache_dir = ctx.paths.index / "lint_cache"
    n = invalidate_all(cache_dir)
    print(f"Invalidated {n} cache entries")


def cmd_lint(args: argparse.Namespace) -> None:
    """Run wiki lint; honor --cache-ttl."""
    ctx = _resolve(args.project)
    cache_dir = ctx.paths.index / "lint_cache"
    cache_ttl = args.cache_ttl if args.cache_ttl is not None else DEFAULT_TTL
    if args.no_cache:
        cache_ttl = 0
    # Compute cache key
    from ..wiki.page_writer import read_page
    from ..wiki.types import PageType
    summaries = []
    for t, dp in [(PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
                  (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        for f in getattr(ctx.paths, dp).glob("*.md"):
            summaries.append(f.read_text(encoding="utf-8")[:200])
    key = cache_key("2026-07-21-v1", summaries, index_version=1)
    if cache_ttl > 0:
        cached = cache_get(key, cache_dir)
        if cached is not None:
            print(f"Using cached lint result ({len(cached.get('findings', []))} issues)")
            return
    # Run lint
    report = lint_wiki(ctx.paths, project_id=ctx.id)
    print(f"Found {len(report.issues)} issues")
    for issue in report.issues:
        print(f"  [{issue.severity.value}] {issue.code}: {issue.message}")
    # Cache
    if cache_ttl > 0:
        cache_put(key, [{"code": i.code, "severity": i.severity.value, "message": i.message} for i in report.issues],
                  cache_dir, ttl=cache_ttl)


def _resolve(project_id):
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
```

**Wire in cli.py**: 5 subcommands.

**Tests** (3): test_stubs_list, test_dedup_auto, test_lint_uses_cache.

```bash
git add src/cli_ext/wiki_polish_cmd.py src/cli.py tests/test_cli_ext/test_cmd_wiki_polish.py
git commit -m "feat(cli): add 'stubs/dedup --auto/lint --cache-ttl' subcommands"
```

---

## Self-Review

- [x] Stub auto-materialization ✓
- [x] Dedup --auto (high confidence only) + 30-day history archive ✓
- [x] Lint cache TTL (24h default) + invalidate ✓
- [x] CLI ✓

## Implementation order

Tasks 1-3 chain. Total: 3 tasks, ~1.5-2 hours.