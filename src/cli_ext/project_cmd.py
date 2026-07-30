"""Project management subcommands: init / list / info / current / select / import / forget / rename / discover."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from ..utils.path import safe_resolve, safe_resolve_posix

from ..project.context import ProjectContext
from ..project.paths import last_project_path as _last_project_path
from ..project.registry import (
    GlobalRegistryStore,
    registry_path as _registry_path,
)


def cmd_project_init(args: argparse.Namespace) -> None:
    """Initialize a new project at the given path."""
    project_path = safe_resolve(args.path)
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
    kb_path = safe_resolve(args.path)
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
        entry_path_canon = safe_resolve_posix(entry.path)
        same_path = [e for e in all_entries if safe_resolve_posix(e.path) == entry_path_canon and e.id != entry.id]
        if same_path:
            print(f"Refusing --delete-data: path {kb_path} is also referenced by:", file=sys.stderr)
            for e in same_path:
                print(f"  - {e.id} ({e.name})", file=sys.stderr)
            sys.exit(3)
        # Safety checks before deletion
        resolved = safe_resolve(kb_path)
        try:
            resolved.relative_to(safe_resolve(Path.cwd()))
        except ValueError:
            print(f"Refusing --delete-data: path {kb_path} is outside CWD", file=sys.stderr)
            sys.exit(3)
        if resolved == resolved.parent or str(resolved) in (str(Path.home()), ""):
            print(f"Refusing --delete-data: would delete root or home directory", file=sys.stderr)
            sys.exit(3)
        # Actually delete
        import shutil
        shutil.rmtree(resolved)
        print(f"Deleted {resolved}")

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

    # Read + validate project.json FIRST (fail without touching registry if malformed)
    from pathlib import Path
    import json as _json
    project_json = Path(entry.path) / ".llm-wiki" / "project.json"
    data = None
    if project_json.exists():
        try:
            data = _json.loads(project_json.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                print(f"project.json at {project_json} is not a JSON object", file=sys.stderr)
                sys.exit(3)
        except _json.JSONDecodeError as e:
            print(f"project.json at {project_json} is malformed: {e}", file=sys.stderr)
            sys.exit(3)
    else:
        print(f"project.json not found at {project_json}", file=sys.stderr)
        sys.exit(3)

    # Write project.json (validated) BEFORE updating registry
    data["name"] = args.new_name
    project_json.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Only now update registry (file write succeeded)
    entry.name = args.new_name
    GlobalRegistryStore.upsert(entry)

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


def cmd_project_set_provider(args: argparse.Namespace) -> None:
    """Set the LLM provider for a project (stored in .llm-wiki/project.json)."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)

    import json as _json
    from pathlib import Path as _Path

    project_json = _Path(entry.path) / ".llm-wiki" / "project.json"
    if not project_json.exists():
        print(f"project.json not found at {project_json}", file=sys.stderr)
        sys.exit(3)

    try:
        data = _json.loads(project_json.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"project.json at {project_json} is not a JSON object", file=sys.stderr)
            sys.exit(3)
    except _json.JSONDecodeError as e:
        print(f"project.json at {project_json} is malformed: {e}", file=sys.stderr)
        sys.exit(3)

    # Validate provider exists
    from ..llm.registry import ProviderRegistry
    available = set(ProviderRegistry.list().keys())
    if args.provider_name not in available:
        print(f"Provider '{args.provider_name}' not found. Available: {', '.join(sorted(available))}",
              file=sys.stderr)
        sys.exit(3)

    data["llm_provider"] = args.provider_name
    project_json.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Project '{entry.name}': LLM provider set to '{args.provider_name}'")
    print(f"  (restart the server or re-enqueue tasks for this to take effect)")


def cmd_project_set_model(args: argparse.Namespace) -> None:
    """Set the LLM model for a project (stored in .llm-wiki/project.json)."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)

    import json as _json
    from pathlib import Path as _Path

    project_json = _Path(entry.path) / ".llm-wiki" / "project.json"
    if not project_json.exists():
        print(f"project.json not found at {project_json}", file=sys.stderr)
        sys.exit(3)

    try:
        data = _json.loads(project_json.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"project.json at {project_json} is not a JSON object", file=sys.stderr)
            sys.exit(3)
    except _json.JSONDecodeError as e:
        print(f"project.json at {project_json} is malformed: {e}", file=sys.stderr)
        sys.exit(3)

    data["llm_model"] = args.model_name
    project_json.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Project '{entry.name}': LLM model set to '{args.model_name}'")
    print(f"  (restart the server or re-enqueue tasks for this to take effect)")
