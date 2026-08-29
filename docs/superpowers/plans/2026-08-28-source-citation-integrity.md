# Knowledge Core 主路径与证据生命周期实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 HTTP ingest 的正式知识生产路径统一到 Knowledge Core，使 claim 在生成 Wiki 前经历来源绑定、结构校验和语义支持判断。

**Architecture:** Collector 生成 `CanonicalDocument`，Analyzer 生成 `KnowledgeCandidate`，随后由现有 `src/kc/integrity/` 和 `src/kc/semantic_support/` 完成 claim-level review。只有通过发布闭包的对象才能进入 Wiki 投影、索引和向量检索；legacy/unified 仅保留为 shadow 或迁移兼容路径。

**Tech Stack:** Python 3.11+, existing KC contracts/compiler/integrity modules, `SemanticSupportChecker`, `EvidenceStorage`, `WikiProjection`, `IntegrityGate`, pytest。

**Spec:** 本文档的“终局架构”和“实施任务”部分。

## Global Constraints

- Knowledge Core 是 claim、evidence、publication state 的唯一真相源。
- 不新增第二套 `evidence_gate.py`、第二套 evidence 状态或 parallel truth model。
- 状态必须区分 `anchored`、`structurally_verified`、`entailed`、`unsupported`、`needs_human_review`。
- `anchored` 只表示 quote 可回到指定 source 的单一 block。
- `structurally_verified` 表示来源、block、hash、schema 和结构规则通过。
- `entailed` 表示语义支持检查通过；仅 quote 存在不能产生此状态。
- legacy/unified 在迁移期不得绕过发布闭包写入正式 Wiki。
- strict 失败不得调用 `commit_ingest()` 或 Wiki projection writer。
- 所有写入通过现有 atomic/write-authority 机制完成。

---

## 终局架构

```text
HTTP ingest
  → Collector / CanonicalDocument
  → Analyzer / KnowledgeCandidate
  → Candidate adapter
  → Evidence binding
  → IntegrityGate (Schema / Provenance / Evidence / ...)
  → SemanticSupportChecker
  → CandidatePromoter / KnowledgeObject
  → Wiki projection + atomic writer
  → search / chat / MCP retrieval filters
```

当前仓库已具备但尚未形成统一主路径的组件：

- `src/kc/compiler/normalize.py`：CanonicalDocument 与 block；
- `src/kc/compiler/evidence.py`：quote、block、hash 的结构校验；
- `src/kc/integrity/gates.py`：ProvenanceGate、EvidenceGate 等质量门；
- `src/kc/integrity/orchestrator.py`：IntegrityGate 编排与闭包报告；
- `src/kc/semantic_support/checker.py`：scope、temporal、contradiction、支持关系判断；
- `src/kc/evidence/storage.py`：Evidence 持久化；
- `src/kc/adapters/wiki_projection.py` / `wiki_writer.py`：Wiki 投影与写入；
- `src/kc/retrieval/filter.py`：默认检索状态过滤。

因此本方案优先做“接通、统一、补齐”，不再新建与这些模块平行的实现。

## 状态与发布规则

```text
quote 命中 source block
  → anchored
结构合同、来源、hash、Provenance/Evidence Gate 通过
  → structurally_verified
SemanticSupportChecker 判断 supports
  → entailed
SemanticSupportChecker 判断 irrelevant / contradicts / insufficient
  → unsupported 或 needs_human_review
```

`entailed` 不是 Generator 的副作用，而是 Reviewer 的明确产物。`unsupported` 和
`needs_human_review` 必须能进入 quarantine/review 流程，不能降级成普通 draft 后继续
进入默认检索。

---

## 与原方案的对比

| 主题 | 原方案 | 本方案 | 原因 |
|---|---|---|---|
| 主路径 | 给旧 generate 加证据闸 | 先接通 Knowledge Core candidate 主路径 | 避免 legacy/candidate 双标准并存 |
| 新模块 | 新建 `src/pipeline/evidence_gate.py` | 复用并完善 `src/kc/integrity/` | 仓库已有 EvidenceGate/IntegrityGate |
| 证据状态 | page-level `verified/partial` | claim-level 五类状态 | 状态必须驱动发布和检索决策 |
| 语义判断 | 不做 entailment | 由 SemanticSupportChecker 产生 `entailed` 或失败状态 | “quote 存在”不等于“支持 claim” |
| claim 合同 | 临时 `statement`→`id/text` adapter | Candidate → KC Claim/KnowledgeObject 的正式 adapter | 让 KC 成为唯一领域模型 |
| 持久化 | 新增 WikiPage 计数字段为主 | EvidenceStorage + claim/evidence refs；Wiki 只做投影 | 避免 Wiki 成为第二真相源 |
| 页面范围 | 只标 source 页 | source 页展示引用；下游页引用 claim/evidence refs | 保持可追溯且避免错误复制 |
| strict | 仅 gate 返回后阻止 commit | Integrity/semantic/review 闭包共同决定 publish | 覆盖结构失败与语义失败 |
| 检索 | 未规定如何消费状态 | 默认过滤 unsupported/quarantined/candidate，允许显式审计查询 | 让质量状态产生真实用户价值 |
| legacy | 保持可写兼容 | 仅 shadow/迁移兼容，不绕过正式发布闭包 | 终局必须只有一套生产标准 |

### 保留内容及原因

- source identity、block 定位和 quote hash：它们是可重复的 provenance 基础。
- 短 quote 防护和跨 block 拒绝：避免伪锚点和无法稳定引用的证据。
- 默认 annotate 与 strict：分别服务可读性和可信优先场景。
- TDD、atomicity、round-trip、smoke test：仍是发布边界的必要证据。
- `anchored → structurally_verified → entailed`：保留分层，但让每一级对应真实阶段。

### 更改内容及原因

- 从 legacy 后置补丁改成 Knowledge Core 前置生命周期：保证所有正式知识经过同一闭包。
- 从 candidate 级报告改成 claim-level verdict：支持一个 candidate 多 claim、多页面和多 evidence。
- 接入已有 SemanticSupportChecker：补上原方案无法完成的语义支持判断。
- 接入已有 EvidenceStorage、IntegrityGate、WikiProjection、DefaultFilter：让状态贯穿存储、发布和检索。
- 将 candidate 路径接通作为第一任务，而不是可选的 T0 检查。

### 删除内容及原因

- 删除平行的 `src/pipeline/evidence_gate.py` 设计：已有 KC integrity 能力，重复实现会分裂规则。
- 删除仅新增 WikiPage 统计字段作为主存储：统计字段不能表达 claim→evidence 关系。
- 删除“source 页有引用即可完成证据闭环”的隐含假设：最终还需要 semantic support 和发布过滤。

---

## Implementation Tasks

### Task 1: Make Knowledge Core the formal candidate ingest path

**Files:** Modify `src/pipeline/ingest.py`, `src/pipeline/analyzer.py`, `src/kc/api.py`; tests under `tests/test_pipeline/` and `tests/test_kc/`.

- [ ] 写失败路由测试：HTTP/programmatic ingest 产生 `KnowledgeCandidate`，并在 Wiki commit 前经过 KC review seam。
- [ ] 运行：`python -m pytest tests/test_pipeline/ tests/test_kc/ -k 'candidate or ingest' -v --import-mode=importlib`；预期失败，因为当前生产代码没有 `generate_from_candidate()` caller。
- [ ] 在 `generate_ingest()` 的正式路径接入 JSON Analyzer、candidate adapter、KC review 和 candidate generator；legacy/unified 只作为显式 shadow/兼容路径。
- [ ] 复跑路由测试，证明顺序为 Analyzer → review → generator/projection → commit。
- [ ] 提交：`git add src/pipeline/ingest.py src/pipeline/analyzer.py src/kc/api.py tests/test_pipeline tests/test_kc; git commit -m "feat(pipeline): route ingest through knowledge core"`。

### Task 2: Unify candidate claims with KC claims and evidence

**Files:** Modify `src/kc/adapters/legacy_analyzer.py`, `src/kc/compiler/extract.py`, `src/kc/compiler/evidence.py`; tests under `tests/test_kc/`.

- [ ] 写失败测试：`statement` 生成稳定 claim id/text/source；evidence source identity、quote 长度、单 block、hash 均可验证。
- [ ] 运行：`python -m pytest tests/test_kc/ -k 'claim or evidence or provenance' -v --import-mode=importlib`；预期失败或暴露现有合同差异。
- [ ] 实现唯一 adapter；source identity 比较统一路径表示但不只比较文件名；短于 20 Unicode 字符记录 `short_quote`；非法 refs 记录失败而不抛 `TypeError`。
- [ ] 复跑相关测试；预期所有 claim/evidence 合同测试通过。
- [ ] 提交：`git add src/kc/adapters/legacy_analyzer.py src/kc/compiler/extract.py src/kc/compiler/evidence.py tests/test_kc; git commit -m "feat(kc): unify candidate claim evidence contracts"`。

### Task 3: Complete structural and semantic review

**Files:** Modify `src/kc/integrity/gates.py`, `src/kc/integrity/orchestrator.py`, `src/kc/semantic_support/checker.py`; tests under `tests/test_kc/`.

- [ ] 写失败测试：有效证据得到 `anchored` 与 `structurally_verified`；source mismatch、cross-block、hash 错误得到 block；semantic supports/irrelevant/contradicts/insufficient 分别得到正确 verdict。
- [ ] 运行：`python -m pytest tests/test_kc/ -k 'integrity or semantic or support' -v --import-mode=importlib`；预期失败于状态映射或 caller 集成。
- [ ] 让 IntegrityGate 输出结构报告，让 SemanticSupportChecker 输出 claim-level SupportVerdict；`supports` 才能升级到 `entailed`，其他结果进入 `unsupported` 或 `needs_human_review`。
- [ ] 复跑相关测试；预期不再把 span 定位单独当成支持。
- [ ] 提交：`git add src/kc/integrity src/kc/semantic_support tests/test_kc; git commit -m "feat(kc): enforce structural and semantic claim review"`。

### Task 4: Persist evidence and project only publishable knowledge

**Files:** Modify `src/kc/evidence/storage.py`, `src/kc/adapters/wiki_projection.py`, `src/kc/adapters/wiki_writer.py`, `src/wiki/core/types.py`; tests under `tests/test_kc/` and `tests/test_wiki/`.

- [ ] 写失败测试：Evidence round-trip、claim→evidence refs、quarantined/unsupported 不得投影，source page 可展示引用。
- [ ] 运行：`python -m pytest tests/test_kc/ tests/test_wiki/ -k 'evidence or projection or writer' -v --import-mode=importlib`；预期失败于发布状态和投影字段。
- [ ] 将 EvidenceStorage 作为 evidence 真相源；WikiPage 只保存稳定 refs/展示状态，正式写入复用 write authority 和 atomic writer。
- [ ] 复跑测试；预期旧页面仍可读取，发布对象可通过 evidence refs 回到 canonical source。
- [ ] 提交：`git add src/kc/evidence src/kc/adapters src/wiki/core/types.py tests/test_kc tests/test_wiki; git commit -m "feat(kc): project reviewed knowledge with evidence refs"`。

### Task 5: Make retrieval and review consume the lifecycle

**Files:** Modify `src/kc/retrieval/filter.py`, existing quality/review service and route files; tests under `tests/test_kc/`, `tests/test_server/`, `tests/test_pipeline/`.

- [ ] 写失败测试：默认检索排除 candidate、quarantined、unsupported；显式审计查询可查看；needs_human_review 进入 ReviewItem。
- [ ] 运行：`python -m pytest tests/test_kc/ tests/test_server/ tests/test_pipeline/ -k 'retrieval or review or evidence' -v --import-mode=importlib`；预期失败于状态未贯通。
- [ ] 让检索、Chat 和 review 使用同一 publication/evidence 状态；不要在各入口重新解释 `verified`。
- [ ] 复跑测试并执行服务 smoke test：`python -m src.cli serve --host 127.0.0.1 --port 19829`，验证 `/health` 和一次 fixture ingest。
- [ ] 提交：`git add src/kc/retrieval src/services src/server tests/test_kc tests/test_server tests/test_pipeline; git commit -m "feat(kc): enforce evidence lifecycle in retrieval"`。

---

## 完成标准

1. HTTP ingest 的正式写入路径经过 Knowledge Core candidate review；legacy/unified 不绕过发布闭包。
2. 每个 claim 都能通过 claim id 回到 Evidence，再回到 `document_id + block_id + quote`。
3. source mismatch、短 quote、跨 block、非法 refs、hash 错误和重复 evidence 均有测试。
4. `anchored`、`structurally_verified`、`entailed`、`unsupported`、`needs_human_review` 的生成条件互不混淆。
5. `entailed` 只由 SemanticSupportChecker/人工 review 产生，不由 quote 定位或 Generator 推断。
6. unsupported/quarantined/candidate 默认不进入正式检索；显式审计查询仍可查看。
7. strict 或发布闭包失败不产生 Wiki、index、vector 新写入。
8. Wiki projection、EvidenceStorage、retrieval filter 和 ReviewItem 使用同一套状态来源。
9. legacy/unified 回归通过，服务 `/health` 和 fixture ingest smoke test 通过。

## 最终边界

本方案的 source-level structural evidence 是基础层，不等于完整事实真伪。终局通过
claim-level semantic support、冲突处理、人工 review 和 retrieval filtering，才能把
“可追溯”逐步提升为“可治理的可信知识”。
