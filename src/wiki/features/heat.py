"""Heat decay tracker for wiki pages."""
import datetime
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.types import WikiPage


HEAT_LOG = ".index/heat_events.log"
HEAT_DECAY_DAYS = 30
HEAT_DECAY_AMOUNT = 10
HEAT_INCREMENT = 5

_decay_bridge = None


def set_decay_bridge(bridge):
    """Register a DecayBridge to receive heat decay callbacks."""
    global _decay_bridge
    _decay_bridge = bridge


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
        from ..storage.page_writer import read_page, write_page, page_path_for
        page_file = page_path_for(self.paths, _infer_type(self.paths, page_id), page_id)
        if not page_file.exists():
            return
        page = read_page(page_file)
        was_zombie = page.heat == 0 and page.zombie_since is not None
        new_heat = min(100, max(0, page.heat + delta))
        page.heat = new_heat
        page.last_used_at = datetime.datetime.now(datetime.timezone.utc)
        page.zombie_since = None
        write_page(self.paths, page)
        self._log(page_id, delta, reason)
        if was_zombie and new_heat > 0 and _decay_bridge is not None:
            _decay_bridge.on_heat_restored(page_id, new_heat)

    def decay(self) -> list[HeatEvent]:
        """Decay all pages whose last_used_at > HEAT_DECAY_DAYS ago."""
        from ..storage.page_writer import read_page, write_page
        from ..core.types import PageType
        from .zombie import ZombieDetector
        events: list[HeatEvent] = []
        now = int(time.time() * 1000)
        threshold = now - HEAT_DECAY_DAYS * 86400 * 1000
        for page_type, dir_prop in [
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
                        page.zombie_since = datetime.datetime.now(datetime.timezone.utc)
                        ZombieDetector.generate_staging_draft(self.paths, page)
                        if _decay_bridge is not None:
                            _decay_bridge.on_heat_decayed(page.id, 0, True)
                    write_page(self.paths, page)
        return events

    def _log(self, page_id, delta, reason):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"page_id": page_id, "delta": delta, "reason": reason, "at": int(time.time() * 1000)}) + "\n")


def decay(page: "WikiPage", now: int | None = None) -> "WikiPage":
    """Pure-function heat decay for a single page.

    Short-circuits if ``page.is_immutable`` (zombie-resist flag).
    Threshold is based on ``max(page.created_at, page.last_used_at)`` —
    treats 0 as missing, so a page with ``last_used_at == 0`` falls back to
    ``created_at`` as its activity baseline.
    """
    # Zombie-resist: immutable pages never decay.
    if page.is_immutable:
        return page

    if now is None:
        now = int(time.time() * 1000)

    threshold = now - HEAT_DECAY_DAYS * 86400 * 1000
    # Treat 0 as missing: use created_at as fallback when last_used_at==0.
    last_activity = max(page.created_at, page.last_used_at)
    if last_activity > 0 and last_activity < threshold and page.heat > 0:
        page.heat = max(0, page.heat - HEAT_DECAY_AMOUNT)
        if page.heat == 0 and page.zombie_since is None:
            page.zombie_since = datetime.datetime.now(datetime.timezone.utc)
    return page


def _infer_type(paths, slug):
    from ..core.types import PageType
    for t, dp in [(PageType.ENTITY, "wiki_entities"), (PageType.CONCEPT, "wiki_concepts"),
                  (PageType.SOURCE, "wiki_sources"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        if (getattr(paths, dp) / f"{slug}.md").exists():
            return t
    return PageType.SOURCE
