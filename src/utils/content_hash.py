"""Content hash cache — SHA256-based content dedup for ingest.

Complements the existing IdempotencyCache (md5-based, TTL 7 days) by tracking
the actual content hash of successfully ingested sources. This prevents
re-ingesting the exact same content even across different task_ids.
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from ..lib.write_hooks import safe_write


class ContentHashCache:
    """SHA256 content hash → (page_id, timestamp) mapping.

    Persisted to `.index/content_hashes.json`. Entries older than 30 days
    are cleaned up on load.
    """

    TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

    def __init__(self, index_path: Path):
        self._index_path = index_path
        self._cache_path = index_path / "content_hashes.json"
        self._cache: dict[str, dict] = {}  # hash -> {"page_id": str, "timestamp": float}
        self._load()

    def _load(self) -> None:
        """Load from disk, clean expired entries."""
        if not self._cache_path.exists():
            return
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            now = time.time()
            self._cache = {
                k: v for k, v in data.items()
                if now - v.get("timestamp", 0) <= self.TTL_SECONDS
            }
        except (json.JSONDecodeError, KeyError):
            self._cache = {}

    def _save(self) -> None:
        """Persist to disk atomically."""
        self._index_path.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self._cache, ensure_ascii=False, indent=2)
        safe_write(self._cache_path, content)

    def compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(self, content_hash: str) -> Optional[str]:
        """Get page_id for a content hash, or None if not found."""
        entry = self._cache.get(content_hash)
        return entry.get("page_id") if entry else None

    def set(self, content_hash: str, page_id: str) -> None:
        """Record a content hash → page_id mapping."""
        self._cache[content_hash] = {
            "page_id": page_id,
            "timestamp": time.time(),
        }
        self._save()

    def has_content(self, content: str) -> Optional[str]:
        """Check if content already processed, return page_id if so."""
        h = self.compute_hash(content)
        return self.get(h)

    def mark_processed(self, content: str, page_id: str) -> None:
        """Mark content as processed with resulting page_id."""
        h = self.compute_hash(content)
        self.set(h, page_id)

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()
        if self._cache_path.exists():
            self._cache_path.unlink()


# Module-level cache (lazy initialized)
_cache: Optional[ContentHashCache] = None


def get_content_hash_cache(index_path: Path | None = None) -> ContentHashCache:
    """Get or create the content hash cache.

    If index_path is None, uses the default .index/ directory under CWD.
    """
    global _cache
    if _cache is None:
        if index_path is None:
            index_path = Path(".index")
        _cache = ContentHashCache(index_path)
    return _cache


def compute_content_hash(content: str) -> str:
    """Convenience function to compute SHA256 hash."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def is_content_processed(content: str, index_path: Path | None = None) -> Optional[str]:
    """Check if content was already processed. Returns page_id if found."""
    return get_content_hash_cache(index_path).has_content(content)


def mark_content_processed(content: str, page_id: str, index_path: Path | None = None) -> None:
    """Record that content was processed into page_id."""
    get_content_hash_cache(index_path).mark_processed(content, page_id)