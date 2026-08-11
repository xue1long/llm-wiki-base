"""Migrate wiki page frontmatter timestamps from int ms to YYYY-MM-DD strings.

Usage:
    python scripts/migrate_timestamps_to_date.py <project_path>
    python scripts/migrate_timestamps_to_date.py --dry-run <project_path>

What it does:
    Scans all wiki/ subdirectories (sources, entities, concepts, synthesis,
    _stubs, _archive) and converts frontmatter fields:
      created_at, updated_at, last_used_at, zombie_since
    from int ms timestamps (or 0 / None) to YYYY-MM-DD strings (or "").

    Leaves already-string values untouched.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


# Fields to migrate from int ms → str date
_DATE_FIELDS = {"created_at", "updated_at", "last_used_at", "zombie_since"}

# Wiki subdirectories that contain .md page files
_WIKI_DIRS = ["sources", "entities", "concepts", "synthesis", "_stubs", "_archive"]


def _ms_to_date(val: int) -> str:
    """Convert unix ms timestamp to YYYY-MM-DD. Returns '' for 0/None."""
    if not val:
        return ""
    try:
        return datetime.fromtimestamp(val / 1000).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return ""


def _migrate_frontmatter(fm: dict) -> bool:
    """Mutate frontmatter dict in-place. Returns True if any field changed."""
    changed = False
    for key in _DATE_FIELDS:
        raw = fm.get(key)
        if raw is None:
            fm[key] = ""
            changed = True
            continue
        if isinstance(raw, (int, float)):
            new_val = _ms_to_date(int(raw))
            if raw != 0:
                print(f"  [{key}] {raw} → {new_val!r}")
            fm[key] = new_val
            changed = True
            continue
        # already a string → leave it
    return changed


def _migrate_file(path: Path, dry_run: bool) -> bool:
    """Migrate a single .md file. Returns True if changed."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  SKIP {path.name}: {e}", file=sys.stderr)
        return False

    if not text.startswith("---\n"):
        return False

    # Find frontmatter boundaries
    end = text.find("\n---", 4)
    if end < 0:
        return False

    fm_text = text[4:end]
    body = text[end + 5:]

    # Parse YAML frontmatter with the safe yaml loader
    # (ruflo-kb uses pyyaml which is already installed)
    try:
        import yaml
        fm = yaml.safe_load(fm_text) or {}
    except Exception as e:
        print(f"  SKIP {path.name}: YAML parse error: {e}", file=sys.stderr)
        return False

    if not isinstance(fm, dict):
        return False

    if not _migrate_frontmatter(fm):
        return False

    if dry_run:
        return True

    # Re-dump frontmatter (preserving order and unicode)
    fm_text_new = yaml.dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    # pyyaml adds trailing newline; strip to one newline before ---
    fm_text_new = fm_text_new.rstrip("\n")
    new_text = f"---\n{fm_text_new}\n---\n\n{body}"
    path.write_text(new_text, encoding="utf-8")
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(f"Usage: python {sys.argv[0]} [--dry-run] <project_path>")
        sys.exit(1)

    root = Path(args[0]).resolve()
    wiki_dir = root / "wiki"
    if not wiki_dir.is_dir():
        print(f"ERROR: {wiki_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    total = 0
    changed = 0
    for sub in _WIKI_DIRS:
        subdir = wiki_dir / sub
        if not subdir.is_dir():
            continue
        for f in sorted(subdir.glob("*.md")):
            total += 1
            if _migrate_file(f, dry_run):
                changed += 1
                if not dry_run:
                    print(f"  OK {sub}/{f.name}")

    print(f"\n{'Dry-run: ' if dry_run else ''}{changed} of {total} files changed.")


if __name__ == "__main__":
    main()