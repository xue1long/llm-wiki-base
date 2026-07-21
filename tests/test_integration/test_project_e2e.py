# tests/test_integration/test_project_e2e.py
"""End-to-end test: project discovery and full lifecycle."""
import json
import os
import subprocess
import sys
from pathlib import Path

from platformdirs import user_config_dir


def test_auto_register_then_init_list_and_info(tmp_path, monkeypatch):
    """CLI honors its isolated config/home while discovering and managing projects."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    real_platform_registry = Path(user_config_dir("ruflo-kb", "ruflo-kb")) / "registry.json"
    real_registry_before = (
        real_platform_registry.read_bytes() if real_platform_registry.exists() else None
    )

    # Keep the subprocess dependency path stable even when APPDATA changes the
    # Windows user-site location.
    dependency_paths = os.pathsep.join(path for path in sys.path if path)
    monkeypatch.setenv("PYTHONPATH", dependency_paths)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))

    base_env = os.environ.copy()

    # A manually-created project must be discovered on the first no-op CLI command.
    discovered_project = home_dir / "Documents" / "discovered-project"
    project_json = discovered_project / ".llm-wiki" / "project.json"
    project_json.parent.mkdir(parents=True)
    project_json.write_text(
        json.dumps(
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "discovered-project",
                "created_at": 1,
                "schema_version": "v2.0",
            }
        ),
        encoding="utf-8",
    )

    discovery_config_dir = tmp_path / "discovery-config"
    discovery_config_dir.mkdir()
    discovery_env = base_env | {"RUFLO_CONFIG_DIR": str(discovery_config_dir)}
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "list"],
        capture_output=True,
        text=True,
        env=discovery_env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "discovered-project" in result.stdout
    assert (discovery_config_dir / "registry.json").exists()

    # Seed the override registry so init must update this exact file, not the
    # normal platform config location.
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    override_registry = config_dir / "registry.json"
    override_registry.write_text(
        json.dumps({"version": 1, "projects": {}, "marker": "override-config"}),
        encoding="utf-8",
    )
    test_env = base_env | {"RUFLO_CONFIG_DIR": str(config_dir)}

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "init", str(project_dir)],
        capture_output=True,
        text=True,
        env=test_env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Initialized" in result.stdout or "myproject" in result.stdout
    assert (project_dir / ".llm-wiki" / "project.json").exists()

    registry_data = json.loads(override_registry.read_text(encoding="utf-8"))
    assert registry_data["projects"]
    assert any(
        entry["path"] == str(project_dir.resolve())
        for entry in registry_data["projects"].values()
    )
    assert "marker" not in registry_data

    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "list"],
        capture_output=True,
        text=True,
        env=test_env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "myproject" in result.stdout

    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "info", "myproject"],
        capture_output=True,
        text=True,
        env=test_env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "myproject" in result.stdout
    assert str(project_dir.resolve()) in result.stdout
    assert (
        real_platform_registry.read_bytes() if real_platform_registry.exists() else None
    ) == real_registry_before
