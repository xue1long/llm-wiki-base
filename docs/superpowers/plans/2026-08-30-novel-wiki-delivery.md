# novel-wiki 最新流水线交付实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `knowledge/novel-wiki` 从历史 Wiki 产物重建为可审计、可恢复、可检索的最新流水线交付实例。

**Architecture:** 保留原实例为只读基线，在独立 staging 项目中执行 Raw → Candidate → Reviewer → Promoter → KnowledgeObject → Wiki/Core/index/vector → PublicationBatch。所有页面、对象、证据、发布批次和向量状态以同一 bundle manifest 关联；只有完整批次才推进 publication waterline。

**Tech Stack:** Python 3.11+, `src.pipeline`, `src.kc`, Wiki storage, PublicationGate, LanceDB, pytest。

**Spec:** `docs/superpowers/plans/2026-08-28-kc-mainline-audited.md`、`docs/ARCHITECTURE.md`、A8 Book contract。

## Global Constraints

- 不修改或删除原始 `knowledge/novel-wiki`；先生成快照和独立 staging 根目录。
- 所有摄取必须走默认 candidate 链；legacy/unified 只用于对照，不得混入发布结果。
- `NEEDS_HUMAN_REVIEW`、REJECTED、向量失败均不得推进发布水位。
- 每个发布页面必须能回溯到 KnowledgeObject、evidence、raw source 和 bundle manifest。
- 中断可恢复、重复执行幂等；失败批次保留 staged/quarantine 状态。
- 交付报告必须记录完整测试、计数、失败项、回滚步骤和已知限制。

---

### Task 1: 建立实例冻结基线

**Files:**
- Create: `knowledge/novel-wiki/.index/delivery/baseline.json`（仅在副本中）
- Test: `tests/test_kc/test_novel_wiki_delivery.py`

**Steps:**

- [ ] 复制实例到带时间戳的 staging 根目录；记录 Git 状态、文件清单、SHA-256、Wiki 类型计数、raw 数量、LanceDB 表/行数。
- [ ] 测试冻结快照能重复计算相同 manifest，且源目录文件变化会被检测。
- [ ] 将原实例设置为只读输入；后续任何写入只允许进入 staging。

### Task 2: 规范化输入与迁移前门禁

**Files:**
- Modify: `src/pipeline/ingest.py`（仅补充实例迁移需要的显式输入/状态记录）
- Create: `scripts/kc_novel_wiki_preflight.py`
- Test: `tests/test_kc/test_novel_wiki_preflight.py`

**Steps:**

- [ ] 扫描 raw/source，建立 `source_id → path → hash → format` 清单；重复源只保留一个 canonical source。
- [ ] 将历史 `entitie` 等非规范类型标记为待重编译输入，不直接修改旧页面。
- [ ] 检查 provider、schema、purpose、vector store、磁盘空间和 API 配额；任一硬条件失败时退出且不写 Wiki。
- [ ] 将 preflight 输出写入 staging delivery 目录，作为后续批次输入锁定文件。

### Task 3: 小批量端到端试运行

**Files:**
- Create: `scripts/kc_novel_wiki_pilot.py`
- Test: `tests/test_kc/test_novel_wiki_pilot.py`

**Steps:**

- [ ] 从不同格式、不同历史类型和含重复/缺证据样本中抽取固定 pilot 集。
- [ ] 运行默认 candidate 链，验证 Reviewer、Promoter、KnowledgeObject 持久化和 evidence refs。
- [ ] 验证 rejected/review-required 样本进入 quarantine/review，不出现在 PublicationBatch。
- [ ] 验证成功样本的 Wiki、Core/index 和 vector 状态均挂在同一 bundle manifest。
- [ ] 记录 pilot 的通过率、人工审核量、token/耗时和预计全量成本；未达到门槛则停止全量。

### Task 4: 全量可恢复重编译

**Files:**
- Modify: `scripts/kc_recover_publications.py`
- Create: `scripts/kc_novel_wiki_rebuild.py`
- Test: `tests/test_kc/test_novel_wiki_rebuild.py`

**Steps:**

- [ ] 按 source manifest 分批执行默认摄取；每批先写 KO/evidence bundle，再生成 Wiki projection。
- [ ] 使用稳定 source hash/idempotency key；重复运行只复用已有成功 bundle，不重复调用 LLM。
- [ ] 每批保留 `candidate.json`、对象文件、evidence、manifest、review/quarantine 结果和错误日志。
- [ ] 进程中断后从最后一个 staged batch 恢复；不得把部分批次标记 published。
- [ ] 全量完成后输出 source、candidate、validated、promoted、published、quarantined、failed 的精确计数。

### Task 5: 发布与 Core/Wiki/vector 一致性验收

**Files:**
- Create: `scripts/kc_novel_wiki_consistency.py`
- Test: `tests/test_kc/test_novel_wiki_consistency.py`

**Steps:**

- [ ] 对每个 published bundle 校验 manifest、Wiki page hash、Core/KO ids、evidence refs、index entries 和 vector ids。
- [ ] 校验 vector 数量、维度、source/page/chunk metadata 与 Wiki 页面一一对应；缺 vector 的批次保持 staged。
- [ ] 重复 publish 必须不产生重复页面、重复 index 行或重复 vector。
- [ ] 人为中断 Wiki 写入、vector upsert 和发布状态写入，验证恢复后最终状态只会是完整 published 或可重试 staged。
- [ ] publication waterline 只允许单调递增，并与最后一个完整 PublicationBatch 相符。

### Task 6: A8 Book 视图重建

**Files:**
- Create: `scripts/kc_novel_wiki_book_delivery.py`
- Test: `tests/test_kc/test_novel_wiki_book_delivery.py`

**Steps:**

- [ ] 从已发布 Core/KO 集合生成 Book outline/chapter 输入；没有稳定 Book 结构的内容保持“非 Book 交付”，不伪造章节。
- [ ] 执行 A8 Book rebuild dry-run，确认 mapper、compile、evidence binding、incremental hash 和 publication version。
- [ ] 只有 IntegrityGate 通过且章节 evidence 完整时写入 Book 交付目录。
- [ ] 验证删除后重建、相同输入 hash 稳定、单 KU 变更只影响受影响章节。

### Task 7: 交付门禁与报告

**Files:**
- Create: `knowledge/novel-wiki-delivery-report.yaml`（在 staging/交付包中）
- Modify: `docs/ARCHITECTURE.md`（如实例运行方式有新增说明）
- Test: `tests/test_kc/test_novel_wiki_delivery_report.py`

**Steps:**

- [ ] 运行主线专项测试、A8 测试、实例一致性检查、恢复演练和检索 smoke test。
- [ ] 使用 `scripts/kc_check_delivery_report.py --strict` 校验报告字段；存在 hard gate failure 时 `next_phase_ready` 必须为 false。
- [ ] 交付报告记录 staging 路径、输入 manifest、批次计数、质量指标、测试命令、失败/隔离项、成本、回滚步骤和已知限制。
- [ ] 生成交付包校验和；人工复核报告后才允许将 staging 切换为实例发布目录。

## 量化交付标准

1. 原始 source manifest 完整，所有输入都有 hash、状态和处理结果。
2. `published` 的每个对象均有 KO、evidence、Wiki page、index/vector 映射；映射缺失数为 0。
3. `REJECTED`、`NEEDS_HUMAN_REVIEW`、vector pending、失败批次均不在 published 集合。
4. 重跑不增加重复对象、页面、索引行或向量；中断恢复后状态可证明。
5. IntegrityGate、A8 Book 验收、检索 smoke test 和 delivery report validator 全部通过。
6. 质量不足或人工审核未完成的内容必须明确隔离；不得用“全量扫描成功”替代“全量可发布”。

## 方案自审：第一轮漏洞审计

- **致命缺陷：** 若直接在原目录重建，失败恢复无法区分旧页面和新页面。整改：独立 staging + manifest 切换。
- **致命缺陷：** 若把 Wiki 写成功当作发布成功，vector 失败会造成三层不一致。整改：PublicationBatch 水位只由 vector-ready 批次推进。
- **重大隐患：** 历史 `entitie` 类型可能被错误当成规范 entity。整改：先标记、重编译、按 schema 重新归类。
- **重大隐患：** `NEEDS_HUMAN_REVIEW` 若默认放行会破坏证据链。整改：隔离并单独统计，人工批准后才可重试发布。
- **重大隐患：** 全量 LLM 调用可能超预算或限流。整改：pilot 先测成本，按批次限速、断点续跑、缓存成功 bundle。
- **重大隐患：** 重跑可能重复写页面/向量。整改：source hash + bundle key + publish 幂等校验。
- **优化疏漏：** 仅测单元测试无法证明实例可检索。整改：加入真实 LanceDB vector/search smoke test。
- **优化疏漏：** 只有成功计数会掩盖隔离内容。整改：报告同时列出全部状态和失败原因分布。

## 方案自审：第二轮压力测试

- provider 在第 N 批超时：批次保持 staged，重启恢复，不推进水位。
- vector upsert 部分失败：保留 pending ledger，禁止 published，重试必须幂等。
- 进程在 Wiki 写入后崩溃：启动扫描 bundle，补齐 index/vector 或回滚 staging 批次，不删除 raw。
- schema 在全量中途变化：输入 manifest 与 schema hash 不一致，停止新批次，旧批次保持可审计。
- 人工审核积压：交付报告将未审核数列为 hard limitation，不能伪称全量交付。
- 磁盘空间不足：preflight 和每批写入前检查空间；失败只停止当前 staging，不碰基线。
- 单个坏源或解析器崩溃：隔离该 source，其他批次继续；最终报告必须包含 source-level failure。
- 旧 vector 库与新页面混用：交付切换前校验 vector namespace/manifest，失败则保持旧实例可用，不做半切换。

## 交付判定

在上述 6 项量化标准全部满足、两轮风险项均有对应控制、人工复核交付报告后，`novel-wiki` 才可标记为“按最新流水线交付”。在此之前只能交付代码和 staging 报告，不能宣称实例完成迁移。
