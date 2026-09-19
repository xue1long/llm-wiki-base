# V7 Replace Plan Stage 1 排查报告

## 发现的问题

### Bug 1（严重）: v7 failure 不抛异常 → 队列把失败标记为 succeeded

**症状**：任务 `kb-20260919114433-db10f079` 状态 `succeeded`，但 wiki 里
0 新页面写入。服务器日志显示 Stage 1 `classify_doc` 因 MiniMax 429 重试
耗尽而 `failed=True`。

**根因**：`src/pipeline/ingest.py` 的 v7 分支在 `failure_stage` 非空时
返回 `([], [], meta{rejected: True})` 而**没有抛异常**。下游
`commit_ingest` 看到 0 pages 后正常返回 → `run_ingest` 返回成功 → 队列
标记 succeeded。

**对比候选路径**：候选路径走 `_reject_candidate()` 抛
`InvalidInputError` → 队列正确分类失败。

**修复**（commit `09e8b4eb`）：v7 分支在 failure_stage 非空时抛异常，
并按瞬时性分两类：

| failure_stage | 异常类 | 队列行为 |
| --- | --- | --- |
| `stage1`（LLM 不可达，e.g. 429 重试耗尽） | `RetryableDependencyError` | 重试 3 次后 dead_letter |
| `budget` / `timeout` / `unhandled` | `RetryableDependencyError` | 同上 |
| `stage3_incomplete` / `stage4_empty` / `stage5_v2_not_implemented` | `InvalidInputError` | 立即 dead_letter（内容/配置问题，重试无意义） |

**验证**：任务 `kb-20260919114847-b9f98fa5` 在 MiniMax 429 期间运行：
- 状态 `failed`（不再是 succeeded）✓
- 错误信息完整：`v7-bridge aborted at stage stage1: All 4 LLM call attempts exhausted` ✓
- retry_count=3（retryable 分类生效）✓
- 最终 dead_letter ✓

### Bug 2（轻微）: frontmatter `created_at` / `updated_at` 写成 `null`

**症状**：v7 写出的 concept / source 页 frontmatter 是
`created_at: null, updated_at: null`。

**根因**：`adapt_concept_page` 计算了 `now = datetime.now(timezone.utc)`
但**忘了传给 WikiPage 构造器**（只有 `build_source_stub_page` 传了）。
WikiPage 的默认是 int `0`，`_to_iso_dt(0)` 返回 `None` → YAML 写成
空串 → PyYAML 序列化为 `null`。

**修复**（commit `09e8b4eb`）：`adapt_concept_page` 补上
`created_at=now, updated_at=now`。

**回归测试**：新增
- `test_adapt_concept_page_sets_timestamps`
- `test_build_source_stub_sets_timestamps`

### 非问题（已确认正常）

1. **v3 path budget abort（`kb-20260919104020-b6ac0244`）**：23 calls >
   20 max 触发 `BridgeBudgetExceeded`，写 `v7_failure.md` 到 quarantine，
   0 副作用。**P1-2 budget cap 完全按设计工作**。
2. **P1-3 topic dedup 生效**：v3 run 日志显示 2 个同 id topic 产 2 个
   distinct page_ids（`-42527c6e31e0399e` / `-a25a425160941f1e`）。
3. **v2 path 页面质量高**：`kb-20260919105159-24b4a79f` 21 秒成功，
   9606 字节 concept 页，8 槽位全填且内容具体（识别出 ASR 错字、
   列出 7 条反模式、4 个具体案例、12 个相关概念）。
4. **RUFLO_PIPELINE_MODE env 正确读出**：服务器日志有 `[v7-bridge]` 标记。

## 环境问题（非代码）

**MiniMax API 429 限流**：从 11:44 起持续 429，v7 的 Stage 1
`classify_doc`（3 重试 × 4 内部尝试 = 12 次调用）全部耗尽。
这是**外部依赖问题**，不是 v7 代码问题。影响：
- Stage 1 灰度期间无法完成真实 ingestion
- 需要等限流恢复，或换 provider

**建议**：
- (a) 等 MiniMax 限流恢复（通常几十分钟）
- (b) 或临时设 `RUFLO_LLM_PROVIDER=ollama`（本地，无限流，但 Ollama
  当前 502 不可用）
- (c) 或降低 v7 内部重试次数（`max_retries` 参数）以减少限流放大

## Stage 1 灰度状态

| 项 | 状态 |
| --- | --- |
| Server 运行 | ✅ `RUFLO_PIPELINE_MODE=v7` on :19828 |
| v7 路径激活 | ✅ 日志有 `[v7-bridge]` |
| v2 path 端到端 | ✅ 1 次成功（21 s / 5 calls / HEALTHY） |
| v3 path budget cap | ✅ 按设计 abort |
| failure 传播 | ✅ 修复后 `failed` + 完整错误信息 |
| timestamps | ✅ 修复 |
| 生产入流量 | ❌ 被 MiniMax 429 阻塞 |

## 提交记录

```
09e8b4eb fix(ingest): v7 bridge failure must raise so the queue marks the task failed
0e47a5c7 fix(v7-bridge): set created_at and updated_at on v7 WikiPage output
aa9a7c32 feat(ingest): wire V7 bridge into generate_ingest via RUFLO_PIPELINE_MODE=v7
```

## 测试状态

48/48 ingest + bridge + adapter 测试通过（含 2 个新 timestamp 回归测试）。

## 下一步

1. **等 MiniMax 限流恢复**后重跑 Stage 1 验证（3-5 次连续成功）
2. **考虑加 provider fallback**：429 时自动切 Ollama（需先修 Ollama 502）
3. **考虑降 v7 重试放大**：`classify_doc` 3 重试 × 4 内部 = 12 次，限流时
   放大严重；可降到 1×2=2 次
4. Stage 1 观察期继续（3 天）
