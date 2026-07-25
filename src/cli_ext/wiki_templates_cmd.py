"""wiki-templates CLI subcommands (Plan 25 v1 follow-up).

Subcommands:
  list         Show all 4 PageTypes with version + source + validity
  show <type>  Print template body_markdown to stdout
  edit <type>  Copy bundled template to user/project dir + open in $EDITOR
  reset <type> Remove user/project override; back up to .bak
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from ..wiki.core.types import PageType
from ..wiki.templates import Template, list_available, resolve


# User-level override directory
_USER_DIR = Path.home() / ".config" / "ruflo-kb" / "wiki-templates"
_PROJECT_DIR_NAME = ".wiki-templates"

# Comment block prepended to copied templates to warn users about
# the mandatory headers (DO NOT EDIT)
_DO_NOT_EDIT_BANNER = """\
<!-- ============================================================
     DO NOT EDIT THE 2 HEADER LINES BELOW.
     The `wiki-template-type` line is REQUIRED and must match the
     filename. The `wiki-template-version` line is used by
     `wiki-templates status` (v3) and the migration CLI.
     Editing them will cause the next resolve() to fail.
     ============================================================ -->
"""


def _validate_template_file(path: Path, expected_type: PageType) -> tuple[bool, str]:
    """Check that a user/project override file has the required headers.

    Returns (is_valid, reason). If invalid, reason explains what's wrong.
    """
    if not path.is_file():
        return False, "file does not exist"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"unreadable: {e}"
    if "<!-- wiki-template-type:" not in content:
        return False, "missing wiki-template-type header"
    if expected_type.value not in content.split("wiki-template-type:", 1)[1].split("-->", 1)[0]:
        return False, f"wiki-template-type does not match {expected_type.value!r}"
    return True, "ok"


def cmd_wiki_templates_list(_args: argparse.Namespace) -> None:
    """Show all 4 PageTypes with version + source + validity."""
    templates = list_available(Path.cwd())
    if not templates:
        print("No templates available", file=sys.stderr)
        sys.exit(1)
    # Header
    print(f"{'TYPE':<10}  {'VERSION':<8}  {'SOURCE':<8}  STATUS")
    print(f"{'----':<10}  {'-------':<8}  {'------':<8}  ------")
    for t in templates:
        # Validity check: a project/user override file must have the right
        # headers; if not, mark it INVALID so the operator knows to fix.
        if t.source in ("project", "user"):
            ok, _ = _validate_template_file(t.path, t.type)
        else:
            ok = True
        status = "ok" if ok else "INVALID"
        print(f"{t.type.value:<10}  {t.version:<8}  {t.source:<8}  {status}")


def cmd_wiki_templates_show(args: argparse.Namespace) -> None:
    """Print the resolved template body_markdown to stdout."""
    type_name = args.type
    try:
        page_type = PageType(type_name)
    except ValueError:
        valid = ", ".join(pt.value for pt in PageType)
        print(f"Unknown type {type_name!r}. Valid: {valid}", file=sys.stderr)
        sys.exit(2)
    t = resolve(page_type, Path.cwd())
    print(t.body_markdown)


def cmd_wiki_templates_edit(args: argparse.Namespace) -> None:
    """Copy bundled template to user/project dir + open in $EDITOR.

    If the destination file already exists, the copy is skipped (no
    overwrite) and the existing file is opened. The user is expected
    to migrate their changes manually.
    """
    type_name = args.type
    try:
        page_type = PageType(type_name)
    except ValueError:
        valid = ", ".join(pt.value for pt in PageType)
        print(f"Unknown type {type_name!r}. Valid: {valid}", file=sys.stderr)
        sys.exit(2)

    # Resolve destination: --project <name> → project dir; else user dir.
    if args.project:
        try:
            from ..lib.project import resolve_project
            ctx, _paths = resolve_project(args.project, by_id_only=True)
            dest_dir = ctx.path / _PROJECT_DIR_NAME
        except Exception as e:
            print(f"Could not resolve project {args.project!r}: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        dest_dir = _USER_DIR

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{page_type.value}.md"

    if not dest_path.exists():
        # Copy from bundled, prepended with DO-NOT-EDIT banner
        try:
            t = resolve(page_type, Path.cwd())
        except FileNotFoundError:
            print(f"No bundled template for {type_name!r}", file=sys.stderr)
            sys.exit(1)
        bundled_body = t.body_markdown
        dest_path.write_text(_DO_NOT_EDIT_BANNER + "\n" + bundled_body, encoding="utf-8")
        print(f"Created: {dest_path}")
    else:
        print(f"Already exists: {dest_path} (not overwritten)")

    # Open in $EDITOR unless --no-open
    if not args.no_open:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        click_edit = _try_import_click_edit()
        if click_edit is not None:
            try:
                click_edit(filename=str(dest_path))
                return
            except Exception as e:
                print(f"click.edit failed: {e}; falling back to $EDITOR", file=sys.stderr)
        if editor:
            os.system(f'{editor} "{dest_path}"')
        else:
            # Last resort: notepad on Windows, vi elsewhere
            if sys.platform == "win32":
                os.system(f'notepad "{dest_path}"')
            else:
                os.system(f'vi "{dest_path}"')


def _try_import_click_edit():
    """Best-effort import of click.edit for $EDITOR integration."""
    try:
        import click  # noqa: F401
        from click import edit as click_edit
        return click_edit
    except ImportError:
        return None


def cmd_wiki_templates_reset(args: argparse.Namespace) -> None:
    """Remove user/project override; back up to .bak.

    Requires --yes for non-interactive use (CI / scripted). Default
    behavior: error out in non-TTY environments without --yes.
    """
    type_name = args.type
    try:
        page_type = PageType(type_name)
    except ValueError:
        valid = ", ".join(pt.value for pt in PageType)
        print(f"Unknown type {type_name!r}. Valid: {valid}", file=sys.stderr)
        sys.exit(2)

    if args.project:
        try:
            from ..lib.project import resolve_project
            ctx, _paths = resolve_project(args.project, by_id_only=True)
            target = ctx.path / _PROJECT_DIR_NAME / f"{page_type.value}.md"
        except Exception as e:
            print(f"Could not resolve project {args.project!r}: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        target = _USER_DIR / f"{page_type.value}.md"

    if not target.exists():
        print(f"No override to remove: {target}", file=sys.stderr)
        sys.exit(1)

    # Require --yes in non-interactive environments (CI, piped input,
    # or explicit RUFO_NONINTERACTIVE=1). Without it, refuse the
    # destructive operation. Using an env var in addition to isatty
    # so subprocess-invoked tests (which inherit a tty) can still
    # force the safe path.
    noninteractive = not sys.stdin.isatty() or os.environ.get("RUFO_NONINTERACTIVE") == "1"
    if not args.yes and noninteractive:
        print(
            f"Refusing to remove {target} without --yes "
            "(non-interactive mode). Pass --yes to confirm.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Back up + remove
    backup = target.with_suffix(target.suffix + ".bak")
    shutil.copy2(target, backup)
    target.unlink()
    print(f"Removed: {target}")
    print(f"Backup:  {backup}")
    print("Next resolve() will fall back to the bundled template.")


def add_wiki_templates_parser(subparsers) -> None:
    """Register the wiki-templates subcommand on the given subparsers object."""
    p = subparsers.add_parser(
        "wiki-templates",
        help="Wiki page template management (list/show/edit/reset)",
    )
    sub = p.add_subparsers(dest="wiki_templates_command", required=True)

    # list
    p_list = sub.add_parser("list", help="Show all PageTypes with version/source")
    p_list.set_defaults(func=cmd_wiki_templates_list)

    # show <type>
    p_show = sub.add_parser("show", help="Print template body_markdown")
    p_show.add_argument("type", help="PageType: source|entity|concept|synthesis")
    p_show.set_defaults(func=cmd_wiki_templates_show)

    # edit <type>
    p_edit = sub.add_parser("edit", help="Copy bundled template to user/project + open in $EDITOR")
    p_edit.add_argument("type", help="PageType: source|entity|concept|synthesis")
    p_edit.add_argument("--project", default=None, help="Project name (resolves to project path)")
    p_edit.add_argument("--no-open", action="store_true", help="Copy without opening editor (CI)")
    p_edit.set_defaults(func=cmd_wiki_templates_edit)

    # reset <type>
    p_reset = sub.add_parser("reset", help="Remove user/project override (back up to .bak)")
    p_reset.add_argument("type", help="PageType: source|entity|concept|synthesis")
    p_reset.add_argument("--project", default=None, help="Project name (resolves to project path)")
    p_reset.add_argument("--yes", action="store_true", help="Skip confirmation (CI use)")
    p_reset.set_defaults(func=cmd_wiki_templates_reset)
