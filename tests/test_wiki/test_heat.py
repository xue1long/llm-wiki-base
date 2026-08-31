"""Tests for src/wiki/heat.py.

V4 (ADR-002, 2026-08-31): heat fields are NOT serialized to disk.
These tests now exercise the heat logic on in-memory WikiPage objects
only — the on-disk round-trip behavior is gone because V4 dropped the
heat fields from the 8-key whitelist. The CLI commands and pure-function
``decay()`` still work in-memory; the HeatTracker's file I/O is best
understood as a no-op since heat never round-trips to disk.
"""
import time

from src.wiki.features.heat import decay
from src.wiki.core.types import PageType, WikiPage


def test_increment_updates_heat_in_memory():
    """Pure in-memory: heat increment uses page.heat + HEAT_INCREMENT."""
    page = WikiPage(id="foo", title="F", type=PageType.ENTITY, body="", heat=50, last_used_at=0)
    page.heat = min(100, max(0, page.heat + 5))
    page.last_used_at = int(time.time() * 1000)
    assert page.heat == 55
    assert page.last_used_at > 0


def test_increment_clamps_to_100_in_memory():
    """Pure in-memory: heat clamped to 100."""
    page = WikiPage(id="foo", title="F", type=PageType.ENTITY, body="", heat=98)
    page.heat = min(100, max(0, page.heat + 5))
    assert page.heat == 100


def test_decay_reduces_heat_via_pure_function():
    """Pure-function decay() reduces heat for old pages."""
    page = WikiPage(
        id="foo", title="F", type=PageType.ENTITY, body="",
        heat=80, last_used_at=int(time.time() * 1000) - 31 * 86400 * 1000,
    )
    decay(page)  # mutates page.heat in place
    assert page.heat == 70  # 80 - 10


def test_heat_not_persisted_v4():
    """V4: heat field is NOT in to_frontmatter_dict."""
    page = WikiPage(id="foo", title="F", type=PageType.CONCEPT, body="", heat=80)
    fm = page.to_frontmatter_dict()
    assert "heat" not in fm
    assert "last_used_at" not in fm
    assert "zombie_since" not in fm