"""Atomic persistence for GBrain runtime status."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping


def runtime_state_path(project_root: Path) -> Path:
    return Path(project_root) / ".index" / "gbrain" / "runtime-state.json"


def load_runtime_state(project_root: Path) -> dict[str, Any]:
    path = runtime_state_path(project_root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_runtime_state(project_root: Path, payload: Mapping[str, Any]) -> None:
    path = runtime_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
