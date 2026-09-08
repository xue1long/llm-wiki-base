"""Migrate deterministic raw identities into the project-local lineage DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.lineage import LineageStore


def _preview_raw_scan(root: Path, db: Path) -> tuple[bool, tuple[dict, ...], set[str]]:
    raw_root = root / "raw" / "sources"
    if not raw_root.is_dir():
        return False, (), set()
    known: dict[str, tuple[str, str]] = {}
    if db.exists():
        try:
            with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as connection:
                known = {
                    str(path): (str(source_id), str(source_hash))
                    for source_id, path, source_hash in connection.execute(
                        "SELECT source_id, source_path, source_hash FROM sources"
                    )
                }
        except sqlite3.Error:
            known = {}
    changes: list[dict] = []
    paths: set[str] = set()
    for path in sorted(item for item in raw_root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        paths.add(rel)
        previous = known.get(rel)
        if previous is None:
            changes.append({
                "source_id": "src-" + hashlib.sha256(rel.encode()).hexdigest()[:32],
                "source_path": rel,
                "source_hash": digest,
                "status": "discovered",
            })
        elif previous[1] != digest:
            changes.append({
                "source_id": previous[0],
                "source_path": rel,
                "source_hash": digest,
                "status": "stale",
            })
    return True, tuple(changes), paths


def migrate(project_root: Path, *, apply: bool = False) -> dict:
    root = Path(project_root)
    db = root / ".index" / "lineage" / "state.db"
    backup = None
    if apply and db.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = db.with_name(f"state.db.backup-{stamp}")
        shutil.copy2(db, backup)
    store = LineageStore.open(root) if apply else None
    if store is None:
        scan_complete, discovered, raw_paths = _preview_raw_scan(root, db)
    else:
        scan = store.discover_raw_sources()
        scan_complete = scan.complete
        discovered = tuple(change.__dict__ for change in scan.changes)
        raw_paths = {str(item["source_path"]) for item in store.sources()}
    report = {
        "project_root": str(root),
        "dry_run": not apply,
        "scan_complete": scan_complete,
        "discovered": list(discovered),
        "legacy_unverified": [],
    }
    legacy_state = root / ".index" / "batch_build_state.json"
    if legacy_state.exists():
        report["legacy_unverified"].append("batch_build_state_present")
        try:
            legacy = json.loads(legacy_state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            legacy = {}
        migrated = 0
        for batch in legacy.values() if isinstance(legacy, dict) else ():
            if not isinstance(batch, dict):
                continue
            for raw_path, entry in (batch.get("raw_states", {}) or {}).items():
                normalized_path = str(raw_path).replace("\\", "/")
                source_id = (
                    store.source_id_for_path(normalized_path)
                    if store is not None else
                    "src-" + hashlib.sha256(normalized_path.encode()).hexdigest()[:32]
                    if normalized_path in raw_paths else None
                )
                if source_id is None:
                    report["legacy_unverified"].append(f"unmapped:{raw_path}")
                    continue
                legacy_status = entry.get("status") if isinstance(entry, dict) else None
                mapped_status = {"done": "ingested", "failed": "failed",
                                 "permanent_failed": "blocked"}.get(legacy_status)
                if mapped_status:
                    if store is not None:
                        store.record_raw_assessment(
                            source_id, mapped_status,
                            (f"legacy_batch_status:{legacy_status}",),
                        )
                    migrated += 1
        report["legacy_migrated"] = migrated
    if not scan_complete:
        report["legacy_unverified"].append("raw_scan_incomplete")
    if backup is not None:
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
