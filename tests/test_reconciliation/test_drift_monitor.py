"""Tests for the Reconciliation drift monitor (Task 50)."""
from __future__ import annotations

import json

from src.reconciliation.canonical_models import CanonicalConcept, ReconciliationStatus
from src.reconciliation.canonical_registry import CanonicalRegistry
from src.reconciliation.drift_monitor import (
    ReconciliationDriftMonitor,
    ReconciliationDriftSnapshot,
    decision_log_path,
)


def _seed_concepts(registry: CanonicalRegistry) -> None:
    """3 ACTIVE + 2 STALE + 1 TOMBSTONED."""
    concepts = {
        "c-active-1": CanonicalConcept(
            canonical_id="c-active-1", preferred_label="A1",
            member_page_ids=["p1"], status=ReconciliationStatus.ACTIVE,
            resolver_fingerprint="fp",
        ),
        "c-active-2": CanonicalConcept(
            canonical_id="c-active-2", preferred_label="A2",
            member_page_ids=["p2"], status=ReconciliationStatus.ACTIVE,
            resolver_fingerprint="fp",
        ),
        "c-active-3": CanonicalConcept(
            canonical_id="c-active-3", preferred_label="A3",
            member_page_ids=["p3"], status=ReconciliationStatus.ACTIVE,
            resolver_fingerprint="fp",
        ),
        "c-stale-1": CanonicalConcept(
            canonical_id="c-stale-1", preferred_label="S1",
            member_page_ids=["p4"], status=ReconciliationStatus.STALE,
            resolver_fingerprint="fp-old",
        ),
        "c-stale-2": CanonicalConcept(
            canonical_id="c-stale-2", preferred_label="S2",
            member_page_ids=["p5"], status=ReconciliationStatus.STALE,
            resolver_fingerprint="fp-old",
        ),
        "c-tomb-1": CanonicalConcept(
            canonical_id="c-tomb-1", preferred_label="T1",
            member_page_ids=[], status=ReconciliationStatus.TOMBSTONED,
            resolver_fingerprint="fp",
        ),
    }
    registry._save_concepts(concepts)


def test_snapshot_with_empty_registry(tmp_path):
    """No concepts -> all counts 0, no drift."""
    snap = ReconciliationDriftMonitor(tmp_path).snapshot()
    assert isinstance(snap, ReconciliationDriftSnapshot)
    assert snap.active_canonical_count == 0
    assert snap.stale_canonical_count == 0
    assert snap.tombstoned_canonical_count == 0
    assert snap.unresolved_decisions_recent == 0
    assert snap.fingerprint_drift_detected is False


def test_snapshot_counts_active_and_stale_correctly(tmp_path):
    """3 ACTIVE + 2 STALE + 1 TOMBSTONED -> accurate counts."""
    reg = CanonicalRegistry(tmp_path)
    _seed_concepts(reg)
    snap = ReconciliationDriftMonitor(tmp_path, current_fingerprint="fp").snapshot()
    assert snap.active_canonical_count == 3
    assert snap.stale_canonical_count == 2
    assert snap.tombstoned_canonical_count == 1


def test_snapshot_detects_fingerprint_drift(tmp_path):
    """Any STALE -> fingerprint_drift_detected = True."""
    reg = CanonicalRegistry(tmp_path)
    _seed_concepts(reg)
    snap = ReconciliationDriftMonitor(tmp_path).snapshot()
    assert snap.fingerprint_drift_detected is True


def test_snapshot_counts_unresolved_decisions_recent(tmp_path):
    """Recent decision_log: 2 UNRESOLVED out of 5 -> unresolved_decisions_recent = 2."""
    reg = CanonicalRegistry(tmp_path)
    _seed_concepts(reg)
    log_path = decision_log_path(tmp_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {"decision": "same"},
        {"decision": "distinct"},
        {"decision": "unresolved"},
        {"decision": "conflict"},
        {"decision": "unresolved"},
    ]
    log_path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    snap = ReconciliationDriftMonitor(tmp_path).snapshot(recent_decisions_limit=5)
    assert snap.unresolved_decisions_recent == 2


def test_snapshot_handles_missing_decision_log(tmp_path):
    """decision_log.jsonl missing -> unresolved_decisions_recent = 0, no crash."""
    reg = CanonicalRegistry(tmp_path)
    _seed_concepts(reg)
    # No decision_log.jsonl exists.
    snap = ReconciliationDriftMonitor(tmp_path).snapshot()
    assert snap.unresolved_decisions_recent == 0


def test_snapshot_handles_corrupt_decision_lines(tmp_path):
    """Corrupt JSONL lines are skipped; valid lines still counted."""
    log_path = decision_log_path(tmp_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps({"decision": "unresolved"}) + "\n" + "garbage\n" + json.dumps({"decision": "unresolved"}) + "\n",
        encoding="utf-8",
    )
    snap = ReconciliationDriftMonitor(tmp_path).snapshot(recent_decisions_limit=10)
    assert snap.unresolved_decisions_recent == 2


def test_snapshot_includes_current_fingerprint_and_timestamp(tmp_path):
    """snapshot.current_fingerprint + taken_at_ms populated."""
    snap = ReconciliationDriftMonitor(tmp_path, current_fingerprint="fp-abc").snapshot()
    assert snap.current_fingerprint == "fp-abc"
    assert snap.taken_at_ms > 0