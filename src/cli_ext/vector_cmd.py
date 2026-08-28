"""`vector` CLI subcommand — R7 vector-pending compensation.

- ``ruflo vector status --project <id>`` — show the pending ledger.
- ``ruflo vector reconcile --project <id>`` — re-index pending pages
  (needs an embedding provider); clears entries that succeed.

The ledger lives at ``.index/vector_pending.json``; wiki pages are the
source of truth, vectors are derived. This command makes the derived
state catch up when an earlier upsert failed.
"""
from __future__ import annotations

import argparse
import sys

from ..lib.project import resolve_project
from ..vector.pending import list_pending, reconcile_pending


def cmd_vector_status(args: argparse.Namespace) -> None:
    """Show pending vector entries for a project."""
    ctx, paths = resolve_project(args.project, by_id_only=True)
    data = list_pending(paths)
    if not data:
        print("No pending vector entries.")
        return
    intent_count = sum(
        1 for meta in data.values()
        if meta.get("publication_state", "pending") == "intent"
    )
    pending_count = len(data) - intent_count
    print(
        f"{len(data)} pending vector entr(ies): "
        f"intent={intent_count}, pending={pending_count}"
    )
    for pid, meta in sorted(data.items()):
        print(f"  {pid}  hash={meta.get('hash', '')[:8]}  "
              f"ts={meta.get('ts', '')}  title={meta.get('title', '')}")


def cmd_vector_reconcile(args: argparse.Namespace) -> None:
    """Re-index pending pages; clear entries that succeed (idempotent)."""
    import asyncio

    ctx, paths = resolve_project(args.project, by_id_only=True)

    def _embed_and_upsert(page, paths, table=None) -> bool:
        """Chunk/embed/upsert one page; return True on success."""
        from src.llm.embedding_runtime import get_embedding_provider
        from src.types import VectorChunk
        from src.utils.path import normalize_source_path
        from src.utils.text import chunk_markdown
        from src.vector.store import init_vector_store_for_paths
        from src.vector.upsert import vector_upsert_chunks
        from datetime import datetime, timezone

        content = (page.body or "").strip()
        if not content:
            return True  # nothing to index
        init_vector_store_for_paths(paths)
        provider = get_embedding_provider()
        if provider is None:
            print("  no embedding provider configured; cannot reconcile",
                  file=sys.stderr)
            return False
        chunks = chunk_markdown(content)
        if not chunks:
            return True
        results = asyncio.run(provider.embed(chunks))
        if results and hasattr(results[0], "embedding"):
            embeddings = [e.embedding for e in results]
        else:
            embeddings = list(results)
        if not embeddings or len(embeddings) != len(chunks):
            return False
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        lance_chunks = [
            VectorChunk(
                id=f"{page.id}-chunk-{i}",
                task_id=page.id,
                content=chunk,
                embedding=embeddings[i],
                path=normalize_source_path(page.id, paths.root),
                updated_at=now,
            )
            for i, chunk in enumerate(chunks)
        ]
        vector_upsert_chunks(lance_chunks)
        return True

    result = reconcile_pending(paths, _embed_and_upsert)
    print(f"Reconciled {result['attempted']} pending entr(ies): "
          f"{result['ok']} ok, {result['failed']} failed "
          f"(intent={result.get('intent', 0)}, "
          f"pending={result.get('pending', 0)}, "
          f"recovered={result.get('recovered', 0)}, "
          f"orphaned={result.get('orphaned', 0)})")
    if result["failed_ids"]:
        print("Failed (will retry on next reconcile / startup):")
        for pid in result["failed_ids"]:
            print(f"  {pid}")
        sys.exit(1)


def add_vector_parser(subparsers) -> None:
    """Register the ``vector`` subcommand tree."""
    p = subparsers.add_parser("vector", help="Vector-pending compensation (R7)")
    p_sub = p.add_subparsers(dest="vector_command", required=True)

    p_status = p_sub.add_parser("status", help="Show pending vector entries")
    p_status.add_argument("--project", required=True)
    p_status.set_defaults(func=cmd_vector_status)

    p_rec = p_sub.add_parser("reconcile", help="Re-index pending pages")
    p_rec.add_argument("--project", required=True)
    p_rec.set_defaults(func=cmd_vector_reconcile)
