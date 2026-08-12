"""Unified, deterministic ingest triage and its project-local audit log."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .prefilter import prefilter
from ..wiki.core.paths import WikiPaths

TriageAction = Literal["process", "skip", "source_only", "reference_list"]
_RULE_VERSION = "triage-v1"


@dataclass(frozen=True)
class TriageResult:
    source_id: str
    grade: Literal["A", "B", "C"]
    action: TriageAction
    reason: str
    rule_version: str = _RULE_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)


def triage(
    source_id: str,
    source_text: str,
    *,
    file_size: int,
    sanitizer_score: float | None = None,
) -> TriageResult:
    """Convert the existing prefilter decision into the stable pipeline contract."""
    result = prefilter(
        source_text=source_text,
        file_size=file_size,
        sanitizer_score=sanitizer_score,
    )
    grade = "C" if result.action in {"skip", "source_only"} else "B"
    return TriageResult(
        source_id=source_id or "(unknown)",
        grade=grade,
        action=result.action,
        reason=result.reason,
        metadata=dict(result.metadata),
    )


def write_triage_result(paths: WikiPaths, result: TriageResult) -> None:
    """Append one triage event, suppressing exact duplicate events."""
    log_path = Path(paths.index) / "triage.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = asdict(result)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    existing: set[str] = set()
    if log_path.exists():
        existing = {
            line.strip()
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    if encoded in existing:
        return
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded + "\n")
