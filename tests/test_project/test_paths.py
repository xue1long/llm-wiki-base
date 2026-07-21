# tests/test_project/test_paths.py
from pathlib import Path

from src.project.paths import config_dir, registry_path, last_project_path


def test_config_dir_returns_path():
    """config_dir() returns a Path object under OS config dir."""
    p = config_dir()
    assert isinstance(p, Path)
    assert p.name == "ruflo-kb" or "ruflo-kb" in str(p)


def test_registry_path_under_config_dir():
    """registry_path() lives under config_dir()."""
    p = registry_path()
    assert p.name == "registry.json"
    assert p.parent == config_dir()


def test_last_project_path_under_config_dir():
    """last_project_path() lives under config_dir()."""
    p = last_project_path()
    assert p.name == "last_project.json"
    assert p.parent == config_dir()
