# Book Lineage 安全整改实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. 每个任务必须先 RED、再 GREEN、再回归；未满足放行门不得进入下一任务。

**Goal:** 在不改变现有 Wiki/KC 内容格式的前提下，阻止 raw、Wiki、KC 与 Book 之间的遗漏、误删、半成品发布和状态漂移。

**Architecture:** 以项目本地 SQLite lineage 状态库记录稳定身份、哈希、关系、状态和 outbox；文件仍是内容载体。Book 先冻结 manifest、写入不可变 release staging，完成 raw 与 Wiki 页面双重闭包后，只通过原子替换 active manifest 发布。

**Tech Stack:** Python 3.11+、stdlib `sqlite3`、现有 `safe_write`、现有 EventBus、pytest；不新增第三方依赖。

**Spec:** `docs/superpowers/plans/2026-09-04-book-lineage-state.md`；审计依据：`docs/superpowers/audits/2026-09-04-book-lineage-state-audit.md`。

## 定点整改边界

- 只处理审计报告列出的三个上线阻断项：Wiki 页面级闭包、不可变 Book 发布、全部生产写入口接入。
- 同时补齐这些阻断项直接依赖的 raw 增删改/不合格、双状态切换、健康检查和恢复测试。
- 不重写现有 Wiki/KC 数据模型，不统一既有 hash，不删除旧 Book，不改无关脚本和测试。
- 现有 `batch_build.py`、`batch_commit.py`、`aggregate_synthesis.py` 先完成写入职责核实；仅修改实际生产写入路径。
- `EventBus` 只负责唤醒，不作为一致性依据；`batch_build_state.json` 在切换前保留为兼容投影。

## 目标状态与不变量

```text
raw source
  -> source_id + raw_hash + explicit decision
  -> Wiki page(s) + many-to-many source links
  -> KC artifact(s)
  -> frozen Book manifest
  -> immutable book/.releases/<run_id>/
  -> atomic book/manifest.json active pointer
```

- 每个发现的 raw 必须是 `included`、`excluded`、`blocked`、`failed` 或 `deleted` 之一；禁止静默丢弃。
- `expected_source_ids == compiled_source_ids`。
- `expected_wiki_page_ids == compiled_wiki_page_ids`。
- raw 扫描不完整时不得生成删除 tombstone。
- raw 变更会使下游变为 stale/pending；raw 删除必须有显式 tombstone。
- 任何失败都保留上一份 active Book。
- outbox 重放幂等，不重复生成 chapter 或状态转换。

## 文件影响清单

### 必须新增

- `src/lineage/__init__.py`：模块公开入口。
- `src/lineage/types.py`：状态、关系、manifest、health 类型。
- `src/lineage/api.py`：唯一对外 API。
- `src/lineage/sqlite_store.py`：SQLite schema、事务、迁移版本、备份和锁。
- `src/lineage/reconcile.py`：写入意图与文件状态对账。
- `scripts/kc_lineage_inventory.py`：只读历史资产盘点。
- `scripts/kc_lineage_migrate.py`：dry-run/apply 迁移。
- `tests/test_lineage/`：状态、raw、写入、Book、恢复、健康检查测试。
- `docs/superpowers/specs/2026-09-04-book-lineage-state.md`：schema 和状态契约（如现有计划尚未补齐）。

### 只在实际调用点成立时修改

- raw：`src/sync/snapshot_store.py`、`src/services/ingest.py`、`src/pipeline/ingest.py`、`src/server/routes/ingest.py`、现有 readiness 模块。
- Wiki/KC：`src/wiki/storage/page_writer.py`、`src/lib/write_hooks.py`、`src/kc/publish/batch.py`、`src/knowledge/core/adapter.py`、`src/events/event_bus.py`、`src/events/events.py`。
- Book：`src/kc/views/book/materialize.py`、`src/kc/views/book/rebuild.py`、`src/kc/views/book/contract.py`、`src/cli_ext/book_cmd.py`、`src/cli.py`。
- 生产脚本：`scripts/batch_build.py`、`scripts/batch_commit.py`、`scripts/aggregate_synthesis.py`；`phase4_batch.py`、`batch_generate.py`、`accept_batch.py`、`ingest_novel_wiki_manual.py` 仅在 inventory 证明其仍写生产资产时修改。
- 运维：`src/cli_ext/`、`AGENTS.md`、`CLAUDE.md`、`docs/ARCHITECTURE.md`、`docs/conventions/directory.md`、新增 `docs/guides/book-lineage.md`。

## 实施顺序

### Task 0：冻结实际生产写入口和基线

**Files:** 新增 `docs/superpowers/audits/2026-09-04-book-lineage-writer-inventory.md`、`scripts/kc_lineage_inventory.py`；只读检查上述脚本和入口。

- [ ] 记录 `git status --short`、HEAD、测试基线；不处理既有脏文件。
- [ ] 对 `batch_build.py`、`batch_commit.py`、`aggregate_synthesis.py` 逐个记录调用链、实际写入函数、输出目录和是否被 HTTP/CLI 调用。
- [ ] 同样核实 `phase4_batch.py`、`batch_generate.py`、`accept_batch.py`、`ingest_novel_wiki_manual.py`。
- [ ] 盘点 raw、Wiki、KC、Book 现有资产，输出 source/path/hash/映射/`legacy_unverified`。
- [ ] 只有完整扫描成功才允许形成 deletion candidate；权限或解析失败记录 `scan_incomplete`。
- [ ] 验收：三类脚本的生产/兼容/测试分类无未解释项；无代码修改。

### Task 1：建立 lineage SQLite 状态库

**Files:** 新增 `src/lineage/{__init__,types,api,sqlite_store,reconcile}.py`；新增 `tests/test_lineage/test_store.py`、`test_transitions.py`。

- [ ] 先写失败测试：schema、唯一 source_id、外键、合法/非法状态转换、tombstone、build run、`PRAGMA integrity_check`。
- [ ] 实现最小 schema：`sources`、`artifacts`、`artifact_sources`、`build_runs`、`build_members`、`write_intents`、`outbox`、schema version。
- [ ] `source_id` 首次持久化；路径变更必须走显式 rename API，hash 只能辅助匹配。
- [ ] Wiki/source 关系使用多对多；不得用单一 source_id 覆盖 synthesis 页面。
- [ ] 所有写入使用事务、foreign keys、busy timeout；每个项目 build/writer 使用单写 lease。
- [ ] 增加 DB 备份、迁移版本和损坏时 fail-closed 行为。
- [ ] 验收：状态非法回退失败；数据库损坏/锁定时不触碰内容文件。

### Task 2：接入 raw 生命周期

**Files:** 仅修改 inventory 确认的 raw 入口；新增 `tests/test_lineage/test_raw_lifecycle.py`。

- [ ] 先写 new/unchanged/changed/deleted/unreadable/unsupported/no-content/provider-error/partial-scan 测试。
- [ ] raw 入队前登记 source_id、canonical path、raw hash 和 operation_id。
- [ ] raw 变更使旧 KC/Wiki/Book 关系 stale，并产生下一次编译的 pending 事件。
- [ ] 只有完整扫描确认缺失且显式确认时生成 tombstone；部分扫描不得误删。
- [ ] 不合格 raw 必须带 reason code，并在 build plan 中显示为 excluded 或 blocking；默认不得静默排除。
- [ ] 验收：每种异常都可在 lineage show 和 Book plan 中看到，旧 Book 不被覆盖。

### Task 3：接入 Wiki/KC 所有真实写入点

**Files:** 只修改 Task 0 列为 production/compatibility 的 writer；新增 `test_artifact_transitions.py`、相关回归测试。

- [ ] 先写原子写失败测试：文件写失败、DB 提交失败、进程中断均不能错误标记 committed。
- [ ] 每个 writer 执行 `pending intent -> 原子文件写 -> committed transition + outbox`；写入使用 operation_id 和 expected hash 对账。
- [ ] `page_writer.py` 记录完整 wiki_page_id、内容 hash、所有 source_ids；synthesis 保留多源边。
- [ ] KC publisher 记录 bundle/object/evidence/publication version；不凭 EventBus 推断成功。
- [ ] 让 `batch_build.py`、`batch_commit.py` 和 `aggregate_synthesis.py` 复用同一 API；旁路写入直接成为 health blocker。
- [ ] legacy batch state 继续双写；比较不一致时 strict Book 直接失败。
- [ ] 验收：HTTP、batch、synthesis、manual（若仍为生产入口）写入能收敛到同一 lineage 状态。

### Task 4：Book 页面级闭包与不可变发布

**Files:** 修改 `src/kc/views/book/{materialize,rebuild,contract}.py`、`src/cli_ext/book_cmd.py`、必要时 `src/cli.py`；新增 Book manifest 测试。

- [ ] 先写缺 raw/KC/Wiki/evidence、重复 source、未知状态、stale hash、缺页面和多页面映射测试。
- [ ] materialize 冻结 source_ids、wiki_page_ids、excluded/blocking entries、输入快照和 policy version。
- [ ] rebuild 只写 `book/.releases/<run_id>/` staging，逐章记录 source_ids 与 wiki_page_ids。
- [ ] 发布前同时检查 source 闭包和 Wiki artifact 闭包，且 blockers 为空。
- [ ] 通过后仅原子替换 `book/manifest.json` active pointer；reader 只按 manifest 读取，不再 glob 半成品文件。
- [ ] 默认 dry-run；`--strict` 显式开启失败即不发布；保留旧 release 供恢复。
- [ ] 验收：任一章节写入中断时旧 Book 仍可读；页面级集合不相等时编译在发布前失败。

### Task 5：增量更新、outbox 恢复和删除

**Files:** 修改 `src/cli_ext/book_cmd.py`、`src/cli.py`、`src/lineage/api.py`、`sqlite_store.py`；新增 `test_incremental_book.py`、`test_outbox_recovery.py`。

- [ ] 新增 `book plan`，从 raw hash 和 active manifest 计算新增、变更、删除、阻塞和可复用章节。
- [ ] 新 raw 只有在 KC/Wiki committed 后进入 Book-pending；当前 build 快照之后到达的 raw 留给下一次。
- [ ] 删除必须由显式 tombstone 驱动；失败时保留最后 active manifest。
- [ ] outbox 使用唯一 event key；重放不重复转换、不重复 chapter。
- [ ] 加入 stale snapshot 拒绝和 build lease，防止全量/增量并发乱序发布。
- [ ] 验收：中断后 replay 可收敛；重复 build 结果一致；删除不会暴露部分 Book。

### Task 6：健康检查、迁移和运维放行

**Files:** 新增 `scripts/kc_lineage_migrate.py`；修改 CLI、文档；新增 `test_health.py`。

- [ ] 提供 `lineage health --project <id> --json` 和 `lineage show --project <id> --json`。
- [ ] health 检查 DB integrity、孤儿关系、hash 不一致、非法状态、pending outbox、stale active Book、legacy projection divergence。
- [ ] migration 默认 dry-run；只自动确认确定性映射，歧义标 `legacy_unverified`；apply 前生成备份。
- [ ] 明确 unresolved、excluded、blocked 的阈值和上线策略；任何未知状态阻塞 strict build。
- [ ] 在临时项目完成全链路 smoke：raw add/change/delete/unsupported、HTTP/batch/synthesis、Book crash boundary、恢复和健康检查。
- [ ] 验收：migration 无未解释 mismatch；健康异常有非零退出码；受保护 `knowledge/novel-wiki` 未被测试写入。

## 两轮 plan audit

### Round 1：全面漏洞审计

| 等级 | 漏洞位置 | 风险后果 | 定点整改要求 |
|---|---|---|---|
| P0 | Task 4 仅 source 闭包 | 一个 source 生成多个 Wiki 页面时可漏页仍成功 | 增加 `expected_wiki_page_ids == compiled_wiki_page_ids` |
| P0 | Book 发布描述 | 逐文件替换会暴露半套 Book | immutable release + atomic active manifest |
| P0 | Task 0 writer inventory | 漏掉脚本会形成旁路写入，DB 永远假健康 | 先核实三入口及所有脚本，未分类不得编码 |
| P1 | raw 扫描/删除 | 权限失败被误判删除，Book 丢章 | complete scan marker + explicit tombstone |
| P1 | source identity | rename 形成重复 source 或断链 | persisted ID + explicit rename API |
| P1 | synthesis mapping | 单源关系丢失多源引用 | artifact_sources 多对多 |
| P1 | SQLite/file 边界 | 崩溃导致 committed 假状态或遗漏 | write intent、operation_id、reconcile、outbox |
| P1 | legacy batch state | 双状态不一致导致计划不完整 | dual-write + divergence blocker + cutover gate |
| P1 | provider/no-content | 不合格 raw 静默不进 Book，无法审计 | explicit reason + excluded/blocking policy |
| P1 | 并发 build | 旧快照覆盖新 Book | lease + frozen snapshot + stale rejection |
| P2 | 历史迁移 | 猜错映射造成虚假完整性 | dry-run、backup、legacy_unverified |
| P2 | DB 锁/损坏 | 恢复过程继续改文件扩大损失 | health first、fail-closed |

**Round 1 结论：** 原方案存在 3 个 P0；已在本实施计划中转为强制任务和放行门。未发现需要扩大范围的缺陷。

### Round 2：压力测试推演

| 场景 | 预期结果 | 计划中的保护 |
|---|---|---|
| discovery 后 raw 消失 | 本次 build blocked/failed，不发布 | operation hash + strict closure |
| raw 目录权限中断 | 不产生删除 | complete scan marker |
| raw rename | 不产生重复 source | explicit rename |
| Wiki 写完 DB 未提交 | 下次对账，不假定成功 | intent + reconcile |
| Book 写到第 N 章崩溃 | active Book 仍为上一 release | staging release + atomic pointer |
| 新 raw 在 build 中到达 | 下一次 build 处理 | frozen snapshot |
| HTTP 与 batch 并发 | 单写串行、无 lost update | SQLite transaction + lease |
| synthesis 多源 | 所有 source edges 保留 | many-to-many |
| provider 截断/无 evidence | blocker，旧 Book 保留 | reason codes + fail-closed |
| outbox 重放两次 | 状态和文件不重复 | unique event key + idempotent upsert |
| DB 损坏/锁定 | 停止写内容并报警 | integrity check + backup |

**Round 2 结论：** 以上失效路径均有明确结果和测试位置；若任一保护未实现，状态为 blocked，不得宣称整改完成。

## 最终放行门

1. Task 0 证明 `batch_build.py`、`batch_commit.py`、`aggregate_synthesis.py` 及其他实际 writer 均已分类并接入或明确非生产。
2. 严格 Book plan 同时满足 source 与 Wiki page 双重集合闭包。
3. Book active pointer 指向单一不可变 release；发布中断不可见半成品。
4. raw 删除、rename、unsupported、no-content、provider-error、partial scan 均有可查询状态。
5. legacy state 与 lineage 完成一次 staging 全量双写比对并一致。
6. crash/replay、并发、DB 损坏/锁定、迁移 dry-run 和临时项目 E2E 全部通过。
7. 未修改受保护项目数据，未处理范围外问题。

任一条件不满足：标记 `blocked`，只修复对应缺口；不得自动转入范围外优化。

## 回滚

- 通过项目级 feature flag 停止 lineage 写入，保留旧 artifact writer。
- 独立关闭 strict Book manifest，恢复旧 dry-run/build 入口；不删除旧 Book。
- 失败 release 只留在 `.index/lineage/runs/` 或 `book/.releases/`，由 retention 流程另行处理。
- 不删除 `state.db`、active `book/manifest.json` 或旧 release；恢复前先备份。

## 交付记录要求

- 每个 Task 一个逻辑 commit；只 `git add` 本任务明确文件。
- 每个任务记录 RED/GREEN、回归命令、变更文件和未处理风险。
- 完成后更新 `.superpowers/sdd/progress.md`；不自动 push。

## 回归核验记录（2026-09-04）

- 核验范围严格限定为既有审计项：3 个 P0、已列 P1/P2、最终放行门、回滚条款及计划引用关系。
- 核验结果：12/12 固定检查通过。
- 已确认：Wiki 页面级闭包、不可变 release、三项生产写入口盘点、raw 部分扫描保护、rename、synthesis 多对多、write intent/reconcile、legacy divergence gate、不合格 raw 显式状态、回滚保护及审计文件引用均已在方案中明确。
- 本轮未主动挖掘或登记新风险，未新增整改任务，未修改生产代码。
- 结论：方案回归核验通过，终止方案审计迭代；后续仅在用户明确授权后进入 Task 0 执行。
