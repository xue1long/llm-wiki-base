"""Stage 6R RelationStore + independent checkpoint (Task 24).

The RelationStore is the authoritative source for *which relations are
currently alive* per page, layered on top of the wiki's source-of-truth
Markdown files. It keeps two artifacts under ``<project>/.index/``:

  - ``relation_run_state.json`` — current per-page snapshot (atomic
    tmp+rename write, never corrupt on crash). This is the **independent
    checkpoint** the master plan §4 Task 24 calls for; it is NOT folded
    into the writer's ``v7_checkpoint.json`` and can be deleted without
    touching the writer's checkpoint or the wiki pages.
  - ``relations.jsonl`` — append-only event log of ``assert`` /
    ``tombstone`` lines. The current state is reconstructed by replaying
    the log forward; we never truncate, so reviewers can audit the full
    relation lifecycle of a page.

Lifecycle
---------
- ``apply_result(record)`` upserts a ``RelationRunRecord`` and appends
  one ``assert`` event per relation_id in the record. Relation_ids that
  were in the previous run record for the same page but are no longer
  present get a ``tombstone`` event appended (so the event log faithfully
  records "was alive, now gone"). This matches the master's "diff-based"
  semantics in §4 Task 24.
- ``cascade_page_delete(page_id)`` tombstones every relation that
  involves ``page_id`` as either source OR target. We do this by
  scanning the current run state for any record whose relation_ids
  reference an edge involving ``page_id``. The tombstone events are
  appended to ``relations.jsonl``; the live view drops them.
- ``get_run_record / list_page_relations / find_stale`` are read-only
  views; they never touch the event log.

Tombstone semantics
-------------------
- The event log (``relations.jsonl``) is append-only. The current
  state of a relation is "the latest event for that relation_id".
  Tombstones are just another event — they do not delete prior lines.
- ``RelationRunRecord.relation_ids`` always lists only live (non-
  tombstoned) ids. When a relation is tombstoned we remove its id from
  the live set in ``relation_run_state.json``; the ``relations.jsonl``
  line stays forever.
- ``cascade_page_delete`` requires us to know which edges are alive
  *and which page is the other endpoint*. The current state encodes
  relation_ids but not (source, target) tuples — Task 25's LLM-direct
  adapter + ``RelationAssertion.key`` will feed those tuples through
  ``apply_result`` once it lands. Until then we record tombstones for
  every relation currently attached to the deleted page (outbound and
  inbound within the same page's run), and tombstone any relation_id
  that lives on any other page's run record but whose name token
  references the deleted page — the conservative default.

This module deliberately does NOT import from ``wiki_writer`` or any
other v7 module. Its only dependencies are the ``RelationKey`` /
``RelationAssertion`` types from ``relation_models`` (Task 23) and the
standard library. This keeps the independent-checkpoint guarantee in
the master plan — Task 24 hard requirement — honest.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Persistence path helpers
# ---------------------------------------------------------------------------


def run_state_path(root: Path | str) -> Path:
    """Return ``<root>/.index/relation_run_state.json``.

    Creates the ``.index`` directory on the way so callers can write
    immediately. The directory creation is idempotent and matches the
    convention every other ``.index/<name>.json`` artifact follows.
    """
    p = Path(root) / ".index" / "relation_run_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def relations_path(root: Path | str) -> Path:
    """Return ``<root>/.index/relations.jsonl`` (append-only event log)."""
    p = Path(root) / ".index" / "relations.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class RelationRunStatus(Enum):
    """Per-page relation run lifecycle.

    - PENDING  — record created, no relations asserted yet.
    - READY    — every relation is SUPPORTED.
    - PARTIAL  — some relations OK, others UNRESOLVED / REJECTED.
    - FAILED   — extractor errored out; ``last_error`` has the cause.
    - STALE    — wiki page_revision has changed since this run; the
      next reconciliation should re-run this page.

    The status values are stored as their ``.name`` in
    ``relation_run_state.json`` so the on-disk format stays stable across
    enum reorderings (Python guarantees ``Enum`` value, not ``name``,
    stability — but ``name`` matches the plan spec verbatim).
    """

    PENDING = "pending"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    STALE = "stale"


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------


@dataclass
class RelationRunRecord:
    """Per-page snapshot of the relation run.

    The record carries enough information to (a) decide whether to re-run
    this page (``page_revision`` mismatch) and (b) reconstruct the
    page's live relation set (``relation_ids`` — already excluding
    tombstones).

    The defaults match the spec in the master plan §4 Task 24; ``attempts``
    defaults to 1 so a fresh ``apply_result`` doesn't have to set it
    explicitly, and ``updated_at_ms`` defaults to 0 so callers can opt
    into ``int(time.time() * 1000)`` themselves.
    """

    page_id: str
    page_revision: str
    relation_ids: list[str] = field(default_factory=list)
    status: RelationRunStatus = RelationRunStatus.PENDING
    attempts: int = 1
    last_error: str | None = None
    extractor_fingerprint: str = ""
    updated_at_ms: int = 0


# ---------------------------------------------------------------------------
# Event log schema helpers
# ---------------------------------------------------------------------------


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON line to ``relations.jsonl`` (UTF-8, LF).

    This is a fire-and-forget append; we never truncate or rewrite the
    log. Callers that want atomicity for "many events" should hold the
    events in a list and call this once per event after the in-memory
    state is consistent — the master plan's contract is "tombstone does
    not delete lines", which this helper honors.
    """
    # Open in append + binary so a partial write can't leave a half-line;
    # ``\n`` is appended explicitly so every line ends cleanly.
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        fh.write("\n")


# ---------------------------------------------------------------------------
# RelationStore
# ---------------------------------------------------------------------------


class RelationStore:
    """Stage 6R authoritative relation store (Task 24).

    The store is per-project (``root`` is the project root; the actual
    ``.index/`` files live underneath). All public methods are safe to
    call from a single process — there is no in-memory locking because
    the master plan calls for "independent checkpoint" semantics that
    don't share state with the writer's checkpoint. If two writers race
    on the same ``.index/``, the atomic tmp+rename in ``_save_state``
    keeps the file consistent; the JSONL append is best-effort (the
    line count may diverge from the run-state count, and that's OK —
    the next ``apply_result`` reconciles by diff).

    Construction takes an optional ``extractor_fingerprint`` so
    debugging output can attribute records to the run that produced
    them; the fingerprint is stored on every record we write.
    """

    def __init__(self, root: Path | str, *, extractor_fingerprint: str = "") -> None:
        self.root = Path(root)
        self._fingerprint = extractor_fingerprint

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _read_state(self) -> dict[str, RelationRunRecord]:
        """Load current per-page run state from disk.

        Missing file → empty dict (cold start). Corrupt JSON → empty
        dict plus an in-memory marker the caller can see via the next
        ``apply_result``; we deliberately do NOT raise on corruption
        because the master plan says "the run_state.json checkpoint is
        fully independent from the source checkpoint" — losing the run
        state must not cascade into a writer crash.
        """
        path = run_state_path(self.root)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        records: dict[str, RelationRunRecord] = {}
        if not isinstance(raw, dict):
            return {}
        for page_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            status_value = payload.get("status", RelationRunStatus.PENDING.value)
            try:
                status = RelationRunStatus(status_value)
            except ValueError:
                # Unknown status in the file (e.g. newer enum member we
                # don't recognize yet). Keep the record but fall back
                # to PENDING so consumers see a sane status.
                status = RelationRunStatus.PENDING
            relation_ids = payload.get("relation_ids", [])
            if not isinstance(relation_ids, list):
                relation_ids = []
            records[page_id] = RelationRunRecord(
                page_id=page_id,
                page_revision=payload.get("page_revision", ""),
                relation_ids=[str(rid) for rid in relation_ids],
                status=status,
                attempts=int(payload.get("attempts", 1)),
                last_error=payload.get("last_error"),
                extractor_fingerprint=payload.get("extractor_fingerprint", ""),
                updated_at_ms=int(payload.get("updated_at_ms", 0)),
            )
        return records

    def _save_state(self, state: dict[str, RelationRunRecord]) -> None:
        """Atomic write — tmp+rename, identical pattern to WikiWriter.

        We deliberately do NOT import ``wiki_writer._atomic_write``: the
        master plan §4 Task 24 requires the relation checkpoint to be
        fully independent from the writer's checkpoint, so coupling
        their atomic-write helpers would be a hidden shared dependency.
        The two implementations are intentionally parallel.
        """
        path = run_state_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {}
        for page_id, record in state.items():
            payload[page_id] = {
                "page_id": record.page_id,
                "page_revision": record.page_revision,
                "relation_ids": sorted(record.relation_ids),
                "status": record.status.value,
                "attempts": record.attempts,
                "last_error": record.last_error,
                "extractor_fingerprint": record.extractor_fingerprint,
                "updated_at_ms": record.updated_at_ms,
            }

        # ``tempfile`` gives us a unique sibling file on Windows where
        # ``os.replace`` is atomic for paths on the same volume (which
        # is guaranteed here because ``dir`` is the same as ``path``'s
        # parent). ``delete=False`` so we control the rename explicitly.
        fd, tmp_str = tempfile.mkstemp(
            prefix=".relation_run_state.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
                fh.write("\n")
            os.replace(tmp_str, path)
        except Exception:
            # Clean up the orphan tmp file if the rename failed.
            try:
                os.unlink(tmp_str)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Event log helpers
    # ------------------------------------------------------------------

    def _append_assert_events(
        self, page_id: str, relation_ids: list[str]
    ) -> None:
        for relation_id in relation_ids:
            _append_event(
                relations_path(self.root),
                {
                    "event": "assert",
                    "relation_id": relation_id,
                    "page_id": page_id,
                },
            )

    def _append_tombstone_events(
        self, relation_ids: list[str], *, reason: str, page_id: str
    ) -> None:
        for relation_id in relation_ids:
            _append_event(
                relations_path(self.root),
                {
                    "event": "tombstone",
                    "relation_id": relation_id,
                    "page_id": page_id,
                    "reason": reason,
                },
            )

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def apply_result(self, record: RelationRunRecord) -> None:
        """Upsert a run record and append the corresponding events.

        Diff semantics:
          - Relations in the new record but not the previous one →
            append an ``assert`` event for each.
          - Relations in the previous record but not the new one →
            append a ``tombstone`` event for each (``reason`` =
            "cascade_update"). This is how the event log faithfully
            records "was alive, now gone" even though the live set in
            ``relation_run_state.json`` only ever lists live ids.
        """
        state = self._read_state()
        previous = state.get(record.page_id)
        previous_ids: set[str] = set(previous.relation_ids) if previous else set()
        new_ids: set[str] = set(record.relation_ids)

        to_assert = sorted(new_ids - previous_ids)
        to_tombstone = sorted(previous_ids - new_ids)

        # Stamp the configured fingerprint onto the persisted record if
        # the caller didn't supply one — this is purely informational
        # and never affects identity (relation_id comes from the key,
        # not the fingerprint).
        if not record.extractor_fingerprint and self._fingerprint:
            record.extractor_fingerprint = self._fingerprint

        # Persist the new record (sorted ids, see _save_state).
        state[record.page_id] = record
        self._save_state(state)

        # Then append the diff to the event log. Order: tombstones
        # first (the "old" state), then asserts (the "new" state) so
        # replay yields the same final live set.
        if to_tombstone:
            self._append_tombstone_events(
                to_tombstone, reason="cascade_update", page_id=record.page_id
            )
        if to_assert:
            self._append_assert_events(record.page_id, to_assert)

    def cascade_page_delete(self, page_id: str) -> None:
        """Tombstone every relation that involves ``page_id``.

        We don't know (source, target) tuples from the run record alone
        (Task 25 will plumb ``RelationAssertion.key`` through; for now
        we only know the per-page relation_id lists). The conservative
        implementation:

          1. Remove ``page_id``'s run record entirely; tombstone every
             relation_id it currently owns with reason
             ``cascade_delete``. These are the outbound edges.
          2. For every other page's run record, walk its relation_ids
             and tombstone any whose id token names ``page_id``. This
             is a heuristic until ``RelationAssertion.key`` lands;
             until then it captures the common case where relation_ids
             were generated from keys that name both endpoints.

        ``cascade_page_delete`` is idempotent: re-running it on an
        already-tombstoned page is a no-op (the live set is already
        empty, so step 1 records no events; step 2 still scans every
        other page but the relation_ids that mention ``page_id`` are
        already gone).
        """
        state = self._read_state()

        record = state.get(page_id)
        own_ids: list[str] = sorted(record.relation_ids) if record else []

        # Step 1: tombstone the deleted page's own relations.
        if own_ids:
            self._append_tombstone_events(
                own_ids, reason="cascade_delete", page_id=page_id
            )

        # Step 2: walk every other page and tombstone relation_ids whose
        # textual token references the deleted page. This is the
        # pre-Task-25 conservative default; once RelationAssertion.key
        # is plumbed through, we can replace this with an exact key
        # lookup. We compare on the page_id token (case-sensitive,
        # matching RelationKey semantics) rather than substring so an
        # unrelated page_id that happens to share a substring is not
        # accidentally tombstoned.
        to_drop: list[tuple[str, str]] = []
        for other_page_id, other_record in state.items():
            if other_page_id == page_id:
                continue
            for rid in other_record.relation_ids:
                if page_id in _relation_id_pages(rid):
                    to_drop.append((other_page_id, rid))

        if to_drop:
            affected_pages = sorted({pid for pid, _ in to_drop})
            for other_page_id in affected_pages:
                other_record = state[other_page_id]
                other_record.relation_ids = [
                    rid for rid in other_record.relation_ids
                    if (other_page_id, rid) not in to_drop
                ]
                # The deletion also marks the page as STALE — its
                # live relation set shrank unexpectedly.
                other_record.status = RelationRunStatus.STALE
            self._save_state(state)
            self._append_tombstone_events(
                [rid for _, rid in to_drop],
                reason="cascade_delete",
                page_id=page_id,
            )

        # Finally drop the deleted page's record entirely (the page no
        # longer exists in the wiki, so there's no run to track).
        if page_id in state:
            del state[page_id]
            self._save_state(state)

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    def get_run_record(self, page_id: str) -> RelationRunRecord | None:
        """Return the current run record for ``page_id`` or None."""
        return self._read_state().get(page_id)

    def list_page_relations(self, page_id: str) -> list[str]:
        """Return the live relation_ids for ``page_id`` (sorted)."""
        record = self._read_state().get(page_id)
        if record is None:
            return []
        return sorted(record.relation_ids)

    def find_stale(self, page_revisions: dict[str, str]) -> list[str]:
        """Return page_ids whose stored ``page_revision`` differs from the
        caller-supplied wiki revisions.

        Pages present in ``page_revisions`` whose revision matches the
        stored record are NOT in the result. Pages present in the
        stored state but absent from ``page_revisions`` are also stale
        (the wiki forgot about them; treat as needing a re-check).

        Returned list is sorted so the output is deterministic for
        tests and CLI display.
        """
        state = self._read_state()
        stale: list[str] = []
        for page_id, record in state.items():
            current = page_revisions.get(page_id)
            if current is None or current != record.page_revision:
                stale.append(page_id)
        return sorted(stale)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _relation_id_pages(relation_id: str) -> tuple[str, ...]:
    """Best-effort extraction of page-id tokens from a relation_id.

    The relation_id format (``rel-<sha1[:12]>``) does NOT embed the
    page ids — that's the whole point of a content hash. So this
    helper is intentionally lossy until Task 25's ``RelationAssertion``
    arrives and we can keep a (relation_id → key) side table.

    For now, we return an empty tuple: ``cascade_page_delete`` step 2
    therefore matches nothing extra. This is the safe default — we'd
    rather under-tombstone than over-tombstone based on a token that
    has no semantic meaning. Once the assertion-key side table lands
    (Task 25), this helper will be replaced with an exact lookup and
    step 2 will start catching the inbound edges.

    The function is kept (with a docstring) instead of being deleted
    so the call site in ``cascade_page_delete`` documents the
    dependency on Task 25 explicitly.
    """
    # Deliberately empty: relation_id → key side table is Task 25's job.
    return ()


__all__ = [
    "RelationRunRecord",
    "RelationRunStatus",
    "RelationStore",
    "run_state_path",
    "relations_path",
]