"""Tests for src/pipeline/ingest_report.py."""
import json

from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.pipeline.ingest_report import build_report, write_ingest_report, IngestReport


def test_build_report_minimal():
    r = build_report(
        task_id="task-1",
        source_path="/tmp/test.md",
        started_at=1000,
        finished_at=2000,
        source_bytes=500,
        pipeline_mode="candidate",
        chunks_count=1,
    )
    assert r.task_id == "task-1"
    assert r.duration_ms == 1000
    assert r.verdict == ""  # not set
    assert r.pages_total == 0


def test_build_report_full():
    r = build_report(
        task_id="task-2",
        source_path="/tmp/doc.pdf",
        started_at=1000,
        finished_at=3500,
        source_bytes=12345,
        pipeline_mode="candidate",
        chunks_count=3,
        claims_count=12,
        evidence_count=8,
        candidate_confidence=0.85,
        verdict="validated",
        pages_total=5,
        pages_by_type={"source": 1, "entity": 2, "concept": 2},
    )
    assert r.verdict == "validated"
    assert r.pages_total == 5
    assert r.chunks_count == 3
    assert r.source_bytes == 12345
    assert r.pages_by_type == {"source": 1, "entity": 2, "concept": 2}


def test_build_report_rejected():
    r = build_report(
        task_id="task-3",
        source_path="/tmp/bad.txt",
        started_at=1000,
        finished_at=1200,
        source_bytes=50,
        pipeline_mode="candidate",
        chunks_count=1,
        verdict="rejected",
        verdict_reason="confidence below threshold",
    )
    assert r.verdict == "rejected"
    assert r.verdict_reason == "confidence below threshold"
    assert r.pages_total == 0


def test_build_report_rounds_confidence():
    r = build_report(
        task_id="task-4",
        source_path="/tmp/x.md",
        started_at=1000,
        finished_at=2000,
        source_bytes=100,
        pipeline_mode="candidate",
        chunks_count=1,
        candidate_confidence=0.87654321,
    )
    assert r.candidate_confidence == 0.8765


def test_to_dict_includes_iso_timestamps():
    r = build_report(
        task_id="task-5",
        source_path="/tmp/x.md",
        started_at=1700000000000,
        finished_at=1700000001000,
        source_bytes=100,
        pipeline_mode="candidate",
        chunks_count=1,
    )
    d = r.to_dict()
    assert d["started_at_iso"] is not None
    assert d["finished_at_iso"] is not None
    assert "T" in d["started_at_iso"]


def test_write_ingest_report_creates_file(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    r = build_report(
        task_id="rep-1",
        source_path="/tmp/test.md",
        started_at=1000,
        finished_at=2000,
        source_bytes=500,
        pipeline_mode="candidate",
        chunks_count=1,
        verdict="validated",
        pages_total=3,
        pages_by_type={"source": 1, "entity": 2},
    )
    out = write_ingest_report(paths, r)
    assert out.exists()
    assert out.suffix == ".json"

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["task_id"] == "rep-1"
    assert data["pages_total"] == 3
    assert data["verdict"] == "validated"


def test_write_ingest_report_creates_dir_if_missing(tmp_path):
    """write_ingest_report creates .index/ingest_reports/ if it doesn't exist."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    reports_dir = paths.root / ".index" / "ingest_reports"
    assert not reports_dir.exists()

    r = build_report(
        task_id="rep-2",
        source_path="/tmp/test.md",
        started_at=1000,
        finished_at=2000,
        source_bytes=100,
        pipeline_mode="candidate",
        chunks_count=1,
    )
    write_ingest_report(paths, r)
    assert reports_dir.exists()
    assert (reports_dir / "rep-2.json").exists()


def test_reports_dir_constant():
    from src.pipeline.ingest_report import REPORTS_DIR
    assert REPORTS_DIR == ".index/ingest_reports"


def test_ingest_report_dataclass_defaults():
    r = IngestReport(task_id="t", source_path="p", started_at=1)
    assert r.finished_at == 0
    assert r.duration_ms == 0
    assert r.pipeline_mode == ""
    assert r.pages_by_type == {}
    assert r.warnings == []
