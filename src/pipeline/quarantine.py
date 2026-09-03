"""Minimal, redacted task quarantine records."""
from __future__ import annotations

import json
import re
from pathlib import Path

_SECRET = re.compile(r"(?i)(authorization\s*:\s*bearer\s+|api[_-]?key\s*[:=]\s*)[^\s,;]+")


def _summary(value):
    if isinstance(value, dict):
        return {str(k): _summary(v) for k, v in value.items() if str(k).lower() not in {"source", "source_text", "prompt", "headers"}}
    if isinstance(value, (list, tuple)):
        return [_summary(v) for v in value[:20]]
    if isinstance(value, str):
        return _SECRET.sub(r"\1[REDACTED]", value)[:500]
    return value


def quarantine_task(context, *, reason_code: str, errors=(), artifacts=None) -> Path:
    root = Path(getattr(context, "project_root", getattr(context, "root", ".")))
    task_id = str(getattr(context, "task_id", "unknown"))
    target = root / ".index" / "quarantine" / task_id
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "run_id": getattr(context, "run_id", ""),
        "source_hash": getattr(context, "source_hash", ""),
        "reason_code": reason_code,
        "errors": _summary(list(errors)),
        "artifacts": _summary(artifacts or {}),
        "recoverable": False,
    }
    (target / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


__all__ = ["quarantine_task"]
