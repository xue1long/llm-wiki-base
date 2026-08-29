"""Tests for Knowledge Core backup + restore API (路线 v2.2 §C-0.5a, Z-1).

4 TDD tests for src/kc/backup/core_snapshot.py:

1. create_snapshot writes dump + identity keys + MANIFEST to .llm-wiki/backups/<ts>/
2. restore_snapshot validates identity_key (KnowledgeObject.id) consistency
3. MANIFEST.yaml contains spec §5.13 required fields incl. before_hash/after_hash
4. .llm-wiki/backups/ is whitelisted in src/maintenance/cache_cleanup.py

NOTE: 路线文档使用 "identity_key" 一词规划未来 B-2.5 字段; 当前实现以现有
KnowledgeObject.id 作为对象唯一标识（v2.1 状态）。测试断言 KO.id 列表一致性
等价于"identity_key 一致性"语义保证。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.knowledge.core.version_manager import (
    _serialize_object,
    _deserialize_object,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


# ── helpers ───────────────────────────────────────────────────────────────


def _make_object(obj_id: str, title: str = "", content: str = "") -> KnowledgeObject:
    """Minimal KnowledgeObject fixture for backup tests."""
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.ENTITY,
        title=title or f"Title {obj_id}",
        content=content or f"content of {obj_id}",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path=f"/test/{obj_id}.md"),
        grade="B",
        heat=50,
    )


def _read_manifest(backup_dir: Path) -> dict:
    """Parse MANIFEST.yaml from backup_dir."""
    import yaml

    return yaml.safe_load((backup_dir / "MANIFEST.yaml").read_text(encoding="utf-8"))


# ── Test 1: create_snapshot writes dump + identity keys + MANIFEST ────────


def test_create_snapshot_writes_to_llm_wiki_backups(tmp_path):
    """create_snapshot 在 .llm-wiki/backups/<snapshot_id>/ 写 4 文件."""
    from src.kc.backup.core_snapshot import create_snapshot

    paths = ensure_knowledge_base(tmp_path)
    objects = [_make_object("ko-a", title="A"), _make_object("ko-b", title="B"), _make_object("ko-c", title="C")]

    snap = create_snapshot(paths, objects=objects)

    # 1. 返回 Snapshot dataclass 含 snapshot_id
    assert isinstance(snap.snapshot_id, str) and snap.snapshot_id.startswith("snap_")
    assert snap.object_count == 3
    assert sorted(snap.identity_keys) == ["ko-a", "ko-b", "ko-c"]

    # 2. 写盘到 .llm-wiki/backups/<snapshot_id>/
    backup_dir = paths.llm_wiki / "backups" / snap.snapshot_id
    assert backup_dir.is_dir(), f"Expected backup dir at {backup_dir}"

    # 3. 4 个文件都在
    assert (backup_dir / "snapshot.json").is_file()
    assert (backup_dir / "identity_keys.txt").is_file()
    assert (backup_dir / "version_events.jsonl").is_file()
    assert (backup_dir / "MANIFEST.yaml").is_file()

    # 4. snapshot.json 含 3 KO，按 id 索引
    snapshot_data = json.loads((backup_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert set(snapshot_data.keys()) == {"ko-a", "ko-b", "ko-c"}
    assert snapshot_data["ko-a"]["title"] == "A"

    # 5. identity_keys.txt 含 3 行按字典序
    keys_text = (backup_dir / "identity_keys.txt").read_text(encoding="utf-8")
    assert keys_text.strip().split("\n") == ["ko-a", "ko-b", "ko-c"]


# ── Test 2: restore_snapshot validates identity_key consistency ──────────


def test_restore_validates_identity_key_consistency(tmp_path):
    """restore 还原后 KO.id 列表与 snapshot 时一致；被改的 KO 恢复原值."""
    from src.kc.backup.core_snapshot import create_snapshot, restore_snapshot

    paths = ensure_knowledge_base(tmp_path)
    objs_v1 = [
        _make_object("ko-1", title="O1", content="alpha"),
        _make_object("ko-2", title="O2", content="beta"),
        _make_object("ko-3", title="O3", content="gamma"),
    ]
    snap = create_snapshot(paths, objects=objs_v1)

    # 模拟: 修改 KO 内容后调用 restore
    modified = [
        _make_object("ko-1", title="O1", content="CHANGED"),
        _make_object("ko-2", title="O2", content="beta"),
        _make_object("ko-3", title="O3", content="gamma"),
    ]
    # 加 1 个原本不在 snapshot 的 KO，模拟数据漂移
    modified.append(_make_object("ko-extra", title="Extra", content="NEW"))

    report = restore_snapshot(snap.snapshot_id, paths, modified_objects=modified)
    assert report.reason_codes == ()
    assert report.identity_keys == sorted(["ko-1", "ko-2", "ko-3"])

    # KO.id 列表与 snapshot 时一致 (ko-extra 应被忽略，不在 snapshot 中)
    restored_dir = paths.llm_wiki / "backups" / snap.snapshot_id
    snapshot_data = json.loads((restored_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert set(snapshot_data.keys()) == {"ko-1", "ko-2", "ko-3"}
    # 被修改的 ko-1 已恢复原值 "alpha"
    assert snapshot_data["ko-1"]["content"] == "alpha"


# ── Test 3: MANIFEST.yaml contains spec §5.13 required fields ─────────────


def test_snapshot_manifest_contains_before_after_hash(tmp_path):
    """MANIFEST.yaml 含 snapshot_id/version_count/identity_count/before_hash/after_hash."""
    from src.kc.backup.core_snapshot import create_snapshot

    paths = ensure_knowledge_base(tmp_path)
    objects = [_make_object(f"ko-{i}", title=f"O{i}") for i in range(4)]

    snap = create_snapshot(paths, objects=objects)
    manifest = _read_manifest(paths.llm_wiki / "backups" / snap.snapshot_id)

    # 必填字段 (spec §5.13 Publication Batch)
    for required_key in (
        "snapshot_id",
        "version_count",
        "identity_count",
        "before_hash",
        "after_hash",
    ):
        assert required_key in manifest, f"MANIFEST missing required key: {required_key!r}"

    assert manifest["snapshot_id"] == snap.snapshot_id
    assert manifest["identity_count"] == 4
    assert isinstance(manifest["before_hash"], str) and len(manifest["before_hash"]) == 64
    assert isinstance(manifest["after_hash"], str) and len(manifest["after_hash"]) == 64

    # before_hash != after_hash (空 before vs 含 KO dump 的 after)
    assert manifest["before_hash"] != manifest["after_hash"]

    # 验证：相同对象 → 相同 after_hash (确定性, spec §5.13 必填字段)
    snap2 = create_snapshot(paths, objects=objects)
    manifest2 = _read_manifest(paths.llm_wiki / "backups" / snap2.snapshot_id)
    assert manifest["after_hash"] == manifest2["after_hash"], (
        "after_hash must be deterministic for identical object content"
    )
    # 但 snapshot_id 必须不同（不同时间戳）
    assert manifest["snapshot_id"] != manifest2["snapshot_id"]


# ── Test 4: backup dir whitelisted in cache_cleanup ───────────────────────


def test_backup_dir_whitelisted_in_cache_cleanup():
    """src/maintenance/cache_cleanup.py 不得误删 .llm-wiki/backups/ 内容.

    验收方式：grep 确认 cleanup_backups 的扫描目标仍是旧 schema 备份目录
    (.llm-wiki/.backup/), 不含新增的 (.llm-wiki/backups/)。同时新增
    cleanup_kc_backups() 函数含对 (paths.llm_wiki / "backups") 的白名单
    引用 (max_count 默认 10)。
    """
    src = Path("src/maintenance/cache_cleanup.py").read_text(encoding="utf-8")

    # 1. cleanup_backups 必须仍指向 .backup/ (schema migration backups)
    assert 'paths.llm_wiki / ".backup"' in src, (
        "cleanup_backups should still target schema-migration .backup/ dir"
    )

    # 2. 新增 cleanup_kc_backups 函数 (max_count 默认 10)
    assert "cleanup_kc_backups" in src, (
        "Cache cleanup must include cleanup_kc_backups() whitelisting .llm-wiki/backups/"
    )
    assert 'llm_wiki / "backups"' in src, (
        "cleanup_kc_backups must point at .llm-wiki/backups/ (NOT .backup/)"
    )
    assert "DEFAULT_KC_BACKUP_MAX_COUNT" in src
    assert "10" in src  # 默认 max_count

    # 3. cleanup_all() 注册 cleaners 时包含 cleanup_kc_backups
    cleanup_all_section = src.split("def cleanup_all")[1]
    assert '"kc_backups"' in cleanup_all_section, (
        "cleanup_all() must register the new kc_backups cleaner"
    )
    assert "cleanup_kc_backups" in cleanup_all_section
