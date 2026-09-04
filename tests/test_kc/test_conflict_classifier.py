"""Tests for Conflict 6-Type Classifier (A-3 / G6, spec §8.2).

6 TDD tests covering the 6 conflict types defined in spec §8.2:

1. ``actual`` — same Context + contradictory propositions
2. ``conditional`` — partial Context overlap + explainable conditions
3. ``temporal`` — time ranges disjoint (priority supersede)
4. ``perspective`` — same scope + different stance (not contradictory)
5. ``none`` — Context disjoint (build related_to, not conflict)
6. ``unresolved`` — unknown dimension + potential mutual exclusion

Each test is intentionally independent of the implementation file
(``src.kc.conflicts.classifier``): until that module ships, every test in this
file must FAIL with ``ImportError`` or ``ModuleNotFoundError``. After the
module ships, all 6 must pass.

Maps directly to the 10 gold cases in ``docs/evaluation/cases/conflict.yaml``
(C-3.2 deliverable, commit 9aed7e2b).
"""
from __future__ import annotations



# NB: src.kc.conflicts.classifier is the module under test — it does not exist
# yet at the time these tests are authored, so the imports below are the red
# signal that kicks off TDD step 2.
from src.kc.conflicts.classifier import Conflict, ConflictClassifier


# ---------------------------------------------------------------------------
# Test 1: actual conflict (CF-001 / CF-002 in conflict.yaml)
# ---------------------------------------------------------------------------


def test_classify_actual():
    """相同 Context + 矛盾命题 → 'actual'.

    Mirrors CF-001 (novel_writing + 快 vs 慢) and CF-002 (data_analysis + sum=100 vs sum=200).
    spec §8.2 X-2: Context 与时间均重叠 + 命题不能同时成立 → actual.
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="Python 节奏要快",
        statement_b="Python 节奏要慢",
        context_a={"domain": "code", "platform": "web"},
        context_b={"domain": "code", "platform": "web"},
    )
    assert conflict.conflict_type == "actual"
    assert conflict.confidence >= 0.7


# ---------------------------------------------------------------------------
# Test 2: conditional conflict (CF-003 / CF-004 in conflict.yaml)
# ---------------------------------------------------------------------------


def test_classify_conditional():
    """部分重叠 Context + 不同条件 → 'conditional'.

    Mirrors CF-003 (TypeScript vs JavaScript, enterprise vs prototype) and CF-004
    (monolith vs microservice, team_size_lt_5 vs team_size_gt_20).
    spec §8.2 X-3: Context 部分重叠 + 条件可解释差异 → conditional.
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="use TypeScript for frontend",
        statement_b="use JavaScript for frontend",
        context_a={"domain": "software_engineering", "platform": "enterprise"},
        context_b={"domain": "software_engineering", "platform": "prototype"},
    )
    assert conflict.conflict_type == "conditional"


# ---------------------------------------------------------------------------
# Test 3: temporal conflict (CF-005 / CF-006 in conflict.yaml)
# ---------------------------------------------------------------------------


def test_classify_temporal():
    """时间不重叠 → 'temporal'.

    Mirrors CF-005 (Python 3.9 vs 3.12) and CF-006 (ruflo-kb v2.0 vs v2.2).
    spec §8.2 X-6: 时间不重叠 → supersede. Disjoint check uses ms timestamps.
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="Python 3.9 is the latest stable version",
        statement_b="Python 3.12 is the latest stable version",
        context_a={"domain": "technology", "platform": "web"},
        context_b={"domain": "technology", "platform": "web"},
        valid_from_a=1633008000000,  # 2021-10-01
        valid_to_a=1672531200000,    # 2023-01-01
        valid_from_b=1704067200000,  # 2024-01-01
        valid_to_b=None,
    )
    assert conflict.conflict_type == "temporal"


# ---------------------------------------------------------------------------
# Test 4: perspective conflict (CF-007 / CF-008 in conflict.yaml)
# ---------------------------------------------------------------------------


def test_classify_perspective():
    """相同范围不同立场 → 'perspective'.

    Mirrors CF-007 (carbon tax: environmentalist vs economist) and CF-008
    (标准化考试: education_policy_maker vs parent).
    spec §8.2 X-4: 事实范围相同但来源立场不同 → perspective (不视为互斥).
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="碳税减少排放",
        statement_b="碳税伤害经济",
        context_a={"domain": "policy", "platform": "web", "perspective": "environmentalist"},
        context_b={"domain": "policy", "platform": "web", "perspective": "economist"},
    )
    assert conflict.conflict_type == "perspective"


# ---------------------------------------------------------------------------
# Test 5: none conflict (CF-010 in conflict.yaml)
# ---------------------------------------------------------------------------


def test_classify_none():
    """Context 完全不重叠 → 'none'.

    Mirrors CF-010 (reading vs writing improves vocabulary — different skill_a / skill_b).
    spec §8.2 X-1: Context 不重叠 → 建立 related_to 关系，不冲突.
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="reading improves vocabulary",
        statement_b="writing improves vocabulary",
        context_a={"domain": "skill_a", "platform": "reading"},
        context_b={"domain": "skill_b", "platform": "writing"},
    )
    assert conflict.conflict_type == "none"


# ---------------------------------------------------------------------------
# Test 6: unresolved conflict (CF-009 in conflict.yaml)
# ---------------------------------------------------------------------------


def test_classify_unresolved():
    """决定性维度 unknown + 潜在互斥 → 'unresolved'.

    Mirrors CF-009 (Vitamin C prevents colds vs does not, both domain:unknown).
    spec §8.2 X-9 + §11.4 #7: 决定性维度 unknown + 潜在互斥 → unresolved + quarantine.
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="Vitamin C prevents colds",
        statement_b="Vitamin C does not prevent colds",
        context_a={"domain": "unknown"},
        context_b={"domain": "unknown"},
    )
    assert conflict.conflict_type == "unresolved"


# ---------------------------------------------------------------------------
# Bonus: API surface — Conflict dataclass + ConflictType literal
# ---------------------------------------------------------------------------


def test_conflict_dataclass_carries_all_signals():
    """Conflict dataclass must round-trip the inputs used for classification.

    A downstream consumer (resolution layer, audit log, eval harness) reads
    ``context_a`` / ``context_b`` / ``valid_from_*`` / ``valid_to_*`` to choose
    the right action. They must be preserved on the returned object.
    """
    c = ConflictClassifier()
    conflict = c.classify(
        statement_a="a",
        statement_b="b",
        context_a={"domain": "x"},
        context_b={"domain": "unknown"},
        valid_from_a=1000,
        valid_to_a=2000,
        valid_from_b=3000,
        valid_to_b=4000,
    )
    assert isinstance(conflict, Conflict)
    assert conflict.context_a == {"domain": "x"}
    assert conflict.context_b == {"domain": "unknown"}
    assert conflict.valid_from_a == 1000
    assert conflict.valid_to_a == 2000
    assert conflict.valid_from_b == 3000
    assert conflict.valid_to_b == 4000


def test_conflict_type_literal_set():
    """ConflictType is a closed enum of 6 spec §8.2 types — no drift allowed."""
    expected = {"actual", "conditional", "temporal", "perspective", "none", "unresolved"}
    # ConflictClassifier.classify returns Conflict whose conflict_type is one of these.
    c = ConflictClassifier()
    observed = set()
    samples = [
        ({"domain": "x"}, {"domain": "y"}),  # none
        ({"domain": "x", "p": "1"}, {"domain": "x", "p": "2"}),  # conditional
        ({"domain": "x"}, {"domain": "unknown"}),  # unresolved (unknown on b)
    ]
    for ca, cb in samples:
        observed.add(
            c.classify("s", "s", context_a=ca, context_b=cb).conflict_type
        )
    assert observed.issubset(expected)
    assert len(expected) == 6  # guard against accidental addition
