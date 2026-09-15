"""D8: review queue CLI for v7_extract failures.

Lists / resolves / shows stats for items in the shared
``.index/reviews_queue.json`` (the same file the Generator pipeline
uses). v7 failures carry ``source="v7_extract"`` — the ``--source``
filter lets operators see only the v7 backlog.

Usage:
    python scripts/review_queue_cli.py list --open
    python scripts/review_queue_cli.py list --source=v7_extract
    python scripts/review_queue_cli.py resolve <item_id> --action=promoted
    python scripts/review_queue_cli.py stats
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_QUEUE_PATH = Path(".index") / "reviews_queue.json"


def _read_queue(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    return [dict(it) for it in items if isinstance(it, dict)]


def _write_queue(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def cmd_list(args: argparse.Namespace) -> int:
    items = _read_queue(args.queue_path)
    if args.source:
        items = [it for it in items if it.get("source") == args.source]
    if args.open:
        items = [it for it in items if not it.get("resolved_at")]
    if not args.json:
        if not items:
            print("(empty)")
            return 0
        for item in items:
            print(f"- {item.get('id')}  source={item.get('source') or '?'}  "
                  f"stage={item.get('failure_stage') or '?'}  reason={item.get('reason')}")
        return 0
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    items = _read_queue(args.queue_path)
    for it in items:
        if it.get("id") == args.item_id:
            it["resolved_at"] = int(time.time() * 1000)
            it["resolution"] = args.action
            _write_queue(args.queue_path, items)
            print(f"resolved {args.item_id} → {args.action}")
            return 0
    print(f"item {args.item_id} not found", file=sys.stderr)
    return 1


def cmd_stats(args: argparse.Namespace) -> int:
    items = _read_queue(args.queue_path)
    by_source: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    open_count = 0
    for it in items:
        src = it.get("source") or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
        stage = it.get("failure_stage") or "unknown"
        by_stage[stage] = by_stage.get(stage, 0) + 1
        if not it.get("resolved_at"):
            open_count += 1
    print(f"Total: {len(items)}  Open: {open_count}")
    print(f"By source: {by_source}")
    print(f"By stage:  {by_stage}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v7 review queue CLI")
    parser.add_argument(
        "--queue-path", default=str(DEFAULT_QUEUE_PATH),
        help="path to reviews_queue.json (default: .index/reviews_queue.json)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="list items")
    list_p.add_argument("--open", action="store_true",
                        help="only show unresolved items")
    list_p.add_argument("--all", action="store_true",
                        help="alias: show all items (default)")
    list_p.add_argument("--source", default=None,
                        help="filter by source (e.g. v7_extract)")
    list_p.add_argument("--json", action="store_true",
                        help="emit full JSON output")

    resolve_p = sub.add_parser("resolve", help="resolve an item")
    resolve_p.add_argument("item_id")
    resolve_p.add_argument(
        "--action", required=True,
        choices=["promoted", "discarded", "retry"],
    )

    stats_p = sub.add_parser("stats", help="show counts")

    args = parser.parse_args(argv)
    args.queue_path = Path(args.queue_path)

    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "resolve":
        return cmd_resolve(args)
    if args.cmd == "stats":
        return cmd_stats(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
