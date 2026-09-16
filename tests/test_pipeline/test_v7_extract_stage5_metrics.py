"""Tests for Stage 5 metrics recorder (Task 48)."""
from __future__ import annotations

import json

from src.pipeline.v7_extract.stage5_metrics import (
    Stage5Metrics,
    Stage5MetricsEntry,
    make_entry,
    metrics_path,
)


def test_metrics_record_run_appends_jsonl(tmp_path):
    """record_run → .index/v7_metrics.jsonl has 1 line after 1 record."""
    m = Stage5Metrics(tmp_path)
    m.record_run(make_entry(
        run_id="run-1", topic_count=5, claim_total=20, claim_supported=15,
    ))
    assert metrics_path(tmp_path).exists()
    text = metrics_path(tmp_path).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["run_id"] == "run-1"
    assert payload["claim_total"] == 20
    assert payload["claim_supported"] == 15
    assert abs(payload["claim_support_ratio"] - 0.75) < 1e-9


def test_metrics_read_recent_returns_last_n(tmp_path):
    """5 records; read_recent(limit=2) → 2 most-recent."""
    m = Stage5Metrics(tmp_path)
    for i in range(5):
        m.record_run(make_entry(
            run_id=f"run-{i}", topic_count=1, claim_total=10, claim_supported=i,
        ))
    recent = m.read_recent(limit=2)
    assert len(recent) == 2
    # Most recent first (run-4 then run-3).
    assert recent[0].run_id == "run-4"
    assert recent[1].run_id == "run-3"


def test_metrics_aggregate_average_ratio(tmp_path):
    """3 ratios (1.0, 0.5, 0.0) → average 0.5."""
    m = Stage5Metrics(tmp_path)
    # Direct Stage5MetricsEntry construction (avoid time.time inaccuracy).
    m.record_run(Stage5MetricsEntry(
        timestamp_ms=1, run_id="a", topic_count=1,
        claim_total=10, claim_supported=10, claim_support_ratio=1.0,
    ))
    m.record_run(Stage5MetricsEntry(
        timestamp_ms=2, run_id="b", topic_count=1,
        claim_total=10, claim_supported=5, claim_support_ratio=0.5,
    ))
    m.record_run(Stage5MetricsEntry(
        timestamp_ms=3, run_id="c", topic_count=1,
        claim_total=10, claim_supported=0, claim_support_ratio=0.0,
    ))
    avg = m.aggregate_average(limit=10)
    assert abs(avg - 0.5) < 1e-9


def test_metrics_record_zero_claim_topic_still_writes(tmp_path):
    """claim_total=0 → ratio=0.0 (not NaN) and entry is written."""
    m = Stage5Metrics(tmp_path)
    entry = make_entry(run_id="r0", topic_count=1, claim_total=0, claim_supported=0)
    assert entry.claim_support_ratio == 0.0
    m.record_run(entry)
    assert metrics_path(tmp_path).exists()
    avg = m.aggregate_average(limit=10)
    assert avg == 0.0


def test_metrics_read_recent_handles_corrupt_lines(tmp_path):
    """A non-JSON line is silently skipped; valid lines still readable."""
    m = Stage5Metrics(tmp_path)
    m.record_run(make_entry(run_id="good", topic_count=1, claim_total=5, claim_supported=4))
    # Manually append garbage.
    with metrics_path(tmp_path).open("a", encoding="utf-8") as fh:
        fh.write("this-is-not-json\n")
    m.record_run(make_entry(run_id="good2", topic_count=1, claim_total=2, claim_supported=2))
    recent = m.read_recent(limit=10)
    # Both good entries present; corrupt line skipped.
    assert len(recent) == 2
    run_ids = [e.run_id for e in recent]
    assert "good" in run_ids
    assert "good2" in run_ids