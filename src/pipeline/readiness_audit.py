"""Durable, metadata-only readiness audit records."""

from __future__ import annotations

import json
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any


_REQUIRED = {
    "assessment_version",
    "policy_version",
    "source_id",
    "decision",
    "reason_codes",
    "input_text_sha256",
    "evidence_capacity",
}
_LEGACY_POLICY = "legacy-sanitizer-v0"
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9._-]+$")
_SENSITIVE = re.compile(r"(?:api.?key|authorization|password|secret|token)", re.I)
_BODY_KEYS = {"body", "content", "input_text", "raw_text", "source_text"}


def _record_path(root: Path, record: dict[str, Any]) -> Path:
    policy_version = str(record.get("policy_version", ""))
    source_id = str(record.get("source_id", ""))
    if not policy_version or not _SAFE_VERSION.fullmatch(policy_version):
        raise ValueError("policy_version is required and must be path-safe")
    if not source_id:
        raise ValueError("source_id is required")
    source_key = sha256(source_id.encode("utf-8")).hexdigest()[:32]
    return Path(root) / ".index" / "quarantine" / "readiness" / policy_version / f"{source_key}.json"


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise TypeError("readiness record must be an object")
    return {
        str(key): value
        for key, value in record.items()
        if str(key).lower() not in _BODY_KEYS and not _SENSITIVE.search(str(key))
    }


def _validate(record: dict[str, Any]) -> None:
    missing = sorted(_REQUIRED - record.keys())
    if missing:
        raise ValueError(f"invalid readiness audit record; missing: {', '.join(missing)}")
    if record["policy_version"] == _LEGACY_POLICY:
        return
    if not isinstance(record["reason_codes"], list):
        raise ValueError("invalid readiness audit record; reason_codes must be a list")
    if not isinstance(record["evidence_capacity"], dict):
        raise ValueError("invalid readiness audit record; evidence_capacity must be an object")


def write_readiness_record(root: Path, record: dict[str, Any]) -> Path:
    """Atomically write one immutable record, separated by policy version."""
    public = _public_record(record)
    _validate(public)
    if public["policy_version"] == _LEGACY_POLICY:
        raise PermissionError("legacy readiness records are read-only")
    destination = _record_path(root, public)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if destination.exists():
        if destination.read_text(encoding="utf-8") == encoded:
            return destination
        raise FileExistsError(f"readiness record already exists: {destination}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.stem}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)
    return destination


def read_readiness_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"corrupt readiness audit record: {path}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"corrupt readiness audit record: {path}")
    _validate(record)
    return record


def compare_readiness_records(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_public = _public_record(old)
    new_public = _public_record(new)
    return {
        key: {"old": old_public.get(key), "new": new_public.get(key)}
        for key in sorted(set(old_public) | set(new_public))
        if old_public.get(key) != new_public.get(key)
    }
