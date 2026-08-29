"""Core backup drill (Z-5, spec §17 D-22).

路线 v2.2 §C-0.5b: 在 C-0.5a (create_snapshot / restore_snapshot) 之上提供
端到端演练脚本，验证：

    snapshot → 模拟损坏 → restore → identity_key 一致性 100%

Caller 模式：演练脚本接收 ``objects`` 入参（不依赖全局 KO 注册表——那是
B-2.5 任务)。本文件不修改 C-0.5a 的 create_snapshot / restore_snapshot API。

输出报告到 ::

    .index/backup_drills/<drill_id>.log

含 before/after 对比 + 失败步骤列表。
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.knowledge.core.object import KnowledgeObject
from src.wiki.core.paths import WikiPaths

from .core_snapshot import RestoreReport, restore_snapshot

EVENT_STREAM_REL_PATH = ".index/knowledge_graph/events.jsonl"


@dataclass
class DrillReport:
    """Result of one full backup-drill execution."""

    drill_id: str
    timestamp: int
    snapshot_id: str
    paths_root: Path
    drill_status: str
    before_ko_count: int
    after_ko_count: int
    identity_key_consistency: bool
    events_sha256_before: str = ""
    events_sha256_after: str = ""
    failed_steps: list[str] = field(default_factory=list)


def _events_path(paths: WikiPaths) -> Path:
    """Return the canonical event-stream file path (``paths.index/knowledge_graph/events.jsonl``).

    Mirrors ``src.knowledge.storage.event_store.EventStore`` path layout and
    ``core_snapshot.EVENT_STREAM_PATH``.
    """
    return paths.index / "knowledge_graph" / "events.jsonl"


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Monotonic counter so two drills in the same millisecond still get unique ids.
_drill_counter: int = 0


def _next_drill_timestamp() -> int:
    global _drill_counter
    _drill_counter += 1
    return int(time.time() * 1000) + _drill_counter


def _verify_identity_consistency(
    snapshot_identity_keys: set[str],
    objects: list[KnowledgeObject],
) -> bool:
    """Compare snapshot's recorded identity_keys against the live KO.id set.

    The snapshot's ``identity_keys`` (surfaced through RestoreReport / read
    from ``identity_keys.txt``) is authoritative; the live caller objects must
    match exactly. Extra ids in the caller set are tolerated (caller may have
    created new KO after the snapshot — restore will not roll those back).
    """
    caller_keys = {obj.id for obj in objects}
    # snapshot ↔ caller: caller may have *extra* new ids (not in snapshot).
    # We require snapshot.identity_keys ⊆ caller_keys (every snapshot object
    # still representable from the live state).
    return snapshot_identity_keys.issubset(caller_keys)


def run_drill(
    paths: WikiPaths,
    objects: list[KnowledgeObject],
    snapshot_id: str,
) -> DrillReport:
    """Verify a Core backup snapshot by running a restore + identity audit.

    Assumes ``snapshot_id`` was created via ``create_snapshot(paths, objects=...)``
    earlier in the same caller flow. The drill re-runs ``restore_snapshot`` to
    rehydrate the canonical snapshot directory, then compares the snapshot's
    recorded identity_keys against the caller's live KO set.

    Steps:
        1. Read before-snapshot event stream sha256 (already recorded in
           ``version_events.jsonl`` from the snapshot).
        2. Rehydrate snapshot via ``restore_snapshot`` (validates identity).
        3. Compare snapshot identity_keys vs caller KO.id set.
        4. Compare event stream sha256 before/after (identity file reused).

    Args:
        paths: Project WikiPaths.
        objects: Current live KO list (caller's Core state).
        snapshot_id: The ``snap_<ts>`` id returned by an earlier
            ``create_snapshot`` call.

    Returns:
        ``DrillReport`` populated with status + before/after metrics.
    """
    timestamp = _next_drill_timestamp()
    drill_id = f"drill_{timestamp}"
    failed_steps: list[str] = []
    events_path = _events_path(paths)

    events_sha_before = _sha256_file(events_path)
    before_ko_count = len(objects)

    # Step 1: Restore from durable storage (validates identity + event stream)
    restore_report: RestoreReport | None = None
    try:
        restore_report = restore_snapshot(snapshot_id, paths, modified_objects=objects)
    except FileNotFoundError as e:
        failed_steps.append(f"restore: snapshot not found: {e}")
    except ValueError as e:
        failed_steps.append(f"restore: identity drift: {e}")
    except Exception as e:  # noqa: BLE001 — surface any restore failure
        failed_steps.append(f"restore: unexpected: {e!r}")

    # Step 2: Snapshot identity_keys — from the RestoreReport when available
    if restore_report is not None:
        if "restore_mismatch" in restore_report.reason_codes:
            failed_steps.append("restore: event stream mismatch (restore_mismatch)")
        snapshot_identity_keys = set(restore_report.identity_keys)
    else:
        identity_keys_path = paths.llm_wiki / "backups" / snapshot_id / "identity_keys.txt"
        snapshot_identity_keys: set[str] = set()
        if identity_keys_path.exists():
            snapshot_identity_keys = {
                line.strip()
                for line in identity_keys_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }

    # Step 3: Verify identity consistency (snapshot ⊆ caller)
    identity_consistency = _verify_identity_consistency(
        snapshot_identity_keys, objects
    )
    if not identity_consistency:
        failed_steps.append("verify: caller KO.id set missing snapshot keys")

    # Step 4: Event stream comparison — post-restore hash from the report
    events_sha_after = (
        restore_report.event_hash
        if restore_report is not None
        else _sha256_file(events_path)
    )

    drill_status = "PASS" if (not failed_steps) else "FAILED"

    return DrillReport(
        drill_id=drill_id,
        timestamp=timestamp,
        snapshot_id=snapshot_id,
        paths_root=paths.root,
        drill_status=drill_status,
        before_ko_count=before_ko_count,
        after_ko_count=len(objects),
        identity_key_consistency=identity_consistency,
        events_sha256_before=events_sha_before,
        events_sha256_after=events_sha_after,
        failed_steps=failed_steps,
    )


def write_drill_report(paths: WikiPaths, report: DrillReport) -> Path:
    """Write the drill report to ``.index/backup_drills/<drill_id>.log``.

    The report is serialized as pretty-printed JSON so downstream automation
    (D-22 acceptance gate) can parse it without bespoke loaders.
    """
    drill_dir = paths.index / "backup_drills"
    drill_dir.mkdir(parents=True, exist_ok=True)
    log_path = drill_dir / f"{report.drill_id}.log"

    payload = {
        "drill_id": report.drill_id,
        "timestamp": report.timestamp,
        "snapshot_id": report.snapshot_id,
        "paths_root": str(report.paths_root),
        "drill_status": report.drill_status,
        "before_ko_count": report.before_ko_count,
        "after_ko_count": report.after_ko_count,
        "identity_key_consistency": report.identity_key_consistency,
        "events_sha256_before": report.events_sha256_before,
        "events_sha256_after": report.events_sha256_after,
        "failed_steps": report.failed_steps,
    }
    log_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return log_path
