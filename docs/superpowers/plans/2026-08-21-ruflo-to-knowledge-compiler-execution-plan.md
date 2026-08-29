# Plan: ruflo-kb 升级为 Knowledge Compiler

status: planned
branch: codex/2026-08-21-knowledge-compiler-upgrade

## Goal

在保留现有数据、测试和运行入口的前提下，先跑通一条可验证的知识编译闭环，再逐步归一架构：

```text
RawSource → CanonicalDocument → Claim + Evidence → Verification
          → KnowledgeObject → WikiProjection
```

阶段顺序：`A 纪律优先 → C 最小闭环 → B 后续归一`

### Non-goals for A/C

- 不新建第二个项目。
- 不一次性重命名或搬迁全部旧代码。
- 不在 C 阶段建设插件市场、复杂 Runtime、Graph DB、多租户或完整生产平台。
- 不在 C 阶段迁移全部历史数据或支持全部输入格式。

## Current baseline

现有项目已有可复用能力：

- `src/knowledge/`：KnowledgeCandidate、KnowledgeObject、生命周期、版本和冲突检测。
- `src/pipeline/`：Collector → Analyzer → Generator → Writer。
- `src/wiki/`：WikiPage、模板、关系、Schema、Lint、质量门禁、原子写入。
- Queue、EventBus、LLM Provider Registry、Vector Search、MCP 和批量处理能力。

迁移期间新增 `src/kc/`，旧 `src/` 保持可运行。目标不是立刻替换旧实现，而是先用 Adapter 形成新闭环。

## Target seam

```text
src/kc/
├── contracts/       # 公开契约和状态
├── domain/          # CanonicalDocument / Claim / Evidence / KnowledgeObject
├── compiler/        # normalize / extract / verify / compile
├── adapters/        # 旧模块接入
└── api.py           # 最小对外入口
```

规则：

1. 新模块只通过 `api.py` 和 `types.py` 暴露接口。
2. Domain 不依赖 FastAPI、LLM SDK、LanceDB、解析器或具体存储。
3. 新数据的事实权威是 `KnowledgeObject + Evidence`。
4. Wiki 只能由 `WikiProjection` 写入，不作为新事实源。
5. 复杂 Runtime、Registry、Storage 分层先不实现，只在真正需要时增加 Adapter。

## A phase: discipline

### A-01: 冻结基线

- Files: `docs/migration/baseline.json`, `scripts/kc_baseline.py`, `.superpowers/sdd/progress.md`
- Test: 记录全量测试、CLI、HTTP `/health`、单文件 ingest、search、MCP 和 batch 冒烟。
- Acceptance: 有可重复执行的基线脚本、失败清单、数据快照位置和回滚入口；不改业务行为。
- Status: completed

### A-02: 统一最小领域词汇

- Files: `CONTEXT.md`, `docs/architecture/naming.md`, `docs/adr/ADR-001-knowledge-compiler-migration.md`
- Test: 新增代码检查 canonical name；旧名称只允许出现在兼容映射中。
- Acceptance: 明确 `RawSource`、`CanonicalDocument`、`DocumentBlock`、`Claim`、`Evidence`、`KnowledgeObject`、`WikiProjection` 的唯一含义。
- Status: completed

### A-03: 定义最小 Contract 和确定性规则

- Files: `src/kc/contracts/`, `src/kc/domain/ids.py`, `src/kc/domain/evidence.py`, `tests/test_kc/test_contracts.py`, `tests/test_kc/test_deterministic_ids.py`
- Test: 覆盖序列化、非法输入、重复任务、raw hash、block hash、Evidence 引用和状态转换。
- Acceptance:
  - `document_id` 由 raw 内容、规范化版本和 parser 版本确定。
  - `block_id` 由 document、规范化序号和 block 内容确定。
  - Evidence 至少包含 `document_id`、`block_id`、`quote_hash`、`supports`、`confidence`。
  - 所有状态转换通过一个公共映射，不允许调用方自行解释状态。
- Status: completed

### A-04: 建立最小边界门禁和写入权威

- Files: `src/kc/adapters/legacy_write_guard.py`, `scripts/check_kc_boundaries.py`, `tests/test_kc/test_boundaries.py`, `tests/test_kc/test_write_authority.py`
- Test: Domain 导入第三方库、绕过公开接口、旧 Writer 直接写新事实时门禁失败。
- Acceptance:
  - 新链路只写 `KnowledgeObject + Evidence`。
  - Wiki 只能由 Projection 写入。
  - 旧 Pipeline 要么经 `LegacyWriteAdapter`，要么在迁移窗口切只读。
  - 权限不足、版本冲突和来源缺失均 fail-closed。
- Status: completed

## C phase: minimum viable compiler

### C-01: 适配 Collector 和 CanonicalDocument

- Files: `src/kc/adapters/legacy_collector.py`, `src/kc/compiler/normalize.py`, `tests/test_kc/test_normalize.py`
- Test: Markdown/TXT/URL 文本生成稳定的 CanonicalDocument 和有序 DocumentBlock；同一输入重复处理得到相同 ID。
- Acceptance: Raw 保持只读；解析失败不发布；Parser/Normalizer 版本写入 Document 元数据。
- Status: completed

### C-02: 适配 Analyzer 和 Evidence 校验

- Files: `src/kc/adapters/legacy_analyzer.py`, `src/kc/compiler/extract.py`, `src/kc/compiler/evidence.py`, `tests/test_kc/test_extract.py`, `tests/test_kc/test_evidence.py`
- Test: 非法 JSON、截断输出、越界 block、quote 不匹配和 hash 错误全部失败或隔离。
- Acceptance: LLM 提供的 Evidence 只能作为候选；最终 Evidence 必须由本地 CanonicalDocument 校验。旧文件/页级 Provenance 标记为 `legacy`，不得伪装成 block 级证据。
- Status: completed

### C-03: 建立 Verification 和 KnowledgeObject 投影

- Files: `src/kc/compiler/verify.py`, `src/kc/compiler/compile.py`, `src/kc/adapters/wiki_projection.py`, `tests/test_kc/test_verify.py`, `tests/test_kc/test_projection.py`
- Test: 无 Evidence、无来源、冲突或校验失败的 Claim 不能发布；投影失败不改变 KnowledgeObject 状态。
- Acceptance: 新 Claim 的 block 级 Evidence 覆盖率 100%；无 Evidence 发布数为 0；每个 Wiki 写入都能反查 KnowledgeObject、Evidence 和 projection version。
- Status: completed

### C-04: 跑通真实入口 E2E

- Files: `src/kc/api.py`, `tests/test_kc/test_e2e.py`, `docs/architecture/e2e.md`
- Test: 至少通过一个 CLI 入口和一个 HTTP 入口执行完整链路：Markdown → CanonicalDocument → Claim + Evidence → Verification → KnowledgeObject → WikiProjection。
- Acceptance: 重复 ingest 不产生重复 document/object；失败任务不产生半发布结果；现有旧链路回归集 100% 通过。
- Status: completed

### C-05: 小批量运行验收

- Files: `scripts/kc_accept_c.py`, `docs/migration/adapter-ledger.md`, `.superpowers/sdd/progress.md`
- Test: 在真实项目数据上执行小批量 ingest、失败重试、恢复和 search 冒烟。
- Acceptance:
  - 连续两次小批量运行通过。
  - 新 Claim Evidence 覆盖率 100%，无证据发布为 0。
  - 重复对象数为 0。
  - p95 耗时和 LLM 成本不超过 A 基线 2 倍；超过则暂停扩量。
  - 每个 Adapter 有调用方、替代目标和退出条件。
- Status: completed

## B backlog: after C is proven

以下任务保留，但不阻塞 A/C 闭环：

### B-01: Agent Retrieval Contract

统一 `search`、`lookup`、`get_evidence`、`get_relations`，建立带标注 Evidence 的小型评测集；目标是期望 Evidence 命中率 ≥90%。

### B-02: 全格式 Canonical Adapter

扩展 PDF、DOCX、XLSX、HTML、转录文本；每种格式独立提供样例、失败样例和 Evidence 定位规则。

### B-03: 历史数据迁移

提供 dry-run、分批、断点续跑和失败清单。迁移报告至少包含总量、成功量、失败量、legacy Evidence 量和未迁移量。

### B-04: Runtime / Workflow / Registry 归一

仅在现有 Adapter 数量和 Workflow 复杂度证明需要时实施；不提前建设插件市场或分布式平台。

### B-05: 生产安全与恢复

补充 Artifact 生命周期、敏感信息脱敏、Provider 凭据隔离、监控告警、Vector/Queue 恢复演练和完整迁移回滚。

## Phase gates

### A gate

- A-01～A-04 完成。
- 新模块有公开 Contract。
- Domain 无第三方依赖。
- 写入权威、Evidence 最小字段和确定性 ID 已有测试。
- 现有功能行为无改变。

### C gate

- C-01～C-05 完成。
- Markdown/TXT/URL 文本真实入口 E2E 通过。
- 新 Claim Evidence 覆盖率 100%，无证据发布为 0。
- 重复对象数为 0，旧回归集 100% 通过。
- 失败、重试和版本冲突不会产生半发布事实。
- 不满足门槛时停止扩量，不进入 B 阶段。

### B gate

- KnowledgeObject + Evidence 成为唯一事实权威。
- Wiki 只作为 Projection。
- 历史数据、全格式、检索、生产安全和恢复能力分别有独立验收报告。
- 旧兼容层只有在零调用方、迁移报告完整和回滚演练通过后才删除。

## Execution loop

每个 A/C 任务严格执行：

```text
失败测试 → 最小实现 → 定向测试 → 相关回归 → 边界门禁 → 文档/进度 → 一个逻辑提交
```

任务必须记录：owner、前置任务、交付文件、测试命令、停止条件和回滚入口。

## Failure policy

- 无来源、Evidence 校验失败、权限不足、版本冲突：fail-closed，进入失败或隔离状态。
- LLM 截断或非法输出：保留原始结果，允许有限重试；不得直接发布。
- 旧 Evidence 无法定位 block：保留为 legacy，不进入默认 verified 检索。
- C 阶段不承诺外部 LLM 调用可回滚；只记录调用和成本。
- C 阶段只保证单对象原子性；跨 Queue、Vector、Artifact 的完整灾难恢复属于 B-05。
- 全量迁移前必须有数据快照；不在脏工作区执行覆盖式迁移。

## Rollback

1. A 阶段回退对应代码和文档提交即可。
2. C 阶段保留旧入口；新链路失败时切回旧 Pipeline，不删除旧产物。
3. C 阶段只要求单对象恢复：未完成对象可重试或隔离，不能半发布。
4. B 阶段才执行 Raw/Canonical/Knowledge/Evidence/Artifact/Wiki、Vector、Queue 的全量快照和恢复演练。

## Audit

### Round 1: completed

已将上一轮发现的必修问题落实为 A/C 门禁：唯一写入权威、确定性 Evidence、真实入口、量化验收、版本冲突停止和基础回滚。

### Round 2: completed

极限故障推演后的生产级事项已从 A/C 主路径移入 B backlog；C 阶段只保留 fail-closed、单对象原子性和可重试，不承诺完整平台级灾备。

### Human review

- Status: pending
- Review requirement: 确认 A/C 最小范围、Evidence 100% 新数据门槛、C 阶段不覆盖全格式和跨系统灾备。

## Completion evidence

- Final commit: pending
- Tests: A/C 定向测试、CLI/HTTP E2E、旧回归集、小批量运行验收
- Static checks: `scripts/check_kc_boundaries.py`
- Documentation updated: `CONTEXT.md`、`docs/adr/`、`docs/architecture/`、迁移台账
- Progress ledger updated: yes
