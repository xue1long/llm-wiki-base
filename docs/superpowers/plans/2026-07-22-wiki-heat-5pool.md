# Wiki Heat + 5-Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Heat decay (0-100, +5 per AI retrieval, -10 per 30 days) + zombie detection at heat=0 for 30 days. Pool enum in WikiPage (deferred to v2.0.1 for routing).

**Tech Stack:** Python 3.11+, dataclass, datetime.

**MVP Scope** (per spec): heat field + decay + increment + zombie detection + CLI `heat show/top/cold/decay/zombies/restore/archive`. Pool enum defined but routing logic deferred.

---

### Task 1: HeatTracker + ZombieDetector

**Files:** `src/wiki/heat.py` + `src/wiki/zombie.py` + tests

```python
# src/wiki/heat.py
"""Heat decay tracker for wiki pages."""
import json
import time
from dataclasses import dataclass
from pathlib import Path


HEAT_LOG = ".index/heat_events.log"
HEAT_DECAY_DAYS = 30
HEAT_DECAY_AMOUNT = 10
HEAT_INCREMENT = 5


@dataclass
class HeatEvent:
    page_id: str
    delta: int
    reason: str          # "ai_retrieval" | "decay" | "manual"
    at: int              # unix ms


class HeatTracker:
    def __init__(self, paths):
        self.paths = paths
        self.log = paths.root / HEAT_LOG
        self.log.parent.mkdir(parents=True, exist_ok=True)

    def increment(self, page_id: str, delta: int = HEAT_INCREMENT, reason: str = "ai_retrieval"):
        """Increase heat (e.g., on AI retrieval)."""
        from .page_writer import read_page, write_page, page_path_for
        from .types import PageType
        page_file = page_path_for(self.paths, _infer_type(self.paths, page_id), page_id)
        if not page_file.exists():
            return
        page = read_page(page_file)
        new_heat = min(100, max(0, page.heat + delta))
        page.heat = new_heat
        page.last_used_at = int(time.time() * 1000)
        page.zombie_since = None
        write_page(self.paths, page)
        self._log(page_id, delta, reason)

    def decay(self) -> list[HeatEvent]:
        """Decay all pages whose last_used_at > HEAT_DECAY_DAYS ago."""
        from .page_writer import read_page, write_page, page_path_for
        from .types import PageType
        from .zombie import ZombieDetector
        events: list[HeatEvent] = []
        now = int(time.time() * 1000)
        threshold = now - HEAT_DECAY_DAYS * 86400 * 1000
        for type, dir_prop in [
            (PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
            (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis"),
        ]:
            for f in getattr(self.paths, dir_prop).glob("*.md"):
                page = read_page(f)
                if page.last_used_at > 0 and page.last_used_at < threshold and page.heat > 0:
                    old_heat = page.heat
                    page.heat = max(0, page.heat - HEAT_DECAY_AMOUNT)
                    events.append(HeatEvent(page.id, page.heat - old_heat, "decay", now))
                    if page.heat == 0 and page.zombie_since is None:
                        page.zombie_since = now
                        ZombieDetector.generate_staging_draft(self.paths, page)
                    write_page(self.paths, page)
        return events

    def _log(self, page_id, delta, reason):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"page_id": page_id, "delta": delta, "reason": reason, "at": int(time.time() * 1000)}) + "\n")


def _infer_type(paths, slug):
    from .types import PageType
    for t, dp in [(PageType.ENTITY, "wiki_entities"), (PageType.CONCEPT, "wiki_concepts"),
                  (PageType.SOURCE, "wiki_sources"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        if (getattr(paths, dp) / f"{slug}.md").exists():
            return t
    return PageType.SOURCE
```

```python
# src/wiki/zombie.py
"""Zombie page detection — generate staging draft when heat hits 0."""
from pathlib import Path
import time


STAGING_DIR = ".index/staging"


class ZombieDetector:
    @staticmethod
    def generate_staging_draft(paths, page) -> Path:
        staging_dir = paths.root / STAGING_DIR
        staging_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        draft_path = staging_dir / f"{page.id}-{ts}.md"
        days_unused = (time.time() * 1000 - (page.last_used_at or 0)) / 86400000
        content = f"""# Staging: {page.title} (zombie)

- page_id: {page.id}
- heat: {page.heat}
- last_used_at: {page.last_used_at}
- days_since_use: {days_unused:.1f}

## Choose:
1. **Keep**: Set is_immutable=true; heat reset to 100
2. **Archive**: Move to wiki/_archive/{page.id}.md
3. **Update**: Re-ingest source to refresh content
"""
        draft_path.write_text(content, encoding="utf-8")
        return draft_path

    @staticmethod
    def list_zombies(paths) -> list[dict]:
        from .page_writer import read_page
        from .types import PageType
        zombies = []
        for t, dp in [(PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
                      (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis")]:
            for f in getattr(paths, dp).glob("*.md"):
                p = read_page(f)
                if p.zombie_since:
                    zombies.append({"id": p.id, "title": p.title, "zombie_since": p.zombie_since})
        return zombies
```

**Tests** (3): test_increment_updates_heat, test_decay_reduces_heat, test_zombie_detected_at_0.

```bash
git add src/wiki/heat.py src/wiki/zombie.py tests/test_wiki/test_heat.py tests/test_wiki/test_zombie.py
git commit -m "feat(wiki): add HeatTracker (decay + increment) + ZombieDetector"
```

---

### Task 2: Extend WikiPage with heat fields + CLI

**Files:** `src/wiki/types.py` + `src/cli_ext/heat_cmd.py` + tests + wire cli.py

```python
# Extend WikiPage
@dataclass
class WikiPage:
    # ... existing fields ...
    heat: int = 50
    last_used_at: int = 0
    zombie_since: int | None = None
```

```python
# src/cli_ext/heat_cmd.py
"""Heat decay CLI."""
import argparse
import sys

from ..wiki.heat import HeatTracker
from ..wiki.zombie import ZombieDetector
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_heat_show(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    from ..wiki.page_writer import read_page, page_path_for
    from ..wiki.types import PageType
    page_file = page_path_for(ctx.paths, _infer_type(ctx.paths, args.page_id), args.page_id)
    if not page_file.exists():
        print(f"Page not found: {args.page_id}", file=sys.stderr); sys.exit(2)
    p = read_page(page_file)
    print(f"  heat: {p.heat}")
    print(f"  last_used_at: {p.last_used_at}")
    print(f"  zombie_since: {p.zombie_since}")


def cmd_heat_top(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    pages = _all_pages(ctx)
    pages.sort(key=lambda p: -p.heat)
    for p in pages[:args.limit]:
        print(f"  {p.heat:3d}  {p.id}  ({p.type.value})")


def cmd_heat_cold(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    pages = [p for p in _all_pages(ctx) if p.heat < 30]
    for p in pages[:args.limit]:
        print(f"  {p.heat:3d}  {p.id}")


def cmd_heat_decay(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    tracker = HeatTracker(ctx.paths)
    if args.dry_run:
        print("(dry run; no writes)")
        return
    events = tracker.decay()
    print(f"Applied {len(events)} decay events")


def cmd_heat_zombies(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    zombies = ZombieDetector.list_zombies(ctx.paths)
    for z in zombies:
        print(f"  {z['id']}  (zombie since {z['zombie_since']})")


def cmd_heat_restore(args: argparse.Namespace) -> None:
    """Reset heat to 100, set is_immutable=true."""
    ctx = _resolve(args.project)
    from ..wiki.page_writer import read_page, write_page, page_path_for
    page_file = page_path_for(ctx.paths, _infer_type(ctx.paths, args.page_id), args.page_id)
    if not page_file.exists():
        print(f"Page not found: {args.page_id}", file=sys.stderr); sys.exit(2)
    p = read_page(page_file)
    p.heat = 100
    p.is_immutable = True
    p.zombie_since = None
    write_page(ctx.paths, p)
    print(f"Restored {p.id}")


def cmd_heat_archive(args: argparse.Namespace) -> None:
    """Move zombie to wiki/_archive/."""
    ctx = _resolve(args.project)
    from ..wiki.page_writer import read_page, page_path_for
    import shutil, os
    page_file = page_path_for(ctx.paths, _infer_type(ctx.paths, args.page_id), args.page_id)
    if not page_file.exists():
        print(f"Page not found: {args.page_id}", file=sys.stderr); sys.exit(2)
    archive_dir = ctx.paths.wiki / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(page_file), str(archive_dir / page_file.name))
    print(f"Archived {args.page_id}")


def _resolve(project_id):
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)


def _all_pages(ctx):
    from ..wiki.page_writer import read_page
    from ..wiki.types import PageType
    out = []
    for t, dp in [(PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
                  (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        for f in getattr(ctx.paths, dp).glob("*.md"):
            out.append(read_page(f))
    return out


def _infer_type(paths, slug):
    from ..wiki.types import PageType
    for t, dp in [(PageType.ENTITY, "wiki_entities"), (PageType.CONCEPT, "wiki_concepts"),
                  (PageType.SOURCE, "wiki_sources"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        if (getattr(paths, dp) / f"{slug}.md").exists():
            return t
    return PageType.SOURCE
```

**Wire in cli.py**: 7 subparsers (show/top/cold/decay/zombies/restore/archive).

**Tests** (3): test_heat_show, test_decay, test_zombies_list.

```bash
git add src/wiki/types.py src/cli_ext/heat_cmd.py src/cli.py tests/test_cli_ext/test_cmd_heat.py
git commit -m "feat(wiki): add heat field to WikiPage + 'heat' CLI (7 subcommands)"
```

---

## Self-Review

- [x] Heat increment / decay / zombie detection ✓
- [x] 7 CLI subcommands ✓
- [x] 5-Pool routing logic deferred to v2.0.1 (per spec polish)
- [x] No placeholders

## Implementation order

Tasks 1-2 chain. Total: 2 tasks, ~1.5-2 hours.