"""Project management subcommands: init / list / info / current / select / import / forget / rename / discover."""
import argparse
import json
import sys

from ..project.context import ProjectContext
from ..project.paths import config_dir as _config_dir
from ..project.registry import (
    GlobalRegistryStore,
    ProjectRegistryEntry,
    registry_path as _registry_path,
)


def cmd_project_init(args: argparse.Namespace) -> None:
    """Initialize a new project at the given path."""
    from pathlib import Path
    project_path = Path(args.path).resolve()
    name = args.name or project_path.name
    ctx = ProjectContext.from_path(project_path, name=name)
    print(f"Initialized project '{ctx.name}' ({ctx.id})")
    print(f"Path: {ctx.path}")


def cmd_project_list(args: argparse.Namespace) -> None:
    """List all registered projects."""
    reg = GlobalRegistryStore.load()
    if not reg.projects:
        print("No projects registered.")
        return
    print(f"{'ID':<40} {'Name':<20} {'Last Opened':<20}")
    print("-" * 80)
    for entry in sorted(reg.projects.values(), key=lambda e: -e.last_opened):
        from datetime import datetime
        ts = datetime.fromtimestamp(entry.last_opened / 1000).isoformat()
        print(f"{entry.id:<40} {entry.name:<20} {ts:<20}")
