# Plan: Task 44 — Canonical claim projection（canonical view from member claims）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第三批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 44)
**Depends:** Task 34 (`canonical_claim_models.py` + `canonical_claim_registry.py`)

## 0. 上下文

Task 34 落地 Phase 2 claim reconciliation 产出 `CanonicalClaim` 列表（每个聚合一组
member claims）。但 `CanonicalClaim.text` 当前是 placeholder（spec: `text = member[0].text`），
对 wiki 渲染没有直接用。

**Task 44 目标**：增加 projection 层，从 `CanonicalClaim` + member `Claim` 列表
投影出可渲染的 canonical view：
- `text`: SAME 决策下用"最有共识"的 member text（按 confidence 加权 + 共识度）；非
  SAME 时按 member text 直接列出
- `evidence_refs`: 聚合所有 member 的 evidence_refs（dedup by span）
- `confidence`: 加权平均
- `view_kind`: enum {SAME / OVERLAP / CONFLICT / SINGLE}

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `project_canonical_view(canonical_claim, member_claims, *, aggregation="consensus")`
   返回 `CanonicalClaimView` dataclass
2. `CanonicalClaimView` 含 (canonical_claim_id, view_kind, text, evidence_refs,
   confidence, member_summary)
3. 5 个测试覆盖：SAME / OVERLAP / CONFLICT / SINGLE / empty

### 1.2 Non-Goal

- **不**改 CanonicalClaim 模型
- **不**改 Phase 2 resolve_claim_identity 流程
- **不**调用 LLM

## 2. 模型

```python
class CanonicalViewKind(str, Enum):
    SAME = "same"                  # member claims 表达同一观点 → 共识文本
    OVERLAP = "overlap"            # 部分共识 → 多文本并列
    CONFLICT = "conflict"          # 互相矛盾 → 分别列出
    SINGLE = "single"              # 单一 member → 直接用

@dataclass
class CanonicalClaimView:
    canonical_claim_id: str
    view_kind: CanonicalViewKind
    text: str
    evidence_refs: list[Any]      # dedup by (item_id, start_byte, end_byte)
    confidence: float
    member_summary: str            # e.g. "3 members (SAME)"
```

## 3. Files

- `src/reconciliation/canonical_claim_projection.py`（新建）
- `tests/test_reconciliation/test_canonical_claim_projection.py`（新建）

## 4. Tests

```python
def test_projection_same_uses_consensus_text():
    """3 SAME members → text = 最高 confidence member + member_summary"""

def test_projection_overlap_lists_all_texts():
    """3 OVERLAP members → text = 三段文本以 \\n 分隔"""

def test_projection_conflict_lists_separately():
    """2 CONFLICT members → text = 两段以 '\\n---\\n' 分隔"""

def test_projection_single_uses_member_text_directly():
    """SINGLE → text = single member text"""

def test_projection_dedups_evidence_refs():
    """重复 evidence_ref → 只保留 1 个"""
```

## 5. Implementation

```python
def project_canonical_view(
    canonical_claim: CanonicalClaim,
    member_claims: list[Claim],
    *,
    aggregation: str = "consensus",
) -> CanonicalClaimView:
    """SAME: pick highest-confidence member as canonical text; member_summary
       lists all 3 members' text snippets.
    CONFLICT: text = each member text separated by '\\n---\\n' (markdown rule).
    OVERLAP: text = each member text separated by '\\n'.
    SINGLE: text = single member text directly.
    
    Always dedup evidence_refs by (item_id, start_byte, end_byte).
    """
```

## 6. Acceptance

- ✅ 5 个测试全绿
- ✅ 不引入新依赖
- ✅ 现有 32 reconciliation + 53+ v7_extract 测试 0 回归