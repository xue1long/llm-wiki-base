"""test_scripts_cmd.py — verify `ruflo migrate` / `audit` / `util` subcommands.

These are thin subprocess wrappers over the legacy scripts, so we only assert
that they register correctly and forward args (spawning the real script would
require project fixtures and real API calls — not covered here).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_cli(*argv: str, timeout: int = 30) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["HTTP_PROXY"] = env.get("HTTP_PROXY", "")
    env["HTTPS_PROXY"] = env.get("HTTPS_PROXY", "")
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *argv],
        capture_output=True, text=True, env=env, timeout=timeout,
    )


def test_migrate_group_registers():
    """ruflo migrate --help lists the 5 migrate subcommands."""
    r = _run_cli("migrate", "--help")
    assert r.returncode == 0
    for name in ("legacy-tags", "pinyin-to-cjk", "slug-aliases",
                 "timestamps", "vector-paths"):
        assert name in r.stdout


def test_audit_group_registers():
    """ruflo audit --help lists the 4 audit subcommands."""
    r = _run_cli("audit", "--help")
    assert r.returncode == 0
    for name in ("blindspots", "placeholder-classify",
                 "wiki-baseline", "quality-check"):
        assert name in r.stdout


def test_util_group_registers():
    """ruflo util --help lists util subcommands."""
    r = _run_cli("util", "--help")
    assert r.returncode == 0
    for name in ("aggregate-synthesis", "cleanup-stubs", "cleanup-tags",
                 "fix-mojibake", "ndg-calibrate", "normalize-sources",
                 "rebuild-index", "stress-test", "sync-wiki-spec",
                 "setup-git-hooks"):
        assert name in r.stdout


def test_batch_group_has_wrapper_subcommands():
    """ruflo batch --help lists wrapper subcommands (beyond run/plan)."""
    r = _run_cli("batch", "--help")
    assert r.returncode == 0
    for name in ("gate-check", "gate-v3", "diagnose-gate", "accept",
                 "generate", "commit", "build", "ingest", "rollback",
                 "pilot", "phase3-accept", "phase4", "phase5-accept",
                 "plan-first", "plan-backlog"):
        assert name in r.stdout


def test_forwarding_passes_args_to_underlying_script():
    """ruflo batch diagnose-gate -- --help forwards to the real script."""
    r = _run_cli("batch", "diagnose-gate", "--", "--help")
    # The underlying argparse rejects missing --root/--batch with exit 2,
    # which proves the args reached the real script, not the outer CLI.
    assert r.returncode == 2
    assert "diagnose_batch_gate.py" in (r.stdout + r.stderr)
    assert "--batch" in (r.stdout + r.stderr)