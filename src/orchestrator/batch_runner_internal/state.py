"""Batch state facade helpers."""
from __future__ import annotations

import time

from src.services.batch_state import load_batch_state, set_raw_status

MAX_FAIL_STREAK = 3


def _set_batch_status(paths, batch_key, status: str, **extra) -> None:
    from src.services.batch_state import update_batch_state

    def _mutate(state: dict) -> dict:
        entry = state.setdefault(batch_key, {})
        if not isinstance(entry, dict):
            entry = {}
            state[batch_key] = entry
        entry["status"] = status
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        for k, v in extra.items():
            entry[k] = v
        return state

    update_batch_state(paths, _mutate)


def _update_fail_streak(paths, batch_key, raw_rel, status) -> None:
    state = load_batch_state(paths)
    entry = state.get(batch_key, {}).get("raw_states", {}).get(raw_rel, {})
    streak = int(entry.get("fail_streak", 0))
    if status == "failed":
        streak += 1
        extra = {"fail_streak": streak}
        if streak >= MAX_FAIL_STREAK:
            extra["blocklisted"] = True
            print(f"ALERT: {raw_rel} failed {streak} consecutive batches — "
                  f"BLOCKLISTED, manual review required", flush=True)
    else:
        extra = {"fail_streak": 0}
    set_raw_status(paths, batch_key, raw_rel, status, **extra)
