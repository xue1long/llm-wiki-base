# V7 替换候选管线 plan-audit 第二轮：压力测试推演

承接第一轮（找出 12 个 ①② 级问题）。本轮模拟**多种失败路径**推演雪崩、找边界临界点、验证兜底覆盖。

## 0. 边界条件清单（基于第一轮问题扩展）

**资源维度**
- R1: 22 KB 文档（超过 16k max_source_chars）→ Stage 2/3/4/5 都跑大 chunk
- R2: 1 KB 文档（短）→ 可能 completeness INCOMPLETE
- R3: 70 KB 文档（远超 max_source_chars）→ Stage 5B 8+1 次 LLM × 多 topic
- R4: 4918 文件 batch（全量）→ 累计 LLM 调用 4918 × ~9 = 44262 次
- R5: 单文件多 topic（v7 经典场景：1 个 source 5+ 个 topic）

**并发维度**
- C1: 6 并发（`DEFAULT_MAX_CONCURRENCY`）跑同一 project
- C2: 6 并发跑不同 project
- C3: 单 project 但不同 source 同时 retry

**故障维度**
- F1: MiniMax API 限速（实测 3 req/min）
- F2: MiniMax API 返回空（finish_reason=length）
- F3: LLM 返回 invalid JSON（parse 失败）
- F4: LLM timeout（30s+）
- F5: WikiWriter 写盘失败（磁盘满 / 权限）
- F6: WikiWriter partial failure（页 1 成功页 2 失败）
- F7: Server 进程 OOM
- F8: 网络 partition（断网 30s 后恢复）

**状态维度**
- S1: source 已经 ingest 过（md5 命中）
- S2: source 部分 ingest（midway crash，留下 .index/quarantine 残骸）
- S3: source 有 v3 候选写的旧 wiki 页 + 新 v7 想写同名 page（覆盖）
- S4: 用户在 ingest 进行中修改 .llm-wiki/project.json

## 1. 失败路径推演

### F1 + R5（限速 + 多 topic）—— 雪崩风险

```
1 task = 1 source
Stage 1 (classify): 1 LLM call
Stage 2 (segment): 0 LLM call (deterministic)
Stage 3 (completeness): 1 LLM call
Stage 4 (cluster): 1 LLM call
Stage 5 (fill_slots_v2 per topic): 8 + 1 LLM calls × N topics
Stage 6 (relations): 1 LLM call
Total: 12 + 8N calls per source

70 KB source: N ≈ 5 topics (judgment from previous attempt's 4 pages)
  Total: 12 + 40 = 52 LLM calls per source
  
MiniMax 实测 3 req/min
  Per source: 52 / 3 = 17 min
  Per batch (4918): 17 × 4918 / 60 = 1394 hours = 58 days
  With concurrency=6: 58/6 = 9.7 days
```

**雪崩临界点**: MiniMax 限速 < 3 req/min OR 并发 ≥ 8 时，queue 大量 task 堆积。

**现方案无 cost budget 兜底**：plan 没设 `max_usd_per_task`，LLM 调用无限重试。

**整改**: 
- (P0) 加 `RUFLO_V7_MAX_USD` / `RUFLO_V7_MAX_CALLS` env，超阈值 → fallback to fail-closed review_queue
- (P0) 加 `MAX_RETRIES = 1` (extract_pilot 已知) 而不是 stage 默认 3（省 60% calls）
- (P1) 加 backoff 监控 + circuit breaker（已有 queue 层面 breaker，但需要 per-task）

### F2（空响应）+ bridge 处理路径

```
classify_doc: failed=True, doc_type='incomplete'
bridge 必须检查 classification.failed → return ExtractionResult.FAILED
  (extract_pilot.py:223 已经做)

如果 bridge 不检查，doc_type='incomplete' 被当成正常类型继续
  → Stage 3 看到 incomplete 类型 → check_completeness 第二次失败
  → 最终 ClusterResult.status = FAILED
  → bridge 返回 (pages=[], extras=[], meta={"failure_stage": "stage1"})
  → commit_ingest 看到 pages=[] → source_grade='C'
  → 写 source stub page（grade=C）+ no concept pages
  → queue status = APPROVED（因为 commit_ingest 成功写盘）
  → 但实际上没提取任何 concept
```

**后果**: 用户看到 APPROVED 但 wiki 是空的。需要 bridge 强制返回"空提取 = dead_letter"。

**整改**: bridge 在 `(pages=[], extras=[], meta={})` 时抛 `InvalidInputError` 或返回特殊状态让 ingest 死信。

### F3 + S1（已 ingest 过）+ V7 idempotency

```
S1: source md5 命中 `.index/v7_full_checkpoint.json` (假设有)
  V7 WikiWriter 已经在 wiki/concepts/ 写过了
  重跑时 cluster_topics 给相同 topic → fill_slots 返回相同 page.id
  → commit_and_index 检测 page_id 已存在 → skip（line 273-275）
  → report.skipped.append(page.id)
  → bridge return (pages=[], extras=[], meta={"skipped": [id]})
  → commit_ingest 看到 pages=[] → 写 source page（覆盖）
  → conflict: source page 已存在
```

**后果**: 重跑同一 source → V7 skip concept（OK）+ commit_ingest 重写 source 页（覆盖 wiki index）。`expected_page_hashes` 参数可防 source 页覆盖，但 bridge 不传这个。

**整改**: bridge 计算 source page 的 sha256，传给 `commit_ingest(expected_page_hashes={source_page.id: hash})`。

### F4 + C1（timeout + 6 并发）

```
Stage 5B review call (max_tokens 4096) 经常 timeout
  → fill_slots_v2 retry (max_retries=3) → 90s per topic
  → 5 topics × 90s = 7.5 min per source
  × 6 并发 = 同一时间 6 sources 都 7.5 min
  → queue pending 堆积（breaker 3 failures → OPEN）
```

**现方案无 timeout override**：LLM provider 的 timeout_seconds 默认 120（ProviderConfig），MiniMax 实测经常超。

**整改**: 
- (P0) bridge 加 per-stage timeout（如 Stage 5B 总预算 5 min/source，超时跳过该 topic）
- (P0) Stage 7 WikiWriter 的 retry budget 不要重写 5-gate（已有 fail-closed）

### F5（磁盘满 / 权限错）

```
WikiWriter._atomic_write: write tmp, replace
  如果磁盘满：tmp write 失败 → exception
  → commit_and_index 抛 → report.failed[page.id] = str(exc)
  → bridge 接 exception？或继续？
  
bridge 当前伪代码没写 exception handling
  → exception 上抛到 run_ingest
  → run_ingest 没 try/except bridge call
  → queue status = FAILED
  → .index/quarantine 写吗？不，V7 bridge 失败路径不写 quarantine
```

**后果**: 磁盘错误 → 任务 FAILED → user 重启 → 重跑 source → 再次失败。**没有 quarantine 记录可查**（因为 V7 bridge 不写）。

**整改**:
- (P0) bridge 在 WikiWriter 抛错时捕获并写到 `.index/quarantine/<task_id>/v7_candidate.json`（V7 不写，但写 markdown 摘要供 ops 排查）
- (P1) 增加 `reviews_queue.json` 写入（V7 失败的标准路径）

### F6（partial failure）

```
5 topics planned, 3 success, 2 fail (Stage 5 technical error)
  WikiWriter.commit_and_index([p1, p2, p3]):
    → 3 written
    → 0 blocked (no P4)
    → 0 failed
  Bridge return (3 pages, [], meta={"written": 3, "blocked": 0, "failed": 0})
  
但 2 failed topics 被静默丢—— review_queue 没写
  → 用户看不到 "5 topic 计划 → 3 成功" 这件事
```

**整改**:
- (P0) WikiWriter 的失败 topics 在 `enqueue_failure` (line 205) 写入 reviews_queue.json —— **但 verify 这件事真发生**。
- (P1) bridge 在 meta 里加 `failed_topics: [topic_id, ...]` 让前端可见。

### S3（同 id 覆盖）—— 与生产 raw 直接相关

```
现有 novel-wiki-v2 的 wiki/concepts/ 里有 "小说大纲写作技巧.md"（候选路径写的）
  V7 重跑 70KB 音频转录任务 → cluster 产出 5 topics → 1 topic id 可能撞 "小说大纲写作技巧"
  V7 WikiWriter 不验证 id 是否存在 → 直接 write_page(path=wiki/concepts/小说大纲写作技巧.md)
  → 覆盖现有候选页！
```

**后果**: 旧候选页面信息丢失。如果 V7 写的版本质量更高则 OK；但 bridge 没做"id 已存在则 merge 或 skip"判断。

**整改**:
- (P0) WikiWriter commit_and_index 加 check: `if (paths.wiki_concepts / f"{page_id}.md").exists() and not in_manifest: report.blocked.append(page_id)`。这等于 V7 自己的 idempotency，但需要 manifest 状态。
- (P1) bridge 在调用 commit_and_index 前先扫 `wiki/concepts/*.md` 已存在的 page_id，在 meta["overwrite_skipped"] 里返回。

### S4（运行时配置变更）

```
ingest 进行中（stage 5 在跑）→ operator `rm .llm-wiki/project.json` 改注册
  ingest 后续步骤访问 paths.root 时找不到
  → exception → run_ingest catch → FAILED
  → 但 partial state 已写
```

**整改**: 这种并发修改是 ops 错误，方案不该解决。但**应当让 partial state 不会污染** —— V7 WikiWriter 的 `commit_and_index` 用 `CommitManifest` 保证 idempotency（Task 19 已实现）。

## 2. 边界临界点

### 临界 1: 0 个 topic 时的 source 页

```
cluster_topics 返回 ClusterResult(topics=[], status=EMPTY)
  bridge → 0 concept pages
  bridge 写 source stub page（仅）→ 写盘成功
  → wiki 有 1 个 source 页，无 concept
  → 视为 "无内容" 任务，APPROVED
  
问题: 这种"空摄取"任务与"摄取失败"任务在队列中状态相同 (APPROVED)。
operator 看 .kb-queue.json 不知道是哪种。
```

**整改**: bridge 在 pages=[] 时返回 `meta={"empty_extraction": True}` + 写 reviews_queue（标记"空摄取"供 ops 排查）。

### 临界 2: Stage 1 全部 UNCERTAIN

```
classification.failed=False 但 uncertain=True
  bridge 现在不知道怎么处理（伪代码没写）
  候选路径走 KC 路径兜底
  V7 没有这种兜底
```

**整改**: bridge 在 classification.uncertain=True 时，记录 warning 到 meta，但仍继续（不确定的 Stage 1 还能给 Stage 3 用作 hint）。

### 临界 3: 极短文档（< 100 字符）

```
Stage 2 deterministic splitter 找不到 byline / heading / numbered list
  → fallback to whole-as-single-item: [{"id": relative, "text": content}]
  Stage 4: cluster_topics 看到 1 item → 至少 1 topic
  Stage 5: 1 topic, 1 page
  → 仍可工作
```

**临界**: 如果 content 是 "" (empty):
```
completeness_status = TECHNICAL_FAILURE (defensive)
bridge 走 FAILED 分支 → 写 reviews_queue
```

**临界**: 如果 content 是 50 字符 whitespace:
```
Stage 3 LLM 可能 COMPLETE 或 INCOMPLETE 随机
```

**整改**: 在 Stage 1 前加 `len(content) < MIN_BYTES` 早 return。

### 临界 4: 49 GB 大文件

```
V7 没有文档大小上限检查（只有 ingest.py:upload route 的 50 MiB cap）
如果绕过 HTTP 上限 → 直接调 run_v7_ingest
  → preprocess_source 调 normalize_text → 全部 49GB 在内存
  → Stage 3 evidence pack 截到 ≤5500 bytes（line 100）
  → 但 Stage 5 fill_slots 看到 source_text=49GB（如果 items 包含）
  → OOM
```

**整改**:
- (P0) bridge 加 `if len(content) > settings().max_source_chars * 4: raise InvalidInputError`
- (P1) bridge 用 `_result.prompt_text` 而非 raw content（preprocess 已处理）

### 临界 5: task_id collision

```
Two ingest tasks concurrently with same source
  → both call preprocess_source → same CanonicalDocument
  → both call V7 → same topic ids
  → both call commit_and_index → race condition on wiki/concepts/<id>.md
  → 文件内容混合（atomic write 替换）
```

**整改**: V7 WikiWriter 的 `commit_and_index` 不锁文件。`_queue_lock.py` 是 V7 内部锁但仅 `extract_full.py` 用，bridge 不通过它。

**整改**:
- (P0) `_queue_lock.py` 改为可由 bridge 调用
- (P1) bridge 在调用 WikiWriter 前 acquire lock per-source

## 3. 兜底机制覆盖率验证

| 失败模式 | plan 覆盖 | 实际缺口 |
| --- | --- | --- |
| F1 限速 | ❌ 无 cost budget | 批量任务 60 天 |
| F2 空响应 | ⚠️ Stage 1 防御 | bridge 二次防御缺 |
| F3 parse 失败 | ✅ stage 内 retry | OK |
| F4 timeout | ❌ 无 per-stage timeout | 批量 hang |
| F5 写盘失败 | ❌ 无 graceful path | quarantine 缺失 |
| F6 partial | ⚠️ review_queue | bridge 不传 |
| C1 6 并发 | ⚠️ 已有 semaphore | 但 bridge 必须加锁 |
| S1 重复 | ✅ V7 WikiWriter idempotency | OK |
| S3 覆盖 | ❌ 无 check | 旧页面丢失 |
| S4 配置变 | ✅ Manifest + lineage | OK |
| R1 22k | ⚠️ Stage 2 deterministic | bridge 必须调 |
| R5 多 topic | ❌ 无 per-topic cap | 一个失败拖全部 |

**未覆盖的失败模式 6/12（50%）**。

## 4. 雪崩推演

### 雪崩 1: LLM 全面故障

```
MiniMax outage (5 min)
  → 6 并发 × 每个 task 9 retry × 3 stage 都失败
  → CircuitBreaker 3 failures → OPEN (src/circuit_breaker.py)
  → 所有 task 进入 FAILED → dead_letter
  → 4918 files queue 全部冻结
  → ops 收到 dead_letter 风暴
```

**雪崩临界**: circuit breaker 阈值（3 failures）太低 + retry budget (3 retries/stage) 太高 → 一次 outage 让 4918 全部失败。

**整改**: 
- (P0) 调高 breaker 阈值到 10
- (P1) 减少 default retries 到 1
- (P1) `extract_pilot.py:163` 已经有 budget；bridge 必须 reuse

### 雪崩 2: WikiWriter partial failure

```
WikiWriter 写第 1 页成功 → 第 2 页失败 → 抛异常
  → commit_and_index partial write state on disk
  → bridge 接 exception → run_ingest catch → FAILED
  → partial wiki state: 1 个 concept 已写但 source 没写
  → 重跑同 source → WikiWriter idempotency check → 1 已写，跳过 → 但 source 是新的
  → 后续 reconcile 找 source → 找不到 → broken wiki
```

**雪崩临界**: WikiWriter 不原子。

**整改**: (P0) bridge 在调用 WikiWriter 之前 snapshot 期望写盘列表 + WikiWriter 的 CommitManifest 必须 commit 后才 report success。这是 V7 Task 19 的设计，验证是否生效。

## 5. 加固方案汇总（按 P0/P1/P2 排序）

### P0（必须修，否则 V7 替换失败）

1. **Bridge 必须按 Stage 2 deterministic split 调用**（F2 整改）—— 把 `_extract_items` 等从 scripts 抽到 `v7_extract.segmentation`
2. **bridge 必须检查 `classification.failed`**（F2/F8 整改）
3. **bridge 必须传 `_result.canonical_text` 而非 raw `source_text`**（O10 整改）
4. **bridge 必须调 `_extracted_text` 经 sanitizer 处理**（F4/F8 整改）
5. **bridge 必须抛 `InvalidInputError` 当 pages=[] + empty source**（F6 / 临界 1 整改）
6. **bridge 不写 source stub 用 V7 WikiWriter**（F3 整改）—— source stub 必须经 `commit_ingest` 写盘
7. **bridge 计算 source page sha256 + 传 `expected_page_hashes`**（S1 整改）
8. **bridge 加 source-page-existing check**（S3 整改）—— 写前扫 `wiki/sources/<id>.md` 存在则 merge or skip
9. **bridge 加 `RUFLO_V7_MAX_USD` / `RUFLO_V7_MAX_CALLS`** budget（H2/F1 整改）
10. **bridge 加 `RUFLO_V7_STAGE_TIMEOUT_SEC`** per-stage timeout（F4 整改）
11. **bridge 加 `_queue_lock` acquire/release**（临界 5 整改）
12. **bridge exception 路径写 `.index/quarantine/<task_id>/v7_<reason>.md`**（F5 整改）

### P1（强烈建议修）

1. **调整 CircuitBreaker 阈值到 10**（雪崩 1 整改）
2. **reducer default retries to 1**（雪崩 1 整改）
3. **`fill_slots_v2` 改成按用户预算切换 v2/v3 默认**（H2 整改）
4. **bridge 在 meta 加 `failed_topics`**（F6 整改）
5. **bridge 加 `len(content) > settings().max_source_chars * 4: raise`**（临界 4 整改）

### P2（nice-to-have）

1. **bridge 加 shadow mode**（与 extract_pilot 的 dry-run 等价）
2. **bridge 加 partial commit report** —— 哪些 page 已写、哪些 failed

---

## 6. 边界条件清单（未在 plan 中提及但需确认）

| # | 边界 | 现状 | 是否要管 |
| --- | --- | --- | --- |
| B1 | content 含 null 字节 | preprocess_source 未过滤 | **要** |
| B2 | content 是 base64 | 无法解码 | **要** |
| B3 | 文件路径含 CJK | 不影响内容 | 否 |
| B4 | 文件是 symlink | Collector 已处理 | 否 |
| B5 | 多个 source 共享同一 wiki/concepts/<id>.md | WikiWriter idempotency | OK |
| B6 | provider 返回 401 | HealthCheck 失败 | **要** |
| B7 | 用户在 ingest 中重启 server | run_v7_ingest 抛 | **要**（manifest 恢复） |
| B8 | 时间戳溢出（> 2^32） | 不可能（现在 2026） | 否 |

---

## 压力测试问题清单

| # | 问题 | P |
| --- | --- | --- |
| ST1 | 缺 cost budget（MiniMax 限速下批量不可行） | P0 |
| ST2 | 缺 per-stage timeout（hang 风险） | P0 |
| ST3 | 缺 partial-failure 路径审计（看不见 5→3 topic 缩减） | P0 |
| ST4 | 缺 S3 同 id 覆盖保护 | P0 |
| ST5 | 缺 quarantine 写入（V7 失败不可查） | P0 |
| ST6 | 缺 `_queue_lock` 接入（并发写竞争） | P0 |
| ST7 | 缺 breaker 阈值调整（一次 outage 全员 dead_letter） | P1 |
| ST8 | 缺 retries 默认调整 | P1 |
| ST9 | 缺 content 大小上限检查（OOM） | P1 |
| ST10 | 缺 B6/B7 边界保护（401 / 重启） | P1 |
| ST11 | 缺 shadow mode（生产 debug 困难） | P2 |

**压力测试 12 项中 P0 = 6 项**。
