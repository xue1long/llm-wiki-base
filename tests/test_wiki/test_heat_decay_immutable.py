"""Tests for heat decay is_immutable short-circuit."""
from src.wiki.features.heat import decay
from src.wiki.core.types import WikiPage


def test_decay_skips_immutable_page():
    """decay() must return page unchanged when is_immutable=True (zombie-resist)."""
    p = WikiPage(
        id="x", title="X", type="entity",
        heat=0, is_immutable=True,
        last_used_at=0, created_at=0,
        zombie_since=None,
    )
    out = decay(p, now=10**12)
    assert out.heat == 0
    assert out.zombie_since is None
