"""Batch state facade helpers."""
from __future__ import annotations

import time

from src.services.batch_state import update_raw_fail_streak

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
    streak, blocklisted = update_raw_fail_streak(
        paths, batch_key, raw_rel, status, max_streak=MAX_FAIL_STREAK
    )
    if blocklisted:
        print(f"ALERT: {raw_rel} failed {streak} consecutive batches — "
              f"BLOCKLISTED, manual review required", flush=True)
