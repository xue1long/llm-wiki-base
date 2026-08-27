"""Tests for Conflict Gate (B-2.8 — spec §11.2 Gate 9 + §8.2 6 类冲突 + §11.4 #6/#7 硬门槛).

路线 v2.2 §B-2.8 — Conflict Gate 完整实现.

TDD coverage (5 tests):
1. ``ConflictGate.check(obj_no_candidate_b_context)`` → pass (helper: 仅在有候选
   比较对象时检查冲突, 缺则不适用)
2. ``ConflictGate.check(obj_with_actual_conflict)`` → block +
   ``actual_conflict:actual`` (spec §11.4 #6 — Actual Conflict 被覆盖即阻断)
3. ``ConflictGate.check(obj_with_unresolved_conflict)`` → block +
   ``unresolved_conflict:unresolved`` (spec §11.4 #7 — Unresolved Conflict
   被发布即阻断)
4. ``ConflictGate.check(obj_with_temporal_conflict_no_supersede)`` → block +
   ``temporal_conflict_no_supersede`` (spec §8.2 X-6 — temporal 冲突需建立
   supersede 关系才能放行, 否则阻断)
5. ``ConflictGate.check(obj_with_conditional_conflict)`` → warn +
   ``conditional_conflict`` (spec §8.2 X-3 — 条件冲突可发布但带限定, 不阻断)

集成:
- spec §8.2 6 类冲突: actual / conditional / temporal / perspective / none /
  unresolved
- spec §11.4 #6 / #7 硬门槛: Actual Conflict 被覆盖 > 0 / Unresolved Conflict
  被发布 > 0 → 阻断
- A-3 ConflictClassifier.classify() 6 类判定 (顶层直调, 非内联简化)
- Temporal Gate (B-2.7) 后接力: Conflict Gate 在比较路径上集成 A-3,
  复用 Context Gate (B-2.6) 的 candidate_b context 通道

Ref: docs/architecture/B-2_11_Gate_design.md §3.9 + spec §11.2/§8.2/§11.4
"""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.integrity.gates import ConflictGate, GateVerdict


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


@dataclass
class NonCandidateObject:
    """Conflict Gate 不直接调用 classify 的对照对象 (无 text/content 属性).
    用于验证仅当 candidate_b 存在时的 conflict 检查路径.
    """

    id: str = "x"
    value: int = 42


@dataclass
class ConflictObject:
    """Conflict Gate 测试用的对象 (含 A-3 ConflictClassifier 期望的所有字段).

    字段:
        id: 对象 id
        text: content attribute — A-3 ConflictClassifier.classify 的输入
        content: 备用 content attribute — A-3 classify 第二个候选源
        context_a: spec §5.1 Context dict (object a 侧)
        valid_from_a / valid_to_a: spec §10 T-2 时间边界 (object a 侧)
        context_b: 同上 (object b 侧, candidate_b)
        valid_from_b / valid_to_b: 同上
        superseded_by: spec §10 T-3 supersede 关系
        supersedes: spec §10 T-3 supersede 关系
    """

    id: str
    text: str = ""
    content: str = ""
    context_a: dict | None = None
    valid_from_a: int | None = None
    valid_to_a: int | None = None
    context_b: dict | None = None
    valid_from_b: int | None = None
    valid_to_b: int | None = None
    superseded_by: str | None = None
    supersedes: str | None = None


def _make_actual_conflict_pair() -> tuple[ConflictObject, ConflictObject]:
    """spec §8.2 X-2: 相同 Context + 矛盾命题 → actual 冲突.

    Mirrors CF-001 (novel_writing + 快 vs 慢). 这里 candidate_a 用
    "Python 节奏要快", candidate_b 用 "Python 节奏要慢", 二者在同一
    domain+platform context 下被 A-3 判定为 actual.
    """
    candidate_a = ConflictObject(
        id="ko_actual_a",
        text="Python 节奏要快",
        context_a={"domain": "code", "platform": "web"},
    )
    candidate_b = ConflictObject(
        id="ko_actual_b",
        text="Python 节奏要慢",
        context_b={"domain": "code", "platform": "web"},
    )
    return candidate_a, candidate_b


def _make_unresolved_conflict_pair() -> tuple[ConflictObject, ConflictObject]:
    """spec §8.2 X-9 + §11.4 #7: 决定性维度 unknown + 潜在互斥 → unresolved.

    candidate_a/b 共享 'platform' 键且至少一侧为 unknown, 触发
    _has_unknown_dimension (A-3 Rule 3) → unresolved.
    """
    candidate_a = ConflictObject(
        id="ko_unresolved_a",
        text="claim about platform X",
        content="claim about platform X",
        context_a={"domain": "code", "platform": "unknown"},
    )
    candidate_b = ConflictObject(
        id="ko_unresolved_b",
        text="claim about platform X",
        content="claim about platform X",
        context_b={"domain": "code", "platform": "unknown"},
    )
    return candidate_a, candidate_b


def _make_temporal_conflict_pair_no_supersede() -> tuple[ConflictObject, ConflictObject]:
    """spec §8.2 X-6: 时间不重叠 → temporal 冲突 (无 supersede 关系则阻断).

    candidate_a 的 valid_to_a=100, candidate_b 的 valid_from_b=200 →
    时间 disjoint → A-3 判定为 temporal. 但两者都没有 superseded_by /
    supersedes 字段 → Conflict Gate 应 block (temporal_conflict_no_supersede).
    """
    candidate_a = ConflictObject(
        id="ko_temporal_a",
        text="Python 3.9 is the latest stable version",
        context_a={"domain": "technology", "platform": "web"},
        valid_from_a=1633008000000,  # 2021-10-01
        valid_to_a=1672531200000,    # 2023-01-01
    )
    candidate_b = ConflictObject(
        id="ko_temporal_b",
        text="Python 3.12 is the latest stable version",
        context_b={"domain": "technology", "platform": "web"},
        valid_from_b=1704067200000,  # 2024-01-01
        valid_to_b=None,
    )
    return candidate_a, candidate_b


def _make_conditional_conflict_pair() -> tuple[ConflictObject, ConflictObject]:
    """spec §8.2 X-3: 部分 Context 重叠 → conditional (条件冲突可发布但带限定).

    Mirrors CF-003 (TypeScript vs JavaScript, enterprise vs prototype).
    candidate_a/b 共享 'domain' 但 'platform' 不同 → partial overlap →
    conditional.
    """
    candidate_a = ConflictObject(
        id="ko_cond_a",
        text="use TypeScript for frontend",
        content="use TypeScript for frontend",
        context_a={"domain": "software_engineering", "platform": "enterprise"},
    )
    candidate_b = ConflictObject(
        id="ko_cond_b",
        text="use JavaScript for frontend",
        content="use JavaScript for frontend",
        context_b={"domain": "software_engineering", "platform": "prototype"},
    )
    return candidate_a, candidate_b


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestConflictGate:
    """spec §11.2 Gate 9: 真实冲突不被静默覆盖."""

    def test_no_candidate_b_context_passes(self):
        """无 candidate_b context → pass (helper: 仅在候选比较对象存在时检查,
        否则不适用 — 与 Context Gate (B-2.6) 候选比较路径对称)."""
        gate = ConflictGate()
        obj = ConflictObject(id="ko_no_compare", text="standalone claim")

        # 不传 context 或 context 不含 candidate_b → 视为不适用 → pass
        verdict = gate.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_actual_conflict_blocks(self):
        """actual 冲突 (相同 Context + 矛盾命题) → block +
        ``actual_conflict:actual`` (spec §11.4 #6 — Actual Conflict 被覆盖即阻断
        默认发布)."""
        gate = ConflictGate()
        candidate_a, candidate_b = _make_actual_conflict_pair()

        context = {"candidate_b": candidate_b}
        verdict = gate.check(candidate_a, context=context)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "actual_conflict:actual" in verdict.reasons

    def test_unresolved_conflict_blocks(self):
        """unresolved 冲突 (决定性维度 unknown + 潜在互斥) → block +
        ``unresolved_conflict:unresolved`` (spec §11.4 #7 — Unresolved Conflict
        被发布即阻断默认发布)."""
        gate = ConflictGate()
        candidate_a, candidate_b = _make_unresolved_conflict_pair()

        context = {"candidate_b": candidate_b}
        verdict = gate.check(candidate_a, context=context)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "unresolved_conflict:unresolved" in verdict.reasons

    def test_temporal_conflict_no_supersede_blocks(self):
        """temporal 冲突但未建立 supersede 关系 → block +
        ``temporal_conflict_no_supersede`` (spec §8.2 X-6 — temporal 冲突需
        supersede 关系才能放行; 无 supersede 关系则阻断默认发布)."""
        gate = ConflictGate()
        candidate_a, candidate_b = _make_temporal_conflict_pair_no_supersede()

        context = {"candidate_b": candidate_b}
        verdict = gate.check(candidate_a, context=context)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "temporal_conflict_no_supersede" in verdict.reasons

    def test_conditional_conflict_warns(self):
        """conditional 冲突 (部分 Context 重叠 + 条件可解释差异) → warn +
        ``conditional_conflict`` (spec §8.2 X-3 — 条件冲突可发布但带限定,
        不阻断默认发布, 仅 warn 留痕)."""
        gate = ConflictGate()
        candidate_a, candidate_b = _make_conditional_conflict_pair()

        context = {"candidate_b": candidate_b}
        verdict = gate.check(candidate_a, context=context)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "conditional_conflict" in verdict.reasons