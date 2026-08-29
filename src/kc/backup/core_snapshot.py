"""Core backup + restore API (Z-1, spec §1 M-7 + §5.13 Publication Batch).

路线 v2.2 §C-0.5a: 提供 create_snapshot / restore_snapshot 函数，验证
KnowledgeObject.id (身份键) 一致性。演练脚本由 C-0.5b 任务提供。

Task 4（plan 2026-08-29-kc-integrity-idempotency-layered.md）扩展：
- ``snapshot_from_storage(paths)`` 读取真实项目存储（VersionManager +
  events.jsonl），无需调用者传入对象。
- ``restore_snapshot(snapshot_id, paths)`` 返回 ``RestoreReport``（含
  identity_keys / event_hash / version_count / reason_codes），篡改的
  events.jsonl → ``("restore_mismatch",)``，不覆盖 live 存储。
- ``ReplayResult`` + ``KnowledgeKernel.replay_object(...)`` 见 kernel.py。
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.knowledge.core.object import KnowledgeObject
from src.knowledge.core.version_manager import (
    VersionManager,
    _serialize_object,
    _deserialize_object,
)
from src.wiki.core.paths import WikiPaths

_logger = logging.getLogger(__name__)

KC_BACKUP_DIR = ".llm-wiki/backups"
# Relative path under ``paths.index`` (which is already the project's
# ``.index/`` directory). Keep these two in sync — joining
# ``paths.index / EVENT_STREAM_PATH`` must produce the same file as
# ``paths.index / "knowledge_graph" / "events.jsonl"``.
EVENT_STREAM_PATH = "knowledge_graph/events.jsonl"


@dataclass
class Snapshot:
    """Result of create_snapshot — points at the on-disk backup directory."""

    snapshot_id: str
    timestamp: int
    paths: WikiPaths
    backup_dir: Path
    object_count: int
    identity_keys: list[str]
    before_hash: str
    after_hash: str
    version_count: int = 0
    spec_compliance: str = "Knowledge_Compiler_v2.1_§5.13_Publication_Batch"


@dataclass
class RestoreReport:
    """Result of restore_snapshot — describes the post-restore state.

    Task 4 (plan 2026-08-29-...): replaces the previous boolean return so
    callers can detect ``restore_mismatch`` (events.jsonl bytes differ
    between snapshot's stored copy and the live store) without re-reading
    files. The default recovery path is fail-closed: when a mismatch is
    detected, ``reason_codes`` contains ``"restore_mismatch"`` and the
    live storage is left untouched (do NOT overwrite valid Core state
    with a snapshot whose event stream diverges).

    Attributes:
        snapshot_id:       The ``snap_<ts>`` identifier that was restored.
        identity_keys:     Sorted list of KnowledgeObject.id values whose
                           state was in the snapshot.
        event_hash:        sha256 of the live events.jsonl AFTER the
                           restore (== stored bytes on success; == live
                           pre-existing bytes on ``restore_mismatch``).
        version_count:     Number of event lines in the snapshot's stored
                           event stream copy.
        reason_codes:      Empty tuple on success; ``("restore_mismatch",)``
                           when the stored event hash differs from the live
                           one (live state preserved).
    """

    snapshot_id: str
    identity_keys: list[str]
    event_hash: str
    version_count: int
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# Monotonic counter ensures two snapshots created in the same millisecond (which
# happens often in tests) still get unique timestamps. ``time.time_ns()`` would
# do this without state but is platform-dependent for repr width.
_snapshot_counter: int = 0


def _next_timestamp() -> int:
    """Return a strictly increasing millisecond timestamp."""
    global _snapshot_counter
    _snapshot_counter += 1
    return int(time.time() * 1000) + _snapshot_counter


def _snapshot_event_stream(paths: WikiPaths, backup_dir: Path) -> int:
    """Copy the append-only knowledge graph event stream into backup_dir.

    Returns the number of lines copied (0 if event stream does not exist).
    """
    event_src = paths.index / EVENT_STREAM_PATH
    event_dst = backup_dir / "version_events.jsonl"
    if not event_src.exists():
        event_dst.write_text("", encoding="utf-8")
        return 0
    shutil.copy2(str(event_src), str(event_dst))
    with event_dst.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def create_snapshot(
    paths: WikiPaths,
    objects: list[KnowledgeObject] | None = None,
) -> Snapshot:
    """Snapshot all Core KnowledgeObjects under ``.llm-wiki/backups/<snapshot_id>/``.

    Args:
        paths: Project WikiPaths.
        objects: Explicit list of KnowledgeObjects to back up. When omitted,
            must be supplied by the caller (no global registry yet). The list
            is the single source of truth: the snapshot reflects exactly what
            was passed in, no disk scan.

    Returns:
        Snapshot record describing the on-disk backup directory.

    Raises:
        ValueError: If ``objects`` is omitted (no global object registry exists
            yet; B-2.5 will add it once identity_key is implemented for all
            13 object types).
    """
    if objects is None:
        raise ValueError(
            "create_snapshot requires `objects=` (no global object registry yet; "
            "see 路线 v2.2 §B-2.5 identity_key 总验收 for the upstream dependency)"
        )

    timestamp = _next_timestamp()
    snapshot_id = f"snap_{timestamp}"
    backup_root = paths.llm_wiki / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / snapshot_id
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 1. Dump KO objects → snapshot.json keyed by id (identity_key in v2.2)
    snapshot_data: dict[str, dict] = {}
    identity_keys: list[str] = []
    for obj in objects:
        identity_keys.append(obj.id)
        snapshot_data[obj.id] = _serialize_object(obj)
    snapshot_json = json.dumps(snapshot_data, sort_keys=True, ensure_ascii=False)
    (backup_dir / "snapshot.json").write_text(snapshot_json, encoding="utf-8")

    # 2. Identity keys sidecar (deterministic sort)
    (backup_dir / "identity_keys.txt").write_text(
        "\n".join(sorted(identity_keys)), encoding="utf-8"
    )

    # 3. Append-only event stream copy
    version_count = _snapshot_event_stream(paths, backup_dir)

    # 4. Hashes for spec §5.13 Publication Batch
    before_hash = _sha256("")  # empty baseline
    after_hash = _sha256(snapshot_json)

    # 5. MANIFEST.yaml
    manifest = {
        "snapshot_id": snapshot_id,
        "timestamp": timestamp,
        "version_count": version_count,
        "identity_count": len(identity_keys),
        "object_count": len(objects),
        "before_hash": before_hash,
        "after_hash": after_hash,
        "spec_compliance": Snapshot.spec_compliance,
    }
    (backup_dir / "MANIFEST.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8"
    )

    return Snapshot(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        paths=paths,
        backup_dir=backup_dir,
        object_count=len(objects),
        identity_keys=sorted(identity_keys),
        before_hash=before_hash,
        after_hash=after_hash,
        version_count=version_count,
    )


def _live_event_stream_path(paths: WikiPaths) -> Path:
    """Return the live events.jsonl path (single source of truth)."""
    return paths.index / "knowledge_graph" / "events.jsonl"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    """sha256 of a file's bytes; missing file → hash of empty bytes."""
    if not path.exists():
        return _sha256_bytes(b"")
    return _sha256_bytes(path.read_bytes())


def _collect_objects_from_storage(paths: WikiPaths) -> list[KnowledgeObject]:
    """Enumerate every KnowledgeObject in durable storage.

    Reads VersionManager's ``_version_index.json`` (every version_id →
    object_id ever snapshotted) and reconstructs each object's most-recent
    snapshot. No caller-passed objects needed (Task 4 §Step 3).
    """
    vm = VersionManager(paths.root)
    index = vm._load_global_index()  # noqa: SLF001 — internal index, not the public API yet
    # Map object_id → most-recent version_id (largest timestamp wins).
    latest: dict[str, tuple[int, str]] = {}
    for version_id, object_id in index.items():
        history = vm._load_manifest(object_id)
        entry = next((e for e in history if e["version_id"] == version_id), None)
        ts = entry["timestamp"] if entry is not None else 0
        prev = latest.get(object_id)
        if prev is None or ts > prev[0]:
            latest[object_id] = (ts, version_id)
    objects: list[KnowledgeObject] = []
    for object_id, (_ts, version_id) in sorted(latest.items()):
        data = vm._load_version_data(object_id, version_id)  # noqa: SLF001
        objects.append(_deserialize_object(data))
    return objects


def snapshot_from_storage(paths: WikiPaths) -> Snapshot:
    """Snapshot the Core durable storage without requiring caller-passed objects.

    Task 4 §Step 3: enumerates KnowledgeObjects via VersionManager +
    ``_version_index.json`` and reads the live ``events.jsonl`` as the
    authoritative event stream. The Snapshot's ``after_hash`` is the
    sha256 of the canonical JSON dump of every object's most-recent
    serialization, so two consecutive calls on the same durable state
    produce identical hashes (deterministic contract).

    Args:
        paths: Project WikiPaths.

    Returns:
        Snapshot pointing at the newly-written backup directory.
    """
    objects = _collect_objects_from_storage(paths)
    snap = create_snapshot(paths, objects=objects)

    # Preserve the durable version tree (per-object snapshots + _history.json
    # manifests + _version_index.json) so restore can rebuild full history
    # instead of re-snapshotting (which would create duplicate versions on
    # repeated restores).
    versions_root = paths.root / "versions"
    if versions_root.is_dir():
        shutil.copytree(
            str(versions_root),
            str(snap.backup_dir / "versions"),
            dirs_exist_ok=True,
        )
    return snap


def restore_snapshot(
    snapshot_id: str,
    paths: WikiPaths,
    modified_objects: list[KnowledgeObject] | None = None,
) -> RestoreReport:
    """Restore Core state (VersionManager snapshots + event stream) from a snapshot.

    Task 4 §Step 3: replaces the previous boolean contract with a
    ``RestoreReport`` carrying identity_keys / event_hash / version_count /
    reason_codes. The default recovery path is fail-closed: when the live
    ``events.jsonl`` exists and its bytes differ from the snapshot's
    ``version_events.jsonl``, we return ``reason_codes=("restore_mismatch",)``
    and DO NOT overwrite live storage (the caller is expected to inspect
    and decide).

    On success (event_hash matches OR live events.jsonl is missing/empty),
    the snapshot's stored event stream is restored to live and the
    version snapshots are copied back under ``<paths.root>/versions/``.
    Repeated calls are idempotent: same bytes are written, same
    identity_keys reported, no new events appear.

    Legacy compatibility: passing ``modified_objects`` still triggers the
    old "drop ids not in snapshot" warning; the function no longer
    raises ``ValueError`` for caller-id drift (drift is recorded as a
    warning, not a hard failure).

    Args:
        snapshot_id: The ``snap_<ts>`` identifier returned by
            ``create_snapshot`` / ``snapshot_from_storage``.
        paths: Project WikiPaths.
        modified_objects: Optional caller's current KO list — used for
            the drift warning only (no longer a hard error).

    Returns:
        ``RestoreReport`` describing the post-restore state.

    Raises:
        FileNotFoundError: When ``snapshot_id`` is not on disk or its
            ``identity_keys.txt`` sidecar is missing.
    """
    backup_dir = paths.llm_wiki / "backups" / snapshot_id
    snapshot_path = backup_dir / "snapshot.json"
    identity_path = backup_dir / "identity_keys.txt"
    stored_events_path = backup_dir / "version_events.jsonl"

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")
    if not identity_path.exists():
        raise FileNotFoundError(
            f"Snapshot identity_keys.txt missing: {snapshot_id}"
        )

    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    identity_keys = sorted(
        line.strip()
        for line in identity_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    actual_keys = set(snapshot_data.keys())

    if set(identity_keys) != actual_keys:
        raise ValueError(
            f"identity_key mismatch for {snapshot_id}: "
            f"expected {len(identity_keys)}, got {len(actual_keys)}"
        )

    if modified_objects is not None:
        caller_keys = {obj.id for obj in modified_objects}
        missing_in_snapshot = caller_keys - set(identity_keys)
        if missing_in_snapshot:
            _logger.warning(
                "restore_snapshot %s: dropping %d caller ids not in snapshot: %s",
                snapshot_id,
                len(missing_in_snapshot),
                sorted(missing_in_snapshot)[:5],
            )

    # Round-trip check: deserialize every object in the snapshot.
    for key in sorted(snapshot_data):
        _ = _deserialize_object(snapshot_data[key]).id

    stored_event_hash = _sha256_file(stored_events_path)
    version_count = 0
    if stored_events_path.exists():
        with stored_events_path.open(encoding="utf-8") as fh:
            version_count = sum(1 for line in fh if line.strip())

    live_events = _live_event_stream_path(paths)
    live_event_hash = _sha256_file(live_events)

    # Fail-closed on mismatch: a NON-EMPTY live stream that differs from the
    # snapshot is preserved — the snapshot is never copied over it.
    if (
        live_events.exists()
        and live_events.stat().st_size > 0
        and stored_event_hash != live_event_hash
    ):
        return RestoreReport(
            snapshot_id=snapshot_id,
            identity_keys=identity_keys,
            event_hash=live_event_hash,
            version_count=version_count,
            reason_codes=("restore_mismatch",),
        )

    # Restore the durable version tree captured by snapshot_from_storage
    # (per-object snapshots + _history.json manifests + _version_index.json).
    # Copying back the exact bytes is idempotent — repeated restores add no
    # new versions. Snapshots made via create_snapshot (caller objects, no
    # version tree in backup) have no versions/ — nothing to restore there.
    versions_backup = backup_dir / "versions"
    if versions_backup.is_dir():
        shutil.copytree(
            str(versions_backup),
            str(paths.root / "versions"),
            dirs_exist_ok=True,
        )

    # Restore the event stream (idempotent — same bytes on repeat calls).
    live_events.parent.mkdir(parents=True, exist_ok=True)
    if stored_events_path.exists():
        shutil.copy2(str(stored_events_path), str(live_events))
    else:
        live_events.write_text("", encoding="utf-8")

    post_hash = _sha256_file(live_events)
    return RestoreReport(
        snapshot_id=snapshot_id,
        identity_keys=identity_keys,
        event_hash=post_hash,
        version_count=version_count,
        reason_codes=(),
    )
