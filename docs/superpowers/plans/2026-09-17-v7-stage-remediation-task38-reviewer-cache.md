# Plan: Task 38 — Stage 5 reviewer cache（避免重复审同一 claim）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 38)

## 0. 上下文

Task 17 落地 `claim_reviewer.review_high_risk_claims()`：每次 ingest 重跑都会让 LLM
重新审同一组 HIGH-risk claims。同一 source 的二次 apply + 同 prompt 不会变 outcome，但
**LLM 重跑浪费 token** + 每次都重新生成 verdict。

**Task 38 目标**：claim_reviewer 增加**简单本地缓存层**，避免对 verbatim 同一 (claim_text,
evidence_refs 序列化) 的二次审。缓存 key 派生是 deterministic 的：
- hash(claim_text + sorted(evidence_ref_byte_ranges) + reviewer_fingerprint)

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. claim_reviewer 增加 cache 参数（默认 None 表示禁用）
2. 命中缓存 → 直接返回上次 verdict，**不消耗 LLM**
3. cache 持久化到 `.index/reviewer_cache.jsonl`（append-only）

### 1.2 Non-Goal

- **不**改 claim_reviewer 的 verdict 语义
- **不**做跨 source 共享 cache（每 source 自己的 cache）
- **不**做 LLM-side 优化（prompt caching 等外部机制）

## 2. Files

- `src/pipeline/v7_extract/claim_reviewer.py`（修改：增加 cache 参数）
- `tests/test_pipeline/test_v7_extract_claim_reviewer.py`（追加测试）

## 3. Tests

```python
@pytest.mark.asyncio
async def test_reviewer_cache_hits_on_identical_claim():
    """cache 命中 → 不调 LLM"""

@pytest.mark.asyncio
async def test_reviewer_cache_misses_on_different_evidence():
    """evidence_refs 不同 → cache miss"""

@pytest.mark.asyncio
async def test_reviewer_cache_persists_to_jsonl(tmp_path):
    """cache 落 .index/reviewer_cache.jsonl"""
```

## 4. Implementation

### 4.1 claim_reviewer.py 改动

在 `review_high_risk_claims` 接受 `cache: ReviewerCache | None = None`：
1. 对每个 HIGH claim，先算 cache_key
2. 命中 → 直接读 verdict，跳过 LLM
3. 未命中 → 走 LLM，verdict 写入 cache

```python
@dataclass
class ReviewerCacheEntry:
    cache_key: str
    claim_id: str
    verdict: ReviewerVerdict
    confidence: float
    reason: str
    reviewed_at_ms: int

class ReviewerCache:
    def __init__(self, root: Path | str):
        self.root = Path(root)
    
    def get(self, cache_key: str) -> ReviewerCacheEntry | None: ...
    
    def put(self, entry: ReviewerCacheEntry) -> None: ...   # append to .index/reviewer_cache.jsonl
    
    def _cache_key(self, claim_text: str, evidence_refs: list[EvidenceRef],
                   reviewer_fingerprint: str) -> str:
        sorted_ranges = sorted([(r.start_byte, r.end_byte) for r in evidence_refs])
        identity = f"{claim_text}|{sorted_ranges}|{reviewer_fingerprint}"
        return "rc-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
```

### 4.2 现有 API 兼容性

**F8 纪律**：`review_high_risk_claims` 旧签名 `cache=None` 时**行为不变**（不读不写 cache）。
现有 8 个 claim_reviewer 测试 0 回归。

## 5. Acceptance

- ✅ cache 命中时不调 LLM
- ✅ 不同 evidence → cache miss
- ✅ 持久化到 `.index/reviewer_cache.jsonl`
- ✅ 现有 8 个 claim_reviewer 测试 0 回归
- ✅ 不引入新依赖