# Plan-Audit Round 2 压力测试 Report

> **审查范围**：`docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md`（Round 1 整改后）
> **审查依据**：`.agents/skills/plan-audit/references/audit-prompts.md` §2（压力测试推演）
> **审查身份**：独立第三方审计专家 / 模拟多种失败路径
> **Round 1 状态**：致命 0 / 重大 0 / 优化 3（已吸收）/ 盲区 3（已部分吸收）
> **关键上下文**：
> - `.memory/feedback-v7-stage3-asr-prompt-fix-2026-09-19.md`（5 跑实测背景）
> - `src/pipeline/v7_extract/invariants.py` I5 定义
> - `src/lineage/api.py:148, 198, 515, 610` 4 处 executemany INSERT
> - `src/pipeline/v7_extract/bridge.py` V7 bridge 主流程
> - `src/pipeline/v7_extract/segmentation.py:34` SegmentationStatus 枚举
> - `scripts/run_v7_5x.py` / `scripts/verify_v7_ingest.py` 验证工具

---

## 压力场景与连锁反应

### 场景 1: 开发人员临时接手 / 不熟 Stage 2 invariant 实现 → 漏改 invariants.py 字段

- **触发条件**:
  - 原作者休假 / 离职，新接手 dev 拿到 plan 文档但**没读 Round 1 审计报告**；
  - 仅按 §Task 1 "思路" 一节照抄 `wrap_items_as_segmentation_result` 内的 `if/elif invariants.i5_gap_at_tail` 判断；
  - 跳过"实施代码"块里看起来"明显重复"的 `validate_segmentation_invariants` 改动。
- **直接后果**:
  - `InvariantReport` dataclass 没有任何 `i5_gap_at_tail` / `i5_gap_bytes` 字段；
  - `wrap_items_as_segmentation_result` 第 154 行 `elif invariants.i5_gap_at_tail and invariants.i5_gap_bytes <= MAX_TAIL_GAP_BYTES` 抛 `AttributeError`；
  - **所有 Stage 2 调用点（V7 bridge / `extract_pilot.py`）立刻崩**，Stage 1 12 次 classify 不跑，bridge 直接 stage2_technical_failure。
- **连锁反应（1-2 步延伸）**:
  1. **5 跑实测全失败**：`run_v7_5x.py` 跑 5 个 ASR 文件，全部 `failure_stage=stage2_technical_failure`；
  2. **Task 3 验收脚本误判**：`verify_v7_ingest.py:134-141` 把 `failure_stage is not None` 标 FAIL → 判据 1 / 5 都挂 → 整体 NOT PASS → 触发 plan 自带的"否则回 Task 1/2 排查"循环；
  3. **新接手 dev 误判方向**：以为 LLM provider 配错（实际是代码层），去 debug `llm-providers list`，浪费 1-2 小时。
- **覆盖检查**:
  - **plan 有预案**：§Task 1 §Implementation invariants.py 改动 显式列出 `i5_gap_at_tail: bool = False` / `i5_gap_bytes: int = 0` 字段 + 默认值 + 计算逻辑；
  - **覆盖盲区**：plan 没显式声明"为什么这两个字段在 §Files '**新增** invariants.py' 段就有但 §思路 'invariants.py（**不动**）' 看似矛盾"——Round 1 整改后**两个段落统一了**（"invariants.py **新增** 字段"），但接手 dev 看 PR diff 时仍可能困惑；
  - **新增 Round 1 复审新-① 已部分缓解**：helper 返回 errors list 模式教会"返回结构变化必须显式"；
  - **验证后**：仍存在被误读风险。
- **临界点**:
  - **"可行" → "失效"**：当接手 dev **没有跑** `git diff src/pipeline/v7_extract/invariants.py` 验证 `i5_gap_at_tail` 字段已添加，而是按 §Task 1 §Test-first 第 1 条"invariants.py 加测试" 推断字段已存在。
  - **触发条件具体化**：若 §Task 1 §Acceptance 验收命令 `pytest tests/test_pipeline/test_v7_extract_invariants.py` 第 1 条新增测试**写得不严格**（只断言 `i5_gap_at_tail=True`，不显式 import `InvariantReport` 验证字段存在），接手的 dev 跑绿测试就能跳过 invariants.py 改动。
- **加固建议**:
  - **P0**：§Task 1 §Acceptance 必须新增"字段存在性 hard check"：```python assert hasattr(InvariantReport, 'i5_gap_at_tail') and hasattr(InvariantReport, 'i5_gap_bytes') ``` 作为测试前置条件；
  - **P1**：§Task 1 §Files 段统一术语：把"**新增** invariants.py 字段（不动 I5 严格性）"合并为一行声明，避免接手 dev 看到两段冲突描述；
  - **P2**：在 `.memory/feedback-v7-stage2-i5-lineage-fix-2026-09-19.md` 实施日志开头加一段"新手入门 checklist"：`git diff src/pipeline/v7_extract/invariants.py | grep -E "i5_gap_(at_tail|bytes)"`。

---

### 场景 2: 磁盘满 → recovery_errors.log 写入失败 → Task 2 写入元数据全链路雪崩

- **触发条件**:
  - 在 CI 或 dev box 上，`.index/lineage/` 所在文件系统被另一进程塞满（例如另一项目在做大规模 log rotation）；
  - Task 2 `_safe_insert_artifact_sources` 的"失败行入 recovery_errors.log"分支触发；
  - `recovery_log.parent.mkdir(parents=True, exist_ok=True)` 失败 + `recovery_log.open("a")` 抛 `OSError: [Errno 28] No space left on device`。
- **直接后果**:
  - 写入 recovery_errors.log 抛 `OSError` → plan §Task 2 代码 `with recovery_log.open("a", encoding="utf-8") as f:` **没 try/except 包裹** → 异常上抛到 `_recover_pending` 的 try/except **(OSError, ValueError)** → `continue` 跳过当前 page_id；
  - **关键**：plan §Task 2 代码决定表 "INSERT 全部成功 → 入 DELETE 列表 / INSERT 部分失败 → 入 DELETE 列表 + 写 log"——但**写 log 本身失败**这条 path 在决策表里**没列出**。
- **连锁反应（1-2 步延伸）**:
  1. **雪崩起点**：当前 page_id 因 OSError 不入 DELETE 列表 → pending_wiki_commits 行永远不被清理 → 下次启动 LineageStore.open() 又尝试恢复、又抛 OSError、又写不出 log → **无限循环 + log 噪声 0 增长**（log 没写入但也没爆炸）；
  2. **健康度恶化**：`health()` 把 pending_wiki_commits 行计入 `pending_outbox` 计数（`api.py:678`）→ novel-wiki-v2 报 `pending_outbox=N` 持续不归零 → 监控告警；
  3. **`commit_ingest` 二次失败**：`LineageStore.open()` 自身**没抛**（`_recover_pending` 静默跳过），但因为 FK 违反被吞、孤儿 source_id 丢失 → `artifact_sources` 行数减少 → `health.orphan_links` 增大 → book_compiled 时 `materialize_book_manifest` 因 health 失败拒绝出书；
  4. **Task 3 验收判据 2 FAIL**：`health --project` exit≠0（pending_outbox 不为 0 + orphan_links 增大）→ plan 整体失败。
- **覆盖检查**:
  - **plan 有预案**：§Task 2 决策表列出"INSERT 抛非 IntegrityError → 跳过（不入 DELETE 列表）" → OSError 落入此分支 → 不入 DELETE 列表 ✓；
  - **plan 无预案**：**写 recovery_errors.log 本身抛异常时怎么办？** 决策表只描述"INSERT 失败"和"INSERT 成功"两类，**没描述 "INSERT 部分成功 + log 写入失败"** 这第三类状态。
- **临界点**:
  - **"可行" → "失效"**：当 `.index/lineage/` 所在文件系统**只剩 inode 但空间满**（如 XFS quota）→ mkdir 失败 → recovery_log.parent.mkdir 抛 PermissionError 或 OSError → 当前 page_id 既不入 DELETE 列表、也不写 log、下次启动仍尝试恢复；
  - **触发条件具体化**：磁盘使用率 > 95% + 同时另一进程在 `.index/` 下写大量 log。
- **加固建议**:
  - **P0**：§Task 2 实施代码在 `with recovery_log.open("a", encoding="utf-8") as f:` 块外包一层 `try/except OSError as log_err:`，失败时**至少**把错误写到 stderr（`sys.stderr.write`）或 stdout logging + **强制入 DELETE 列表**（保证 pending 表清空）：
    ```python
    try:
        with recovery_log.open("a", encoding="utf-8") as f:
            f.write(f"{...} skipped={errors}\n")
    except OSError as log_err:
        log.error("recovery_errors.log write failed: %s (page=%s)", log_err, page_id)
        # 仍然入 DELETE 列表（log 失败不阻断 pending 清理）
    pending_deletions.append(page_id)
    ```
  - **P1**：磁盘满早期预警——`recovery_log.parent.stat()` 后若可用空间 < 1MB，**前置**抛出 `RuntimeError` 让运维看到（不要等写入失败）；
  - **P2**：recovery_errors.log 加 `logrotate` 配置（plan 任务范围外，但 ADR-0015 必含要素"Consequences"可提示）。

---

### 场景 3: LLM 502/429/timeout + provider 切换 + Stage 3 classify 12 次重试雪崩

- **触发条件**:
  - Stage 1 跑 `classify_doc(source_text, llm=provider)`：plan 上下文说"5 跑实测 4/5 在 Stage 3 失败"，但 plan 没说 Stage 1 也走 LLM；
  - 默认 `minimax` provider 在跑第 3 个 ASR 文件时返回 `502 Bad Gateway` 或 `429 Rate Limit`（minimax 限流）；
  - Stage 1 没有重试逻辑 → classify_doc 返回 `Classification(failed=True, error="502 Bad Gateway")`；
  - bridge.py:305 `if classification.failed:` → `failure_stage="stage1"` → bridge 退出。
- **直接后果**:
  - **5 跑实测 Task 3 判据 1 FAIL**：5 个文件中 3 个 stage1 失败 → `verify_v7_ingest.py:134` 判定 FAIL；
  - **链路问题不在本 plan 范围**：provider 切换、LLM 重试、timeout 都不是本 plan 解决的；
  - **plan 未触及**：§非目标 第 22-28 行明确"不动 RUFLO_PIPELINE_MODE / 不处理 Stage 3 prompt 改动"——但**Stage 1 限流**完全没在 §非目标 显式排除，让审计者怀疑"是否 plan 隐含要修 Stage 1 重试"。
- **连锁反应（1-2 步延伸）**:
  1. **雪崩边界效应**：plan 假设"Stage 1 + Stage 3 都通过 = Task 1 + Task 2 修复即可"，但生产场景下 Stage 1 502 让 5 跑变 3 跑（甚至 1 跑），**统计功效（statistical power）归零**——剩 2 个跑通的 ASR 文件根本无法判定"TAIL_RESIDUE 是否真的修了 ASR 问题"；
  2. **回归测试假绿**：单元测试用 mock LLM 全绿（mock provider 不会 502），但实测时全挂 → **测试套假绿 + plan 验收误判 PASS**；
  3. **回滚决策两难**：5 跑没拿到有效数据 → 不知道 Task 1 修复是否生效 → 是 revert Task 1 commit 还是 revert Task 2 commit？→ 没有运营日志辅助决策。
- **覆盖检查**:
  - **plan 有预案**：§非目标 显式排除 Stage 3 prompt 改动 / Stage 1 灰度期 / Stage 6 关系抽取 → **隐含不修 provider 限流问题**；
  - **plan 无预案**：5 跑实测的**抗 provider 抖动能力**未说明——若 minimax 5 次跑里 502 两次，**这两次的失败归因**是 provider 问题还是 plan 修复未生效？plan 没区分。
- **临界点**:
  - **"可行" → "失效"**：当 minimax provider 限流频率 > 5 跑中 1 次（20%）时，**实测样本不足**判定 Task 1 修复有效性；
  - **触发条件具体化**：minimax provider 当日 quota 用完 + 5 跑间隔 < 1 分钟（无 retry 间隔让限流累积）。
- **加固建议**:
  - **P0**：§Task 3 §验收 显式加"判据前置条件"：```run_v7_5x.py 必须在 provider 健康时才能视为有效测试。provider 健康 = 5 个文件全部 classify_doc 返回 failed=False 且 duration < 30s```——5 跑前先做 1 个 sanity probe 文件验证 provider；
  - **P1**：§Task 3 §注意事项 明确"限流场景下不视为 plan 失败，而是 provider 问题，记入 `.memory/feedback-*.md` 另开 plan 处理"；
  - **P2**：plan 加 "provider 切换白名单"——若 minimax 失败，自动切到 ollama（dev box 备用），确保 5 跑不被单点 provider 卡死。

---

### 场景 4: Stage 1 classify_doc 12 次超时（max_retries=3 × 默认 4 candidate doc_type？）→ bridge 超时雪崩

- **触发条件**:
  - plan 上下文说"Stage 1 classify_doc 12 次"——这暗示 Stage 1 有重试/枚举逻辑；
  - `bridge.py:66` `DEFAULT_STAGE_TIMEOUT_SEC: int = 120` — 单次 LLM 调用 120s 超时；
  - 若 minimax 响应慢（无 502 但每次 110-115s），**单个 Stage 1 调用 120s 超时** → 异常上抛 → bridge 失败。
- **直接后果**:
  - `bridge.py:185-192` `await asyncio.wait_for(coro, timeout=budget.stage_timeout_sec)` 抛 `asyncio.TimeoutError`；
  - bridge.py 没显式 except TimeoutError → 异常冒泡到 `run_v7_ingest` 顶层 → `failure_stage="uncaught_timeout"`（或 plan 自定义 stage）；
  - 5 跑实测看到大量 uncaught_timeout → Task 3 判据 1 FAIL。
- **连锁反应（1-2 步延伸）**:
  1. **cost 浪费**：每次 timeout 已消耗 token 计费（minimax 计费按 prompt tokens），但没产出结果 → 5 跑浪费 5 × 单价；
  2. **quarantine 累积**：plan 上下文说"任务 FAILED + quarantine"——bridge.py 没显式 except TimeoutError 走 quarantine 路径，而是异常冒泡 → quarantine 永远不写入 → **真实失败原因丢失**，运维排查不到。
- **覆盖检查**:
  - **plan 有预案**：plan §非目标 不处理 Stage 1 行为，但**显式声明了"5 跑实测是 Task 1 + Task 2 修复的验收"** → 若 Stage 1 超时挡住验收，**plan 没说怎么办**；
  - **plan 无预案**：bridge.py 在 timeout 时**没有 quarantine fallback 路径**——这是 Stage 0 既有实现的 gap，但 plan 完全没提。
- **临界点**:
  - **"可行" → "失效"**：当 minimax 平均响应 60-100s（不超时但接近阈值）+ classify_doc 多次串行调用时，单个文件总耗时 5-10 分钟 → 5 跑实测 = 25-50 分钟 → **CI timeout 杀进程**；
  - **触发条件具体化**：CI runner 限制单测 30 分钟 + minimax 慢响应。
- **加固建议**:
  - **P0**：§Task 3 §验收 增加"判据时间预算"——5 跑总耗时 ≤ 25 分钟（每跑平均 5 分钟），超过则视为 provider 问题（不在 plan 修复范围），重置跑；
  - **P1**：bridge.py timeout 应有专门的 failure_stage="stage_timeout" 标记，方便 verify_v7_ingest 区分 "bridge 真失败" vs "provider 慢响应"；
  - **P2**：bridge.py 在 TimeoutError 时调用 `enqueue_failure()` 写入 quarantine（plan §非目标"不动 Stage 1 灰度"边界明确——但 quarantine 写入是基础设施层，应在 §任务范围外说明"future hardening"）。

---

### 场景 5: minimax 突发限流 + 数据库 schema 迁移并发 → lineage 表结构不一致雪崩

- **触发条件**:
  - 5 跑实测过程中，运维同时推数据库 schema 迁移（例如在 `state.db` 加 `recovered_at` 列）；
  - `LineageStore.open()` 的 `db.executescript(...)` 用 `CREATE TABLE IF NOT EXISTS`（api.py:50）——**对已存在的旧表不加列**；
  - 但同时**新版本** LineageStore 用 `INSERT INTO artifact_sources(...)` 时旧表无 `recovered_at` 列（如果有此列假设）→ `sqlite3.OperationalError: no such column`。
- **直接后果**:
  - 假设 schema 迁移**没**真正发生（仅作为风险情景）——真实风险是另一类：**同时打开两个 LineageStore 实例**（如 5 跑脚本 + server 进程）→ SQLite database is locked (`sqlite3.OperationalError: database is locked`)；
  - api.py:49 有 `PRAGMA busy_timeout=5000` → 5 秒后**自动重试**——但若锁持续 > 5s，**抛 OperationalError 上抛**；
  - Task 2 helper 没显式处理 OperationalError → 决策表**只列 IntegrityError** → OperationalError 落入"未分类异常 → raise"分支 → `_recover_pending` 抛错 → bridge 退出。
- **连锁反应（1-2 步延伸）:
  1. **雪崩起点**：OperationalError 抛到 bridge.py → bridge 标 stage2_technical_failure → 5 跑中第 2、3 个文件都因锁失败 → 5 跑实测全挂；
  2. **诊断困难**：错误是锁 vs 是 UNIQUE vs 是 FK？`log.exception("recover_pending IntegrityError for %s", page_id)`（plan §Task 2 实施代码）只 catch IntegrityError，**OperationalError 不被 catch** → 错误冒泡到 `LineageStore.open()` → open() 不接 catch → 抛到 caller；
  3. **数据一致性窗口**：若 OperationalError 抛在 INSERT 中间，`with self._db:` 上下文管理器**自动回滚事务**（api.py:504 / 597 / 552）→ 事务安全 ✓ → 但 task 上下文状态丢失 → bridge 重试时 `LineageStore.open()` **重新初始化**——重新跑 `_recover_pending`——若同样问题持续，**死循环**。
- **覆盖检查**:
  - **plan 有预案**：busy_timeout=5000 自动等待（既有），OperationalError 不在本 plan 修复范围（隐含的 §非目标）；
  - **plan 无预案**：schema 迁移并发场景 + OperationalError 分类完全没考虑。
- **临界点**:
  - **"可行" → "失效"**：当 5 跑实测脚本与运行中的 server 进程并发访问 `state.db` 时，且 server 在做 `book_compiled` 长事务（10s+ 持锁）；
  - **触发条件具体化**：dev box 同时跑 `python -m src.cli serve` + `python scripts/run_v7_5x.py`。
- **加固建议**:
  - **P0**：§Task 3 §验收命令前置 `pkill -f "src.cli serve"` 或 `lsof knowledge/novel-wiki-v2/.index/lineage/state.db` 确认无其他进程持有；
  - **P1**：§Task 2 决策表显式增加 "OperationalError（锁）→ 等 1s 重试 1 次，再失败 raise"；
  - **P2**：ADR-0015 Consequence 段提示"lineage schema 演进需独立 schema migration plan，本 plan 不涉及"。

---

### 场景 6: 并发写同一 page_id → V7 bridge 两次跑同一文件 → wiki/concepts/ 覆盖雪崩

- **触发条件**:
  - 运维误操作——5 跑脚本跑完第 1 个文件后，**手动**再次跑同 1 个文件（"replay test"）；
  - 第二次跑时，第 1 次的 page_id 已写入 `wiki/concepts/abc.md`；
  - 第二次跑 `bridge.py` 产生**新 page list**（不同 topic.id 因 LLM 抖动的边缘情况）→ 同一个 base_page_id 但不同 topic 内容 → `commit_ingest` 用相同 page_id 覆盖；
  - bridge.py:406 `seen_page_ids: Counter[str] = Counter()` 是**单次 bridge 内的去重**，**不跨 bridge 持久化**。
- **直接后果**:
  - 第 1 次 bridge 写到 wiki/concepts/page-x.md；
  - 第 2 次 bridge 同样 page-id → `commit_ingest` 写新内容到 wiki/concepts/page-x.md（**覆盖**）→ 第 1 次的内容永久丢失；
  - **更糟**：第 2 次的 `record_wiki_commit` 调 `link_artifact(artifact_kind='wiki', artifact_id='page-x', source_ids=(...)` → api.py:606 `DELETE FROM artifact_sources WHERE artifact_id=?` 清空 → `executemany INSERT` 重建——**只要第 2 次的 source_ids tuple 含重复**（参见场景 7），又撞 UNIQUE。
- **连锁反应（1-2 步延伸）**:
  1. **数据丢失**：第 1 次的内容被覆盖，log.md 仍记录第 1 次的成功，但实际文件已变 → **日志与文件不一致**；
  2. **幂等性退化**：bridge.py 的 page_id 生成用 `topic.id` 哈希 → 同一 topic 在两次 LLM 调用中产生**不同的 topic.id**（即便 base_page_id 一致）→ 不能简单判断"已存在则跳过"；
  3. **regression test 假绿**：plan §Task 3 判据 4 "幂等性观察"（verify_v7_ingest.py:183-190）只观察 file count delta——若两次都成功写 file count 不变 → 看起来幂等，但实际内容变了。
- **覆盖检查**:
  - **plan 有预案**：§Rollback 说"Task 2 rollback 不清 pending_wiki_commits"——这是数据保护，但**不防止并发覆盖**；
  - **plan 无预案**：并发 / replay 场景完全没覆盖。
- **临界点**:
  - **"可行" → "失效"**：当运维在 5 跑实测**未完成**时手动重跑同一文件 → 数据覆盖；
  - **触发条件具体化**：5 跑实测中途 dev box 重启 / CI 重试 / 手动 `./run_v7_5x.py --only-file X`。
- **加固建议**:
  - **P0**：§Task 3 §验收加前置检查——`md5sum wiki/concepts/*` 跑前快照 + 跑后对比，**文件内容变了视为覆盖 bug**（不仅是 file count）；
  - **P1**：bridge.py 写盘前检查 `wiki/concepts/{page_id}.md` 是否存在，若存在且 hash 不同 → 写入 `.index/quarantine/<task_id>/overwrite_warning.md` 而非覆盖；
  - **P2**：§Open risks 段追加"并发覆盖风险——本 plan 未处理，建议未来 plan 加 page_id 锁"。

---

### 场景 7: link_artifact 运行态 source_ids tuple 含重复 → 4 处 executemany 雪崩边界

- **触发条件**:
  - Round 1 已整改 ①-2：plan §Task 2 把 4 处 executemany 改用 `_safe_insert_artifact_sources` helper；
  - 但 plan §Task 2 决策表对 `link_artifact`（运行态）的错误处理细化说：**"FK violation 抛 DataConsistencyError；UNIQUE violation 不抛；其他 errors 抛"**；
  - 实测场景：novel-wiki-v2 的 Stage 5 claim_extractor 在 ASR 转录稿上跑出**同一 raw source 被算两次**（因为 ASR 的"声音结尾重复"导致 evidence 引用同一 source 两次）→ record_wiki_commit 的 source_ids tuple = ('src-001', 'src-001')；
  - helper `seen: set[str]` 去重后实际只剩一个 → INSERT 一次 → 不撞 UNIQUE → 看似 OK；
  - **但**——Stage 5 的 `_current_source_id`（commit_ingest.py:1723）也加进 source_ids tuple：实际 source_ids = ('src-001', 'src-001', 'cur-src') → helper 去重后 = ('src-001', 'cur-src') → INSERT 两次 → 不撞 UNIQUE（不同 sid）→ 但若 cur-src 在 sources 表中**不存在**（FK 违反），抛 FK violation。
- **直接后果**:
  - plan §Task 2 决策表"link_artifact 抛 DataConsistencyError"——运行态 FK 违反**真抛**；
  - `record_wiki_commit` 抛 DataConsistencyError → bridge 退出 → commit_ingest 失败 → **同 stage3_incomplete 一样卡 0 页面**；
  - **与未修 plan 的 5 跑实测行为无差别**——Task 2 修复对"运行态 FK 违反"反而让**失败更显眼**（DataConsistencyError 抛而非 IntegrityError 吞），但**outcome 一样：0 wiki 写入**。
- **连锁反应（1-2 步延伸）**:
  1. **数据丢失**：bridge 失败时 commit_ingest 未提交任何页面，但 Stage 5 LLM 调用成本已花；
  2. **quarantine 没写**：DataConsistencyError 抛后**没**调 `enqueue_failure()`（bridge.py 没显式 except）→ 真实失败原因丢失；
  3. **Task 3 判据 1 FAIL**：verify_v7_ingest.py:134 标 FAIL → plan 整体失败 → 但 plan 自带的"否则回 Task 1/2 排查"循环**误导**开发者去查 I5 / lineage，**实际问题是 Stage 5 产生重复 source_id**。
- **覆盖检查**:
  - **plan 有预案**：决策表显式区分 link_artifact 与 _recover_pending 错误处理（line 336-340）；
  - **plan 无预案**：**上游 Stage 5 source_ids 产生逻辑**完全没排查——若 Stage 5 把同一 source 算两次是系统性 bug，plan 修了"下游 INSERT 兜底"但**没修源头**。
- **临界点**:
  - **"可行" → "失效"**：当 ASR 转录稿在 Stage 5 claim_extractor 上**持续**产生重复 source_id（系统性 bug）→ 每次 ingest 都撞 → 5 跑实测每次都 FK violation → 任务彻底无法运行；
  - **触发条件具体化**：Stage 5 prompt 包含"引用原话时引用 source"指令，但 ASR 转录稿同一段对话被引用多次时，Stage 5 输出 list 含重复。
- **加固建议**:
  - **P0**：§Task 2 helper 在 link_artifact 调用点**保留 UNIQUE 静默**（不去重，因为去重会丢信息），但**显式 log 重复 source_id**——让 Stage 5 prompt 修复 plan 能定位；
  - **P1**：§Open risks 追加"Stage 5 source_ids 产生逻辑未排查——若 Stage 5 系统性产生重复 source_id，Task 2 修复无能为力，需独立 plan"；
  - **P2**：bridge.py 的 DataConsistencyError 应调 `enqueue_failure()` 写 quarantine，方便运维定位 Stage 5 bug 而非误以为是 I5 / lineage 问题。

---

### 场景 8: MAX_TAIL_GAP_BYTES=1024 边界 → 1025 字节 gap → DEGRADED 退化到原行为 → LLM 仍判 INCOMPLETE

- **触发条件**:
  - plan §Task 1 实施代码用 `i5_gap_bytes <= MAX_TAIL_GAP_BYTES` 判定 TAIL_RESIDUE；
  - MAX_TAIL_GAP_BYTES=1024；
  - novel-wiki-v2 的某个 ASR 文件（不在 5 跑实测 5 个中）的尾 gap 是 **1025 字节**（介于"自然 ASR 烂尾"与"真分段 bug"边界）；
  - 退化到 status=DEGRADED → boundary_confidence=0.5 → Stage 3 LLM 看到 `boundary_confidence=0.5` 仍判 INCOMPLETE。
- **直接后果**:
  - **该文件 5 跑实测 FAIL**：判据 1 / 5 标 FAIL；
  - **plan 的"源头修复"声称效果部分失效**：5/6 个 ASR 文件修好，1/6 仍 DEGRADED；
  - **运维视角**：5 跑实测"不全绿" → plan 自带循环"否则回 Task 1/2 排查" → dev 反复调整 MAX_TAIL_GAP_BYTES → 但 1024 是经验值，调到 2048 也只多覆盖一类。
- **连锁反应（1-2 步延伸）**:
  1. **阈值调参循环**：dev 调 1024 → 2048 → 4096 → 8192，每次调整都要重跑 5 跑实测（每次 25-50 分钟）→ **1-2 天调参循环**；
  2. **阈值过大掩盖真 bug**：调到 8192 时，**真分段 bug**（gap = 5KB）也被判 TAIL_RESIDUE → boundary_confidence=1.0 → Stage 3 LLM 看到"完整"信号但实际有 missing item → **静默质量退化**；
  3. **跨项目不可移植**：100KB 的网页转录稿 gap 可能是 5KB（HTML 转写丢失），但 100KB 的 ASR 文件 gap 可能是 50B——固定阈值无法跨 KB 适配。
- **覆盖检查**:
  - **plan 有预案**：§Task 1 §Test-first 阈值边界 2 条 fixture（gap=1024 / 1025）已覆盖**单文件**；
  - **plan 无预案**：**跨文件大小 / 跨项目类型**的阈值自适应——Round 1 二次复审 ③-C 已要求 1024/1025 边界 fixture，但 plan 没要求"如果不同 size 的源需要不同阈值，quality_settings.json 应可配置"。
- **临界点**:
  - **"可行" → "失效"**：当 novel-wiki-v2 的 ASR 文件大小分布**不均匀**（有的 1KB，有的 1MB）时，固定 1024 阈值**要么过严要么过松**；
  - **触发条件具体化**：100KB ASR 文件末尾有 2KB HTML 转写丢失（1MB 文件的 0.2%）——固定 1024 阈值判 DEGRADED，但比例上是"0.2% 缺失"远低于"真分段 bug"（往往 5%+ 缺失）。
- **加固建议**:
  - **P0**：§Open risks 追加 `MAX_TAIL_GAP_BYTES = 1024` 是经验值，可能未来需按项目调整——这条已经在 Round 1 §Open risks 列出，**但没声明"何时调整 / 如何调整 / 谁来调"**；
  - **P1**：plan 加 "阈值调整 runbook"——若 5 跑实测发现 gap=1025 仍期望 TAIL_RESIDUE，应通过 quality_settings.json 的 `max_tail_gap_bytes` 项目级配置覆盖（ADR-0015 Consequence 段已暗示"可能需要项目级配置"）；
  - **P2**：替代方案——阈值改为**比例式** `gap_ratio = gap_bytes / source_size`，TAIL_RESIDUE 当 `gap_ratio < 0.005`（即 0.5%），而非固定字节。

---

### 场景 9: SQLite 版本 < 3.6.19 → INSERT OR IGNORE 行为不一致 → FK 违反雪崩

- **触发条件**:
  - `src/lineage/api.py:48` `db.execute("PRAGMA foreign_keys=ON")` —— SQLite FK 强制在 **3.6.19+** 才支持；
  - 若 dev box 用老系统 SQLite（如 CentOS 7 默认 3.7.17 OK，但 macOS 系统 Python 自带 3.16+ OK）—— **基本不会触发的边界 case**；
  - 但 `INSERT OR IGNORE` 的 FK 行为在不同 SQLite 版本有差异：3.6.19 之前 FK 强制不完整，OR IGNORE 不一定能 catch FK 错误。
- **直接后果**:
  - 在 SQLite < 3.6.19 上，PRAGMA foreign_keys=ON **实际无效**（不抛 FK 违反）→ INSERT OR IGNORE 看似成功但**实际写入了孤儿引用**（referential integrity 静默破坏）；
  - **Task 2 helper 的 try/except IntegrityError** 在 FK 违反时不触发 → 看似 helper "成功" → pending_deletions.append(page_id) → DELETE pending → **孤儿引用永久写入**；
  - `health()` 报 orphan_links 增大 → book_compiled 时 `materialize_book_manifest` 因 orphan 拒绝出书 → Task 3 判据 2 FAIL。
- **连锁反应（1-2 步延伸）**:
  1. **静默数据腐败**：orphan_links 增长但 plan 没断言 → 5 跑实测看起来 PASS（判据 1/2 表面绿）但**实际 lineage 已腐败**；
  2. **book_compiled 长期失效**：future plan 跑 book 编译时才发现 lineage 数据不一致 → 需要单独 data migration plan；
  3. **Task 2 rollback 无效**：revert 后状态不变（orphan 已写入数据库，revert 不改 DB）→ **revert 是假 revert**。
- **覆盖检查**:
  - **plan 有预案**：plan §Task 2 决策表区分 UNIQUE / FK 错误处理（Round 1 已整改）；
  - **plan 无预案**：**SQLite 版本依赖**完全没声明——plan 假设 dev box 用现代 SQLite，但若用老 SQLite，plan 修复**静默失效**。
- **临界点**:
  - **"可行" → "失效"**：当 dev box SQLite < 3.6.19 时，PRAGMA foreign_keys=ON 不生效 → helper try/except 永远不 catch FK → orphan 永久写入；
  - **触发条件具体化**：macOS 系统 Python 3.8 自带 SQLite 3.28+（OK），但 Linux 某些 minimal container（如 alpine 3.10）自带 SQLite 3.30+（OK）——**实际触发条件罕见**但**未声明"最低 SQLite 版本"**。
- **加固建议**:
  - **P1**：§Open risks 追加"依赖 SQLite >= 3.6.19 (2010-04-12 发布)"——这是**已知约束**，应在 ADR-0015 / memory feedback 显式声明；
  - **P2**：§Task 3 §验收前置 `python -c "import sqlite3; print(sqlite3.sqlite_version)"` 验证 ≥ 3.6.19；
  - **P3**：可选——LineageStore.open() 加 SQLite 版本断言，不满足时 raise RuntimeError 强制升级。

---

## 临界点汇总

| 临界点 | 当前 plan 行为 | 失效条件 | 加固建议 |
|---|---|---|---|
| **invariants.py 字段存在性** | §Task 1 §Files 显式列出"新增 i5_gap_at_tail 字段" | 接手 dev 未跑 git diff 验证字段已添加 | P0: 加 AttributeError hard check 测试；P1: 统一 Files 段描述 |
| **recovery_errors.log 写失败** | §Task 2 决策表仅列 "INSERT 部分失败 → 写 log" | 磁盘满 / inode 耗尽 / 权限丢失 | P0: log 写入包 try/except + 强制入 DELETE 列表；P1: 磁盘满早期预警 |
| **provider 限流** | §非目标 不显式排除 provider 修复 | minimax 限流频率 > 5 跑中 20% | P0: 跑前 sanity probe；P1: provider 切换白名单 |
| **LLM 慢响应 / TimeoutError** | bridge.py TimeoutError 无 quarantine fallback | 单次 Stage 1 调用 110-115s | P0: 判据时间预算 ≤ 25 分钟；P1: bridge.py 加 stage_timeout 标记 |
| **SQLite database lock** | busy_timeout=5000 自动等锁 | server + 5 跑脚本并发访问 | P0: 5 跑前 lsof 检查；P1: 决策表加 OperationalError 处理 |
| **并发覆盖同一 page_id** | bridge.py seen_page_ids 仅单 bridge 去重 | 运维手重跑同一文件 | P0: md5sum 跑前快照；P1: 写入前 hash 比对 |
| **运行态 source_ids 重复** | link_artifact 抛 DataConsistencyError | Stage 5 系统性产生重复 source_id | P0: helper log 重复 source_id；P1: Open risks 追加 Stage 5 上游排查 |
| **MAX_TAIL_GAP_BYTES 阈值边界** | gap=1024 → TAIL_RESIDUE；gap=1025 → DEGRADED | 不同 size 的 ASR 文件需要不同阈值 | P0: quality_settings.json 项目级配置；P1: 改比例式阈值 |
| **SQLite 版本 < 3.6.19** | 假设 SQLite 现代版本 | 老 SQLite 上 FK 强制无效 | P1: ADR-0015 声明 SQLite >= 3.6.19；P2: LineageStore.open() 版本断言 |
| **写入 wiki/concepts/ 后 quarantine 写入失败** | bridge.py 无 except OSError 包装 enqueue_failure | quarantine 目录权限丢失 | P2: bridge.py 关键写入加 try/except OSError |

---

## 加固方案（按 P0/P1/P2 优先级）

### P0（必须修，否则 plan 在生产环境下可能失效）

1. **§Task 1 §Acceptance 加 invariants.py 字段 hard check**（场景 1）
   ```python
   def test_invariant_report_has_gap_fields():
       from src.pipeline.v7_extract.invariants import InvariantReport
       assert hasattr(InvariantReport, 'i5_gap_at_tail')
       assert hasattr(InvariantReport, 'i5_gap_bytes')
   ```

2. **§Task 2 实施代码：recovery_errors.log 写失败时强制入 DELETE 列表**（场景 2）
   ```python
   pending_deletions.append(page_id)
   if errors:
       try:
           recovery_log.parent.mkdir(parents=True, exist_ok=True)
           with recovery_log.open("a", encoding="utf-8") as f:
               f.write(...)
       except OSError as log_err:
           log.error("recovery log write failed: %s (page=%s)", log_err, page_id)
   ```

3. **§Task 3 §验收 加 provider sanity probe + 时间预算**（场景 3、4）
   ```bash
   # 5 跑前 sanity probe
   python -X utf8 scripts/smoke_v7_bridge.py --provider minimax --file <probe.md>
   # 若 probe 在 30s 内返回非 INCOMPLETE 状态 → provider 健康
   # 5 跑总耗时 ≤ 25 分钟（每跑平均 5 分钟）
   ```

4. **§Task 3 §验收 加 md5sum 跑前快照**（场景 6）
   ```bash
   # 5 跑前
   md5sum wiki/concepts/*.md > /tmp/wiki-concepts-before.md5
   # 5 跑后
   md5sum wiki/concepts/*.md > /tmp/wiki-concepts-after.md5
   diff /tmp/wiki-concepts-before.md5 /tmp/wiki-concepts-after.md5
   # 仅当新增文件，无覆盖时视为幂等
   ```

5. **§Task 2 helper 在 link_artifact 调用点保留 UNIQUE 静默 + log 重复**（场景 7）
   ```python
   # link_artifact path: detect dup source_ids, log but don't raise
   duplicates = [sid for sid in source_ids if list(source_ids).count(sid) > 1]
   if duplicates:
       log.warning("link_artifact dup source_ids: %s/%s", artifact_id, duplicates)
   errors = _safe_insert_artifact_sources(db, artifact_id, source_ids)
   fk_errors = [e for e in errors if e[1] == "FK violation"]
   if fk_errors:
       raise DataConsistencyError(f"orphan source_ids in runtime path: {fk_errors}")
   ```

### P1（应该修，影响 plan 鲁棒性）

7. **§Task 2 决策表加 OperationalError（database lock）处理**（场景 5）
   ```python
   except sqlite3.OperationalError as e:
       if "locked" in str(e):
           log.warning("db locked, retry once after 1s")
           time.sleep(1)
           # retry helper
       else:
           raise
   ```

8. **§Open risks 追加 Stage 5 source_ids 上游排查**（场景 7）
   ```
   - Task 2 加去重 → 历史脏数据被去重 = 历史信息丢失（**可接受**，因为脏数据本来就错）
   - **新增**：Stage 5 claim_extractor 在 ASR 转录稿上可能系统性产生重复 source_id（**未排查**）→ Task 2 修复可能掩盖上游 Stage 5 bug
   ```

9. **§Open risks 追加 MAX_TAIL_GAP_BYTES 自适应配置**（场景 8）
   ```
   - Task 1 MAX_TAIL_GAP_BYTES = 1024 阈值是经验值 → 应通过 quality_settings.json 项目级配置覆盖
   - 替代方案：改比例式阈值 gap_ratio = gap_bytes / source_size < 0.005
   ```

10. **§Task 3 §验收加 SQLite 版本检查**（场景 9）
    ```bash
    python -c "import sqlite3; assert sqlite3.sqlite_version >= '3.6.19', sqlite3.sqlite_version"
    ```

11. **bridge.py 在 TimeoutError / DataConsistencyError 时调 enqueue_failure 写 quarantine**（场景 4、7）
    ```python
    except (asyncio.TimeoutError, DataConsistencyError) as e:
        result.failure_stage = f"{stage}_timeout" if isinstance(e, asyncio.TimeoutError) else f"{stage}_data_consistency"
        result.failure_reason = str(e)
        try:
            enqueue_failure(paths.root, task_id, result.failure_stage, str(e))
        except OSError:
            log.error("quarantine write failed: %s", e)
        return result
    ```

### P2（锦上添花，提升运维可观测性）

13. **ADR-0015 Consequence 段显式声明 SQLite 版本约束**（场景 9）
14. **§Task 3 §验收前置 lsof 检查 server 进程未运行**（场景 5）
15. **recovery_errors.log 加 logrotate 配置**（场景 2 衍生）
16. **bridge.py 加 stage_timeout 标记 + DataConsistencyError 标记**（场景 4、7）
17. **plan 加新手入门 checklist**（场景 1 衍生）：在 feedback 文件开头列"接手 dev 必看 5 件事"
18. **§Task 3 §验收 区分"plan 修复未生效" vs "provider / 基础设施问题"**（场景 3、4、5）

---

## 总结

- **致命压力点**: **0**
  - 理由：Round 1 已整改 2 个致命（①-1 invariants.py 字段 + ①-2 4 处 executemany），本次 Round 2 推演未发现新的"立即崩"级问题；
  - 但**场景 1**（接手 dev 漏改 invariants.py）是 Round 1 ①-1 的衍生——通过 P0 加固可完全缓解。

- **重大压力点**: **3**
  - 场景 2（recovery_errors.log 写失败 → pending_wiki_commits 永远不清）：disk-full 在 dev/CI 上较常见，但 plan 决策表**没列**此状态 → 雪崩起点；
  - 场景 3（provider 限流 → 5 跑实测样本不足 → 误判 plan 修复无效）：minimax 限流在高峰时段常见，plan 完全没预案；
  - 场景 8（MAX_TAIL_GAP_BYTES=1024 阈值边界）：固定阈值跨项目不可移植，5/6 个文件修好，1/6 仍 FAIL → plan 自带"否则回 Task 1/2 排查"循环误导 dev 调参。

- **优化压力点**: **6**
  - 场景 1（接手 dev 漏改 invariants.py）；
  - 场景 4（LLM TimeoutError 无 quarantine fallback）；
  - 场景 5（SQLite database lock 无 OperationalError 处理）；
  - 场景 6（并发覆盖同一 page_id）；
  - 场景 7（Stage 5 source_ids 重复上游排查缺失）；
  - 场景 9（SQLite 版本依赖未声明）。

- **建议**: **PASS with MANDATORY P0 FIXES**
  - **不**是 NEEDS-FIX（Round 1 致命 2 + 重大 5 + 优化 6 已整改）；
  - **但**强烈建议在实施前完成 5 项 P0 加固（场景 1/2/3/6/7），否则在生产场景下**至少**有以下风险：
    - 接手 dev 可能漏改 invariants.py 字段（场景 1）；
    - 磁盘满时 recovery_errors.log 写失败导致 pending 表永远不清（场景 2）；
    - provider 限流时 5 跑实测样本不足误判（场景 3）；
    - 运维手重跑同一文件导致内容覆盖（场景 6）；
    - Stage 5 系统性产生重复 source_id 时 plan 修复无效（场景 7）。
  - **P1 + P2 建议在 Task 4 文档同步阶段同步追加到 ADR-0015 Consequence 段**，作为已知约束记录。

---

## 附录：场景与 plan 整改映射表

| 场景 | 对应 Round 1 审计点 | Round 1 是否已整改 | Round 2 加固建议 |
|---|---|---|---|
| 1 | ①-1（invariants.py 字段缺失） | ✓ 已整改 | P0 加 hard check 测试 |
| 2 | ②-2（DELETE pending 在 try 内） | ✓ 已整改（移出 try） | P0 加 log 写失败兜底 |
| 3 | ②-4（5 跑判据无精确定义） | ✓ 已整改（逐字引用脚本） | P0 加 provider sanity probe |
| 4 | ②-4 衍生（LLM 抖动风险） | 部分（provider 检查 B-7） | P0 加时间预算 |
| 5 | B-7（5 跑前置条件） | ✓ 已整改 | P0 加 lsof 检查 |
| 6 | 新发现 | n/a | P0 加 md5sum 跑前快照 |
| 7 | ①-2（4 处 executemany） | ✓ 已整改（helper 4 处统一） | P0 helper 保留 UNIQUE 静默 + log |
| 8 | ③-2（阈值边界） | ✓ 已整改（1024/1025 fixture） | P0 quality_settings.json 配置 |
| 9 | 新发现（SQLite 版本依赖） | n/a | P1 ADR-0015 显式声明 |

---

**审计完成时间**: 2026-09-19
**审计身份**: 独立第三方审计专家（Round 2 压力测试推演）
**审计方法**: 模拟 9 种失败路径（覆盖人员缺位 / 资源不足 / 接口报错 / 超时 / 突发变更 5 类），推演连锁反应，验证兜底覆盖率
**审计依据**: `.agents/skills/plan-audit/references/audit-prompts.md` §2
**审计输出**: 本报告（致命 0 / 重大 3 / 优化 6 / 建议 PASS with MANDATORY P0 FIXES）