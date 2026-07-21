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


def cmd_project_import(args: argparse.Namespace) -> None:
    """Import an existing KB (path with .llm-wiki/project.json) into registry."""
    from pathlib import Path
    kb_path = Path(args.path).resolve()
    if not (kb_path / ".llm-wiki" / "project.json").exists():
        print(f"No .llm-wiki/project.json at {kb_path}", file=sys.stderr)
        sys.exit(2)
    ctx = ProjectContext.from_path(kb_path, name=args.name)
    print(f"Imported project '{ctx.name}' ({ctx.id})")


def cmd_project_forget(args: argparse.Namespace) -> None:
    """Remove entry from global registry (does NOT delete files unless --delete-data)."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)

    if args.delete_data:
        from pathlib import Path
        kb_path = Path(entry.path)
        if not kb_path.exists():
            print(f"Path no longer exists: {kb_path}; cannot --delete-data safely", file=sys.stderr)
            sys.exit(3)
        # Refuse if path is shared (multiple entries pointing to same path)
        all_entries = list(GlobalRegistryStore.load().projects.values())
        same_path = [e for e in all_entries if e.path == entry.path and e.id != entry.id]
        if same_path:
            print(f"Refusing --delete-data: path {kb_path} is also referenced by:", file=sys.stderr)
            for e in same_path:
                print(f"  - {e.id} ({e.name})", file=sys.stderr)
            sys.exit(3)
        # Actually delete
        import shutil
        shutil.rmtree(kb_path)
        print(f"Deleted {kb_path}")

    GlobalRegistryStore.remove(entry.id)
    print(f"Project '{entry.name}' removed from registry")


def cmd_project_rename(args: argparse.Namespace) -> None:
    """Rename a project (updates registry + project.json)."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)

    # Update registry
    entry.name = args.new_name
    GlobalRegistryStore.upsert(entry)

    # Update project.json
    from pathlib import Path
    import json as _json
    project_json = Path(entry.path) / ".llm-wiki" / "project.json"
    if project_json.exists():
        data = _json.loads(project_json.read_text(encoding="utf-8"))
        data["name"] = args.new_name
        project_json.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Renamed '{args.id_or_name}' → '{args.new_name}'")


def cmd_project_discover(args: argparse.Namespace) -> None:
    """Manually trigger auto-discovery of existing KBs."""
    from ..project.discovery import auto_register_on_first_run
    contexts = auto_register_on_first_run()
    if not contexts:
        print("No new projects found.")
        return
    print(f"Discovered {len(contexts)} project(s):")
    for ctx in contexts:
        print(f"  - {ctx.name} ({ctx.id}) at {ctx.path}")
