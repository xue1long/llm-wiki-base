"""Tests for heat decay created_at fallback when last_used_at is empty."""
from datetime import datetime, timezone, timedelta
from src.wiki.features.heat import decay
from src.wiki.core.types import WikiPage


def test_decay_uses_created_at_when_last_used_empty():
    """decay() must use created_at as threshold when last_used_at is empty.

    Page created 100 days ago (last_used_at empty). Should decay.
    """
    # Create timestamps 100 days ago
    now = datetime.now(timezone.utc)
    created_dt = now - timedelta(days=100)
    created_at = created_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    p = WikiPage(
        id="x", title="X", type="entity",
        heat=50, is_immutable=False,
        last_used_at="", created_at=created_at,
    )
    out = decay(p)
    assert out.heat < 50  # decayed based on created_at fallback
