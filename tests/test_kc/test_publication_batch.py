"""Tests for B-4 Publication Batch (spec §5.13 + §17 D-21)."""
from __future__ import annotations

import pytest

from src.kc.publish.batch import (
    ObjectVersion,
    PublicationGate,
)


def test_create_batch_preparing():
    """create_batch → preparing, publication_version=1."""
    gate = PublicationGate()
    batch = gate.create_batch([ObjectVersion("claim", "c1", 1)])
    assert batch.status == "preparing"
    assert batch.publication_version == 1
    assert batch.batch_id.startswith("pub_1_")
    assert len(batch.object_versions) == 1


def test_publish_batch_switches_water_level():
    """publish_batch → published + current_version 更新到 1."""
    gate = PublicationGate()
    batch = gate.create_batch([ObjectVersion("claim", "c1", 1)])
    published = gate.publish_batch(batch.batch_id)
    assert published.status == "published"
    assert published.published_at is not None
    assert gate.current_version == 1
    assert gate.is_current(1) is True


def test_publish_batch_repeat_raises():
    """重复发布 → ValueError."""
    gate = PublicationGate()
    batch = gate.create_batch([ObjectVersion("claim", "c1", 1)])
    gate.publish_batch(batch.batch_id)
    with pytest.raises(ValueError):
        gate.publish_batch(batch.batch_id)


def test_withdraw_batch():
    """withdraw_batch → withdrawn."""
    gate = PublicationGate()
    batch = gate.create_batch([ObjectVersion("claim", "c1", 1)])
    gate.publish_batch(batch.batch_id)
    withdrawn = gate.withdraw_batch(batch.batch_id)
    assert withdrawn.status == "withdrawn"
    # 撤回后 current_version 保持 1（默认水位不自动回退，需显式切换）
    assert gate.current_version == 1


def test_persist_load_roundtrip(tmp_path):
    """persist() + load() → 状态一致."""
    state_path = tmp_path / "pub_state.json"
    gate = PublicationGate(state_path=state_path)
    batch = gate.create_batch(
        [ObjectVersion("claim", "c1", 1), ObjectVersion("evidence", "e1", 2)],
        invalidated_object_ids=["old_claim_0"],
    )
    gate.publish_batch(batch.batch_id)
    gate.persist()

    loaded = PublicationGate(state_path=state_path).load()
    assert loaded.current_version == 1
    assert len(loaded._active_batches) == 1
    restored = loaded._active_batches[batch.batch_id]
    assert restored.status == "published"
    assert restored.publication_version == 1
    assert len(restored.object_versions) == 2
    assert restored.invalidated_object_ids == ("old_claim_0",)


def test_publish_batch_nonexistent_raises():
    """发布不存在的 batch → KeyError."""
    gate = PublicationGate()
    with pytest.raises(KeyError):
        gate.publish_batch("pub_does_not_exist")


def test_is_current_false_for_old_version():
    """旧版本 → is_current=False."""
    gate = PublicationGate()
    batch1 = gate.create_batch([ObjectVersion("claim", "c1", 1)])
    gate.publish_batch(batch1.batch_id)
    batch2 = gate.create_batch([ObjectVersion("claim", "c2", 1)])
    gate.publish_batch(batch2.batch_id)
    assert gate.current_version == 2
    assert gate.is_current(1) is False
    assert gate.is_current(2) is True
