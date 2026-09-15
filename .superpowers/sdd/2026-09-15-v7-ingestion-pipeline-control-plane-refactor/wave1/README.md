# Wave 1 启动上下文

> 本目录给后续 Wave 1 subagent(Luna-A / Luna-B / Luna-C)提供完整上下文。
> 主 agent 已在 Wave 0 完成:A1-A7 启动前置 + 决策落地 + 共享 fixture + `_queue_lock.py`。

## 三 lane 启动包

- `luna-a-prompt.md` — Task 1 provenance + `_page_id.py`(主 agent 派发给 Luna-A)
- `luna-b-prompt.md` — Task 3 queue core + 稳定 hash ID(主 agent 派发给 Luna-B)
- `luna-c-prompt.md` — Task 0 async regression(主 agent 派发给 Luna-C)

## 全局上下文(三个 lane 都需要阅读)

### 计划文件

`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`(749 行,plan-audit 整改后)

### Wave 0 产出

- `wave0/prerequisites.md` — A1-A7 核对结果
- `wave0/stage6-investigation.md` — Stage 6 调研
- `wave0/conflict-table.md` — 写集合 + import 依赖(强制遵守)
- `wave0/shared-fixture.md` — 共享 fixture 说明

### 物理产物

- `src/pipeline/v7_extract/_queue_lock.py` — O1 软 PID 锁
- `tests/fixtures/v7_control_plane/{source_a.md, source_b.md, expected_ids.json}` — 共享 fixture
- `.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/progress.md` — Wave 完成后追加

## 派发约束(主 agent 遵守)

1. **串行派发**(plan §6 的"并行"在主会话无法满足,串行保证写集合不冲突)
2. **每个 lane 必须 TDD**:先红测试 → 实现 → 绿 → 单 lane commit
3. **每个 lane commit 前**:`pytest tests/<对应目录> -q` + `git diff --check` + `compileall`
4. **commit 信息**:按 repo 风格 `type(scope): summary`,中文描述
5. **失败处理**:单个 lane 失败 → 主会话进入 fix loop,不派发下一个 lane
6. **冲突裁决**(如果意外冲突):`脚本身份契约优先 / queue schema 保持兼容 / P2 原则不破坏`

## 验证标准(主会话 Wave 1 收尾时执行)

```powershell
$env:PYTHONPATH = "."
python -m pytest tests/test_pipeline/test_v7_extract_slot_filler.py tests/test_pipeline/test_v7_extract_topic_clusterer.py tests/test_pipeline/test_v7_extract_failures.py tests/test_pipeline/test_v7_extract_wiki_writer.py tests/test_pipeline/test_v7_extract_stage4.py tests/test_pipeline/test_v7_extract_stage5.py tests/test_pipeline/test_v7_extract_stage7.py tests/test_scripts/test_extract_pilot.py tests/test_scripts/test_extract_full.py -q
python -m compileall -q src/pipeline/v7_extract
git diff --check
```

## Wave 1 完成 → Wave 2 启动

Wave 1 三个 lane 全部 commit 后:
1. 主会话执行"Wave 1 完成标准"测试套
2. `git tag v7-control-plane-wave1`(为 Wave 2 失败留回滚点)
3. 更新 ledger(progress.md)记录 Wave 1 commit hash
4. 进入 Wave 2(Luna-D,串行 Task 2 统一 `ExtractionResult`)
