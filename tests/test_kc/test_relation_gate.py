"""Tests for Relation Gate (B-2.10 commit 3).

路线 v2.2 §B-2.10 commit 3 — spec §11.2 Gate 10: 关系类型在受控集合中.

TDD coverage (6 tests):
1. ``RelationGate.check(non_wiki_page_object)`` → pass (helper: 不适用)
2. ``RelationGate.check(WikiPage_with_spec_relation)`` → pass (spec §3.6 9 类)
3. ``RelationGate.check(WikiPage_with_legacy_relation)`` → warn +
   ``legacy_relation_prefer_spec:<name>`` (WikiPage 17 类兼容历史)
4. ``RelationGate.check(WikiPage_with_x_registered_relation)`` → pass (registry 注入时)
5. ``RelationGate.check(WikiPage_with_x_unregistered_relation)`` → block +
   ``x_unregistered:<name>`` (x-* 未登记需 ADR)
6. ``RelationGate.check(WikiPage_with_unknown_relation)`` → block +
   ``unknown_relation:<name>`` (不在 registry)

集成:
- spec §11.2 Gate 10 完整实现
- spec §3.6 9 类受控关系 + WikiPage 17 类 built-in + x-* 自定义命名空间
- B-2.10 commit 1 ADR + commit 2 RelationRegistry (顶层直调 is_allowed())
- A-4 Approval Gate (relation 创建 = merge/split/supersede/concept_identity_change)
  留 known_limitations (由 IntegrityGate 流水线集成)

Ref: docs/architecture/B-2_11_Gate_design.md §3.10 + spec §11.2/§3.6 + ADR-003
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.kc.contracts.relation_registry import RelationRegistry
from src.kc.integrity.gates import RelationGate


# 仓库 .kc/relation_registry.yaml 路径 (commit 1 已创建)
REGISTRY_YAML_PATH = Path(__file__).parent.parent.parent / ".kc" / "relation_registry.yaml"


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


@dataclass
class NonWikiPageObject:
    """Relation Gate 不直接处理的对照对象 (无 relations 字段).

    用于验证 Relation Gate 对非 WikiPage / 非 KnowledgeObject 的处理路径
    (helper: 不适用 → pass).
    """

    id: str = "x"
    value: int = 42


@dataclass
class FakeRelation:
    """Relation-like 对象 (含 type 字段). WikiPage.relations 元素."""

    type: str
    target_id: str = "target_xyz"


@dataclass
class FakeWikiPage:
    """Relation Gate 测试用的伪 WikiPage 对象 (含 relations 字段).

    字段:
        id: 对象 id
        relations: list[FakeRelation] — WikiPage 关系列表
    """

    id: str
    relations: list[FakeRelation] = field(default_factory=list)


@pytest.fixture(scope="module")
def registry() -> RelationRegistry:
    """加载真实 .kc/relation_registry.yaml 作为测试 fixture."""
    return RelationRegistry.load(REGISTRY_YAML_PATH)


@pytest.fixture(scope="module")
def gate_with_registry(registry: RelationRegistry) -> RelationGate:
    """注入 RelationRegistry 的 RelationGate (B-2.10 完整路径)."""
    return RelationGate(registry=registry)


@pytest.fixture
def gate_no_registry() -> RelationGate:
    """不注入 registry 的 RelationGate (内联简化判定, 仅检查 x-* 格式)."""
    return RelationGate(registry=None)


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestRelationGate:
    """spec §11.2 Gate 10: 关系类型在受控集合中."""

    def test_non_wiki_page_object_passes(self, gate_with_registry):
        """无 relations 字段对象 → pass (helper: 不适用, 与 RetrievalGate 同模式)."""
        obj = NonWikiPageObject(id="ko_no_relations_field")
        verdict = gate_with_registry.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert "pass" in verdict.reasons

    def test_wiki_page_with_spec_relation_passes(self, gate_with_registry):
        """WikiPage 含 spec §3.6 9 类关系 → pass (例如 is_a / part_of)."""
        page = FakeWikiPage(
            id="wp_spec",
            relations=[FakeRelation(type="is_a"), FakeRelation(type="part_of")],
        )
        verdict = gate_with_registry.check(page)

        assert verdict.passed is True
        assert verdict.severity == "info"
        # 没有 block / warn reason
        assert not any(r.startswith("legacy_") for r in verdict.reasons)
        assert not any(r.startswith("unknown_") for r in verdict.reasons)
        assert not any(r.startswith("x_") for r in verdict.reasons)

    def test_wiki_page_with_legacy_relation_warns(self, gate_with_registry):
        """WikiPage 含 WikiPage 17 类 built-in → warn + legacy_relation_prefer_spec:<name>.

        注意: spec §3.6 9 类中 depends_on / supports / supersedes / contradicts /
        derived_from 与 WikiPage 重名, spec 优先; 测试用 WikiPage 独有
        is_part_of (WikiPage built-in, 不在 spec 中) → 命中 legacy.
        """
        page = FakeWikiPage(
            id="wp_legacy",
            relations=[FakeRelation(type="is_part_of")],
        )
        verdict = gate_with_registry.check(page)

        # legacy → passed=True (warn, 不阻断)
        assert verdict.passed is True
        assert verdict.severity == "warn"
        assert "legacy_relation_prefer_spec:is_part_of" in verdict.reasons

    def test_wiki_page_with_registered_custom_relation_passes(self, gate_with_registry):
        """WikiPage 含 x-* 已登记关系 → pass (registry 注入时走 is_allowed())."""
        page = FakeWikiPage(
            id="wp_custom_registered",
            relations=[FakeRelation(type="x-novel-character-arc")],
        )
        verdict = gate_with_registry.check(page)

        assert verdict.passed is True
        # 不应触发 unknown_/x_unregistered
        assert not any(r.startswith("unknown_") for r in verdict.reasons)
        assert not any(r.startswith("x_unregistered") for r in verdict.reasons)

    def test_wiki_page_with_unregistered_custom_relation_blocks(self, gate_with_registry):
        """WikiPage 含 x-* 未登记关系 → block + x_unregistered:<name> (需 ADR)."""
        page = FakeWikiPage(
            id="wp_custom_unregistered",
            relations=[FakeRelation(type="x-unknown-fictional-relation")],
        )
        verdict = gate_with_registry.check(page)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "x_unregistered:x-unknown-fictional-relation" in verdict.reasons

    def test_wiki_page_with_unknown_relation_blocks(self, gate_with_registry):
        """WikiPage 含完全未知关系 (不在 spec / legacy / x-*) → block + unknown_relation:<name>."""
        page = FakeWikiPage(
            id="wp_unknown",
            relations=[FakeRelation(type="foobar_random_thing")],
        )
        verdict = gate_with_registry.check(page)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "unknown_relation:foobar_random_thing" in verdict.reasons
