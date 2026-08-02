"""Ingest observability — per-task JSON reports + Prometheus counter."""
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..wiki.core.paths import WikiPaths


_logger = logging.getLogger(__name__)

REPORTS_DIR = ".index/ingest_reports"


@dataclass
class IngestReport:
    task_id: str
    source_path: str
    started_at: int
    finished_at: int = 0
    duration_ms: int = 0
    pipeline_mode: str = ""
    source_bytes: int = 0
    chunks_count: int = 1
    chunk_threshold: int = 12000
    claims_count: int = 0
    evidence_count: int = 0
    candidate_confidence: float = 0.0
    verdict: str = ""          # validated | rejected | needs_human_review | skipped
    verdict_reason: str = ""
    pages_total: int = 0
    pages_by_type: dict[str, int] = field(default_factory=dict)
    quarantined_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at_iso"] = _ts_to_iso(self.started_at)
        d["finished_at_iso"] = _ts_to_iso(self.finished_at) if self.finished_at else None
        return d


def _ts_to_iso(ts: int) -> str:
    """Convert Unix ms to ISO-8601 string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()


def write_ingest_report(paths: WikiPaths, report: IngestReport) -> Path:
    """Write ingest report to .index/ingest_reports/<task_id>.json."""
    reports_dir = paths.root / REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"{report.task_id}.json"
    out.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    _logger.info("[ingest_report] wrote %s (%d pages, %d ms)", out.name, report.pages_total, report.duration_ms)
    return out


def build_report(
    *,
    task_id: str,
    source_path: str,
    started_at: int,
    finished_at: int,
    source_bytes: int,
    pipeline_mode: str,
    chunks_count: int,
    chunk_threshold: int = 12000,
    claims_count: int = 0,
    evidence_count: int = 0,
    candidate_confidence: float = 0.0,
    verdict: str = "",
    verdict_reason: str = "",
    pages_total: int = 0,
    pages_by_type: dict | None = None,
    quarantined_count: int = 0,
    warnings: list | None = None,
) -> IngestReport:
    """Build an IngestReport from keyword arguments (convenience constructor)."""
    return IngestReport(
        task_id=task_id,
        source_path=str(source_path),
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=finished_at - started_at if started_at and finished_at else 0,
        pipeline_mode=pipeline_mode,
        source_bytes=source_bytes,
        chunks_count=chunks_count,
        chunk_threshold=chunk_threshold,
        claims_count=claims_count,
        evidence_count=evidence_count,
        candidate_confidence=round(candidate_confidence, 4),
        verdict=verdict,
        verdict_reason=verdict_reason,
        pages_total=pages_total,
        pages_by_type=pages_by_type or {},
        quarantined_count=quarantined_count,
        warnings=warnings or [],
    )
