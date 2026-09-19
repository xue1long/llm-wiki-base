# Plan: Task 45 — Stage 6R relation 基于 canonical_id（替换 page_id）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第三批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 45)

## 0. 上下文

Stage 6R `RelationKey.source_page_id` / `target_page_id` 是 page 维度的 relation
（Task 23）。但 Task 27 后 Phase 1 identity reconciliation 已经在 canonical_id 维度
做了跨源 page 收敛。**一个 canonical 内的多个 page 不应互相产生 intra-canonical relations**
（应该通过 canonical 自身），而跨 canonical 的 relations 才是 Stage 6R 的真正对象。

**Task 45 目标**：增加 `CanonicalRelationKey`，Stage 6R 在已应用 identity reconciliation
的项目上，从 `RelationAssertion` 投影出 `CanonicalRelation`：
- source_canonical_id / target_canonical_id 通过 `CanonicalRegistry.get_by_alias` /
  `get_concept(page_id)` 反查
- canonical 维度 relation 持久化到 `.index/reconciliation/canonical_relations.jsonl`

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `CanonicalRelationKey.canonical_id_a` / `canonical_id_b` / `predicate`
2. `derive_canonical_relation(page_relation_or_assertion, *, registry)` 把 page-level
   relation 投影到 canonical-level
3. 持久化：`<.index/reconciliation/canonical_relations.jsonl>`
4. 4 个测试覆盖：投影 round-trip / unknown page → None / same canonical skip

### 1.2 Non-Goal

- **不**改 RelationPredicate / RelationKey（page 维度）
- **不**改 RelationStore 主流程（独立可调用）
- **不**调用 LLM

## 2. 模型

```python
@dataclass(frozen=True)
class CanonicalRelationKey:
    canonical_id_a: str       # sorted for symmetric predicates
    canonical_id_b: str
    predicate: RelationPredicate

    def relation_id(self) -> str:
        identity = f"{self.canonical_id_a}|{self.predicate.value}|{self.canonical_id_b}"
        return "crel-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]

@dataclass
class CanonicalRelation:
    key: CanonicalRelationKey
    relation_id: str
    confidence: float
    source_page_ids: list[str]    # 派生自 source canonical 的所有 member page_ids
    target_page_ids: list[str]
    support_status: RelationSupportStatus
```

## 3. Files

- `src/reconciliation/canonical_relations.py`（新建）
- `tests/test_reconciliation/test_canonical_relations.py`（新建）

## 4. Tests

```python
def test_derive_canonical_relation_resolves_pages_via_registry():
    """2 page-level relations between same canonical pair → 1 canonical relation"""

def test_derive_canonical_relation_returns_none_for_unknown_page():
    """page_id 不在 registry → None"""

def test_derive_canonical_relation_symmetric_canonical_fold():
    """related_to 对称：page_a→page_b 与 page_b→page_a → 同 canonical relation"""

def test_derive_canonical_relation_skips_intra_canonical_pairs():
    """source page 与 target page 同 canonical → skip（不创建 intra-canonical relation）"""
```

## 5. Implementation

```python
def derive_canonical_relation(
    assertion: RelationAssertion | PageRelation,
    *,
    registry: CanonicalRegistry,
) -> CanonicalRelation | None:
    """Resolve assertion's source/target page_ids to canonical_ids via registry.
    
    Returns None if either side is unknown to the registry.
    Skips pairs whose source and target belong to the SAME canonical
    (intra-canonical relations are not Stage 6R's job).
    """
```

## 6. Acceptance

- ✅ 4 个测试全绿
- ✅ 不引入新依赖
- ✅ 现有 38 reconciliation + 53+ v7_extract 测试 0 回归