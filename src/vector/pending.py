"""R7 — vector-pending compensation ledger (Wiki written, vectors missing).

Audit A-02/A-04 related: the wiki is the source of truth and LanceDB is
derived, but there was no explicit sync state — a page written to disk
whose vector upsert failed left search silently missing the page.

Design (architecture-remediation R7, plan-audit hardening):
- ``mark_intent(paths, pages)`` records a pre-commit publication intent;
  ``promote_intent`` changes it to ``pending`` after the Wiki commit.
- ``mark_pending(paths, pages)`` remains the compatibility entry point for
  already-committed pages.
- ``clear_pending(paths, page_ids)`` removes entries after a successful
  upsert.
- ``reconcile_pending(paths)`` re-upserts pending pages whose body hash
  changed OR that are still missing from the vector table; on success the
  entries are cleared. Idempotent.
- ``scan_wiki_vector_diff(paths)`` (startup fallback) compares wiki pages
  against the vector table and (re)marks missing ones — the final safety
  net when a crash happened between wiki commit and pending write.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from ..lib.write_hooks import safe_write
from ..wiki.core.paths import WikiPaths

_logger = logging.getLogger(__name__)
_READY_KEY = "__ready__"


def pending_path(paths: WikiPaths) -> Path:
    """Path of the vector-pending ledger (``.index/vector_pending.json``)."""
    return paths.index / "vector_pending.json"


def _load(paths: WikiPaths) -> dict:
    p = pending_path(paths)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("vector pending ledger is unreadable") from exc
    if not isinstance(data, dict):
        raise ValueError("vector pending ledger must contain an object")
    return data


def _save(paths: WikiPaths, data: dict) -> None:
    p = pending_path(paths)
    p.parent.mkdir(parents=True, exist_ok=True)
    safe_write(p, json.dumps(data, indent=2, ensure_ascii=False))


def _pending_entries(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != _READY_KEY}


def _ready_pages(data: dict) -> dict:
    ready = data.get(_READY_KEY, {})
    pages = ready.get("pages", {}) if isinstance(ready, dict) else {}
    return pages if isinstance(pages, dict) else {}


def body_hash(body: str) -> str:
    """Stable hash of a page body (used to detect content changes)."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _page_entry(page, publication_state: str) -> dict:
    page_hash = body_hash(page.body or "")
    return {
        "hash": page_hash,
        "page_content_hash": page_hash,
        "vector_content_hash": None,
        "embedding_model": None,
        "ts": int(time.time()),
        "title": getattr(page, "title", "") or page.id,
        "publication_state": publication_state,
        "status": publication_state,
    }


def mark_intent(paths: WikiPaths, pages: list) -> int:
    """Record publication intent before the Wiki batch is written."""
    data = _load(paths)
    for page in pages:
        data[page.id] = _page_entry(page, "intent")
        _ready_pages(data).pop(page.id, None)
    _save(paths, data)
    return len(pages)


def promote_intent(paths: WikiPaths, page_ids: list[str]) -> int:
    """Mark intents as pending after their Wiki batch commits."""
    data = _load(paths)
    promoted = 0
    for page_id in page_ids:
        entry = data.get(page_id)
        if entry is not None and entry.get("publication_state", "pending") == "intent":
            entry["publication_state"] = "pending"
            promoted += 1
    if promoted:
        _save(paths, data)
    return promoted


def mark_pending(paths: WikiPaths, pages: list) -> int:
    """Record pages needing vector indexing (wiki already committed).

    Stores ``{page_id: {hash, ts, title}}``. Called right after the wiki
    batch commit; a later successful upsert clears the entry.
    """
    data = _load(paths)
    for page in pages:
        data[page.id] = _page_entry(page, "pending")
        _ready_pages(data).pop(page.id, None)
    _save(paths, data)
    return len(pages)


def clear_pending(paths: WikiPaths, page_ids: list[str]) -> int:
    """Remove entries after a successful vector upsert."""
    data = _load(paths)
    cleared = 0
    for pid in page_ids:
        if pid in data:
            del data[pid]
            cleared += 1
    if cleared:
        _save(paths, data)
    return cleared


def list_pending(paths: WikiPaths) -> dict:
    """Return the pending ledger (page_id → metadata)."""
    return _pending_entries(_load(paths))


def _find_page_file(paths: WikiPaths, page_id: str) -> Path | None:
    """Locate a wiki page file by id under ``wiki/`` (excluding metadata)."""
    for p in paths.wiki.rglob("*.md"):
        if p.name == "index.md" or p.name == "log.md":
            continue
        if p.stem == page_id or p.stem.startswith(page_id + "-"):
            return p
    return None


def _iter_wiki_pages(paths: WikiPaths):
    """Yield every wiki page file (excluding index.md / log.md)."""
    from ..wiki.storage.page_writer import read_page
    for p in sorted(paths.wiki.rglob("*.md")):
        if p.name in ("index.md", "log.md"):
            continue
        try:
            yield read_page(p)
        except Exception:
            continue


def reconcile_pending(
    paths: WikiPaths,
    embed_and_upsert,
    table=None,
) -> dict:
    """Re-index pending pages; clear entries that succeed.

    ``embed_and_upsert(page, paths, table)`` must chunk/embed/upsert one
    page and return True on success. Pages whose body hash changed since
    marking are re-upserted (the stored hash is refreshed on success).
    Idempotent: success clears the entry, failure keeps it.
    """
    from ..wiki.storage.page_writer import read_page

    data = _load(paths)
    entries = _pending_entries(data)
    if not entries:
        return {
            "attempted": 0,
            "ok": 0,
            "failed": 0,
            "failed_ids": [],
            "intent": 0,
            "pending": 0,
            "recovered": 0,
            "orphaned": 0,
        }

    attempted = 0
    ok_ids: list[str] = []
    failed_ids: list[str] = []
    orphaned = 0
    recovered = 0
    intent_count = 0
    pending_count = 0

    changed = False
    for pid, meta in list(entries.items()):
        attempted += 1
        state = meta.get("publication_state", "pending")
        if state == "intent":
            intent_count += 1
        else:
            pending_count += 1
        try:
            f = _find_page_file(paths, pid)
            if f is None:
                if state == "intent":
                    # The Wiki batch never committed; discard the orphaned
                    # pre-commit intent without hiding a committed page.
                    del data[pid]
                    orphaned += 1
                else:
                    # Preserve the existing pending deletion behavior.
                    failed_ids.append(pid)
                continue
            page = read_page(f)
            if body_hash(page.body or "") != meta.get("hash"):
                _logger.info("[vector-pending] %s changed since mark; re-indexing", pid)
            success = embed_and_upsert(page, paths, table)
            if isinstance(success, dict):
                ok = success.get("status", "ok") == "ok"
                vector_hash = success.get("vector_content_hash")
                model = success.get("embedding_model")
                failure_status = success.get("status", "failed")
            else:
                ok = bool(success)
                vector_hash = body_hash(page.body or "") if ok else None
                model = meta.get("embedding_model")
                failure_status = "failed"
            if ok:
                ok_ids.append(pid)
                meta["page_content_hash"] = body_hash(page.body or "")
                meta["vector_content_hash"] = vector_hash
                meta["embedding_model"] = model
                ready = data.setdefault(_READY_KEY, {"pages": {}})
                ready.setdefault("pages", {})[pid] = {
                    "page_content_hash": meta["page_content_hash"],
                    "vector_content_hash": vector_hash,
                    "embedding_model": model,
                }
                changed = True
                if state == "intent":
                    recovered += 1
            else:
                meta["status"] = failure_status
                changed = True
                failed_ids.append(pid)
        except Exception as e:
            meta["status"] = "failed"
            changed = True
            _logger.warning("[vector-pending] reconcile failed for %s: %s", pid, e)
            failed_ids.append(pid)

    if orphaned:
        changed = True
    if changed:
        _save(paths, data)
    clear_pending(paths, ok_ids)
    # Refresh hashes for re-indexed-but-failed pages is not done (they
    # stay pending with the old hash so a later retry re-checks).
    return {
        "attempted": attempted,
        "ok": len(ok_ids),
        "failed": len(failed_ids),
        "failed_ids": failed_ids,
        "intent": intent_count,
        "pending": pending_count,
        "recovered": recovered,
        "orphaned": orphaned,
    }


def readiness(paths: WikiPaths, embedding_model: str | None = None) -> dict:
    """Return a conservative, explainable Wiki/Vector readiness result."""
    data = _load(paths)
    entries = _pending_entries(data)
    states = {meta.get("status", meta.get("publication_state", "pending")) for meta in entries.values()}
    if "failed" in states:
        reason = "failed"
    elif "unavailable" in states:
        reason = "unavailable"
    elif entries:
        reason = "pending"
    else:
        reason = "ready"

    ready_pages = _ready_pages(data)
    if not ready_pages and not entries:
        reason = "unavailable"
    if reason == "ready":
        if not embedding_model:
            reason = "embedding_model"
        else:
            for metadata in ready_pages.values():
                if (
                    metadata.get("embedding_model") != embedding_model
                    or not metadata.get("page_content_hash")
                    or metadata.get("page_content_hash") != metadata.get("vector_content_hash")
                ):
                    reason = "embedding_model" if metadata.get("embedding_model") != embedding_model else "hash_mismatch"
                    break
    if reason == "ready":
        for page in _iter_wiki_pages(paths):
            metadata = ready_pages.get(page.id)
            if metadata is None:
                reason = "page_unpublished"
                break
            if body_hash(page.body or "") != metadata.get("page_content_hash"):
                reason = "hash_mismatch"
                break

    return {
        "ready": reason == "ready",
        "reason": reason,
        "pending": sum(1 for meta in entries.values() if meta.get("status", meta.get("publication_state")) in {"intent", "pending"}),
        "failed": sum(1 for meta in entries.values() if meta.get("status") == "failed"),
        "embedding_model": embedding_model,
    }


def scan_wiki_vector_diff(
    paths: WikiPaths,
    table,
    page_ids_in_table: list[str],
) -> int:
    """Mark wiki pages missing from the vector table as pending (startup).

    ``page_ids_in_table`` is the set of page ids currently indexed.
    Returns the number of newly-marked pages. This is the crash-recovery
    safety net: it runs at startup / CLI health and re-marks anything the
    wiki has that the vector store lacks.
    """
    existing = set(page_ids_in_table)
    existing.update(
        value.rsplit("-chunk-", 1)[0]
        for value in page_ids_in_table
        if "-chunk-" in value
    )
    data = _load(paths)
    added = 0

    for page in _iter_wiki_pages(paths):
        if page.id in existing or page.id in data:
            continue
        data[page.id] = _page_entry(page, "pending")
        added += 1

    if added:
        _save(paths, data)
    return added
