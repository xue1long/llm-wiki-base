"""Tests for src/wiki/heat.py."""
import time

from src.wiki.features.heat import HeatTracker
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page


def test_increment_updates_heat(tmp_path):
    """increment() raises page.heat by HEAT_INCREMENT (clamped to 100)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="foo", title="F", type=PageType.ENTITY, body="", heat=50, last_used_at=0))

    tracker = HeatTracker(paths)
    tracker.increment("foo")

    # Reload
    from src.wiki.storage.page_writer import read_page, page_path_for
    p = read_page(page_path_for(paths, PageType.ENTITY, "foo"))
    assert p.heat == 55
    assert p.last_used_at > 0
    assert p.zombie_since is None


def test_increment_clamps_to_100(tmp_path):
    """increment() doesn't push heat above 100."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="foo", title="F", type=PageType.ENTITY, body="", heat=98))

    tracker = HeatTracker(paths)
    tracker.increment("foo")

    from src.wiki.storage.page_writer import read_page, page_path_for
    p = read_page(page_path_for(paths, PageType.ENTITY, "foo"))
    assert p.heat == 100


def test_decay_reduces_heat(tmp_path):
    """decay() reduces heat for old pages."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # 31 days ago in milliseconds
    old_ts = int(time.time() * 1000) - 31 * 86400 * 1000
    write_page(paths, WikiPage(id="foo", title="F", type=PageType.ENTITY, body="", heat=80, last_used_at=old_ts))

    tracker = HeatTracker(paths)
    events = tracker.decay()

    assert len(events) == 1
    assert events[0].page_id == "foo"
    assert events[0].reason == "decay"

    from src.wiki.storage.page_writer import read_page, page_path_for
    p = read_page(page_path_for(paths, PageType.ENTITY, "foo"))
    assert p.heat == 70  # 80 - 10
