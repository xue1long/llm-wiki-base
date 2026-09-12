"""The small, verified GBrain settings surface used by ruflo-kb."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class GBrainSettingsError(ValueError):
    """GBrain did not accept or confirm a setting change."""


def _run(runtime_path: str | Path, *args: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    if shutil.which("bun") is None:
        raise GBrainSettingsError("bun_missing")
    env = os.environ.copy()
    env["GBRAIN_NO_MODE_SWITCH_UX"] = "1"
    try:
        return subprocess.run(
            ["bun", "run", "src/cli.ts", *args],
            cwd=runtime_path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
        raise GBrainSettingsError("search_command_failed") from exc


def read_search_mode(runtime_path: str | Path) -> str:
    result = _run(runtime_path, "search", "modes", "--json")
    if result.returncode != 0:
        raise GBrainSettingsError("search_modes_failed")
    try:
        report = json.loads(result.stdout)
        mode = str(report["active_mode"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GBrainSettingsError("search_modes_invalid") from exc
    if mode not in {"conservative", "balanced", "tokenmax"}:
        raise GBrainSettingsError("search_mode_invalid")
    return mode


def apply_search_mode(runtime_path: str | Path, mode: str) -> dict[str, Any]:
    if mode not in {"conservative", "balanced", "tokenmax"}:
        raise GBrainSettingsError("search_mode_invalid")
    result = _run(runtime_path, "config", "set", "search.mode", mode)
    if result.returncode != 0:
        raise GBrainSettingsError("search_mode_apply_failed")
    effective = read_search_mode(runtime_path)
    if effective != mode:
        raise GBrainSettingsError("search_mode_not_effective")
    return {"gbrain_mode": effective}


__all__ = ["GBrainSettingsError", "apply_search_mode", "read_search_mode"]
