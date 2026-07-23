"""Auto-merge high-confidence duplicate entity pages (--auto flag)."""
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..storage.page_writer import read_page, write_page, page_path_for
from ..core.types import PageType, WikiPage
from ..core.paths import WikiPaths
from ...lib.write_hooks import safe_write, DELETE_SENTINEL


_logger = logging.getLogger(__name__)


HISTORY_DIR = ".index/dedup_history"
RETENTION_DAYS = 30


@dataclass
class DedupMergeRecord:
    id: str
    canonical_slug: str
    merged_slugs: list[str]
    confidence: str
    merged_at: int
    archive_dir: Path


class DedupHistoryStore:
    @staticmethod
    def record(paths: WikiPaths, canonical: str, merged: list[str], confidence: str) -> DedupMergeRecord:
        history_root = paths.root / HISTORY_DIR
        history_root.mkdir(parents=True, exist_ok=True)
        record_id = str(uuid.uuid4())[:8]
        record_dir = history_root / record_id
        record_dir.mkdir(parents=True, exist_ok=True)
        for slug in merged:
            src = page_path_for(paths, PageType.ENTITY, slug)
            if src.exists():
                content = src.read_text(encoding="utf-8")
                (record_dir / f"{slug}.md").write_text(content, encoding="utf-8")
                # Use safe_write so the deletion is deferred when called inside
                # an AtomicContext (atomic, batched commit).
                safe_write(src, DELETE_SENTINEL)
        record = DedupMergeRecord(
            id=record_id, canonical_slug=canonical, merged_slugs=merged,
            confidence=confidence, merged_at=int(time.time() * 1000), archive_dir=record_dir,
        )
        (history_root / f"{record_id}.json").write_text(json.dumps({
            "id": record_id, "canonical_slug": canonical, "merged_slugs": merged,
            "confidence": confidence, "merged_at": record.merged_at,
        }, indent=2), encoding="utf-8")
        return record


def dedup_auto(paths: WikiPaths, provider, threshold: str = "high") -> list[DedupMergeRecord]:
    """Auto-merge high-confidence duplicates. Returns list of merge records."""
    from .dedup import find_duplicates
    duplicates = find_duplicates(paths, provider)
    records: list[DedupMergeRecord] = []
    for slug_a, slug_b in duplicates:
        if threshold == "high":
            records.append(DedupHistoryStore.record(paths, slug_a, [slug_b], "high"))
    return records
