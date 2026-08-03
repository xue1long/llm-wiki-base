"""Tests for heat decay created_at fallback when last_used_at==0."""
from src.wiki.features.heat import decay
from src.wiki.core.types import WikiPage


def test_decay_uses_created_at_when_last_used_zero():
    """decay() must use created_at as threshold when last_used_at==0.

    Page created 100 days ago (last_used_at==0). Should decay.
    """
    # 100 days ago in milliseconds, relative to now=10**12
    now = 10**12
    created_at = now - 100 * 86400 * 1000
    p = WikiPage(
        id="x", title="X", type="entity",
        heat=50, is_immutable=False,
        last_used_at=0, created_at=created_at,
    )
    out = decay(p, now=now)
    assert out.heat < 50  # decayed based on created_at fallback
