# Plan: Task 35 — Stage 4 reviewer（high-risk topic candidate）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 35)

## 0. 上下文

Stage 4 cluster_topics 已经产出 TopicCandidate（Task 11）。当前 LLM 在两阶段（discovery
+ grouping）里判定 candidate 集合 / topic 标题 / item_indexes。

**盲区**：LLM 给的 topic title 可能是：
- **HIGH-risk**："X 提高 10%" / "X 优于 Y" / "X 不适用于..." —— 数字/否定/比较/适用性
  模式（与 Task 17 claim reviewer 同套 pattern）
- **普通**：仅是名词短语如"扩句法"

LLM 没有"自己的语义是否安全"的判断通道。当 LLM 声称一个 HIGH-risk topic title
时，整个 wiki page 的 title 会因此带 risk。这是 wiki 级的 risk，需要独立 reviewer。

**Task 35 目标**：Stage 4 clusterer 在最终产物（TopicCandidate list）上做一次 reviewer pass，
对 HIGH-risk topic 标题二次裁决：SUPPORTED / OVERSTATED / CONTRADICTED / UNRESOLVED。
VERDICT 不是 CONTRADICTED 的 topic 才能进入 Stage 5。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. 每个 TopicCandidate 携带 `topic_review_status: TopicReviewStatus`
2. CONTRADICTED 的 topic 走 Stage 4 `__other__` 桶或 quality gate 拦截，不进 Stage 5
3. reviewer 失败 → 所有 HIGH-risk topic 降级（不写盘）

### 1.2 Non-Goal

- **不**改 Stage 4 现有的 9 metrics / quality gates / FAILED-DEGRADED-UNCERTAIN 三态
- **不**改 TopicCandidate 的 script-owned id 生成（Task 12 不动）
- **不**改 Stage 5B claim reviewer（Task 17，独立模块）

## 2. 模型

```python
class TopicReviewStatus(str, Enum):
    SUPPORTED = "supported"           # LLM 接受 topic title 与 items 一致
    OVERSTATED = "overstated"         # title 比 items 包含的内容更宽泛（降权但保留）
    CONTRADICTED = "contradicted"     # items 不支持 title（不进 page）
    UNRESOLVED = "unresolved"         # 技术失败或证据不足

@dataclass
class TopicReviewRecord:
    topic_id: str                     # 来自 TopicCandidate.id（script hash）
    title: str                        # 来自 TopicCandidate.title
    status: TopicReviewStatus
    reason: str                       # short, <=200 chars
    confidence: float                 # 0..1
    evidence_excerpts: list[str]      # 引用 items 的 deterministic excerpt
    reviewer_fingerprint: str         # sha1(prompt + items_hash)[:12]
    reviewed_at_ms: int
```

## 3. Files

- `src/pipeline/v7_extract/topic_reviewer.py`（新建）
- `src/pipeline/v7_extract/prompts/builtin/topic_reviewer.toml`（新建）
- `tests/test_pipeline/test_v7_extract_topic_reviewer.py`（新建）

## 4. Tests

```python
def test_topic_review_status_enum_has_four_values():
    """SUPPORTED / OVERSTATED / CONTRADICTED / UNRESOLVED"""

def test_topic_reviewer_only_invoked_for_high_risk_title():
    """low-risk title（无数字/否定/比较/适用性 pattern）→ 不进 reviewer"""

def test_topic_reviewer_rejects_overstated_title():
    """title 含 'X 提高 10%' + items 不含证据 → → CONTRADICTED"""

def test_topic_reviewer_failure_marks_all_high_risk_unresolved():
    """LLM 失败 → 所有 HIGH-risk topic 标 UNRESOLVED（quality gate 仍可能降级但不抛异常）"""

def test_topic_review_record_topic_id_matches_candidate_id():
    """TopicReviewRecord.topic_id == TopicCandidate.id（script-owned 同步）"""
```

## 5. Implementation

### 5.1 topic_reviewer.py

```python
MAX_TOPICS_PER_REVIEW_CALL = 8   # LLM batch 上限，避免 prompt 爆预算

@dataclass
class TopicReviewerVerdict(str, Enum):
    SUPPORTED = "supported"
    OVERSTATED = "overstated"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"

_TOPIC_RISK_PATTERNS = (
    re.compile(r"\d+(\.\d+)?\s*%"),
    re.compile(r"\d+(\.\d+)?\s*倍"),
    re.compile(r"提高|降低|增加|减少|提升|下降|增长|缩小|放大"),
    re.compile(r"适合|不适合|适用于|不适用|只适合|仅适合"),
    re.compile(r"导致|引起|造成|引发|由于|因为|因此"),
    re.compile(r"优于|劣于|好于|差于|强于|弱于|相当于|高于|低于"),
    re.compile(r"不是|并非|不能|无法|不应|不需要|不同于"),
)

def assess_topic_risk(title: str) -> bool: ...

@dataclass
class TopicReviewInput:
    topic_id: str
    title: str
    items: list[str]                 # item text excerpts

async def review_high_risk_topics(
    candidates: list[TopicReviewInput],
    *,
    llm: LLMClient,
    template = None,
    project_root = None,
    max_retries: int = 3,
) -> list[TopicReviewRecord]:
    """仅审 risk==HIGH 的 candidate. low-risk 直接返回 SUPPORTED without LLM call.
    
    Technical failure (all retries exhausted) → all HIGH-risk topics UNRESOLVED.
    LLM verdict CONTRADICTED → TopicReviewRecord.status=CONTRADICTED.
    Caller filters out CONTRADICTED before Stage 5.
    
    Never raises (Failure Contract §1).
    """
```

### 5.2 prompt template

```toml
[meta]
prompt_kind = "topic_reviewer"
version = "1.0"

[system]
text = """You are a V7 topic title reviewer. Verify whether the LLM-generated
topic title accurately reflects the candidate items below. Reply with JSON only.

Verdicts (use EXACTLY these strings):
  - "supported":    title matches items, no exaggeration
  - "overstated":   title is wider/more absolute than items support
  - "contradicted": items do NOT support the title (caller will drop)
  - "unresolved":   insufficient evidence to decide

Do not invent topic_ids. Cite item excerpts verbatim from the user message."""

[user]
template = """\
Review these high-risk topic titles against their candidate items.

Topic 1: id={topic_id_1}, title="{title_1}"
Items (excerpts):
{items_block_1}

Topic 2: id={topic_id_2}, title="{title_2}"
Items (excerpts):
{items_block_2}

...

For each topic return a verdict:
{"verdicts": [{"topic_id": "...", "verdict": "supported|overstated|contradicted|unresolved", "confidence": 0.0..1.0, "reason": "<=30 chars"}]}"""
```

### 5.3 不动 Stage 4 cluster_topics 签名

**严格 F8 纪律**：不破坏 Stage 4 的对外接口。`cluster_topics()` 不接受新 kwarg
reviewer；reviewer 是**独立可调用模块**（`review_high_risk_topics(candidates, ...)`），
Stage 4 caller 自己决定是否调用。本 Task 只产出 reviewer 模块 + prompt + 5 测试，
Stage 4 接线留给 Task 35 caller（实际 Stage 4 caller 是 `extract_pilot.py`，暂不动）。

## 6. Acceptance

- ✅ 4 个 verdict 值
- ✅ low-risk topic 不进 reviewer（不消耗 LLM）
- ✅ HIGH-risk topic 受审：CONTRADICTED → caller 丢弃
- ✅ reviewer 整体失败 → 所有 HIGH-risk 标 UNRESOLVED（永不抛异常）
- ✅ TopicReviewRecord.topic_id 与 TopicCandidate.id 一致（脚本同步）
- ✅ 现有 23 reconciliation + 53 v7_extract 测试 0 回归
- ✅ 不引入新依赖

## 7. Status

draft → 等 plan-audit Round 1/R2 + 人工复核 → in-progress → completed

---

**写于 2026-09-17 master plan 第二批**