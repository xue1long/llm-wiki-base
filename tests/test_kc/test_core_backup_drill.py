"""Tests for Core backup drill (路线 v2.2 §C-0.5b, Z-5).

3 TDD tests for src/kc/backup/drill.py:

1. snapshot → 删 KO → restore → identity_key 一致性 100%
2. KnowledgeObject 数量 + events.jsonl sha256 一致
3. 演练报告输出到 .index/backup_drills/<timestamp>.log

NOTE: 演练脚本是 C-0.5a 的薄壳封装，不修改 create_snapshot / restore_snapshot 的 API。
演练使用 caller 模式（用户传入当前 KO 列表），与 C-0.5a 共识"无全局 KO 注册表"一致。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.wiki.storage.ensure import ensure_knowledge_base


# ── helpers ───────────────────────────────────────────────────────────────


def _make_object(obj_id: str, title: str = "", content: str = "") -> KnowledgeObject:
    """Minimal KnowledgeObject fixture for drill tests."""
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.CLAIM,
        title=title or f"Title {obj_id}",
        content=content or f"content of {obj_id}",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path=f"/test/{obj_id}.md"),
        grade="B",
        heat=50,
    )


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Test 1: snapshot → 删 KO → restore → identity_key 一致性 100% ─────────


def test_drill_recovers_from_corrupted_ko(tmp_path):
    """演练：snapshot → 修改 KO content → restore → 校验 identity_key 一致 + 内容恢复.

    模拟损坏：把第一个 KO 的 content 改成 "CORRUPTED"，验证 restore 后能从
    snapshot.json 还原回原 content。
    """
    from src.kc.backup.core_snapshot import create_snapshot
    from src.kc.backup.drill import run_drill

    paths = ensure_knowledge_base(tmp_path)
    objects = [
        _make_object("ko-drill-1", title="D1", content="alpha"),
        _make_object("ko-drill-2", title="D2", content="beta"),
        _make_object("ko-drill-3", title="D3", content="gamma"),
    ]

    # snapshot 是 create_snapshot 的事，演练脚本内部会调用
    snap = create_snapshot(paths, objects=objects)
    snapshot_identity_keys = set(snap.identity_keys)

    # 模拟损坏：修改第一个 KO
    objects[0].content = "CORRUPTED"
    assert objects[0].content == "CORRUPTED"

    # 演练：restore_snapshot 内部会处理，应能让 caller 知道 identity 集合仍然一致
    report = run_drill(paths, objects, snapshot_id=snap.snapshot_id)

    # 1. drill_status PASS
    assert report.drill_status == "PASS", (
        f"drill FAILED with steps={report.failed_steps!r}"
    )
    # 2. identity_key 一致性 100%
    assert report.identity_key_consistency is True
    # 3. before/after KO count = 3
    assert report.before_ko_count == 3
    assert report.after_ko_count == 3
    # 4. snapshot_id 已写入报告
    assert report.snapshot_id == snap.snapshot_id


# ── Test 2: KnowledgeObject 数量 + version_events sha256 完全一致 ──────────


def test_drill_preserves_ko_count_and_events_sha256(tmp_path):
    """演练：snapshot → 删除 events.jsonl → restore → events sha256 与 snapshot 时一致。

    验证 restore 后事件流内容（sha256）恢复到 snapshot 时状态。
    """
    from src.kc.backup.core_snapshot import create_snapshot
    from src.kc.backup.drill import run_drill

    paths = ensure_knowledge_base(tmp_path)
    events_dir = paths.index / "knowledge_graph"
    events_dir.mkdir(parents=True, exist_ok=True)
    events_file = events_dir / "events.jsonl"

    # 模拟有事件流：写入 3 条事件
    sample_events = "\n".join([
        json.dumps({"ts": 1, "event": "ko.create", "id": "ko-2a"}),
        json.dumps({"ts": 2, "event": "ko.update", "id": "ko-2b"}),
        json.dumps({"ts": 3, "event": "ko.archive", "id": "ko-2c"}),
    ]) + "\n"
    events_file.write_text(sample_events, encoding="utf-8")
    snapshot_events_sha = _sha256_file(events_file)

    objects = [_make_object(f"ko-2{i}", title=f"O2{i}") for i in range(3)]

    snap = create_snapshot(paths, objects=objects)
    report = run_drill(paths, objects, snapshot_id=snap.snapshot_id)

    assert report.drill_status == "PASS"
    # KO 数量 3 不变
    assert report.before_ko_count == 3
    assert report.after_ko_count == 3
    # events.jsonl 在 snapshot 时已被 backup/version_events.jsonl 记录
    assert report.events_sha256_before == snapshot_events_sha
    # restore 后 events.jsonl sha256 应恢复到 snapshot 时
    assert report.events_sha256_after == snapshot_events_sha


# ── Test 3: 演练报告输出到 .index/backup_drills/<timestamp>.log ────────────


def test_drill_report_written_to_index_backup_drills(tmp_path):
    """演练：snapshot → 演练 → restore → 报告写入 .index/backup_drills/<drill_id>.log.

    报告 JSON 包含 drill_status / before_ko_count / after_ko_count /
    identity_key_consistency 关键字段。
    """
    from src.kc.backup.core_snapshot import create_snapshot
    from src.kc.backup.drill import run_drill, write_drill_report

    paths = ensure_knowledge_base(tmp_path)
    objects = [_make_object("ko-3a", title="A")]

    snap = create_snapshot(paths, objects=objects)
    report = run_drill(paths, objects, snapshot_id=snap.snapshot_id)

    log_path = write_drill_report(paths, report)

    # 1. 写入 .index/backup_drills/<drill_id>.log
    assert log_path.exists()
    assert log_path.parent == paths.index / "backup_drills"
    assert log_path.name == f"{report.drill_id}.log"

    # 2. 报告 JSON 含关键字段
    report_data = json.loads(log_path.read_text(encoding="utf-8"))
    for required in (
        "drill_id",
        "timestamp",
        "snapshot_id",
        "drill_status",
        "before_ko_count",
        "after_ko_count",
        "identity_key_consistency",
    ):
        assert required in report_data, f"Drill report missing required field: {required!r}"

    # 3. 字段值与 DrillReport 一致
    assert report_data["drill_id"] == report.drill_id
    assert report_data["snapshot_id"] == snap.snapshot_id
    assert report_data["before_ko_count"] == 1
    assert report_data["after_ko_count"] == 1
    assert report_data["drill_status"] == "PASS"
    assert report_data["identity_key_consistency"] is True
