# src/cli_ext/schema_cmd.py
"""Schema management subcommands: list / diff / upgrade / downgrade / backup."""
import argparse
import sys
from pathlib import Path

from ..schemas.migration import MigrationContext, SchemaVersion
from ..schemas.registry import MigrationRegistry
from ..schemas.backup import BackupManager


def cmd_schema_list(args: argparse.Namespace) -> None:
    """List registered schemas + available migration edges."""
    # Show static schema info (from MigrationRegistry)
    edges = []
    for (sname, f, t) in MigrationRegistry._migrations.keys():
        edges.append((sname, f, t))

    # Group by schema
    by_schema: dict[str, list] = {}
    for sname, f, t in edges:
        by_schema.setdefault(sname, []).append((f, t))

    if not by_schema:
        print("No schemas registered.")
        return

    for sname, edges in sorted(by_schema.items()):
        print(f"Schema: {sname}")
        for f, t in sorted(edges, key=lambda e: (e[0].value, e[1].value)):
            print(f"  {f.value} → {t.value}")
        print()


def _parse_version_or_exit(raw: str) -> SchemaVersion:
    """Parse a version string into SchemaVersion, or exit 2 with friendly error."""
    try:
        return SchemaVersion(raw)
    except ValueError as e:
        print(f"Invalid version: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_schema_diff(args: argparse.Namespace) -> None:
    """Show field changes between two versions of a schema.

    MVP: read project's wiki/ frontmatter; show which pages have which fields.
    """
    from ..project.context import ProjectContext, ProjectNotFoundError
    try:
        ctx = ProjectContext.resolve(None)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    from_v = _parse_version_or_exit(args.from_v)
    to_v = _parse_version_or_exit(args.to_v)
    print(f"Schema diff: {args.schema} {from_v.value} → {to_v.value}")
    print()
    # Simple diff: count pages at each version
    pages = list(ctx.path.glob("wiki/**/*.md"))
    at_from = sum(1 for f in pages if f"schema_version: {from_v.value}" in f.read_text(encoding="utf-8"))
    at_to = sum(1 for f in pages if f"schema_version: {to_v.value}" in f.read_text(encoding="utf-8"))
    print(f"  Pages at {from_v.value}: {at_from}")
    print(f"  Pages at {to_v.value}: {at_to}")
    print()
    # Check migration path
    try:
        path = MigrationRegistry.migration_path(args.schema, from_v, to_v)
        print(f"  Migration path: {len(path)} step(s)")
    except Exception as e:
        print(f"  ⚠ No migration path: {e}")


def cmd_schema_upgrade(args: argparse.Namespace) -> None:
    """Upgrade project schema to specified version."""
    from ..project.context import ProjectContext, ProjectNotFoundError
    try:
        ctx = ProjectContext.resolve(None)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    to_v = _parse_version_or_exit(args.to)
    # Read current version
    pj = ctx.path / ".llm-wiki" / "project.json"
    if not pj.exists():
        print("No project.json; run `project init` first", file=sys.stderr)
        sys.exit(2)

    import json
    data = json.loads(pj.read_text(encoding="utf-8"))
    cur = SchemaVersion(data.get("schema_version", "v1.0"))
    if cur == to_v:
        print(f"Already at {to_v.value}")
        return

    # Find path
    try:
        path = MigrationRegistry.migration_path("wiki_page", cur, to_v)
    except Exception as e:
        print(f"No migration path: {e}", file=sys.stderr)
        sys.exit(2)

    if args.preview:
        print(f"Preview: {cur.value} → {to_v.value} ({len(path)} step)")
        for m in path:
            plan = m.preview(MigrationContext(project_id=ctx.id, project_path=ctx.path, dry_run=True))
            for s in plan.steps:
                print(f"  - {s}")
        return

    # Apply each migration
    for m in path:
        backup_dir = BackupManager.create_backup(ctx.path, reason=f"schema upgrade {m.from_version}→{m.to_version}")
        m_ctx = MigrationContext(
            project_id=ctx.id,
            project_path=ctx.path,
            backup_dir=backup_dir,
        )
        result = m.up(m_ctx)
        if not result.success:
            print(f"Migration {m.from_version}→{m.to_version} failed: {result.errors}", file=sys.stderr)
            sys.exit(1)
        print(f"  ✓ {m.from_version.value} → {m.to_version.value}: {result.files_changed} files changed")

    print(f"Upgraded to {to_v.value}")


def cmd_schema_downgrade(args: argparse.Namespace) -> None:
    """Downgrade project schema."""
    from ..project.context import ProjectContext, ProjectNotFoundError
    try:
        ctx = ProjectContext.resolve(None)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    to_v = _parse_version_or_exit(args.to)
    pj = ctx.path / ".llm-wiki" / "project.json"
    import json
    data = json.loads(pj.read_text(encoding="utf-8"))
    cur = SchemaVersion(data.get("schema_version", "v1.0"))

    # Reverse path
    try:
        forward = MigrationRegistry.migration_path("wiki_page", to_v, cur)
    except Exception as e:
        print(f"No reverse path: {e}", file=sys.stderr)
        sys.exit(2)

    if args.preview:
        print(f"Preview: {cur.value} → {to_v.value} ({len(forward)} step reverse)")
        return

    for m in reversed(forward):
        backup_dir = BackupManager.create_backup(ctx.path, reason=f"downgrade {m.from_version}→{m.to_version}")
        m_ctx = MigrationContext(project_id=ctx.id, project_path=ctx.path, backup_dir=backup_dir)
        result = m.down(m_ctx)
        print(f"  ✓ {m.from_version.value} ← {m.to_version.value}: {result.files_changed} files changed")

    print(f"Downgraded to {to_v.value}")


def cmd_schema_backup(args: argparse.Namespace) -> None:
    """List / restore backups."""
    from ..project.context import ProjectContext, ProjectNotFoundError
    try:
        ctx = ProjectContext.resolve(None)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.action == "list":
        backups = BackupManager.list_backups(ctx.path)
        if not backups:
            print("No backups.")
            return
        for b in backups:
            print(f"  {b.name}  {b.reason}")
    elif args.action == "restore":
        if not args.name:
            print("Backup name required for restore (use --name)", file=sys.stderr)
            sys.exit(2)
        BackupManager.restore(ctx.path, args.name)
        print(f"Restored from {args.name}")