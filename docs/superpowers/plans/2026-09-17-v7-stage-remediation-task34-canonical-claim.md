# Plan: Task 34 — CanonicalClaim 模型 + Phase 2 claim reconciliation

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批首个 Task，需 plan-audit)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 34)
**ADR:** 依赖 ADR 0012 (Knowledge Reconciliation Plane)

## 0. 上下文

Master plan 第一批（Tasks 1-33）已落地 Phase 1 identity reconciliation：
- `canonical_id` (c-<uuid4_hex[:16]>) 与 `page_id` 解耦
- `CanonicalRegistry` 收纳 page-level membership
- `ReconciliationDecision` 8 态裁决

**Phase 1 的盲区**：同一 canonical 内的多个 page 各有独立 claims（来自 Stage 5B）。
例如：canonical "扩句法" 收敛了 5 个 source-local page，每个 page 都有自己的
"扩句法是通过..." claim。**这些 claims 是不是"同一句"？是不是"互相印证"？是不是
"互相矛盾"？** Phase 1 完全不回答。

**Task 34 目标**：claim 维度跨 page 收敛。Phase 2 在 Phase 1 canonical 之上做
claim-level reconciliation，把同一 canonical 内的 member claims 按语义分桶。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. 每个 CanonicalConcept 可附带 0..N 个 `CanonicalClaim` 聚合视图（member claims 的
   SAME / OVERLAP / CONFLICT 分桶结果）
2. wiki page 输出时，从其 canonical 拉聚合 view，作为"该 canonical 下所有 source 的
   共识/分歧/冲突证据"

### 1.2 Non-Goal

- **不**做 claim-level LLM rewrite（"把 5 个 claim 合并成 1 句新的"）—— 留 Task 44
  (canonical claim projection)
- **不**做跨 canonical 的 same_as 传递闭包（"A=扩句法" + "B=扩句法" + "A=B"）——
  留第三批
- **不**改 page frontmatter（page view 仍 source-local，不写 canonical_claim_id）
- **不**改 Phase 1 identity reconciliation（独立 plane）

## 2. 模型

### 2.1 CanonicalClaim

```python
@dataclass
class CanonicalClaim:
    canonical_claim_id: str        # cc-<sha1(canonical_id + text_hash + support_kind)[:12]>
    canonical_id: str              # 隶属的 CanonicalConcept
    text: str                      # 聚合后的 canonical text（任务 44 投影，本 Task = member[0].text）
    member_claim_ids: list[str]    # 隶属的 member Claim.claim_id
    decision: ClaimReconciliationDecision
    confidence: float              # 0..1，加权平均
    support_kind: RelationSupportKind   # EXPLICIT / INFERRED / LLM_DIRECT / HEURISTIC
    created_at_ms: int
    updated_at_ms: int
```

### 2.2 ClaimReconciliationDecision（5 态，ReconciliationDecision 的子集）

```python
class ClaimReconciliationDecision(str, Enum):
    SAME = "same"                  # 多个 member claim 表达同一观点
    OVERLAP = "overlap"            # 部分重叠但不完全一致
    CONFLICT = "conflict"          # 互相矛盾
    UNRESOLVED = "unresolved"      # 技术失败或证据不足
    SINGLE = "single"              # 单一 member claim（无需聚合）
```

### 2.3 持久化布局

```
<project_root>/.index/reconciliation/
├── canonical_concepts.json          # 已有
├── alias_records.json               # 已有
├── decision_log.jsonl               # 已有
├── canonical_claims.json            # 新增：dict[canonical_claim_id -> CanonicalClaim]
└── claim_decision_log.jsonl         # 新增：每 claim 决策一行
```

## 3. Files

- `src/reconciliation/canonical_claim_models.py`（新建）— CanonicalClaim + ClaimReconciliationDecision
- `src/reconciliation/canonical_claim_registry.py`（新建）— CanonicalClaimRegistry + 持久化
- `src/reconciliation/claim_resolver.py`（新建）— claim_resolver 主入口
- `src/reconciliation/prompts/builtin/claim_resolve.toml`（新建）— LLM prompt
- `tests/test_reconciliation/test_canonical_claim_models.py`（新建）
- `tests/test_reconciliation/test_canonical_claim_registry.py`（新建）
- `tests/test_reconciliation/test_claim_resolver.py`（新建）

## 4. Tests（每个测试名 = 1 个 invariant）

```python
# test_canonical_claim_models.py
def test_canonical_claim_id_is_deterministic_hash():
    """cc-<sha1(canonical_id + text_hash + support_kind)[:12]>"""

def test_claim_decision_enum_has_five_values():
    """SAME / OVERLAP / CONFLICT / UNRESOLVED / SINGLE"""

def test_canonical_claim_member_ids_are_deduped():
    """add_member_claim idempotent"""

# test_canonical_claim_registry.py
def test_registry_persists_canonical_claims(tmp_path):
    """save + load round-trip"""

def test_apply_decisions_groups_same_claims_into_one_canonical_claim(tmp_path):
    """3 个 member claim 全部 SAME → 1 个 CanonicalClaim, member_claim_ids == 3"""

def test_apply_decisions_separates_conflicting_claims(tmp_path):
    """2 个 claim CONFLICT → 2 个 CanonicalClaim, 各自 1 member"""

def test_registry_reversible_per_claim(tmp_path):
    """remove_member_claim 撤销 + re-add 恢复"""

# test_claim_resolver.py
def test_llm_only_returns_decision_not_canonical_claim_id():
    """LLM 不输出 canonical_claim_id；脚本生成"""

def test_technical_failure_returns_unresolved():
    """LLM 全程失败 → 所有 claim 对 UNRESOLVED"""

def test_bounded_evidence_pack_per_claim_pair():
    """claim pair 的 evidence pack ≤ 1500B/claim"""
```

## 5. Implementation

### 5.1 CanonicalClaim 模型

```python
def canonical_claim_id_for(canonical_id: str, text: str, support_kind: str) -> str:
    text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    identity = f"{canonical_id}|{text_hash}|{support_kind}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"cc-{digest}"

@dataclass
class CanonicalClaim:
    canonical_claim_id: str
    canonical_id: str
    text: str
    member_claim_ids: list[str]
    decision: ClaimReconciliationDecision
    confidence: float
    support_kind: RelationSupportKind
    created_at_ms: int
    updated_at_ms: int
    resolver_fingerprint: str = ""

    def add_member_claim(self, claim_id: str) -> None:
        if claim_id not in self.member_claim_ids:
            self.member_claim_ids.append(claim_id)

    def remove_member_claim(self, claim_id: str) -> bool:
        try:
            self.member_claim_ids.remove(claim_id)
            return True
        except ValueError:
            return False
```

### 5.2 CanonicalClaimRegistry

```python
def canonical_claims_path(root) -> Path: ...
def claim_decision_log_path(root) -> Path: ...

class CanonicalClaimRegistry:
    def __init__(self, root, *, resolver_fingerprint=""): ...
    
    def load_canonical_claims(self) -> dict[str, CanonicalClaim]: ...
    def save_canonical_claims(self, claims: dict) -> None: ...
    
    def apply_claim_decisions(
        self,
        canonical_id: str,
        decisions: list[ClaimDecisionRecord],
        *,
        resolver_fingerprint: str = "",
    ) -> list[CanonicalClaim]:
        """priority: same > overlap > conflict > unresolved > single
        SAME/OVERLAP → join existing or new canonical_claim
        CONFLICT → separate canonical_claim per member
        SINGLE → 1 member, 1 canonical_claim (text = member[0].text)
        UNRESOLVED → skip
        """
    
    def remove_member_claim(self, canonical_claim_id: str, claim_id: str) -> bool:
        """如果 member_claim_ids 空 → 保留 CanonicalClaim 但 status=SINGLE"""
    
    def find_stale(self, current_fingerprint: str) -> list[str]:
        """F4 对齐：canonical_claim.resolver_fingerprint drift → STALE"""
```

### 5.3 ClaimResolver

```python
MAX_CLAIM_PAIRS_PER_RESOLVE_CALL = 50  # R1 整改：pair 上限避免 O(N^2) LLM

async def resolve_claim_identity(
    canonical_id: str,
    member_claims: list[Claim],
    *,
    source_bytes: dict[str, bytes],
    llm,
    template=None,
    project_root=None,
    resolver_fingerprint="",
    max_retries=3,
) -> list[ClaimDecisionRecord]:
    """LLM receives pair-wise candidate pairs (top-N within canonical, capped at
    MAX_CLAIM_PAIRS_PER_RESOLVE_CALL).
    Returns decisions (SAME / OVERLAP / CONFLICT / UNRESOLVED).
    LLM never generates canonical_claim_id.
    Technical failure → UNRESOLVED.
    """
```

### 5.4 Crash Recovery（Round 2 R2 整改）

```python
async def reconcile_unfinished_claim_resolutions(
    project_root: Path | str,
    *,
    current_fingerprint: str,
) -> list[str]:
    """Startup hook: scan claim_decision_log.jsonl, find canonical_ids with
    in-flight resolutions (apply_claim_decisions started but not finished).
    
    Mirrors Phase 1 `reconcile_unfinished_commits` pattern (Task 19).
    Returns canonical_ids needing retry.
    """
```

### 5.5 Trigger Hook（Round 1 R4 整改）

```python
async def reconcile_canonical_claims(
    canonical_ids: list[str],
    *,
    project_root: Path | str,
    llm,
    body_by_canonical: dict[str, dict[str, bytes]],
    resolver_fingerprint: str = "",
) -> ReconcileClaimResult:
    """Phase 2 main entry. Per canonical, run resolve_claim_identity + apply_claim_decisions.
    
    Trigger: after Phase 1 apply_decisions for a page, enqueue canonical_ids into
    claim_resolve_pending.jsonl; background job consumes pending list.
    """

## 6. Acceptance

- ✅ canonical_claim_id 是脚本生成（LLM 不参与）
- ✅ LLM 失败 → UNRESOLVED（永不抛异常）
- ✅ 同 canonical 内 3 个 claim SAME → 1 个 CanonicalClaim 含 3 members
- ✅ 2 个 claim CONFLICT → 2 个 CanonicalClaim 各自 1 member
- ✅ reversible：remove_member_claim 可撤销 + re-add 恢复
- ✅ F4 fingerprint drift 检测
- ✅ MAX_CLAIM_PAIRS_PER_RESOLVE_CALL=50 限制（避免 O(N^2) LLM 爆炸）
- ✅ `reconcile_unfinished_claim_resolutions` startup hook 恢复 in-flight resolution
- ✅ existing 23 reconciliation 测试 0 回归
- ✅ 不引入新依赖

## 7. Status

draft → 等 plan-audit Round 1/R2 + 人工复核 → in-progress → completed

---

**写于 2026-09-17 master plan 第二批启动**