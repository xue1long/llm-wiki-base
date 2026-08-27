"""CLI: Run Core backup drill (Z-5, spec §17 D-22).

Standalone executable that exercises the snapshot → restore → verify drill
defined in ``src/kc.backup.drill``. Provides a thin argparse wrapper around
``run_drill`` + ``write_drill_report`` for ops / acceptance-gate usage.

Usage::

    python -m scripts.kc_core_backup_drill \
        --project-root ./sandbox/proj_drill \
        --snapshot-id snap_1756000000000 \
        --objects '[{"id":"ko-1","type":"claim","title":"A","content":"x", ...}]'

The ``--objects`` argument is a JSON list of KnowledgeObject dicts OR a path
to a JSON file prefixed with ``@`` (e.g. ``@./objs.json``). Use snapshot-less
mode via ``--no-snapshot`` to exercise only the restore/verify half.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add repo root to sys.path so 'from src.xxx import ...' resolves when invoked
# as a bare script (python scripts/kc_core_backup_drill.py ...).
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.kc.backup.core_snapshot import create_snapshot  # noqa: E402
from src.kc.backup.drill import run_drill, write_drill_report  # noqa: E402
from src.knowledge.core.version_manager import _deserialize_object  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.storage.ensure import ensure_knowledge_base  # noqa: E402


def _parse_objects(arg: str) -> list:
    """Parse ``--objects`` JSON list (or ``@file`` reference) into KOs.

    Uses the canonical ``_deserialize_object`` from ``version_manager`` (the same
    helper ``create_snapshot`` writes to disk) so the CLI round-trip stays in
    sync with the snapshot format.
    """
    if arg.startswith("@"):
        file_path = Path(arg[1:])
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(arg)
    return [_deserialize_object(item) for item in payload]


def main() -> int:
    parser = argparse.ArgumentParser(description="Core backup drill (Z-5, spec §17 D-22)")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--snapshot-id",
        type=str,
        default=None,
        help="Existing snapshot id to drill against (skips create_snapshot).",
    )
    parser.add_argument(
        "--objects",
        type=str,
        required=True,
        help="JSON list of KnowledgeObject dicts, or @file.json reference.",
    )
    args = parser.parse_args()

    paths = WikiPaths(args.project_root)
    # Ensure the project layout exists (matches C-0.5a semantics).
    ensure_knowledge_base(args.project_root)

    caller_objects = _parse_objects(args.objects)

    snapshot_id = args.snapshot_id
    if snapshot_id is None:
        # Convenience: caller didn't supply a snapshot — create one now.
        snap = create_snapshot(paths, objects=caller_objects)
        snapshot_id = snap.snapshot_id

    report = run_drill(paths, caller_objects, snapshot_id=snapshot_id)
    log_path = write_drill_report(paths, report)

    print(  # noqa: T201 — CLI output
        json.dumps(
            {
                "drill_id": report.drill_id,
                "snapshot_id": report.snapshot_id,
                "drill_status": report.drill_status,
                "before_ko_count": report.before_ko_count,
                "after_ko_count": report.after_ko_count,
                "identity_key_consistency": report.identity_key_consistency,
                "log_path": str(log_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    return 0 if report.drill_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
