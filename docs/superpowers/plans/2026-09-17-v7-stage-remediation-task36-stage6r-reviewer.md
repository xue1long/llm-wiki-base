# Plan: Task 36 — Stage 6R semantic reviewer（high-risk relation）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 36)

## 0. 上下文

Stage 6R `relation_extractor.py`（Task 25 落地）让 LLM 在 6 策略候选里裁决 relations，
最终产 `RelationAssertion`。

**盲区**：LLM 给的 relation 可能是 HIGH-risk 的：
- 数字类："X 比 Y 高 30%"
- 因果类："X 导致 Y"
- 反向类："X 不是 Y 的子类型"（否定）
- 比较类："X 优于 Y"

现有 12 invariant validator（Task 26）只做机械验证（target 存在、self-loop、predicate 合法等），
**不**判 relation 的语义是否被 cited evidence 真正支撑。

**Task 36 目标**：Stage 6R 在 relation 上做 reviewer pass，对 HIGH-risk predicate relation 二次裁决：
SUPPORTED / OVERSTATED / CONTRADICTED / UNRESOLVED。
CONTRADICTED 的 relation 不进 RelationStore。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. 每个 RelationAssertion 携带 `relation_review_status: RelationReviewStatus`
2. CONTRADICTED 的 relation 在 `filter_substantive_relations` 闸门之外再被丢弃
3. reviewer 失败 → 所有 HIGH-risk relation 标 UNRESOLVED（不进 store）

### 1.2 Non-Goal

- **不**改 Stage 6R 现有的 12 invariants（Task 26）
- **不**改 `RelationPredicate` 13 枚举（Task 23）
- **不**改 `RelationStore` 持久化 schema（Task 24）
- **不**改 relation_extractor 的现有调用链

## 2. 模型

```python
class RelationReviewStatus(str, Enum):
    SUPPORTED = "supported"           # relation 与 evidence 一致
    OVERSTATED = "overstated"         # relation 范围比 evidence 更宽
    CONTRADICTED = "contradicted"     # evidence 不支持 relation（不进 store）
    UNRESOLVED = "unresolved"         # 技术失败或证据不足

@dataclass
class RelationReviewRecord:
    relation_id: str                  # 来自 RelationKey.relation_id()（脚本 hash）
    source_page_id: str
    target_page_id: str
    predicate: RelationPredicate
    status: RelationReviewStatus
    reason: str                       # short, <=200 chars
    confidence: float                 # 0..1
    reviewer_fingerprint: str         # sha1(prompt + relation_hash)[:12]
    reviewed_at_ms: int
```

## 3. Files

- `src/pipeline/v7_extract/relation_reviewer.py`（新建）
- `src/pipeline/v7_extract/prompts/builtin/relation_reviewer.toml`（新建）
- `tests/test_pipeline/test_v7_extract_relation_reviewer.py`（新建）

## 4. Tests

```python
def test_relation_review_status_enum_has_four_values():
    """SUPPORTED / OVERSTATED / CONTRADICTED / UNRESOLVED"""

def test_relation_reviewer_only_invoked_for_high_risk_predicate():
    """low-risk predicate（refines/supported_by 等）→ 不进 reviewer"""

def test_relation_reviewer_rejects_overstated_causal_relation():
    """predicate='causes' 但 evidence 不含因果 → CONTRADICTED"""

def test_relation_reviewer_failure_marks_all_high_risk_unresolved():
    """LLM 失败 → 所有 HIGH-risk relation 标 UNRESOLVED"""

def test_relation_review_record_relation_id_matches_assertion_id():
    """RelationReviewRecord.relation_id == RelationAssertion.relation_id"""
```

## 5. Implementation

### 5.1 relation_reviewer.py

```python
MAX_RELATIONS_PER_REVIEW_CALL = 12  # 比 topic 多，因为 relation 有 evidence_refs

@dataclass
class RelationReviewInput:
    relation_id: str
    source_page_id: str
    target_page_id: str
    predicate: RelationPredicate
    evidence_excerpts: list[str]      # 来自 source_bytes[ref.start_byte:ref.end_byte]

_HIGH_RISK_PREDICATES: tuple[RelationPredicate, ...] = (
    RelationPredicate.CAUSES,
    RelationPredicate.REQUIRES,
    RelationPredicate.CONTRADICTS,
    RelationPredicate.DEPENDS_ON,
    RelationPredicate.EXTENDS,
    RelationPredicate.BROADER,        # 通过 canonical 反射后是 HIGH-risk（Task 35-36 一致性）
    RelationPredicate.NARROWER,
)

def is_high_risk_predicate(predicate: RelationPredicate) -> bool: ...

async def review_high_risk_relations(
    assertions: list[RelationAssertion],
    *,
    source_bytes: dict[str, bytes],
    llm: LLMClient,
    template = None,
    project_root = None,
    max_retries: int = 3,
) -> list[RelationReviewRecord]:
    """仅审 high-risk predicate. low-risk 直接返回 SUPPORTED without LLM.
    
    Technical failure → all high-risk relations UNRESOLVED.
    Never raises (Failure Contract §1).
    """
```

### 5.2 prompt template

```toml
[meta]
prompt_kind = "relation_reviewer"
version = "1.0"

[system]
text = """You are a V7 relation semantic reviewer. Verify HIGH-risk predicate
relations against their cited evidence. Reply with JSON only.

Verdicts (use EXACTLY):
  - "supported":   evidence supports the relation
  - "overstated":  relation is wider than evidence warrants
  - "contradicted": evidence contradicts the relation (caller will drop)
  - "unresolved":  insufficient evidence to decide

Cite relation_id verbatim from the user message. Do not invent ids."""

[user]
template = """\
Review these HIGH-risk predicate relations against their cited evidence.

Relation 1: id={rel_id_1}, {source} --[{predicate}]--> {target}
Evidence:
  - {excerpt_1a}
  - {excerpt_1b}

Relation 2: id={rel_id_2}, ...

For each return:
{"verdicts": [{"relation_id": "...", "verdict": "supported|overstated|contradicted|unresolved", "confidence": 0.0..1.0, "reason": "<=30 chars"}]}"""
```

### 5.3 不动 Stage 6R 已有模块

**F8 纪律**：不动 relation_extractor / relation_models / relation_store / candidate_retrieval。
reviewer 是**独立可调用模块**。Stage 6R caller 决定是否调用，本 Task 不接线。

## 6. Acceptance

- ✅ 4 个 verdict 值
- ✅ low-risk predicate 不进 reviewer
- ✅ HIGH-risk relation 受审：CONTRADICTED → caller 丢弃
- ✅ reviewer 整体失败 → 所有 HIGH-risk 标 UNRESOLVED
- ✅ RelationReviewRecord.relation_id == RelationAssertion.relation_id（脚本同步）
- ✅ 现有 58 v7_extract + 32 reconciliation 测试 0 回归
- ✅ 不引入新依赖

## 7. Status

draft → 等 plan-audit → in-progress → completed