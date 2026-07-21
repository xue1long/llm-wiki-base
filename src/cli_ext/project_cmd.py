"""Project management subcommands: init / list / info / current / select / import / forget / rename / discover."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from ..project.context import ProjectContext
from ..project.paths import last_project_path as _last_project_path
from ..project.registry import (
    GlobalRegistryStore,
    registry_path as _registry_path,
)


def cmd_project_init(args: argparse.Namespace) -> None:
    """Initialize a new project at the given path."""
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
        ts = datetime.fromtimestamp(entry.last_opened / 1000).isoformat()
        print(f"{entry.id:<40} {entry.name:<20} {ts:<20}")


def cmd_project_info(args: argparse.Namespace) -> None:
    """Print full metadata for one project."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)
    ts = datetime.fromtimestamp(entry.last_opened / 1000).isoformat()
    print(f"ID:            {entry.id}")
    print(f"Name:          {entry.name}")
    print(f"Path:          {entry.path}")
    print(f"Last Opened:   {ts}")
    print(f"Schema Version: {entry.schema_version}")


def cmd_project_current(args: argparse.Namespace) -> None:
    """Print the resolved current project (from last_project pointer or registry)."""
    ctx = ProjectContext.resolve(None)
    print(f"Current project: {ctx.name} ({ctx.id})")
    print(f"Path: {ctx.path}")


def cmd_project_select(args: argparse.Namespace) -> None:
    """Set the last_project pointer to a specific project."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)
    GlobalRegistryStore.save_last_project(id=entry.id, path=entry.path)
    print(f"Selected project: {entry.name} ({entry.id})")
