"""Tests for src/wiki/lint_cache.py."""
import time

from src.wiki.features.lint_cache import cache_key, get, put, invalidate_all


def test_cache_key_deterministic():
    """Same inputs produce same cache key."""
    summaries = ["abc", "def"]
    k1 = cache_key("v1", summaries, 1)
    k2 = cache_key("v1", summaries, 1)
    assert k1 == k2
    # Different version → different key
    k3 = cache_key("v2", summaries, 1)
    assert k1 != k3


def test_cache_put_get_round_trip(tmp_path):
    """put() stores data; get() retrieves it before expiry."""
    cache_dir = tmp_path / "cache"
    findings = [{"code": "LINT-X", "message": "test"}]
    key = cache_key("v1", ["s"], 1)

    put(key, findings, cache_dir, ttl=3600)
    cached = get(key, cache_dir)
    assert cached is not None
    assert cached["findings"] == findings


def test_cache_expired_returns_none(tmp_path):
    """Expired cache entries return None."""
    cache_dir = tmp_path / "cache"
    findings = [{"code": "LINT-X"}]
    key = cache_key("v1", ["s"], 1)

    put(key, findings, cache_dir, ttl=0)  # Immediate expiry
    # Manually expire by patching time
    cached = get(key, cache_dir)
    # ttl=0 means expires_at = now, so depending on timing, may already be expired
    # Either None or about to expire
    if cached is not None:
        # If still cached, force expiry by manipulating the file
        path = cache_dir / f"{key}.json"
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        data["expires_at"] = int(time.time() * 1000) - 1000
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    cached = get(key, cache_dir)
    assert cached is None


def test_invalidate_all_clears_cache(tmp_path):
    """invalidate_all() deletes all .json files in cache_dir."""
    cache_dir = tmp_path / "cache"
    put("k1", [{"x": 1}], cache_dir, ttl=3600)
    put("k2", [{"x": 2}], cache_dir, ttl=3600)
    assert len(list(cache_dir.glob("*.json"))) == 2

    n = invalidate_all(cache_dir)
    assert n == 2
    assert len(list(cache_dir.glob("*.json"))) == 0
