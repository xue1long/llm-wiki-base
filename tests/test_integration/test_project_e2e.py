# tests/test_integration/test_project_e2e.py
"""End-to-end test: full project lifecycle."""
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_init_then_list_then_info(tmp_path, monkeypatch):
    """CLI flow: init → list → info."""
    import os
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Build env with RUFLO_CONFIG_DIR override
    test_env = os.environ.copy()
    test_env["RUFLO_CONFIG_DIR"] = str(config_dir)

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    # Run `python -m src.cli project init <path>`
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "init", str(project_dir)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Initialized" in result.stdout or "myproject" in result.stdout

    # project.json created
    assert (project_dir / ".llm-wiki" / "project.json").exists()

    # Run `python -m src.cli project list`
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "list"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0
    assert "myproject" in result.stdout

    # Run `python -m src.cli project info <name>`
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "info", "myproject"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0
    assert "myproject" in result.stdout
    assert str(project_dir.resolve()) in result.stdout