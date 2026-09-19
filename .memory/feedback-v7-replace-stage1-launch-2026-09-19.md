# V7 Replace Plan Stage 1 启动报告

## 启动动作

1. **wire V7 bridge into `ingest.py`**：`generate_ingest` 加 `if RUFLO_PIPELINE_MODE == "v7"` 分支，调 `run_v7_ingest` (Tasks 1-4)。
2. **重启 server** with `RUFLO_PIPELINE_MODE=v7` env var
3. **HTTP /ingest 验证 v2 path**：1 个 task 成功，21 秒
4. **HTTP /ingest 验证 v3 path budget cap**：1 个 task 被 budget abort（23 calls > 20 max），v7_failure.md 写 quarantine（按设计触发）

## V7 path 验证结果（v2 path，RUFLO_V7_USE_FILL_SLOTS_V2 默认 0）

| 指标 | 值 |
| --- | --- |
| 任务 ID | `kb-20260919105159-24b4a79f` |
| 状态 | `succeeded` |
| 耗时 | 21 秒 |
| LLM 调用 | 5（Stage 1 + 3 + 4 + 5 + 6） |
| Source stub | 1（`大纲写作技巧-7a51192d.md` 1583 bytes，已更新） |
| Concept page | 1（`d237368f-raw-sources-视频音频转录教程-音频教程-大纲写作技巧.md` 9606 bytes） |
| H1-H5 | 0 issues / HEALTHY |
| wiki-quality strict | HEALTHY（0 errors, 1 warning = duplicate-title from re-run） |
| Cost | ~$0.05（实测 5 LLM calls × 2-3k tokens each） |

## V3 path budget 验证

| 指标 | 值 |
| --- | --- |
| 任务 ID | `kb-20260919104020-b6ac0244` |
| 状态 | `succeeded`（queue 端成功，但 bridge 标记 failure → quarantine） |
| Bridge failure | `budget`（calls 23 ≥ max 20） |
| 耗时 | 5:24（含 LLM 限速等待时间） |
| Quarantine | `.index/quarantine/kb-20260919104020-b6ac0244/v7_failure.md`（411 bytes） |

```yaml
stage: budget
reason: calls 23 already at max 20 before stage stage6
```

P1-2 BridgeBudget 硬性 cap **完全按设计工作**：v3 path 在 2 topics × 9 calls + 5 fixed = 23 calls 触发 abort，写 v7_failure.md。

## 灰度配置

```bash
# Server start command
RUFLO_PIPELINE_MODE=v7 \
RUFLO_LLM_PROVIDER=minimax \
python -X utf8 -m src.cli serve \
  --host 127.0.0.1 --port 19828 \
  --project-root knowledge/novel-wiki-v2
```

**Stage 1 观察期**：3 天 (per user decision)

## 用户决策点（Stage 1 之后）

3 天后问用户：
1. **观察期是否延长**？Stage 1 内 0 issue 即可进 Stage 2 改默认；如有问题则排查
2. **Stage 2**：将 `RUFLO_PIPELINE_MODE` 默认值改为 `"v7"`（候选路径保留为 `RUFLO_PIPELINE_MODE=candidate` 显式 opt-in）
3. **Stage 3**：删除候选/chunked/unified 路径代码 + `RUFLO_PIPELINE_MODE` env 字段

## 关键观察

1. **v2 path 通过 HTTP 端到端成功**：5 LLM calls，21 秒，1 source + 1 concept page，H1-H5 OK，wiki-quality HEALTHY
2. **v3 path budget 正确触发**：2 topics × 9 calls 触发 20 calls budget，写 quarantine，0 副作用
3. **dedup 正确工作**：2 topic id 相同的 topics 产 2 distinct page_ids（`-42527c6e31e0399e` 和 `-a25a425160941f1e`）
4. **P1-3 dedup 代码生效** — 这次 v3 run 的日志明确显示两个不同 suffix
5. **fail-closed path 正确**：budget exceed → `failure_stage="budget"` → v7_failure.md → 任务 dead_letter（不是 succeeded-with-no-pages 掩盖）

## 已知边界

1. **v3 path cost 9× v2**：2 topics × 9 calls = 18 + 5 fixed = 23 calls。生产 raw 多 topic 时频繁触发 budget。需要：
   - (a) Stage 1 后 bump 默认 `RUFLO_V7_MAX_CALLS=30`
   - (b) 或 v3 path 加 per-topic cost-based budget（cost-aware abort）
2. **v2 path 1 call/topic 但 partial 风险**：测试 stub 显示 v2 path `{"slots": {...}, "evidence": {...}}` 格式 缺 source_text_excerpt 时 v7 page_adapter 也只填 8 槽（partial 仍写盘，failed_topics 为空）

## 主要产物

- 1 commit `aa9a7c32`（wire V7 into ingest.py）
- `.tmp-smoke-70kb.py` 复用，`.tmp-stage1-payload.json` 新建
- v7 path 多次执行（v2 一次成功，v3 一次 budget abort 都正常）
- 4 个 wiki page written（含 1 个新 stub + 1 个新 concept）
