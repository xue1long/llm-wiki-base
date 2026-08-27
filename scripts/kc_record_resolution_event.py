"""Record resolution_event to .index/resolution_events.jsonl (A-1 demo tool).

append-only JSONL writer following spec §5.11:
- actor writes one JSON object per line
- each event carries event_id + candidate_ref + candidate_set + action +
  reason_codes + policy_version + model + confidence
- replayable from JSONL by downstream Identity Resolution audit (B-2)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.kc.domain import (
    ResolutionEvent,
    should_merge_ku,
    should_split_ku,
)


def record_event(event: ResolutionEvent, project_root: Path) -> Path:
    """Append ``event`` to ``.index/resolution_events.jsonl`` under ``project_root``.

    Returns the JSONL path. Caller can tail / grep / replay the file later.
    """
    event_log = project_root / ".index" / "resolution_events.jsonl"
    event_log.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "event_id": event.event_id,
        "candidate_ref": list(event.candidate_ref),
        "candidate_set": [list(c) for c in event.candidate_set],
        "action": event.action,
        "reason_codes": list(event.reason_codes),
        "context_policy_version": event.context_policy_version,
        "temporal_policy_version": event.temporal_policy_version,
        "model": event.model,
        "model_version": event.model_version,
        "confidence": event.confidence,
        "approval_id": event.approval_id,
        "created_at": event.created_at,
    }
    with event_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return event_log


def demo_split_decision() -> ResolutionEvent:
    """Demo: A-1 dry-run (commit e9812664) 对 66 叙事类页面启发式拆分 demo."""
    return ResolutionEvent(
        event_id="rev_demo_001",
        candidate_ref=("knowledge_unit", "ku_existing_001"),
        candidate_set=(("knowledge_unit", "ku_existing_001", 1.0),),
        action="split",
        reason_codes=("internal_questions_gt_1",),
        context_policy_version="id-v1",
        temporal_policy_version="id-v1",
        model=None,
        model_version=None,
        confidence=0.85,
        approval_id=None,
        created_at=int(time.time() * 1000),
    )


def make_event_from_split_decision(
    *,
    event_id: str,
    target_ku_id: str,
    claim_count: int,
    internal_questions: int,
    same_platform: bool = True,
    same_audience: bool = True,
    time_ranges_overlap: bool = True,
    update_correlation: float = 1.0,
    confidence: float = 0.85,
    approval_id: str | None = None,
) -> ResolutionEvent:
    """Build a ResolutionEvent from a split-decision evaluation.

    Bridges ``should_split_ku`` (spec §4.4 helper) with ``ResolutionEvent``
    (spec §5.11 record) so callers can persist audit trail in one call.
    """
    should_split = should_split_ku(
        claim_count=claim_count,
        internal_questions=internal_questions,
        same_platform=same_platform,
        same_audience=same_audience,
        time_ranges_overlap=time_ranges_overlap,
        update_correlation=update_correlation,
    )
    action = "split" if should_split else "keep_separate"

    reason_codes: list[str] = []
    if internal_questions > 1:
        reason_codes.append("internal_questions_gt_1")
    if not same_platform:
        reason_codes.append("same_platform_false")
    if not same_audience:
        reason_codes.append("same_audience_false")
    if not time_ranges_overlap:
        reason_codes.append("time_ranges_overlap_false")
    if update_correlation < 0.5:
        reason_codes.append("update_correlation_lt_0_5")
    if not reason_codes:
        reason_codes.append("no_split_signal")

    return ResolutionEvent(
        event_id=event_id,
        candidate_ref=("knowledge_unit", target_ku_id),
        candidate_set=(("knowledge_unit", target_ku_id, 1.0),),
        action=action,  # type: ignore[arg-type]
        reason_codes=tuple(reason_codes),
        confidence=confidence,
        approval_id=approval_id,
        created_at=int(time.time() * 1000),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record KU ResolutionEvent (spec §5.11)")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root (defaults to CWD). JSONL written to <root>/.index/",
    )
    args = parser.parse_args(argv)

    event = demo_split_decision()
    log_path = record_event(event, args.project_root)
    print(f"Recorded event {event.event_id} to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
