"""Event-source replay surface (OPEN-4).

Implements :func:`replay_object_from_events`, a real
``events.jsonl``-driven replay that reconstructs an object's state at a
given ``target_version``. This is independent of the snapshot-based
:meth:`KnowledgeKernel.replay_object` so the prior contract — including
its :meth:`KnowledgeKernel.replay_core_from_events` placeholder that
returns ``reason_codes=("event_replay_stub",)`` — remains intact.

Event schema (read-only — we never write here)::

    {
        "action":      "kc.object.created" | "kc.object.updated"
                     | "kc.object.deleted",
        "stream_id":   <object_id>,
        "event_version": <int 1-based, per stream>,
        "timestamp":   <int epoch ms>,
        "object_id":   <str>,
        "object_type": <"KnowledgeUnit" | "Evidence"
                       | "StructuredFact" | "Claim"
                       | "Approval" | "PublicationBatch" | ...>,
        ...payload keys spread at top level
    }

Ordering: events are read from the JSONL file in line order, but the
replay logic re-sorts by ``event_version`` so a write race that landed
events out of order on disk still produces the correct state. The
``_EventFileLock`` from OPEN-1 prevents such races under normal
operation; the sort here is defence-in-depth (the surface must remain
correct even if a caller bypasses the store's append path).

Supported object types: any object whose events carry an
``object_type`` field. The dispatch is field-driven — no hardcoded
branches per type — so adding a new ``object_type`` (e.g. a future
``KnowledgeFragment``) is purely a data change.
"""
from __future__ import annotations

import json
from pathlib import Path


# --- Public exception types ----------------------------------------------


class ReplayObjectError(Exception):
    """Base class for event-source replay errors.

    All exceptions raised from :func:`replay_object_from_events` derive
    from this class so callers can catch the whole family with one
    ``except`` clause if they only care that replay failed.
    """


class ObjectDeletedBeforeTargetVersion(ReplayObjectError):
    """Raised when ``target_version`` is at or after a recorded deletion.

    Replay does not invent state for an object the event stream says
    no longer exists. The exception carries ``object_id`` and
    ``target_version`` for diagnostics.
    """

    def __init__(self, object_id: str, target_version: int, deleted_at: int) -> None:
        self.object_id = object_id
        self.target_version = target_version
        self.deleted_at = deleted_at
        super().__init__(
            f"Object {object_id!r} was deleted at event_version={deleted_at}; "
            f"cannot replay target_version={target_version}."
        )


class TargetVersionBeyondHistory(ReplayObjectError):
    """Raised when ``target_version`` exceeds the recorded event count.

    Distinct from the deletion case so callers can distinguish
    "this object never reached that version" from "this object was
    explicitly removed". Carries the actual history length for
    diagnostics.
    """

    def __init__(self, object_id: str, target_version: int, history_length: int) -> None:
        self.object_id = object_id
        self.target_version = target_version
        self.history_length = history_length
        super().__init__(
            f"Object {object_id!r} has only {history_length} recorded "
            f"event(s); target_version={target_version} is beyond history."
        )


# --- Internal helpers -----------------------------------------------------


# Per-event ``action`` values we recognise. Update on both ends together.
_ACTION_CREATED = "kc.object.created"
_ACTION_UPDATED = "kc.object.updated"
_ACTION_DELETED = "kc.object.deleted"
_REPLAYABLE_ACTIONS = frozenset({_ACTION_CREATED, _ACTION_UPDATED, _ACTION_DELETED})

# Event keys that are replay metadata — they describe the event itself
# rather than the object state. Stripped from the merged state payload
# so callers see only object fields (plus a synthetic ``version``).
_EVENT_META_KEYS = frozenset(
    {
        "action",
        "stream_id",
        "event_version",
        "timestamp",
        "operation_id",
        "payload_hash",
        # ``object_id`` and ``object_type`` are kept — they describe the
        # object, not the event envelope.
    }
)


def _read_events(events_dir: Path) -> list[dict]:
    """Read all events from ``{events_dir}/events.jsonl``.

    Skips malformed lines silently (they are dropped from replay but
    do not fail the call — the store's append path never writes them
    and a corrupt line should not freeze every read).
    """
    events_file = events_dir / "events.jsonl"
    if not events_file.exists():
        return []
    events: list[dict] = []
    with open(events_file, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return events


def _filter_stream(events: list[dict], object_id: str) -> list[dict]:
    """Return events that target *object_id*, in ``event_version`` order.

    Matches either by ``stream_id`` (the canonical key) or by the spread
    ``object_id`` payload field. The sort is stable on ties.
    """
    matched = [
        e for e in events
        if e.get("stream_id") == object_id
        or e.get("object_id") == object_id
    ]
    matched.sort(key=lambda e: (int(e.get("event_version", 0) or 0), int(e.get("timestamp", 0) or 0)))
    return matched


def _apply_event(state: dict | None, event: dict) -> dict | None:
    """Fold one *event* onto the replay *state*.

    * ``kc.object.created``: initial state — payload (minus meta keys)
      is the whole object.
    * ``kc.object.updated``: shallow-merge payload into the existing
      state (later events win on key collision, matching the snapshot
      semantics used elsewhere).
    * ``kc.object.deleted``: returns ``None`` — the object no longer
      exists at or after this event.
    """
    action = event.get("action")
    payload = {k: v for k, v in event.items() if k not in _EVENT_META_KEYS}
    if action == _ACTION_CREATED:
        new_state: dict = dict(payload)
        new_state["version"] = int(event.get("event_version", 1) or 1)
        return new_state
    if action == _ACTION_UPDATED:
        if state is None:
            # An update without a prior creation is a malformed event
            # stream; surface as the object's initial state rather than
            # silently dropping the field. ``version`` is taken from the
            # event itself.
            new_state = dict(payload)
            new_state["version"] = int(event.get("event_version", 1) or 1)
            return new_state
        merged = {**state, **payload}
        merged["version"] = int(event.get("event_version", 1) or 1)
        return merged
    if action == _ACTION_DELETED:
        return None
    # Unknown action — replay only knows the three documented event
    # types; skip silently rather than abort the whole call.
    return state


# --- Public entry point ---------------------------------------------------


def replay_object_from_events(
    object_id: str,
    target_version: int,
    *,
    events_dir: Path,
    object_type: str | None = None,
) -> dict | None:
    """Reconstruct an object's state at ``target_version`` from events.

    Reads every ``kc.object.created`` / ``kc.object.updated`` /
    ``kc.object.deleted`` event for ``object_id`` from
    ``{events_dir}/events.jsonl`` (the file OPEN-1's ``JSONLEventStore``
    writes), folds them in ``event_version`` order, and returns the
    state as a dict.

    Args:
        object_id: The KnowledgeObject id to reconstruct. Events for
            other objects in the same file are ignored.
        target_version: 1-based version number. The returned state is
            what the object looked like after exactly this many
            replayable events had been applied (creation counts as
            version 1).
        events_dir: Directory containing ``events.jsonl``. Normally the
            project root's ``.index/knowledge_graph`` path; passed in
            rather than read from a global so the function stays pure
            and unit-testable.
        object_type: Optional guard — when set, the function asserts
            the first replayable event carries a matching
            ``object_type``. Useful when callers know the type and
            want a fast-fail on mismatched identifiers.

    Returns:
        ``dict`` carrying the reconstructed object state (object fields
        plus a synthetic ``version`` key). Returns ``None`` when no
        events for ``object_id`` exist in the file (the object is
        unknown in this event stream).

    Raises:
        ObjectDeletedBeforeTargetVersion: a deletion event was recorded
            at or before ``target_version``; the object no longer
            exists at that version.
        TargetVersionBeyondHistory: ``target_version`` exceeds the
            number of recorded replayable events for this object.
        ValueError: ``target_version`` is less than 1.
    """
    if target_version < 1:
        raise ValueError(
            f"target_version must be >= 1 (got {target_version})"
        )

    events = _read_events(Path(events_dir))
    stream_events = _filter_stream(events, object_id)
    replayable = [e for e in stream_events if e.get("action") in _REPLAYABLE_ACTIONS]

    if not replayable:
        return None

    if object_type is not None:
        first_type = replayable[0].get("object_type")
        if first_type is not None and first_type != object_type:
            # Don't silently coerce — surface the mismatch so callers
            # know their identifier refers to a different object kind.
            raise ReplayObjectError(
                f"Object {object_id!r} first event has object_type="
                f"{first_type!r}, expected {object_type!r}."
            )

    history_length = len(replayable)

    # Deletion takes precedence: if the stream records a deletion at
    # version K, the object does not exist at or after K regardless of
    # how many further events the caller asks for. Check this before
    # the beyond-history guard so callers can't accidentally mask a
    # deletion by asking for a version past the recorded history.
    deletion_event_version: int | None = None
    for ev in replayable:
        if ev.get("action") == _ACTION_DELETED:
            deletion_event_version = int(ev.get("event_version", 0) or 0)
            break
    if deletion_event_version is not None and target_version >= deletion_event_version:
        raise ObjectDeletedBeforeTargetVersion(
            object_id=object_id,
            target_version=target_version,
            deleted_at=deletion_event_version,
        )

    if target_version > history_length:
        raise TargetVersionBeyondHistory(
            object_id=object_id,
            target_version=target_version,
            history_length=history_length,
        )

    # Apply only the events up to and including ``target_version``.
    # Earlier events must not contaminate the replayed snapshot —
    # callers asking for v1 want the state after the first event, not
    # after every event ever recorded for the object.
    state: dict | None = None
    deleted_at: int | None = None
    for idx, event in enumerate(replayable[:target_version], start=1):
        if event.get("action") == _ACTION_DELETED:
            deleted_at = int(event.get("event_version", idx) or idx)
        state = _apply_event(state, event)
        if state is None:
            # Deletion was observed at or before the requested
            # version. The state is no longer available.
            raise ObjectDeletedBeforeTargetVersion(
                object_id=object_id,
                target_version=target_version,
                deleted_at=deleted_at if deleted_at is not None else idx,
            )

    return state


__all__ = [
    "ObjectDeletedBeforeTargetVersion",
    "ReplayObjectError",
    "TargetVersionBeyondHistory",
    "replay_object_from_events",
]
