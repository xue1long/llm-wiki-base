"""Templates CLI."""
import argparse
import sys
from pathlib import Path

from ..lib.write_hooks import safe_write
from ..templates.loader import create, delete, list_templates, load, update_metadata


def cmd_templates_list(_args: argparse.Namespace) -> None:
    print("Templates:")
    for t in list_templates():
        kind = "bundled" if t.builtin else "custom"
        print(f"  - {t.name} ({kind}) {t.description}".rstrip())


def cmd_templates_show(args: argparse.Namespace) -> None:
    try:
        t = load(args.name)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Template: {t.name}")
    print("Files:")
    for f in t.files:
        print(f"  - {f}")


def cmd_templates_apply(args: argparse.Namespace) -> None:
    """Apply template to project (after `project init`)."""
    try:
        from ..project.context import ProjectContext, ProjectNotFoundError
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        template = load(args.name)
        # Existing `templates apply` historically overwrote project files.
        # Keep that compatibility; new project init uses the shared loader.
        written = []
        for rel_path, content in template.files.items():
            dest = Path(ctx.path) / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            safe_write(dest, content)
            written.append(dest)
        for rel_path in template.extra_dirs or []:
            (Path(ctx.path) / rel_path).mkdir(parents=True, exist_ok=True)
    except (FileNotFoundError, ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Applied template '{args.name}' to {ctx.path} ({len(written)} files)")


def cmd_templates_create(args: argparse.Namespace) -> None:
    try:
        t = create(args.name, source=args.source, description=args.description or "", icon=args.icon or "")
    except (FileNotFoundError, ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Created template '{t.name}'")


def cmd_templates_edit(args: argparse.Namespace) -> None:
    try:
        t = update_metadata(args.name, description=args.description, icon=args.icon)
    except (FileNotFoundError, ValueError, PermissionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Updated template '{t.name}'")


def cmd_templates_delete(args: argparse.Namespace) -> None:
    try:
        delete(args.name)
    except (FileNotFoundError, ValueError, PermissionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Deleted template '{args.name}'")
