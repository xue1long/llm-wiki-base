from __future__ import annotations

import json
import sys

from ..lib.project import resolve_project
from ..lineage import LineageStore
from ..project.context import ProjectNotFoundError


def _resolve(project: str | None):
    try:
        ctx, _ = resolve_project(project)
        return ctx
    except ProjectNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_lineage_health(args) -> int:
    ctx = _resolve(args.project)
    health = LineageStore.open(ctx.path).health()
    payload = health.__dict__ | {"ok": health.ok}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("healthy" if health.ok else "unhealthy")
        for key, value in payload.items():
            print(f"{key}: {value}")
    if not health.ok:
        raise SystemExit(1)
    return 0


def cmd_lineage_show(args) -> int:
    ctx = _resolve(args.project)
    store = LineageStore.open(ctx.path)
    payload = {"sources": list(store.sources()), "artifacts": list(store.artifacts()),
               "pending_outbox": [list(item) for item in store.pending_outbox()]}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(payload, ensure_ascii=False))
    return 0
