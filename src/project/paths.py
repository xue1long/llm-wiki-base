# src/project/paths.py
"""OS-specific config directory paths for ruflo-kb global state.

Uses platformdirs to follow OS conventions:
- Linux: ~/.config/ruflo-kb/
- macOS: ~/Library/Application Support/ruflo-kb/
- Windows: %APPDATA%/ruflo-kb/
"""
from pathlib import Path

from platformdirs import user_config_dir


_APP_NAME = "ruflo-kb"
_APP_AUTHOR = "ruflo-kb"


def config_dir() -> Path:
    """Return OS-standard config directory for ruflo-kb."""
    return Path(user_config_dir(_APP_NAME, _APP_AUTHOR))


def registry_path() -> Path:
    """Path to global registry.json mapping project UUID → metadata."""
    return config_dir() / "registry.json"


def last_project_path() -> Path:
    """Path to last_project.json (single pointer)."""
    return config_dir() / "last_project.json"
