"""Tests for RelationRegistry (B-2.10 commit 2).

路线 v2.2 §B-2.10 commit 2 — RelationRegistry dataclass + load/save/is_allowed.

TDD coverage (7 tests):
1. ``RelationRegistry.load(yaml_path)`` 返回 registry 含 9 spec + 17 legacy
2. ``registry.is_allowed('is_a')`` → ``(True, 'spec')``
3. ``registry.is_allowed('part_of')`` → ``(True, 'spec')``
4. ``registry.is_allowed('is_part_of')`` → ``(True, 'legacy')`` (WikiPage 17 类)
5. ``registry.is_allowed('x-novel-character-arc')`` → ``(True, 'custom')`` (x-* 已登记)
6. ``registry.is_allowed('x-unknown-relation')`` → ``(False, 'custom_unregistered')`` (x-* 未登记)
7. ``registry.is_allowed('foobar')`` → ``(False, 'unknown')`` (不在 registry)

集成:
- spec §3.6 9 类受控关系
- WikiPage 17 类 built-in 兼容历史 (mode: legacy)
- x-* 自定义命名空间 (mode: custom, 必须登记到 .kc/relation_registry.yaml)
- ADR: docs/adr/2026-08-26-relation-registry.md

Ref: docs/architecture/B-2_11_Gate_design.md §3.10 + spec §3.6 + §11.2
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.kc.contracts.relation_registry import (
    RelationMode,
    RelationRegistry,
    RelationType,
)


# 仓库 .kc/relation_registry.yaml 路径 (commit 1 已创建)
REGISTRY_YAML_PATH = Path(__file__).parent.parent.parent / ".kc" / "relation_registry.yaml"


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> RelationRegistry:
    """加载真实 .kc/relation_registry.yaml 作为测试 fixture."""
    return RelationRegistry.load(REGISTRY_YAML_PATH)


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestRelationRegistryLoad:
    """spec §3.6: 9 spec + 17 legacy + x-* custom 三类受控关系."""

    def test_load_returns_registry_with_9_spec_17_legacy(self, registry):
        """RelationRegistry.load(yaml_path) 返回 registry 含 9 spec + 17 legacy.

        ADR-003 决策: spec §3.6 9 类受控 + WikiPage 17 类 legacy 兼容.
        """
        # spec §3.6 9 类
        assert len(registry.spec_relations) == 9
        spec_names = {r.name for r in registry.spec_relations}
        expected_spec = {
            "is_a", "part_of", "related_to", "depends_on", "supports",
            "contradicts", "example_of", "supersedes", "derived_from",
        }
        assert spec_names == expected_spec

        # WikiPage 17 类 legacy (含与 spec 重名 5 类)
        assert len(registry.legacy_relations) == 17
        legacy_names = {r.name for r in registry.legacy_relations}
        # WikiPage 17 类 (src/wiki/features/relations.py 枚举值)
        expected_legacy = {
            "is_part_of", "contains", "references", "referenced_by",
            "causes", "caused_by", "supports", "supported_by",
            "supersedes", "superseded_by", "depends_on", "required_by",
            "analogous_to", "opposite_of", "derived_from", "derives",
            "contradicts",
        }
        assert legacy_names == expected_legacy

        # custom namespace
        assert registry.custom_prefix == "x-"
        assert "x-novel-character-arc" in registry.custom_existing

    def test_load_sets_version_and_spec_version(self, registry):
        """registry.version == 1, spec_version == 'KC v2.1 §3.6'."""
        assert registry.version == 1
        assert registry.spec_version == "KC v2.1 §3.6"


class TestRelationRegistryIsAllowed:
    """RelationRegistry.is_allowed() 5 类判定 (spec / legacy / custom / custom_unregistered / unknown)."""

    def test_spec_relation_is_a_returns_spec(self, registry):
        """is_a 是 spec §3.6 受控关系 → (True, 'spec')."""
        assert registry.is_allowed("is_a") == (True, "spec")

    def test_spec_relation_part_of_returns_spec(self, registry):
        """part_of 是 spec §3.6 受控关系 → (True, 'spec')."""
        assert registry.is_allowed("part_of") == (True, "spec")

    def test_legacy_relation_is_part_of_returns_legacy(self, registry):
        """is_part_of 是 WikiPage built-in → (True, 'legacy') (兼容历史, 推荐用 spec part_of)."""
        assert registry.is_allowed("is_part_of") == (True, "legacy")

    def test_custom_registered_relation_returns_custom(self, registry):
        """x-novel-character-arc 是已登记的 x-* 命名空间 → (True, 'custom')."""
        assert registry.is_allowed("x-novel-character-arc") == (True, "custom")

    def test_custom_unregistered_relation_returns_custom_unregistered(self, registry):
        """x-unknown-relation 是未登记的 x-* 命名空间 → (False, 'custom_unregistered') (需 ADR)."""
        assert registry.is_allowed("x-unknown-relation") == (False, "custom_unregistered")

    def test_unknown_relation_returns_unknown(self, registry):
        """foobar 不在 registry 中 (不在 spec / legacy / x-* 已登记) → (False, 'unknown')."""
        assert registry.is_allowed("foobar") == (False, "unknown")


class TestRelationRegistrySpecRelationFields:
    """spec §3.6 9 类受控关系字段完整性 (mode / spec_ref / inverse / description)."""

    def test_spec_relation_has_mode_spec(self, registry):
        """spec §3.6 9 类必须 mode='spec'."""
        for rel in registry.spec_relations:
            assert rel.mode == "spec", f"{rel.name} should have mode='spec'"

    def test_legacy_relation_has_mode_legacy(self, registry):
        """WikiPage 17 类 built-in 必须 mode='legacy'."""
        for rel in registry.legacy_relations:
            assert rel.mode == "legacy", f"{rel.name} should have mode='legacy'"


class TestRelationRegistrySave:
    """RelationRegistry.save() 反向序列化 (供后续 ADR 登记时使用)."""

    def test_save_writes_yaml_with_9_spec_17_legacy(self, registry, tmp_path):
        """save() 写到 YAML 后重新 load 应得到等价 registry."""
        out_path = tmp_path / "out_registry.yaml"
        registry.save(out_path)

        reloaded = RelationRegistry.load(out_path)
        assert len(reloaded.spec_relations) == len(registry.spec_relations)
        assert len(reloaded.legacy_relations) == len(registry.legacy_relations)
        assert reloaded.custom_prefix == registry.custom_prefix
        assert set(reloaded.custom_existing) == set(registry.custom_existing)