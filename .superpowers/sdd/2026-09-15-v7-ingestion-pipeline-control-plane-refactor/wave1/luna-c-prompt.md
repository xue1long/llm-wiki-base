# Luna-C Prompt — Task 0 async regression

> **本文件由主 agent 生成,Luna-C subagent 直接按此执行。**
> **不要修改本文件,只读。**

## 你的角色

你是 **Luna-C**,Wave 1 三个并行 lane 之一。
你的工作是 **Task 0:旧同步 stage 测试迁移到 async**。**注意:你只改测试,不改 src/**。

## 全局上下文(必读)

- 计划文件:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- Wave 0 产出:`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/wave0/`
- 当前 commit:`9e641367`
- 共享 fixture:`tests/fixtures/v7_control_plane/{source_a.md, source_b.md, expected_ids.json}`
- 冲突表:`wave0/conflict-table.md`

## 任务范围(Task 0)

### 修改文件(只测试)

- 🟡 修改 `tests/test_pipeline/test_v7_extract_stage4.py`(如果存在,迁移到 async)
- 🟡 修改 `tests/test_pipeline/test_v7_extract_stage5.py`(如果存在,迁移到 async)
- 🟡 修改 `tests/test_pipeline/test_v7_extract_stage7.py`(如果存在,迁移到 async)

### **绝对不允许**碰

- `src/pipeline/v7_extract/` 下任何文件(你的工作严格限定在测试侧)
- Luna-A 的 `_page_id.py` / `slot_filler.py` 改造
- Luna-B 的 `failures.py` 改造

## 实现要求

### 1. 调研当前状态

```bash
# 查看 v3 实施已迁移的测试 vs 还没迁移的:
ls tests/test_pipeline/test_v7_extract_stage*.py
git log --oneline tests/test_pipeline/test_v7_extract_stage*.py | head -10
```

很可能 v3 实施 Phase 2 已经把这些测试改成 async(`@pytest.mark.asyncio` + `async def test_*`)。
你的工作可能是:

- **情况 A**:测试已经是 async,只是命名 `stage4/5/7` 与 v3 命名不一致 → 改名为 v3 习惯命名
- **情况 B**:测试还残留 sync 调用 → 加 `@pytest.mark.asyncio`,内部 `await` 异步函数
- **情况 C**:测试不存在 → 新建最小测试覆盖 Stage 4/5/7 的 async 入口

### 2. 复用共享 fixture

新增测试**必须**用 `tests/fixtures/v7_control_plane/source_a.md` / `source_b.md` 作为 source 内容,
**禁止**新建临时 fixture 文件(plan H5 加固)。

### 3. 测试内容(每个 stage 至少 2 个测试)

**Stage 4(`topic_clusterer`)**:
- async 调用 + FakeLLMClient 返回合法 topics → 解析正确
- async 调用 + LLM 抛异常 → 返回空列表(P2 不抛异常)

**Stage 5(`slot_filler`)**:
- async 调用 + 合法 evidence → ConceptPage.has_evidence = True
- async 调用 + evidence item_id 不在 available → slot 标 needs_review

**Stage 7(`wiki_writer`)**:
- topic_id="__other__" → blocked,不写盘
- topic_id 正常 + has_evidence → written

## TDD 节奏

1. **先调研**:确认 stage4/5/7 测试当前状态(已 async / 仍 sync / 不存在)
2. **按情况 A/B/C 处理**
3. **跑测试**:
   ```powershell
   $env:PYTHONPATH = "."
   python -m pytest tests/test_pipeline/test_v7_extract_stage4.py tests/test_pipeline/test_v7_extract_stage5.py tests/test_pipeline/test_v7_extract_stage7.py -q
   ```
4. **commit**(单一逻辑 commit):
   ```bash
   git add tests/test_pipeline/test_v7_extract_stage4.py \
           tests/test_pipeline/test_v7_extract_stage5.py \
           tests/test_pipeline/test_v7_extract_stage7.py
   git commit -m "test(v7-extract): migrate stage4/5/7 tests to async (T0)"
   ```

## 完成报告(回到主 agent 时给我)

- commit hash
- 调研结论(A / B / C 中哪种情况)
- 改动文件清单(可能为空,如果 A 情况只是 rename)
- 测试结果(passed N / failed 0)
- 任何与 plan 的偏离

## 不要做的事

- **不要碰 src/ 下任何文件**
- 不要新建 fixture 目录
- 不要写 stage1/3 的测试(那是 v3 实施已完成的)
- 不要碰 Luna-A/B 的工作集
