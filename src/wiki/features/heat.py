"""Heat decay tracker for wiki pages."""
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...utils.timestamp import now_iso, parse_iso, timestamp_diff_days

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
    at: str              # ISO 8601 timestamp


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
        page.last_used_at = now_iso()
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
        now_iso_ts = now_iso()
        for page_type, dir_prop in [
            (PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
            (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis"),
        ]:
            for f in getattr(self.paths, dir_prop).glob("*.md"):
                page = read_page(f)
                # Check if last_used_at is older than HEAT_DECAY_DAYS
                if not page.last_used_at:
                    continue
                days_unused = timestamp_diff_days(now_iso_ts, page.last_used_at)
                if days_unused is None or days_unused < HEAT_DECAY_DAYS:
                    continue
                if page.heat > 0:
                    old_heat = page.heat
                    page.heat = max(0, page.heat - HEAT_DECAY_AMOUNT)
                    events.append(HeatEvent(page.id, page.heat - old_heat, "decay", now_iso_ts))
                    if page.heat == 0 and page.zombie_since is None:
                        page.zombie_since = now_iso_ts
                        ZombieDetector.generate_staging_draft(self.paths, page)
                        if _decay_bridge is not None:
                            _decay_bridge.on_heat_decayed(page.id, 0, True)
                    write_page(self.paths, page)
        return events

    def _log(self, page_id, delta, reason):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"page_id": page_id, "delta": delta, "reason": reason, "at": now_iso()}) + "\n")


def decay(page: "WikiPage", now: str | None = None) -> "WikiPage":
    """Pure-function heat decay for a single page.

    Short-circuits if ``page.is_immutable`` (zombie-resist flag).
    Threshold is based on ``max(page.created_at, page.last_used_at)`` —
    treats empty string as missing, so a page with ``last_used_at == ""`` falls back to
    ``created_at`` as its activity baseline.
    """
    # Zombie-resist: immutable pages never decay.
    if page.is_immutable:
        return page

    if now is None:
        now = now_iso()

    # Get last activity timestamp (prefer last_used_at, fallback to created_at)
    last_activity = page.last_used_at or page.created_at
    if not last_activity:
        return page

    days_unused = timestamp_diff_days(now, last_activity)
    if days_unused is not None and days_unused >= HEAT_DECAY_DAYS and page.heat > 0:
        page.heat = max(0, page.heat - HEAT_DECAY_AMOUNT)
        if page.heat == 0 and page.zombie_since is None:
            page.zombie_since = now
    return page


def _infer_type(paths, slug):
    from ..core.types import PageType
    for t, dp in [(PageType.ENTITY, "wiki_entities"), (PageType.CONCEPT, "wiki_concepts"),
                  (PageType.SOURCE, "wiki_sources"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        if (getattr(paths, dp) / f"{slug}.md").exists():
            return t
    return PageType.SOURCE
