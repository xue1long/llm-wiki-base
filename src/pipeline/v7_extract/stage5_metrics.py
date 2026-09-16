"""Stage 5 claim_support_ratio 长期指标 (Task 48).

Persists each ingest run's claim metrics to ``<.index/v7_metrics.jsonl``
(append-only JSONL). Provides read-recent + aggregate-average helpers
for the Reconciliation drift monitor (Task 50) and external tooling.

Pure IO + math; no LLM. Failure Contract §1: all IO swallow + log.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path


log = logging.getLogger(__name__)


@dataclass
class Stage5MetricsEntry:
    """One ingest run's Stage 5 metrics snapshot."""

    timestamp_ms: int
    run_id: str
    topic_count: int
    claim_total: int
    claim_supported: int
    claim_support_ratio: float
    reviewer_verdicts_count: int = 0
    clusterer_fingerprint: str = ""


def metrics_path(root: Path | str) -> Path:
    """<.index/v7_metrics.jsonl>"""
    p = Path(root) / ".index" / "v7_metrics.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class Stage5Metrics:
    """Stage 5 metrics recorder + reader.

    Storage is append-only JSONL; reads walk the file from the end backwards
    so that ``read_recent(limit=N)`` is O(N) not O(file_size).
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = metrics_path(self.root)

    def record_run(self, entry: Stage5MetricsEntry) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("Stage5Metrics.record_run: write failed: %s", e)

    def read_recent(self, *, limit: int = 10) -> list[Stage5MetricsEntry]:
        """Return the last ``limit`` entries (most recent first)."""
        if limit <= 0:
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("Stage5Metrics.read_recent: read failed: %s", e)
            return []
        lines = [ln for ln in text.splitlines() if ln.strip()]
        recent = lines[-limit:]
        recent.reverse()   # most recent first
        out: list[Stage5MetricsEntry] = []
        for line in recent:
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            try:
                out.append(Stage5MetricsEntry(
                    timestamp_ms=int(payload["timestamp_ms"]),
                    run_id=str(payload.get("run_id", "")),
                    topic_count=int(payload.get("topic_count", 0) or 0),
                    claim_total=int(payload.get("claim_total", 0) or 0),
                    claim_supported=int(payload.get("claim_supported", 0) or 0),
                    claim_support_ratio=float(payload.get("claim_support_ratio", 0.0) or 0.0),
                    reviewer_verdicts_count=int(payload.get("reviewer_verdicts_count", 0) or 0),
                    clusterer_fingerprint=str(payload.get("clusterer_fingerprint", "") or ""),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def aggregate_average(self, *, limit: int = 10) -> float:
        """Arithmetic mean of recent ``limit`` claim_support_ratio values.

        Returns 0.0 when there are no entries. This is the dashboard-friendly
        long-term ratio (Task 50 drift monitor consumes this).
        """
        recent = self.read_recent(limit=limit)
        if not recent:
            return 0.0
        return sum(e.claim_support_ratio for e in recent) / len(recent)


def make_entry(
    *,
    run_id: str,
    topic_count: int,
    claim_total: int,
    claim_supported: int,
    reviewer_verdicts_count: int = 0,
    clusterer_fingerprint: str = "",
) -> Stage5MetricsEntry:
    """Convenience builder: compute ratio + timestamp."""
    ratio = (claim_supported / claim_total) if claim_total > 0 else 0.0
    return Stage5MetricsEntry(
        timestamp_ms=int(time.time() * 1000),
        run_id=run_id,
        topic_count=topic_count,
        claim_total=claim_total,
        claim_supported=claim_supported,
        claim_support_ratio=ratio,
        reviewer_verdicts_count=reviewer_verdicts_count,
        clusterer_fingerprint=clusterer_fingerprint,
    )


__all__ = [
    "Stage5Metrics",
    "Stage5MetricsEntry",
    "make_entry",
    "metrics_path",
]