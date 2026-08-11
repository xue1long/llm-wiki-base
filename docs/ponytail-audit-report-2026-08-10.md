# Ponytail 过度工程审计报告

> **审计日期：** 2026-08-10
> **审计范围：** 全仓库（`src/` + 根目录文件）
> **审计工具：** ponytail-audit（v4.9.0）
> **代码总量：** ~49,393 行 Python（581 个文件，含测试和脚本）

---

## 执行摘要

本次审计共发现 **~1,050 行可删除代码**、**6 个可废弃模块**、**10 个一次性调试脚本**、**6 个产物文件**，以及若干可简化或合并的模块。核心发现分为三类：

1. **Dead Code（直接删除）** — 无任何生产代码调用，可安全移除
2. **YAGNI（过度设计）** — 抽象层为零或一个实现，无实际价值
3. **Shrink（可精简）** — 代码可简化、合并或拆分

---

## 一、Dead Code — 直接删除（无任何调用者）

### 1.1 一次性 Root 调试脚本（10 个文件，~384 行）

| 文件 | 行数 | 说明 |
|------|------|------|
| `_check_issues.py` | 36 | 一次性 git diff 检查 |
| `_check_issues2.py` | 17 | 同上，另一版本 |
| `_check_issues3.py` | 42 | 同上，第三版 |
| `_check_quality.py` | 99 | wiki 页面质量检查 |
| `_fix_all.py` | 53 | 批量修复脚本 |
| `_revert_bad.py` | 20 | 批量回滚脚本 |
| `_revert_list.py` | 29 | 生成回滚列表 |
| `fix_backtick.py` | 21 | JS 反引号修复 |
| `fix_backtick2.py` | 18 | 同上，另一版本 |
| `test_llm_response.py` | 41 | 一次性 LLM 测试 |

**建议：** 全部删除。这些是临时诊断脚本，不在版本控制中跟踪（均在 `.gitignore` 之外）。

### 1.2 Root 产物文件（6 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `PROJECT_COMPARISON_2026-08-10.md` | 149 | 一次性项目对比报告 |
| `WEBUI_IMPROVEMENT_PLAN_2026-08-10.md` | 109 | 一次性改进计划 |
| `_test_output.txt` | 7 | 测试输出 |
| `_revert_files.txt` | 44 | 回滚文件列表 |
| `openai-test.err` | 4 | 错误日志 |
| `server.log.err` | 7 | 服务器日志 |

**建议：** 删除产物文件。日志和报告应放入 `.gitignore` 或 `docs/` 目录。

### 1.3 `src/metrics/` — 6 个文件，233 行，零生产调用

预注册了 5 个指标，但**没有任何生产代码调用 `.inc()`、`.add()`、`.set()` 或 `.observe()`**：

- `INGEST_TOTAL` — 从未 inc
- `CHAT_TOTAL` — 从未 inc
- `LLM_CALL_DURATION` — 从未 observe
- `LLM_COST_USD_TOTAL` — 从未 inc（仅 `metrics_cmd.py` 读取 `_values`）
- `ACTIVE_TASKS` — 从未 set

连带 dead code：
- `src/metrics/persistence.py`（64 行，sqlite3 持久化，无调用者）
- `src/metrics/histogram.py`（23 行，仅测试使用）
- `src/metrics/gauge.py`（21 行，无调用者）
- `src/metrics/counter.py`（17 行，仅 `metrics_cmd.py` 读取）
- `src/metrics/prometheus_format.py`（54 行，仅 `metrics_cmd.py` 和 `metrics_route.py` 导入）
- `src/metrics/registry.py`（54 行，注册表无实际注册的生产指标）

**建议：** 保留 `metrics/` 结构但移除所有预注册指标和 sqlite 持久化，或完全移除模块（233 行 + 测试文件）。如果计划未来接入 Prometheus，保留框架但去掉从未使用的代码。

### 1.4 `src/orchestrator/` — 4 个文件，276 行，零外部调用者

| 文件 | 行数 | 说明 |
|------|------|------|
| `orchestrator.py` | — | 无生产代码导入 |
| `router.py` | — | 无生产代码导入 |
| `state_machine.py` | — | 状态机逻辑（已被 `src/queue/state.py` 取代） |
| `audit_hard.py` | — | 无生产代码导入 |

`state_machine.py` 中的状态转移矩阵已被 `src/queue/state.py` 完全取代，但旧文件未被删除。

**建议：** 删除整个 `src/orchestrator/` 包。如果 `state_machine.py` 还有引用，确认迁移完成后再删除。

### 1.5 `src/sync/` — 2 个文件，176 行，已废弃

| 文件 | 行数 | 说明 |
|------|------|------|
| `file_watcher.py` | 106 | `start_watch()` / `stop()` 已标记 `DeprecationWarning`，零调用者 |
| `snapshot_store.py` | 70 | 无生产代码调用者 |

**建议：** 按注释计划在 1.0 版本删除。当前即可安全移除。

---

## 二、YAGNI — 过度设计（抽象层多于实际需求）

### 2.1 `src/queue/ports.py`（89 行）— 5 个 Protocol 零外部导入

定义 `QueueBackend`、`InFlightTracker`、`EventEmitter`、`RetryPolicy`、`_RetryLike` 五个 Protocol，每个都有唯一的具体实现：
- `QueueBackend` → `JsonFileBackend`
- `InFlightTracker` → `InMemoryInFlightTracker`
- `RetryPolicy` → `DefaultRetryPolicy`
- `EventEmitter` → `EventBus`

没有外部代码通过 Protocol 类型导入，也没有替代实现。

**建议：** 删除 `ports.py`，让 `QueueService` 直接依赖具体类。如果未来需要多实现，再引入 Protocol。

### 2.2 `src/pipeline/ports.py`（55 行）— `PipelineStage` Protocol

- `PipelineStage` Protocol 的唯一实现是 `src/pipeline/stages/` 下的三个包装类
- 每个包装类（`CollectorStage`、`AnalyzerStage`、`GeneratorStage`）只是调用实际函数
- `PipelineRunner` 只在 `run_stages()` 中使用

**建议：** 删除 `PipelineStage` Protocol，让 `PipelineRunner` 直接调用函数列表。`PipelineContext` dataclass 保留。

### 2.3 `src/pipeline/stages/` 三层包装（3 个文件，60 行）

每个 stage 只是薄薄一层：
- `CollectorStage`（26 行）→ 调用 `pipeline.collect()`
- `AnalyzerStage`（26 行）→ 调用 `analyzer.analyze()`
- `GeneratorStage`（30 行）→ 调用 `generator.generate()`

`PipelineService`（`src/pipeline/service.py`）注册这些 stage，但不通过 stage 模式获得任何额外价值（没有装饰器、中间件、动态插拔等）。

**建议：** 内联到 `PipelineRunner` 或 `PipelineService`，删除 `stages/` 包。

---

## 三、Shrink — 可精简的代码

### 3.1 `src/pipeline/_pipeline_common.py`（393 行）

`parse_llm_json()` 函数包含多个可独立测试的辅助函数，全部内联在同一文件中：
- `_escape_string_controls()`（37 行）
- `_repair_json()`（58 行）
- `_dump_failed_json()`（36 行）

当前结构合理，但函数太长（`parse_llm_json` 本身 ~160 行），建议将 `_repair_json` 和 `_escape_string_controls` 提取到单独模块。

### 3.2 `src/pipeline/__init__.py`（220 行）— compat shim 膨胀

- `_get_provider()`（42 行）内联在 `__init__.py` 中
- `_resolve_wiki_paths()`（30+ 行）内联在 `__init__.py` 中
- 大量 re-export 和模块加载顺序 hack

**建议：** 将 compat 函数移到 `src/pipeline/_compat.py` 子模块。

### 3.3 `src/templates/` vs `src/wiki/templates/` 命名冲突

- `src/templates/`（38 行）— 用于 `project init --template` 的项目初始化模板
- `src/wiki/templates/`（~1,600 行）— wiki 页面渲染模板

两个不同的模板系统使用了相同的命名空间，容易混淆。`src/wiki/features/lint.py` 中 `from ..templates import list_resolved` 实际导入的是 `src/wiki/templates`（因为 `lint.py` 在 `src/wiki/` 下），但阅读代码时容易误以为导入的是 `src/templates/`。

**建议：** 将 `src/templates/` 重命名为 `src/project_templates/` 或合并到 `src/project/` 中。

---

## 四、整体统计

| 类别 | 可删除行数 | 文件数 | 影响 |
|------|-----------|-------|------|
| Dead Code：root 脚本 | ~384 | 10 | 无风险 |
| Dead Code：产物文件 | ~316 | 6 | 无风险 |
| Dead Code：orchestrator | ~276 | 4 | 需确认无残留引用 |
| Dead Code：sync | ~176 | 2 | 已标记 deprecated |
| Dead Code：metrics 未使用 | ~233 | 6 | 保留框架或全删 |
| YAGNI：queue ports | ~89 | 1 | 低风险 |
| YAGNI：pipeline stages | ~115 | 4 | 需重构 runner |
| **总计可删除** | **~1,589** | **33** | |
| 可精简（非删除） | ~250 | 3 | 重构建议 |

**净效果：** 删除 1,050-1,589 行，移除 6 个模块（orchestrator、sync、metrics 部分），消除 10 个 root 脚本和 6 个产物文件。

---

## 五、执行优先级

### P0 — 立即安全删除（无风险）
1. 删除 10 个 root 调试脚本
2. 删除 6 个产物文件
3. 删除 `src/sync/`（已 deprecated）

### P1 — 需确认后删除
4. 删除 `src/orchestrator/`（确认 `state_machine.py` 已完全迁移到 `src/queue/state.py`）
5. 清理 `src/metrics/` 中未使用的预注册指标和 sqlite 持久化

### P2 — 重构建议
6. 删除 `src/queue/ports.py`，内联 Protocol
7. 删除 `src/pipeline/stages/`，内联到 runner
8. 将 `src/pipeline/__init__.py` 中的 compat 函数移到 `_compat.py`

### P3 — 低优先级
9. 重命名 `src/templates/` 避免命名冲突
10. 拆分 `_pipeline_common.py` 中的 JSON 修复函数

---

*本报告由 ponytail-audit v4.9.0 自动生成，基于 `src/` 代码分析和跨模块依赖追踪。*