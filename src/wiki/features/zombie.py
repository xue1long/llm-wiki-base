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
        from ..storage.page_writer import read_page
        from ..core.types import PageType
        zombies = []
        for t, dp in [(PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
                      (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis")]:
            for f in getattr(paths, dp).glob("*.md"):
                p = read_page(f)
                if p.zombie_since:
                    zombies.append({"id": p.id, "title": p.title, "zombie_since": p.zombie_since})
        return zombies