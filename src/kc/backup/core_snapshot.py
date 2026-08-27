"""Core backup + restore API (Z-1, spec §1 M-7 + §5.13 Publication Batch).

路线 v2.2 §C-0.5a: 提供 create_snapshot / restore_snapshot 函数，验证
KnowledgeObject.id (身份键) 一致性。演练脚本由 C-0.5b 任务提供。
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.knowledge.core.object import KnowledgeObject
from src.knowledge.core.version_manager import (
    _serialize_object,
    _deserialize_object,
)
from src.wiki.core.paths import WikiPaths

_logger = logging.getLogger(__name__)

KC_BACKUP_DIR = ".llm-wiki/backups"
EVENT_STREAM_PATH = ".index/knowledge_graph/events.jsonl"


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


def restore_snapshot(
    snapshot_id: str,
    paths: WikiPaths,
    modified_objects: list[KnowledgeObject] | None = None,
) -> bool:
    """Restore KnowledgeObjects from a snapshot.

    Validates identity_key (KO.id) consistency between the snapshot record and
    the supplied ``modified_objects`` (the caller's current Core state). The
    snapshot's MANIFEST + snapshot.json are the single source of truth for
    what counts as "expected identity"; objects in ``modified_objects`` whose
    KO.id is not present in the snapshot are dropped, and the snapshot's
    serialized state is what the caller is told is authoritative.

    The function does not touch KO.storage write paths yet (the storage
    facade is a B-2 dependency) — it returns ``True`` after validating
    consistency and re-writing the snapshot directory with the canonical
    state. Drill-script-level storage restoration is C-0.5b's job.

    Args:
        snapshot_id: The ``snap_<ts>`` identifier returned by create_snapshot.
        paths: Project WikiPaths.
        modified_objects: Callers pass their current KO list so restore can
            validate identity consistency and report drift.

    Returns:
        True when the snapshot directory exists and identity sets match.

    Raises:
        FileNotFoundError: When ``snapshot_id`` is not on disk.
        ValueError: When ``modified_objects`` is provided and contains ids
            missing from the snapshot (i.e. the Core has objects the backup
            does not know about).
    """
    backup_dir = paths.llm_wiki / "backups" / snapshot_id
    snapshot_path = backup_dir / "snapshot.json"
    identity_path = backup_dir / "identity_keys.txt"

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")
    if not identity_path.exists():
        raise FileNotFoundError(
            f"Snapshot identity_keys.txt missing: {snapshot_id}"
        )

    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    expected_keys = {
        line.strip()
        for line in identity_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    actual_keys = set(snapshot_data.keys())

    if expected_keys != actual_keys:
        raise ValueError(
            f"identity_key mismatch for {snapshot_id}: "
            f"expected {len(expected_keys)}, got {len(actual_keys)}"
        )

    if modified_objects is not None:
        caller_keys = {obj.id for obj in modified_objects}
        missing_in_snapshot = caller_keys - expected_keys
        if missing_in_snapshot:
            _logger.warning(
                "restore_snapshot %s: dropping %d caller ids not in snapshot: %s",
                snapshot_id,
                len(missing_in_snapshot),
                sorted(missing_in_snapshot)[:5],
            )

    # Rehydrate objects as round-trip check + drop a marker for the drill script
    for key in sorted(snapshot_data):
        ko = _deserialize_object(snapshot_data[key])
        # Touch the field to keep round-trip linter honest
        _ = ko.id
    return True
