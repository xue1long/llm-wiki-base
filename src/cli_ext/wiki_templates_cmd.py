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
from ..wiki.templates.parser import TemplateParseError, validate_type_header


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
    Delegates to parser.validate_type_header for the actual check so the
    CLI shares the parser's regex / error wording.
    """
    if not path.is_file():
        return False, "file does not exist"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"unreadable: {e}"
    try:
        validate_type_header(content, expected_type)
    except TemplateParseError as e:
        return False, str(e)
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
        help="Wiki page template management (list/show/edit/reset/status/diff/upgrade)",
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

    # status
    p_status = sub.add_parser(
        "status",
        help="Show per-type template source/version + bundled-upgrade flag",
    )
    p_status.set_defaults(func=cmd_wiki_templates_status)

    # diff <type>
    p_diff = sub.add_parser(
        "diff",
        help="Diff user override against bundled (or bundled against user if no override)",
    )
    p_diff.add_argument("type", help="PageType: source|entity|concept|synthesis")
    p_diff.set_defaults(func=cmd_wiki_templates_diff)

    # upgrade <type>
    p_upgrade = sub.add_parser(
        "upgrade",
        help="Overwrite user override with bundled (requires --force, or --if-unmodified)",
    )
    p_upgrade.add_argument("type", help="PageType: source|entity|concept|synthesis")
    p_upgrade.add_argument(
        "--force", action="store_true",
        help="Overwrite without checking for user edits",
    )
    p_upgrade.add_argument(
        "--if-unmodified", action="store_true",
        help="Only overwrite if user file hasn't been modified since install",
    )
    p_upgrade.set_defaults(func=cmd_wiki_templates_upgrade)

    # reset <type>
    p_reset = sub.add_parser("reset", help="Remove user/project override (back up to .bak)")
    p_reset.add_argument("type", help="PageType: source|entity|concept|synthesis")
    p_reset.add_argument("--project", default=None, help="Project name (resolves to project path)")
    p_reset.add_argument("--yes", action="store_true", help="Skip confirmation (CI use)")
    p_reset.set_defaults(func=cmd_wiki_templates_reset)


# ---------------------------------------------------------------------------
# v3: status / diff / upgrade
# ---------------------------------------------------------------------------

def _resolve_target_path(args, page_type: "PageType") -> Path:
    """Return the user or project override file path for a page type.

    Same logic as cmd_wiki_templates_edit: --project → project dir, else
    user dir. Raises FileNotFoundError if neither exists.
    """
    if args.project:
        from ..lib.project import resolve_project
        ctx, _paths = resolve_project(args.project, by_id_only=True)
        return ctx.path / _PROJECT_DIR_NAME / f"{page_type.value}.md"
    return _USER_DIR / f"{page_type.value}.md"


def cmd_wiki_templates_status(_args: argparse.Namespace) -> None:
    """Show per-type template source/version + bundled-upgrade flag.

    Refreshing the state file at every call ensures we capture any
    sha256 changes to the bundled files since last invocation.
    """
    from ..wiki.templates.state import refresh_state, State
    from ..wiki.templates.types import BUNDLED_DIR

    # Refresh state so we always have current bundled sha256s.
    state, changed = refresh_state()

    # For each PageType, print:
    # - source (bundled / user / project)
    # - version
    # - bundled-updated (since last refresh_state() — usually "" unless a deploy)
    templates = list_available(Path.cwd())
    print(f"{'TYPE':<10}  {'VERSION':<8}  {'SOURCE':<10}  NOTES")
    print(f"{'----':<10}  {'-------':<8}  {'------':<10}  -----")
    for t in templates:
        notes = ""
        if t.source in ("project", "user") and t.type.value in changed:
            notes = "bundled-updated"
        elif t.source == "bundled":
            notes = "(default)"
        print(f"{t.type.value:<10}  {t.version:<8}  {t.source:<10}  {notes}")


def cmd_wiki_templates_diff(args: argparse.Namespace) -> None:
    """Show diff between user override (if any) and bundled.

    If no user override exists, prints "(no override; bundled is the
    active template)". Exit 0 either way.
    """
    import difflib
    from ..wiki.templates.types import BUNDLED_DIR

    type_name = args.type
    try:
        page_type = PageType(type_name)
    except ValueError:
        valid = ", ".join(pt.value for pt in PageType)
        print(f"Unknown type {type_name!r}. Valid: {valid}", file=sys.stderr)
        sys.exit(2)

    user_path = _USER_DIR / f"{page_type.value}.md"
    bundled_path = BUNDLED_DIR / f"{page_type.value}.md"

    if not user_path.is_file():
        print(f"(no override; bundled is the active template: {bundled_path})")
        return

    if not bundled_path.is_file():
        print(f"Bundled template missing: {bundled_path}", file=sys.stderr)
        sys.exit(2)

    user_text = user_path.read_text(encoding="utf-8").splitlines(keepends=True)
    bundled_text = bundled_path.read_text(encoding="utf-8").splitlines(keepends=True)

    diff = difflib.unified_diff(
        bundled_text, user_text,
        fromfile=f"bundled/{page_type.value}.md",
        tofile=f"user/{page_type.value}.md",
    )
    has_changes = False
    for line in diff:
        has_changes = True
        sys.stdout.write(line)
    if not has_changes:
        print("(user override is identical to bundled)")


def cmd_wiki_templates_upgrade(args: argparse.Namespace) -> None:
    """Overwrite user override with current bundled content.

    Modes:
      --force          : overwrite unconditionally
      --if-unmodified  : only overwrite if user file hash matches the
                         sha256 recorded in state file at install time
                         (i.e. user never modified it after install)

    Without either flag, refuse and instruct user to use --force or
    --if-unmodified. This is the Bug 6 fix: never silently overwrite
    a modified user override.
    """
    from ..wiki.templates.state import State, compute_sha256
    from ..wiki.templates.types import BUNDLED_DIR

    type_name = args.type
    try:
        page_type = PageType(type_name)
    except ValueError:
        valid = ", ".join(pt.value for pt in PageType)
        print(f"Unknown type {type_name!r}. Valid: {valid}", file=sys.stderr)
        sys.exit(2)

    if not args.force and not args.if_unmodified:
        print(
            f"Refusing to overwrite user override without --force or "
            "--if-unmodified.\n"
            f"  Use `wiki-templates diff {type_name}` to see what would change.",
            file=sys.stderr,
        )
        sys.exit(2)

    user_path = _USER_DIR / f"{page_type.value}.md"
    bundled_path = BUNDLED_DIR / f"{page_type.value}.md"

    if not bundled_path.is_file():
        print(f"Bundled template missing: {bundled_path}", file=sys.stderr)
        sys.exit(2)

    bundled_text = bundled_path.read_text(encoding="utf-8")
    bundled_sha = compute_sha256(bundled_path)

    if args.if_unmodified:
        if not user_path.is_file():
            print(f"No user override to upgrade: {user_path}", file=sys.stderr)
            sys.exit(1)
        # Compare against recorded installed_sha256; missing → treat
        # as modified (don't silently overwrite).
        state = State.load()
        prev = state.bundled.get(page_type.value)
        if prev is None:
            print(
                "State file has no recorded sha256 for this type — cannot "
                "verify 'unmodified'. Re-run with --force.",
                file=sys.stderr,
            )
            sys.exit(2)
        user_sha = compute_sha256(user_path)
        if user_sha != prev.sha256:
            print(
                f"User override at {user_path} has been modified since the "
                "last recorded state (sha256 mismatch). Use --force to "
                "overwrite, or edit manually.",
                file=sys.stderr,
            )
            sys.exit(2)

    # Back up + overwrite
    if user_path.is_file():
        backup = user_path.with_suffix(user_path.suffix + ".bak")
        shutil.copy2(user_path, backup)
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(bundled_text, encoding="utf-8")

    print(f"Upgraded: {user_path}")
    if user_path.with_suffix(user_path.suffix + ".bak").is_file():
        print(f"Backup:   {user_path.with_suffix(user_path.suffix + '.bak')}")
    print(f"New sha:  {bundled_sha[:16]}…")
    print("Next resolve() will use this user override.")
