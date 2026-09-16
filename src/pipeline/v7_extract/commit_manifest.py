"""Stage 7 CommitManifest + phase machine (Task 19, plan 2026-09-17).

The commit manifest is a crash-consistency ledger for one batch of
``commit_and_index`` work. Each invocation creates a manifest at
``<root>/.index/commit_manifests/<commit_id>.json`` with:

  - a top-level ``CommitPhase`` state machine
    (PREPARED → STAGING → PUBLISHING → INDEXING → CHECKPOINTING →
     FINALIZING → COMMITTED, or → FAILED, or → RECONCILED on restart)
  - per-page ``PageCommitRecord`` entries carrying the on-disk path and
    a sha1 ``revision_hash`` placeholder (Task 20 will replace this
    with a frontmatter+body hash).

The manifest is rewritten at every phase transition with an atomic
``tmp + rename`` write (matches ``wiki_writer._atomic_write``; no new
dependency). On startup, ``reconcile_unfinished_commits(root)`` walks
every non-terminal manifest and uses the on-disk file presence +
``revision_hash`` to decide whether each page committed cleanly:

  * crash *before* publish → no page record exists, phase stays
    ``PREPARED``; the caller must re-run ``commit_and_index``.
  * crash *after* publish / *before* index → page file on disk +
    sha1 matches → mark ``COMMITTED``; manifest top-level becomes
    ``RECONCILED``.
  * page file on disk but sha1 differs from the recorded
    ``revision_hash`` → mark ``FAILED`` (hash mismatch); manifest
    overall ``FAILED``.

The manifest is intentionally append-and-rewrite (never deleted) so
post-mortem audits can inspect every crash.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


_TERMINAL_PHASES = frozenset({"committed", "reconciled"})


class CommitPhase(str, Enum):
    """9-state machine for one ``commit_and_index`` batch (Task 19)."""

    PREPARED = "prepared"
    STAGING = "staging"
    PUBLISHING = "publishing"
    INDEXING = "indexing"
    CHECKPOINTING = "checkpointing"
    FINALIZING = "finalizing"
    COMMITTED = "committed"
    FAILED = "failed"
    RECONCILED = "reconciled"  # terminal: recovered from a crash


@dataclass
class PageCommitRecord:
    """One page's outcome inside a ``CommitManifest``.

    ``revision_hash`` is a sha1 placeholder today (Task 19 spec); Task 20
    will extend it to cover frontmatter + body. ``written_path`` is the
    absolute path returned by ``WikiWriter._page_path`` at the time of
    write; ``None`` until the page has been published.
    """

    page_id: str
    topic_id: str
    source_paths: list[str]
    phase: CommitPhase = CommitPhase.PREPARED
    revision_hash: str = ""
    written_path: str | None = None
    error: str | None = None
    committed_at_ms: int | None = None


@dataclass
class CommitManifest:
    """One batch's crash-consistency ledger."""

    commit_id: str
    source_id: str
    created_at_ms: int
    updated_at_ms: int
    pipeline_fingerprint: str
    phase: CommitPhase = CommitPhase.PREPARED
    pages: dict[str, PageCommitRecord] = field(default_factory=dict)
    error: str | None = None
    attempt: int = 1

    # ----- (de)serialisation -----

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Enum → its string value (so the on-disk JSON uses "prepared" etc.)
        data["phase"] = self.phase.value
        data["pages"] = {
            pid: {**asdict(rec), "phase": rec.phase.value}
            for pid, rec in self.pages.items()
        }
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CommitManifest":
        phase_raw = payload.get("phase", CommitPhase.PREPARED.value)
        try:
            phase = CommitPhase(phase_raw)
        except ValueError:
            phase = CommitPhase.PREPARED

        pages: dict[str, PageCommitRecord] = {}
        for pid, raw in (payload.get("pages") or {}).items():
            if not isinstance(raw, dict):
                continue
            try:
                rec_phase = CommitPhase(raw.get("phase", CommitPhase.PREPARED.value))
            except ValueError:
                rec_phase = CommitPhase.PREPARED
            pages[str(pid)] = PageCommitRecord(
                page_id=str(raw.get("page_id", pid)),
                topic_id=str(raw.get("topic_id", "")),
                source_paths=list(raw.get("source_paths", []) or []),
                phase=rec_phase,
                revision_hash=str(raw.get("revision_hash", "") or ""),
                written_path=(
                    str(raw["written_path"])
                    if raw.get("written_path") not in (None, "")
                    else None
                ),
                error=(str(raw["error"]) if raw.get("error") else None),
                committed_at_ms=(
                    int(raw["committed_at_ms"])
                    if raw.get("committed_at_ms") is not None
                    else None
                ),
            )
        return cls(
            commit_id=str(payload.get("commit_id", "") or uuid.uuid4().hex),
            source_id=str(payload.get("source_id", "") or ""),
            created_at_ms=int(payload.get("created_at_ms", 0) or 0),
            updated_at_ms=int(payload.get("updated_at_ms", 0) or 0),
            pipeline_fingerprint=str(payload.get("pipeline_fingerprint", "") or ""),
            phase=phase,
            pages=pages,
            error=(str(payload["error"]) if payload.get("error") else None),
            attempt=int(payload.get("attempt", 1) or 1),
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def manifest_dir(root: Path | str) -> Path:
    """Return the per-project manifest directory (created on demand)."""
    p = Path(root) / ".index" / "commit_manifests"
    p.mkdir(parents=True, exist_ok=True)
    return p


def manifest_path(root: Path | str, commit_id: str) -> Path:
    return manifest_dir(root) / f"{commit_id}.json"


# ---------------------------------------------------------------------------
# Persistence — atomic tmp + rename (matches wiki_writer._atomic_write)
# ---------------------------------------------------------------------------


def write_manifest(root: Path | str, manifest: CommitManifest) -> Path:
    """Persist ``manifest`` atomically. Returns the path written."""
    path = manifest_path(root, manifest.commit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return path


def read_manifest(path: Path) -> CommitManifest | None:
    """Parse ``path`` into a ``CommitManifest``; ``None`` if missing/malformed."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return CommitManifest.from_dict(payload)


# ---------------------------------------------------------------------------
# Listing / reconciliation
# ---------------------------------------------------------------------------


def list_unfinished_manifests(root: Path | str) -> list[CommitManifest]:
    """Return all non-terminal manifests, ordered by ``created_at_ms`` ascending."""
    directory = Path(root) / ".index" / "commit_manifests"
    if not directory.exists():
        return []
    results: list[CommitManifest] = []
    for path in directory.glob("*.json"):
        manifest = read_manifest(path)
        if manifest is None:
            continue
        if manifest.phase.value in _TERMINAL_PHASES:
            continue
        results.append(manifest)
    results.sort(key=lambda m: (m.created_at_ms, m.commit_id))
    return results


def _hash_file(path: Path) -> str:
    """Sha1 of a file's content; empty string if the file is missing/empty."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if not data:
        return ""
    return hashlib.sha1(data).hexdigest()


def reconcile_unfinished_commits(root: Path | str) -> list[CommitManifest]:
    """Reconcile every non-terminal manifest under ``root``.

    For each ``PageCommitRecord``:
      * if ``written_path`` is set, the file exists, and the on-disk sha1
        matches ``revision_hash`` → mark ``COMMITTED`` (idempotent).
      * if ``written_path`` is set, the file exists, but the sha1 differs
        → mark ``FAILED`` with ``error="hash_mismatch"``.
      * otherwise leave the record's phase as-is (still pending, or
        previously FAILED).

    Top-level phase:
      * all pages ``COMMITTED`` → ``RECONCILED`` (terminal).
      * any page ``FAILED`` or any page still pending → ``FAILED``
        (the caller decides whether to re-run).

    The reconciled manifest is persisted (atomic rewrite). Reconciled
    manifests are returned so callers can log/audit them.
    """
    directory = Path(root) / ".index" / "commit_manifests"
    if not directory.exists():
        return []
    now_ms = int(time.time() * 1000)

    reconciled: list[CommitManifest] = []
    for path in sorted(directory.glob("*.json")):
        manifest = read_manifest(path)
        if manifest is None:
            continue
        if manifest.phase.value in _TERMINAL_PHASES:
            continue

        any_failed = False
        any_pending = False
        any_committed = False
        for record in manifest.pages.values():
            if record.phase == CommitPhase.COMMITTED:
                any_committed = True
                continue
            written_path_str = record.written_path
            if not written_path_str:
                # Scenario A: crash before publish — nothing on disk yet.
                any_pending = True
                continue
            written_path = Path(written_path_str)
            if not written_path.exists():
                # Scenario A': record was created but file vanished.
                any_pending = True
                continue
            on_disk_hash = _hash_file(written_path)
            if record.revision_hash and on_disk_hash != record.revision_hash:
                record.phase = CommitPhase.FAILED
                record.error = "hash_mismatch"
                any_failed = True
                continue
            if record.revision_hash:
                record.phase = CommitPhase.COMMITTED
                if record.committed_at_ms is None:
                    record.committed_at_ms = now_ms
                any_committed = True
            else:
                # File exists but we never recorded a hash — treat as
                # pending so the caller re-runs (safer than marking
                # committed for an unknown content).
                any_pending = True

        # Scenario A: no page records at all (crash before any publish)
        # → keep PREPARED so the caller re-runs commit_and_index.
        if not manifest.pages:
            manifest.phase = CommitPhase.PREPARED
        elif any_failed:
            manifest.phase = CommitPhase.FAILED
        elif any_pending:
            manifest.phase = CommitPhase.PREPARED
        elif any_committed:
            manifest.phase = CommitPhase.RECONCILED
        else:
            manifest.phase = CommitPhase.PREPARED
        manifest.updated_at_ms = now_ms
        write_manifest(root, manifest)
        reconciled.append(manifest)

    return reconciled


# ---------------------------------------------------------------------------
# Helpers reused by wiki_writer
# ---------------------------------------------------------------------------


def default_commit_id_factory() -> str:
    """Default commit id factory — uuid4 hex (32 chars, no dashes)."""
    return uuid.uuid4().hex
