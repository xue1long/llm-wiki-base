#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrate LanceDB vector-row ``path`` values to project-relative form.

Why (cross-device fix): vector rows previously stored ABSOLUTE paths, so a
project copied between devices (OneDrive -> D:) left stale rows pointing at
the old root. Stale rows made ``librarian._merge_duplicates`` fail archiving.

What it does (idempotent, ZERO embedding API calls):
  1. Build ``{task_id: rel_path}`` from every wiki note under
     wiki/{sources,concepts,entities,synthesis} — task_id is the
     content-derived ``kb-arch-<sha256[:12]>`` the archive writer uses.
  2. Scan the ``chunks`` table. For each ``kb-arch-`` row:
       * task_id matches a note  -> rewrite ``path`` to the note's
         project-relative path (embedding preserved).
       * no match                -> delete the row (stale content).
       * other task_id prefix    -> skip untouched.
  3. Rebuild ``.index/batch_build_state.json`` ``archived`` from the ground
     truth (matched note + its digest) so unchanged notes are SKIPPED by the
     next ``batch_build --only archive`` instead of being re-embedded.

Usage:
    python scripts/migrate_vector_paths.py --root knowledge/novel-wiki
    python scripts/migrate_vector_paths.py --root knowledge/novel-wiki --dry-run

Note: ``table.update(values=...)`` stores plain strings as literals (LanceDB
0.27.1) — do NOT add quotes to the value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.utils.path import migrate_state_paths, normalize_source_path, safe_resolve
from src.wiki.core.paths import WikiPaths

TASK_ID_PREFIX = "kb-arch-"
NOTE_DIRS = ["sources", "concepts", "entities", "synthesis"]


def task_id_for_digest(digest: str) -> str:
    """The archive task_id for a note with content sha256 ``digest``."""
    return f"{TASK_ID_PREFIX}{digest[:12]}"


def migration_action(task_id: str, index: dict[str, str]):
    """Decide what to do with a vector row given its ``task_id``.

    Returns ``("rewrite", rel_path)`` when the row matches a current note,
    ``("delete", None)`` for a stale ``kb-arch-`` row with no matching note,
    ``("skip", None)`` for rows whose task_id is not ``kb-arch-`` prefixed
    (never touch those — deleting them would lose legitimate data).
    """
    if not task_id.startswith(TASK_ID_PREFIX):
        return "skip", None
    rel = index.get(task_id)
    if rel is None:
        return "delete", None
    return "rewrite", rel


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build_index(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(task_id -> rel_path, rel_path -> digest)`` for all wiki notes."""
    paths = WikiPaths(root)
    tid_to_rel: dict[str, str] = {}
    rel_to_digest: dict[str, str] = {}
    for sub in NOTE_DIRS:
        d = paths.wiki / sub
        if not d.is_dir():
            continue
        for note in sorted(d.rglob("*.md")):
            if note.name in {"index.md", "log.md"}:
                continue
            digest = sha256_file(note)
            tid = task_id_for_digest(digest)
            rel = normalize_source_path(str(note), paths.root)
            tid_to_rel[tid] = rel
            rel_to_digest[rel] = digest
    return tid_to_rel, rel_to_digest


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"ingested": {}, "archived": {}, "failed": {}}


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def rebuild_archived_state(
    state: dict,
    matched_tids: set[str],
    tid_to_rel: dict[str, str],
    rel_to_digest: dict[str, str],
    root: Path,
) -> dict:
    """Mark every note whose vector row exists as archived (ground truth)."""
    state = migrate_state_paths(state, root)
    archived = state.setdefault("archived", {})
    failed = state.setdefault("failed", {})
    for tid in matched_tids:
        rel = tid_to_rel[tid]
        archived[rel] = rel_to_digest[rel]
        failed.pop(rel, None)
    return state


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Migrate LanceDB vector-row paths to project-relative form (cross-device)."
    )
    ap.add_argument("--root", default=None, help="Project root (default: CWD)")
    ap.add_argument("--dry-run", action="store_true", help="Report only; make no changes")
    args = ap.parse_args()

    from src.vector.store import get_table, init_vector_store_for_paths
    from src.vector.upsert import _escape_sql_string_literal

    root = safe_resolve(args.root) if args.root else safe_resolve(Path.cwd())
    paths = WikiPaths(root)
    init_vector_store_for_paths(paths)
    table = get_table(paths)

    tid_to_rel, rel_to_digest = build_index(root)
    index = tid_to_rel
    print(f"[migrate] indexed {len(index)} notes under {root}")

    rows = table.to_arrow().to_pylist()
    rewrite: dict[str, str] = {}   # task_id -> rel_path (update once per task_id)
    delete: set[str] = set()       # task_id -> delete once
    seen_tids: set[str] = set()
    skip = unchanged = 0
    for r in rows:
        tid = r["task_id"]
        seen_tids.add(tid)
        action, rel = migration_action(tid, index)
        if action == "skip":
            skip += 1
        elif action == "delete":
            delete.add(tid)
        else:  # rewrite
            if r["path"] == rel:
                unchanged += 1
            else:
                rewrite[tid] = rel

    print(
        f"[migrate] rows={len(rows)} rewrite={len(rewrite)} delete={len(delete)} "
        f"skip={skip} unchanged={unchanged}"
    )

    if args.dry_run:
        print("[migrate] dry-run — no changes made")
        return 0

    for tid, rel in rewrite.items():
        safe = _escape_sql_string_literal(tid)
        table.update(where=f"task_id = '{safe}'", values={"path": rel})
    for tid in delete:
        safe = _escape_sql_string_literal(tid)
        table.delete(f"task_id = '{safe}'")

    matched = seen_tids & set(index)
    state = rebuild_archived_state(
        _load_state(root / ".index" / "batch_build_state.json"),
        matched,
        tid_to_rel,
        rel_to_digest,
        root,
    )
    _save_state(root / ".index" / "batch_build_state.json", state)
    print(f"[migrate] rebuilt archived state for {len(matched)} matched task_ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
