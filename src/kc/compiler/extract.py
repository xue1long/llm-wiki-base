"""Strict parsing of the small candidate payload used by the adapter seam."""

from __future__ import annotations

import json
from typing import Any


def parse_candidate_json(payload: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("candidate JSON is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list) or not value["claims"]:
        raise ValueError("candidate JSON must contain non-empty claims")
    for claim in value["claims"]:
        if not isinstance(claim, dict) or not claim.get("id") or not claim.get("text"):
            raise ValueError("claim requires id and text")
        if not isinstance(claim.get("evidence"), list) or not claim["evidence"]:
            raise ValueError("claim requires evidence")
    return value
