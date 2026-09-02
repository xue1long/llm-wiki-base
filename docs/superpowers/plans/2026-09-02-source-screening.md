# Source Screening Implementation Plan

> **For agentic workers:** Execute task-by-task with test-first verification.

**Goal:** 在 Analyzer 前筛选源文档，确定性无关内容跳过，不确定内容不自动拒绝。

**Architecture:** 新增 `source_screening` 深模块，接收现有预处理结果和原文元数据，返回 `accept/skip/review`。只在现有 LLM 前置 seam 接入；`review` 继续进入 Analyzer 并记录原因。

**Tech Stack:** Python 3.11+, dataclasses, 现有 `BudgetedLLM`、pytest。

**Spec:** 会话中确认的“系统规则确定性拦截，LLM 判断不确定内容，低置信度不自动拒绝”方案。

## Global Constraints

- 保留既有 prefilter、readiness、Analyzer、Reviewer、Generator 行为边界。
- 系统规则不得因语义不确定而自动 skip。
- LLM 失败、低置信度、非法输出统一为 review 并继续原摄取流程。
- 不新增模型、依赖、远程服务或模板类型。

### Task 1: Screening contract and deterministic rules

**Files:**
- Create: `src/pipeline/source_screening/types.py`
- Create: `src/pipeline/source_screening/rules.py`
- Create: `src/pipeline/source_screening/api.py`
- Create: `src/pipeline/source_screening/__init__.py`
- Test: `tests/test_pipeline/test_source_screening.py`

- [ ] Write tests for deterministic skip, deterministic accept, and uncertain review.
- [ ] Run the focused test and observe missing module/API failure.
- [ ] Implement the smallest rule-based contract and export `screen_source`.
- [ ] Run the focused test until green.

### Task 2: Optional LLM review for uncertain sources

**Files:**
- Modify: `src/pipeline/source_screening/api.py`
- Test: `tests/test_pipeline/test_source_screening.py`

- [ ] Add tests for valid LLM accept/skip, low confidence review, and provider failure review.
- [ ] Implement one bounded JSON call through the existing provider seam.
- [ ] Keep malformed/failed responses as review without raising.
- [ ] Run screening tests until green.

### Task 3: Ingest seam integration

**Files:**
- Modify: `src/pipeline/ingest.py`
- Modify: `src/pipeline/triage.py`
- Test: `tests/test_pipeline/test_ingest_screening.py`

- [ ] Add an integration test proving deterministic skip does not call the provider.
- [ ] Add an integration test proving review continues into the existing Analyzer path.
- [ ] Integrate screening after triage and before existing wiki-index/Analyzer work.
- [ ] Persist screening metadata through the existing triage audit record.
- [ ] Run the focused ingest tests and related pipeline regression.
