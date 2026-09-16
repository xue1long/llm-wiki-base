"""Reconciliation 长期 drift 监控 (Task 50).

Reads ``canonical_concepts.json`` + ``decision_log.jsonl`` to produce
a snapshot of the current reconciliation state. Read-only; no LLM,
no network.

Use case: scheduled job / health endpoint surfaces drift (e.g. STALE
canonical concepts after a resolver_fingerprint bump; rising
unresolved ratio on recent decisions) so operators see the situation
without grepping JSONL files.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from src.reconciliation.canonical_models import ReconciliationStatus
from src.reconciliation.canonical_registry import CanonicalRegistry


log = logging.getLogger(__name__)


@dataclass
class ReconciliationDriftSnapshot:
    active_canonical_count: int
    stale_canonical_count: int
    tombstoned_canonical_count: int
    unresolved_decisions_recent: int
    fingerprint_drift_detected: bool
    current_fingerprint: str = ""
    taken_at_ms: int = 0


def decision_log_path(root: Path | str) -> Path:
    """<.index/reconciliation/decision_log.jsonl>"""
    return Path(root) / ".index" / "reconciliation" / "decision_log.jsonl"


def _count_recent_unresolved(root: Path | str, *, limit: int = 10) -> int:
    """Count UNRESOLVED decisions in the last ``limit`` lines of decision_log.

    Returns 0 if the file is missing or malformed. Defensive: each line is
    parsed in isolation, one bad line does not poison the count.
    """
    path = decision_log_path(root)
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    recent = lines[-limit:] if limit > 0 else []
    count = 0
    for line in recent:
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        decision = str(payload.get("decision", "")).strip().lower()
        if decision == "unresolved":
            count += 1
    return count


class ReconciliationDriftMonitor:
    """Read-only snapshot of the reconciliation registry + decision log."""

    def __init__(self, root: Path | str, *, current_fingerprint: str = "") -> None:
        self.root = Path(root)
        self.current_fingerprint = current_fingerprint

    def snapshot(self, *, recent_decisions_limit: int = 10) -> ReconciliationDriftSnapshot:
        registry = CanonicalRegistry(self.root)
        concepts = registry.load_concepts()

        active = sum(1 for c in concepts.values() if c.status is ReconciliationStatus.ACTIVE)
        stale = sum(1 for c in concepts.values() if c.status is ReconciliationStatus.STALE)
        tombstoned = sum(1 for c in concepts.values() if c.status is ReconciliationStatus.TOMBSTONED)

        unresolved = _count_recent_unresolved(self.root, limit=recent_decisions_limit)

        # F4: if any STALE concept exists, drift is detected.
        drift = stale > 0

        return ReconciliationDriftSnapshot(
            active_canonical_count=active,
            stale_canonical_count=stale,
            tombstoned_canonical_count=tombstoned,
            unresolved_decisions_recent=unresolved,
            fingerprint_drift_detected=drift,
            current_fingerprint=self.current_fingerprint,
            taken_at_ms=int(time.time() * 1000),
        )


__all__ = [
    "ReconciliationDriftMonitor",
    "ReconciliationDriftSnapshot",
    "decision_log_path",
]