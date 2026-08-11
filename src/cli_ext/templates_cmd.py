"""Templates CLI."""
import argparse
import sys

from ..lib.write_hooks import safe_write
from ..templates.loader import load, list_bundled


def cmd_templates_list(_args: argparse.Namespace) -> None:
    print("Bundled templates:")
    for t in list_bundled():
        print(f"  - {t}")


def cmd_templates_show(args: argparse.Namespace) -> None:
    try:
        t = load(args.name)
    except FileNotFoundError as e:
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
        t = load(args.name)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    from ..wiki.core.paths import WikiPaths
    paths = WikiPaths(ctx.path)
    for rel_path, content in t.files.items():
        dest = paths.root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Audit I6/M1: route through safe_write so writes are atomic and
        # AtomicContext-aware (a future `templates apply` invocation inside
        # a wider atomic operation will not produce torn files).
        safe_write(dest, content)
    print(f"Applied template '{t.name}' to {paths.root}")
