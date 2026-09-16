# ADR 0012: V7 Knowledge Reconciliation Plane — 跨源 canonical identity 与 reversible membership

- **状态**: Accepted
- **日期**: 2026-09-17
- **计划**: `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §4 Tasks 27–31
- **依赖**: ADR 0011 (V7 摄取 outcome 控制面) — 同一 codebase 演进的下一层
- **前置 ADR**: 0007 (KnowledgeCandidate ownership), 0009 (per-source template routing)

## 背景

V7 ingestion pipeline（ADR 0011）把"source → wiki page"做成了 idempotent 的、可
重跑的、可 audit 的链路。但 wiki page 仍然是 source-local identity —— 同一概念在
两篇不同 source 中产生两个独立 page（如"扩句法"在《写作技法.md》和
《新手入门.md》中各有一个 page）。这造成三个问题：

1. **知识不收敛**：cross-source 重复概念导致 wiki 出现 N 个语义相同 page，
   wiki 内 link、relation、synthesis 聚合产生 N×N 噪声
2. **merge 是破坏性的**：旧 v2 路径里人工或脚本强制合并 page，**永久破坏** source-local
   page 与其 frontmatter、relations、provenance；不可逆
3. **LLM 不能识别"这是同一概念"**：跨源检索需要某种 canonical anchor，
   但当前 `PageRelation` / wiki frontmatter relations 都是 page-to-page

第一版 v7 已在 wiki frontmatter 写 `relations: [{target: ..., type: ...}]`，
**best-effort 视图**——它是 page-to-page 的，没有跨源收敛语义。

## 决策

新增 **Knowledge Reconciliation Plane**（Plan §1.3 Layer 8 / §4 Tasks 27–31），
与 V7 ingestion 解耦，单独异步跑：

### Layer 8 设计原则

1. **`canonical_id` 与 `page_id` 完全解耦**：
   - `page_id` = wiki 文件名（slug / card_xxx），Stage 7 决定，仍 source-local
   - `canonical_id` = `c-<uuid4_hex[:16]>`，reconciliation 决定，跨源稳定
   - `canonical_id` **永不**进 wiki frontmatter；frontmatter 是 page view，不是 canonical view

2. **Identity Contract — 脚本管身份**：
   - LLM 只判 `decision ∈ {SAME, ALIAS, BROADER, NARROWER, OVERLAP, CONFLICT, DISTINCT, UNRESOLVED}`
   - LLM 永不生成 `canonical_id` / `decision_id` / `resolver_fingerprint` —— 全部由脚本 sha1 生成
   - 决策历史 append-only（`decision_log.jsonl`），永不 truncate

3. **Reversible Membership**：
   - `CanonicalRegistry.remove_membership(page_id, canonical_id)` 只删 `member_page_ids` 一项
   - canonical 实体 + aliases 不删
   - 最后一个 member 移除时 canonical 进入 `TOMBSTONED`，但**保留**（re-apply SAME 可复活）
   - page 文件本身不动 —— reversibility 是 page 维度 + canonical 维度两个独立

4. **F4 — Fingerprint Drift**：
   - 每个 canonical 存 `resolver_fingerprint`（与 pipeline_fingerprint 同形式：stage fingerprints + template hashes 的 sha1）
   - 启动时 `mark_stale_concepts(current_fingerprint)` 扫描 ACTIVE canonicals
   - fingerprint 不匹配 → 标 `STALE`，**不自动重审**（增量 re-evaluation 留第四批 Task 47）

5. **F15 — Alias 单源**：
   - `CanonicalRegistry.add_alias` 是 alias 唯一写入路径
   - 内部通过 `SlugAliasRegistryAdapter` 转发到 `.llm-wiki/slug_aliases.json`
   - 同 `(alias_text, language)` 不同 `canonical_id` → **保留第一个**（no clobber）
   - Reconciliation 任务完成后**同时**更新两个存储，避免漂移

6. **LLM 受控 ontology + bounded evidence**：
   - `identity_resolve.toml` prompt 锁死 8 决策枚举 + canonical_id 复制规则
   - Bounded Evidence Contract §3.2：`MAX_KEY_SLOT_CHARS=600`, `MAX_EVIDENCE_CHARS=1500`
   - LLM 失败 → 所有候选 `UNRESOLVED`（fail-closed, **永不抛异常**）

7. **F10 — vector_neighbor 必须第一批落地**：
   - 6 种 retrieval 策略（含 vector_neighbor）全部进 v1，**不**留第二批
   - 10k canonical retrieval < 100ms 硬指标（实测 24-26ms）
   - vector similarity 仅是"值得比较"信号，不是 merge 决策；merger 看 LLM decision

### 持久化布局

```
<project_root>/.index/reconciliation/
├── canonical_concepts.json   # dict[canonical_id -> CanonicalConcept]
├── alias_records.json        # dict[(alias_text, language) -> AliasRecord]
└── decision_log.jsonl        # append-only, 每决策一行（审计 + 重放）

<project_root>/.llm-wiki/slug_aliases.json   # F15: alias 单源同步
```

### 决策优先级（apply_decisions 排序）

```
same > alias > conflict > overlap > broader/narrower > distinct > unresolved
```

任一 page 一次 apply 只取**首个**有效决策。`UNRESOLVED` 永远不动 canonical。

### 与 wiki 层的耦合

**单向**：Reconciliation 读 wiki `revision_hash`（来自 Stage 7 frontmatter），
判断 `find_stale`（relation lifecycle），但 Reconciliation **不写** wiki 文件。
反过来，wiki 写路径 `commit_and_index` 不知道 canonical_id 存在 —— 这是 F8 决策
回退：**零 reader 改造 blast radius**。

## 后果

### 正面

1. **cross-source 概念可收敛**：N 个 source-local page → 1 个 canonical + N members
2. **reversible**：任何误合并可 `remove_membership` 撤销，不破坏 source provenance
3. **LLM 受控**：脚本管 canonical_id + decision_id，LLM 不可身份伪造
4. **crash-safe**：所有写入 tmp + rename；jsonl append-only；startup `reconcile_unfinished_commits`
   + `mark_stale_concepts` 主动恢复
5. **pipeline 升级自动 STALE**：`resolver_fingerprint` 漂移自动暴露需要重审的 canonicals，
   不静默用旧 decision

### 负面 / 已知边界

1. **Phase 1 只判 identity，不判 claim same_as**：canonical identity 与 canonical claim
   是两个独立 plane。本 ADR 不解决"两个 page 的同一句话是否算同一 claim"——这是
   第二批 Task 34 (`CanonicalClaim` + claim reconciliation) 的范畴
2. **vector_neighbor 依赖 embedding provider**：LanceDB / embedding service 不可用时，
   5 种策略降级到 5；F10 指标仍然通过（无 vector 时 5 策略更快）
3. **alias 双存储一致性靠 `add_alias` 单入口保证**：若有人绕过 registry 直接写
   `slug_aliases.json`，Reconciliation 下次启动时不会感知 —— 这是 F15 的代价
4. **STALE canonical 不自动重审**：增量 re-evaluation 留第四批 Task 47；
   本 ADR 只暴露信号，不消费信号

### 不在第一批（推迟到第二批 / 第四批）

- Claim-level reconciliation（Task 34）
- Same-as 跨文档传递闭包（Task 41-45 第三批）
- Canonical claim projection（Task 44）
- 旧 page → canonical 的 migration 工具（Task 51）
- 长期 drift 监控（Task 50）

## 实施记录

- Plan: `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §4 Tasks 27–31
- Commits: `016787b1` (27), `662cecfd` (28), `178ad4a4` (29), `495ad547` (30), `97d85ec3` (31)
- 测试基线: 23 passed / 0 failed（`tests/test_reconciliation/`）
- E2E 故障注入：commit `98f8adc0` (Task 32) 含 reconciliation attach + UNRESOLVED 路径

## 备选方案（已拒绝）

### 备选 A — 在 wiki frontmatter 直接写 canonical_id

- 优点：单一存储
- 缺点：破坏"page_id 是 page view"的边界；每次 reconciliation 触发 wiki 重写；
  wiki writer 必须知道 reconciliation 存在（reader 改造 blast radius）
- **拒绝原因**：F8 决策回退硬要求零 reader 改造

### 备选 B — 强制 single canonical per concept

- 优点：实现简单
- 缺点：不可逆；page 维度无 provenance 保留；STALE fingerprint 无信号
- **拒绝原因**：违反 reversibility 原则；违反 Identity Contract（脚本不背 LLM 决策）

### 备选 C — Reconciliation 跑在 wiki write 之前（同步）

- 优点：写入即已已 reconcil
- 缺点：把 5 秒 LLM 工作挂在主 ingest 路径；wiki write 速度从 ~25 分钟/批
  涨到 ~50 分钟；增加 ingest 失败面
- **拒绝原因**：plan §1.2 non-goal "不破坏 Stage 1–7 主链路"；Reconciliation
  应是独立 plane，不依赖 ingest completion

## 相关 ADR

- **ADR 0011**（V7 摄取 outcome 控制面）：本 ADR 是其 Layer 8 扩展
- **ADR 0007**（KnowledgeCandidate ownership）：reconcile 决策应用到的是已写盘的 page，
  KnowledgeCandidate 是 ingest 阶段的中间产物，两者生命周期不同
- **ADR 0009**（per-source template routing）：source → page 路由仍 source-local，
  reconciliation 在其上层做收敛

## 变更日志

- **2026-09-17**：初版（Accepted），基于 master plan Tasks 27–31 实施