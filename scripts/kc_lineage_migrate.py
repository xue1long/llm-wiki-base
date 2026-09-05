"""Migrate deterministic raw identities into the project-local lineage DB."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.lineage import LineageStore


def migrate(project_root: Path, *, apply: bool = False) -> dict:
    root = Path(project_root)
    db = root / ".index" / "lineage" / "state.db"
    store = LineageStore.open(root)
    scan = store.discover_raw_sources()
    report = {
        "project_root": str(root),
        "dry_run": not apply,
        "scan_complete": scan.complete,
        "discovered": [change.__dict__ for change in scan.changes],
        "legacy_unverified": [],
    }
    legacy_state = root / ".index" / "batch_build_state.json"
    if legacy_state.exists():
        report["legacy_unverified"].append("batch_build_state_present")
    if not scan.complete:
        report["legacy_unverified"].append("raw_scan_incomplete")
    if apply and db.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = db.with_name(f"state.db.backup-{stamp}")
        shutil.copy2(db, backup)
        report["backup"] = str(backup)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = migrate(args.project_root, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["scan_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
