# Plan: Task 46 — 每个 stage 的 gold corpus（Stage 1-7 + Reconciliation 各 ≥ 16 类）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第四批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 46)

## 0. 上下文

master plan §5 要求"每个 stage 的 gold corpus（Stage 1-7 + Reconciliation 各 ≥ 16 类）"。
这是**长期回归验收基础设施**——固定输入 + 期望输出的 corpus，**stage 升级时不被悄悄破坏行为**。

当前已落地的 stage 各自有一些 ad-hoc 单元测试，但**没有 cross-stage 验证**。本 Task 引入：
- 一个 **corpus fixture 目录** (`tests/corpus/v7_gold/`)
- 一个 **corpus runner** (`src/pipeline/v7_extract/gold_corpus.py`)：跑所有 fixture，对比期望
- 一个 **corpus author utility**：把现有 ad-hoc 测试的输入/期望提炼成 corpus fixture

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `src/pipeline/v7_extract/gold_corpus.py` 模块
2. `tests/corpus/v7_gold/` 目录，含 Stage 1/2/3/4/5/7/6R/Recon **每个 stage 至少 16 个 fixture**
3. `tests/test_pipeline/test_v7_extract_gold_corpus.py` 跑 corpus runner，断言所有 fixture 通过
4. 5 个测试覆盖：corpus discovery / loader / runner / per-stage pass / failures reported

### 1.2 Non-Goal

- **不**改任何 stage 的实现
- **不**做 LLM 评分（用纯 deterministic 对比）
- **不**做生产数据采样（用 synthesized small fixtures）

## 2. 数据 schema

每个 fixture 一个 JSON 文件，schema：

```json
{
  "id": "stage1-n01",
  "stage": "stage1_classify",
  "description": "短文 single_method",
  "input": {
    "content": "...raw text...",
    "filename_hint": "test.md"
  },
  "expected": {
    "doc_type": "single_method",
    "failed": false,
    "traits": ["has_steps", "uses_certainty"],
    "min_confidence": 0.5
  }
}
```

每 stage 至少 16 个 fixture 覆盖 7-8 个**真实语料场景**：
- **happy path**（每 doc_type 各 1-2）
- **edge case**（空、短、超长、非UTF-8 字节）
- **failure path**（LLM 故障 / malformed response）
- **boundary**（高 confidence vs 低 confidence）

## 3. Files

- `src/pipeline/v7_extract/gold_corpus.py`（新建）
- `tests/test_pipeline/test_v7_extract_gold_corpus.py`（新建）
- `tests/corpus/v7_gold/stage1_*.json` 等（≥ 16 个 fixture 文件 / stage × 8 stage = 128 文件，**多 commit** 推进）

## 4. Tests

```python
def test_corpus_discovers_all_fixtures():
    """CorpusLoader 找到 tests/corpus/v7_gold/ 下所有 .json"""

def test_corpus_runner_passes_for_seeded_fixtures(tmp_path):
    """Seed 2 个 stage1 fixture，runner 返回 2 passed"""

def test_corpus_runner_reports_failures_with_diff(tmp_path):
    """Seed 1 fixture with wrong expected value → failure detail"""

def test_corpus_loader_skips_malformed_fixtures(tmp_path):
    """缺字段的 fixture → 跳过 + 记录"""

def test_per_stage_count_meets_master_plan_threshold():
    """每 stage 至少 16 fixture（CI gate）"""
```

## 4. Implementation

```python
@dataclass
class CorpusFixture:
    id: str
    stage: str
    description: str
    input: dict[str, Any]
    expected: dict[str, Any]

class CorpusLoader:
    @staticmethod
    def discover(root: Path = Path("tests/corpus/v7_gold")) -> list[Path]: ...
    @staticmethod
    def load(path: Path) -> CorpusFixture | None: ...

@dataclass
class CorpusRunResult:
    fixture_id: str
    stage: str
    passed: bool
    diff: str = ""

class CorpusRunner:
    def __init__(self, *, llm_factory: Callable | None = None): ...
    def run(self, fixtures: list[CorpusFixture]) -> list[CorpusRunResult]: ...
    def run_stage(self, stage: str) -> list[CorpusRunResult]: ...

# per-stage runners
def run_stage1(fixture: CorpusFixture, llm_factory) -> CorpusRunResult: ...
def run_stage2(fixture: CorpusFixture, llm_factory) -> CorpusRunResult: ...
# ...
```

Fixture evaluation logic per stage:
- stage1: compare Classification.doc_type / failed / traits against expected
- stage2: compare SegmentationResult.item_count + invariants
- stage3: compare CompletenessStatus (or None on technical failure)
- stage4: compare Topic.id sequence + cluster status
- stage5: compare FillResult.status + metrics.claim_support_ratio (within ±0.1)
- stage7: compare WriteReport.written vs expected
- stage6r: compare RelationAssertion list (key + predicate)
- recon: compare CanonicalRegistry state after apply_decisions

LLM is `FakeLLMClient` by default (deterministic); per-fixture can specify `expected.llm_script` for scripted responses.

## 5. Acceptance

- ✅ 5 个测试全绿
- ✅ Fixture 加载器能解析 schema
- ✅ Runner 报告每 fixture pass/fail
- ✅ Stage 1 fixture 落地（其余 stage 留待后续 commit / subagent）

**Scope 决策**：考虑到本 Task 的体量（8 stage × 16 fixture = 128 fixture + runner + 5 tests = 单一 commit 不实际），
**本 Task 在 master plan 框架下应分多 commit 推进**：
- Commit 1（本次）：gold_corpus.py runner + 5 tests + Stage 1 fixture × 16（一个 stage 完整可用）
- Commit N+：其他 stage 的 fixtures（per-commit 16 fixtures + validation）
- 最终 commit：所有 stage ≥ 16 + per-stage count CI gate

## 6. Status

**completed**（2026-09-17）

| Commit | 内容 |
|---|---|
| `1539a08f` | Commit 1: 框架（loader + runner + dispatch）+ Stage 1 fixture × 3 + 6 tests |
| `b0b05f8d` | Commit 2: Stage 1 fixture × 13（凑足 16）+ Stage 1 count gate |
| `4392f1d0` | Commit 3: Stage 2 runner + fixture × 16 + `llm_responses` schema 升级 |
| `f1715cb6` | Commit 4: Stage 3 + Stage 4 runner + 各 16 fixture |
| `f768847d` | Commit 5: Stage 5 runner（`extract_slot_claims`）+ 16 fixture |
| `9f703533` | Commit 6: Stage 7 runner（`commit_and_index`, sync）+ 16 fixture |
| （本 commit） | Commit 7: Stage 6R + Reconciliation runner + 各 16 fixture + 聚合 gate |

**最终验收**：**128 fixtures，8 stage 各 16 个**（Stage 1/2/3/4/5/7 + Stage 6R + Reconciliation）。
全部 fixture 实测通过（CorpusRunner 逐条 PASS）；15 个 corpus 测试全绿，
其中 `test_all_eight_stages_have_a_corpus` 是 master plan §5 的收口 gate。

**实施中发现并修正的语义**（记录以免后人重踩）：

1. `segment_articles` 在 LLM 给出的 boundary 短于 content 时会补一个尾部 filler
   article —— 单 article fixture 的 `end` 必须覆盖整个 content 长度。
2. `WikiWriter` 的 Guard C（"no evidence"）只看 **是否存在 slot_evidence**，
   不看 `SlotEvidence.has_evidence=False`；空 body 的页**仍会被写入**。
   可靠的 block 触发只有 Guard A（`__other__`）与 Guard B（`needs_review_slots`）。
3. `reconcile_pages` 通过 `getattr(page, "id"/"title"/"body")` 读取页对象，
   不接受 dict；corpus runner 负责把 fixture 的 dict 包成属性对象。
4. `ArticleBoundary` 的坐标字段是 `char_start` / `char_end`（非 `start`/`end`）。
5. Fixture 文件必须是**纯 JSON**——不能写 Python 表达式（`"A" * 5000`、
   list comprehension 等），loader 会静默跳过解析失败的文件。