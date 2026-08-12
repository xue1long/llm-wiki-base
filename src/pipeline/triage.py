"""Unified, deterministic ingest triage and its project-local audit log."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .prefilter import prefilter
from ..wiki.core.paths import WikiPaths
from ..lib.write_hooks import safe_write

TriageAction = Literal["process", "skip", "source_only", "reference_list"]
_RULE_VERSION = "triage-v1"
_LOG_LOCK = threading.Lock()


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
    record = asdict(result)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with _LOG_LOCK:
        previous = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        if encoded in {line.strip() for line in previous.splitlines() if line.strip()}:
            return
        safe_write(log_path, previous + encoded + "\n")
