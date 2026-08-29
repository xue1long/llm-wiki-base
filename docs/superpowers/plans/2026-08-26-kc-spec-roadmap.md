# Plan: Knowledge Compiler v2.1 路线（路线 v2.2 / 通过 plan-audit 两轮 + 9 项 Z 盲区 + 4 项重大补位）

> **状态**：路线 v2.2（在 v2.1 基础上吸收 spec 映射审计发现的 4 项重大补位 + 3 项优化）
> **路线类型**：spec-aligned，按 9 维度标尺设计（plan-audit §0）
> **覆盖目标**：从现状 15-20% → spec §14 A0-A9 Gate 全部通过 + spec §17 DoD 全部满足
> **覆盖度**：254 项 spec 具体目标中 247 项 (97.2%) 路线覆盖（v2.1 校正后）+ 4 项重大补位（v2.2 新增）+ 3 项优化合并
> **配套文档**：
> - 上一版路线（已被本版替代）：`docs/superpowers/plans/2026-08-26-knowledge-compiler-absorption.md`（v1，pending → deprecated）
> - 上一版路线 v2.1：本文档已被合并入 v2.2（差异见 §11 v2.2 增量变更）
> - 执行期 KC 迁移：`docs/superpowers/plans/2026-08-21-ruflo-to-knowledge-compiler-execution-plan.md`（A/C 完成、B 部分进行中）
> - **路线 v2.1 评估报告**：`C:/Users/HP/Documents/Codex/2026-08-26/referenced-chatgpt-conversation-this-is-an/outputs/ROADMAP_V21_SPEC_MAPPING_AUDIT.md`（254 项逐项映射）

---

## §0 预埋审查标准（plan-audit §0）

| 维度 | 本路线标准 |
|---|---|
| 目标对齐 | 每任务映射到 spec §14 的某个 A0-A9 Gate 或 §11 的某个具体 Gate |
| 前提假设 | 每阶段标注关键假设（如"假设现有 1163 测试不回归"），假设失效时回滚 |
| 边界场景 | 输入格式损坏、单 Evidence 不足、LLM 截断、并发写同一 Unit、Schema 迁移、旧页面无 `evidence_refs`、6749 页面被默认闭包过滤、cache cleanup 误删 |
| 依赖项 | 每阶段前置任务、外部依赖、缺失兜底 |
| 风险与副作用 | 显式列出每个任务的"可能拖垮全局"路径 |
| 可执行性 | 每任务 ≤ 3 新文件 + 2 改文件（沿用 absorption plan 纪律） |
| 验收标准 | 可量化："覆盖率从 15% 到 X%"、"某类错误注入测试阻止率 100%"、"real-data span accuracy ≥95%" |
| 盲区清单 | 显式承认"不知道"的部分——金标数据集人工标注、6749 页面 PageType 分布 |
| 回滚预案 | 每阶段可独立回滚，不影响已发布数据；旧字段保留读兼容 |

---

## §1 当前状态盘点（截至 2026-08-26）

### 1.1 项目进度（execution plan 已完成 + absorption plan v1 pending）

| 阶段 | 状态 | 来源 |
|---|---|---|
| A-01 基线冻结 | ✅ | execution plan |
| A-02 命名 + 术语 | ✅ | execution plan + `CONTEXT.md` |
| A-03 最小 Contract + 确定性 ID | ✅ | `src/kc/contracts/`, `src/kc/domain/ids.py` |
| A-04 边界门禁 + 写入权威 | ✅ | `scripts/check_kc_boundaries.py` |
| C-01 Collector + CanonicalDocument | ✅ | `src/kc/compiler/normalize.py` |
| C-02 Analyzer + Evidence 校验 | ✅ | `src/kc/compiler/evidence.py`, `extract.py` |
| C-03 Verify + KnowledgeObject 投影 | ✅ | `src/kc/compiler/verify.py`, `compile.py` |
| C-04 真实入口 E2E | ✅ | `src/kc/api.py`, `POST /api/v1/kc/compile` |
| C-05 小批量运行验收 | ✅ | `scripts/kc_accept_c.py`, 2 轮 2 文件 OK |
| B-01 Retrieval Contract | ⚠️ 进行中 | `src/kc/retrieval.py` 骨架，3 个 case |
| B-02 全格式适配 | ⚠️ 进行中 | PDF/DOCX/XLSX smoke 通过，SRT/VTT OK |
| B-03 历史迁移 | ⚠️ 进行中 | 1343 sources dry-run，10 文件 Pilot OK |
| B-04 Runtime/Registry | ⏸ 延后 | 阈值未达 |
| B-05 生产安全 | ⏸ 延后 | Artifact 生命周期未定 |
| absorption plan v1 | 📋 pending | 本路线 v2 替代其优先级 |

### 1.2 关键代码现状

| 资产 | 路径 | 状态 |
|---|---|---|
| KnowledgeObject | `src/knowledge/core/object.py` | 10 字段 + 8 状态，缺 `identity_key` / `knowledge_mode` / `superseded_by` / `valid_from` / `context` |
| WikiPage | `src/wiki/core/types.py` | 26 字段，`verified_at` 已有但默认 0；`_ko_extra` 多业务共用 |
| Evidence (KC) | `src/kc/contracts/evidence.py` | 7 字段 frozen dataclass + 确定性 quote_hash |
| Evidence (legacy) | `src/knowledge/claims/model.py` | 4 字段，仅 path/page/quote/added_at |
| hybrid_search | `src/searcher/hybrid_search.py` | keyword 路径 line 226-227 反查 `_ko_extra.evidence` 但未生效；semantic 路径完全丢失 evidence |
| dedup_auto | `src/wiki/features/dedup_auto.py` | 自动 merge（无 Approval），108+ 页已合并 |
| KC retrieval | `src/kc/retrieval.py` | `RetrievalResult` + `RetrievalEvidence`，provenance 区分 evidence/legacy |
| 金标数据集 | `docs/evaluation/retrieval_cases.json` | 3 case 硬编码 |
| 现有 wiki 页面 | `knowledge/**/*.md` | 6749 个文件 |
| `.llm-wiki/` + `.index/` | 项目根 | 已有项目 metadata 和 cache |

### 1.3 8 个核心差距（spec 杠杆点）

| # | 差距 | spec 来源 | 当前 | 杠杆 |
|---|---|---|---|---|
| G1 | Evidence 一等公民 | §3.2, §5.7 | `_ko_extra` 扁平 | 极高 |
| G2 | Default Retrieval Filter | §11.3, §12.1 | 无过滤 | 极高 |
| G3 | KnowledgeUnit 单独建模 | §4.2, §5.4 | KO 单层化 | 高 |
| G4 | Temporal Validity + 派生 | §10 | 无字段 | 高 |
| G5 | Observed/Synthesized 标签 | §7 | 无 | 中高 |
| G6 | Conflict 6 类型 | §8.2 | 3 类启发式 | 中 |
| G7 | Approval / 高风险审批 | §5.11, §11.4 #4 | 无 | 中 |
| G8 | 100 金标数据集 | §15 | 3 case | 极高（基建） |

---

## §2 三段路线（C-0 + C-1~C-4 + A-1~A-5 + B-1~B-5）

> 总时间估算：10-12 周到 MVP 完整版（沿用 execution plan C/A Gate + spec §A0-A9 验收）

### 阶段 C：核心层止血 + 评估基建

> **目标**：把"反幻觉锚点"立起来，把"能不能验证对错"的工具搭起来
> **为什么 C 先**：G1+G2+G8 是 spec 反幻觉 + 可验证的最低要求；不先做，后续 A/B 段都没法定量验收

#### C-0 Frontmatter Schema 演进（前置任务）⭐ 新增

> **背景**：`_ko_extra` 是 frontmatter 序列化层的"未声明字段逃生口"，含 4 类业务数据（evidence / provenance / source_status / memory.decision），共 63 处引用。路线 v1 的"清空 `_ko_extra.evidence`"是错的——多业务共用，演进而非清理。

**4 commit 分阶段迁移**：

| Commit | 业务数据 | 目标字段 | backfill | 验证 |
|---|---|---|---|---|
| 1 | `_ko_extra.source_status` | `WikiPage.workflow_state` 扩展值 | 统计现状分布，机械化映射 | capture 单测无回归 + grep count=0 |
| 2 | `_ko_extra.memory.decision` | `WikiPage.decision_record: dict \| None` | 统计现状占比，迁移 | memory/decision 单测无回归 |
| 3 | `_ko_extra.provenance` | 保留为 `_ko_extra` 内部 key（spec §5.7 要求 Evidence 内部字段） | 不迁移 | grep count 不变 |
| 4 | `_ko_extra.evidence` | `WikiPage.evidence_refs: list[str]` | dry-run 现状，迁移 + C-1 持久化目录同步 | C-1 验收 + 回退路径生效 |

**Files**：
- `src/wiki/core/types.py`（字段扩展，每 commit 一类）
- `backfill/c_<n>_<key>_migrate.py`（每 commit 一个迁移脚本）
- `tests/test_wiki/test_ko_extra_migration.py`（N 测试覆盖）

**关键约束**：
- 每个 commit 保留旧 key 的 read 兼容（deprecated 警告日志）
- 每个 commit 必须 dry-run 先于实际迁移
- 4 commit 全完成后才删除 `_ko_extra` 写入路径

**验收**：4 commit + 每 commit 全量测试无回归 + `_ko_extra` 写入路径仅剩 provenance

---

#### C-0.5 Core 独立备份与恢复（Z-1 + Z-5）⭐ 新增

> **背景**：spec §1 M-7 "Knowledge Core 删除后不能依赖消费视图恢复" + §17 D-22 "Core 备份恢复演练通过"
> **决策**：拆为两个任务 — C-0.5a 备份 API + C-0.5b 演练脚本

##### C-0.5a Core 备份 API（Z-1）

**Files**：
- `src/kc/backup/core_snapshot.py`（快照 + 还原 API）
- `scripts/kc_core_backup.sh` + `scripts/kc_core_restore.sh`（CLI 入口）
- `tests/test_kc/test_core_backup.py`（4 测试）

**核心 Schema**：
```
.llm-wiki/backups/<timestamp>/
├── snapshot.json           # 所有 KnowledgeObject dump
├── identity_keys.txt       # 当前所有 identity_key 列表（一致性校验）
├── version_events.jsonl    # append-only 事件流快照
└── MANIFEST.yaml           # snapshot_id, version_count, identity_count, file_hash
```

**TDD**：
1. `kc_core_backup.create_snapshot(paths)` 返回 snapshot_id，写盘 `.llm-wiki/backups/`
2. `kc_core_restore(snapshot_id)` 还原 + 验证 identity_key 一致
3. snapshot 含 `before_hash/after_hash` 摘要（spec §5.13 Publication Batch 必填）
4. 备份目录加入 `cache cleanup` 白名单

**验收**：4 测试通过；与现有 `safe_write` 集成不破坏 atomic 写入

##### C-0.5b Core 备份演练脚本（Z-5）

**Files**：
- `scripts/kc_core_backup_drill.py`（演练：snapshot → 模拟损坏 → restore → 一致性校验）
- `tests/test_kc/test_core_backup_drill.py`（3 测试）

**TDD**：
1. 演练执行：snapshot → 删 `.llm-wiki/` 部分文件 → restore → 检查 identity_key 100% 一致
2. KnowledgeObject 数量、version_events 完全一致
3. 演练报告输出到 `.index/backup_drills/<timestamp>.log` 含前后 sha256 对比

**验收**：3 测试通过；演练脚本可独立运行；spec §17 D-22 通过

---

#### C-1 Evidence 一等公民（G1）⭐ 最高 ROI（升级版）

> **背景**：路线 v1 写"清空 `_ko_extra.evidence`"——F-1 整改后改为"4 commit 演进第 4 commit"。C-1 实际是 C-0 的最后一步 + 持久化目录建设。

**Files**：
- `.index/evidence/<evidence_id>.json`（持久化目录）
- `src/kc/evidence/storage.py`（read/write API）
- `WikiPage.evidence_refs: list[str]` 字段（已在 C-0 Commit 4 加）
- WikiPage reader 优先读 `evidence_refs` → 回退 `_ko_extra.provenance`
- `scripts/kc_evidence_migrate.py`（从 `_ko_extra.evidence` 批量迁移到 `.index/evidence/`）
- **v2.2 优化**：C-1 任务内 Evidence dataclass 扩展 2 字段（spec §5.7 + §6 E-5/E-14/E-15）—— `computation_provenance: dict | None`（input_ids/algorithm/algorithm_version/result_hash）+ `structured_provenance: dict | None`（schema_id/record_key/field_path）

**测试组成（12 个测试）**：H-5 决策 + v2.2 优化
- 5 个单元测试：Evidence dataclass + EvidenceAdapter（已有）
- 3 个 round-trip 测试：WikiPage evidence_refs 字段
- 2 个 real-data 测试：抽样 100 个现有页面验证 evidence span 可定位率
- real-data 集成到 `scripts/kc_retrieval_eval.py` 输出 `span_accuracy` 指标
- 2 个 **v2.2 补位测试**：缺 `structured_provenance` → strength 降 weak；缺 `computation_provenance` → strength 降 weak

**验收**：
- 12 测试通过
- 现有 1163 测试无回归
- `real-data span_accuracy ≥95%`
- `grep -l "_ko_extra.evidence" 写入路径` = 0（C-0 Commit 4 后由 C-1 接管）
- **v2.2 验收补位**：Evidence 缺 `structured_provenance` 时强度降为 weak（spec §6 E-15）；缺 `computation_provenance` 时强度降为 weak（spec §6 E-14）

**阻断**：M12 向量检索 evidence 覆盖率从 0 升到 ≥80%

**回滚**：`.index/evidence/` 删除，WikiPage `evidence_refs` 字段删除（旧 `_ko_extra` 路径恢复）

---

#### C-2 Default Retrieval Filter（G2）⭐ 第二高 ROI

**Files**：
- `src/searcher/hybrid_search.py` 加 default filter（status=verified + temporal=current，**默认开启**）
- `src/kc/retrieval.py` 加 `include_quarantined=False` / `include_unknown=False` 参数
- `tests/test_searcher/test_default_filter.py`（5 测试 + 错误注入：quarantined/rejected/candidate 不得返回）

**验收**：
- 5 测试 + 错误注入 100% 阻止
- spec §11.4 #1（Unsupported Fact=0）首次可测量
- spec §11.4 #2（Critical Evidence Missing=0）首次可测量
- **关键**：6749 现有页面的兼容处理（H-2 决策 = 30 天过渡期，详细策略见 B-3）

**回滚**：默认参数 back-compat，旧调用方零影响

---

#### C-3 金标数据集骨架（G8）⭐ 评估基建（F-2 整改版）

> **决策**：29→100 case 分阶段，A0 Gate 显式延后到 B-5

**Files**：
- `evaluation/cases/source_trust.yaml`（5 case）
- `evaluation/cases/evidence_span.yaml`（5 case）
- `evaluation/cases/conflict.yaml`（actual/conditional/temporal/perspective/unresolved 各 2 = 10 case）
- `evaluation/cases/identity.yaml`（merge/supersede/keep_separate 各 3 = 9 case）
- `evaluation/cases/retrieval.yaml`（5 case，含 query_time、context）
- `evaluation/cases/_meta.yaml`（缺口标注 + 覆盖率报告）
- `scripts/kc_eval.py`（输出 Precision/Recall + 失败样本 ID + 缺口清单）

**case 标签三档**：
- `full`：完整 11 字段 + 人工核查
- `partial`：部分字段 + 缺口标注
- `synthetic`：LLM 提案 + 规则验证，confidence="low"

**验收**：
- 29 case + 显式缺口标注
- 每个 case 标 `full` / `partial` / `synthetic` 三档
- `scripts/kc_eval.py` 输出 14 维度覆盖率报告
- **不宣称 A0 Gate 通过**——A0 Gate 延后到 B-5（100 case 完整）

**盲区**：标注一致性（K-3 加固——单人 re-test 稳定性）

---

#### C-3.5 Agent Task 评估集（Z-3）⭐ 新增

> **背景**：spec §15 V-14 "Agent Task Success Rate ≥0.85" + §17 D-15 "Agent Task ≥0.85 + Citation Accuracy ≥0.95"
> **决策**：C-3 金标 29 case 起步后立即补，C 阶段就建立 Agent Task 评估骨架

**Files**：
- `evaluation/agent_tasks/*.yaml`（≥10 个固定 agent task 案例）
- `scripts/kc_agent_eval.py`（评估脚本：调用 MCP/Agent 完成任务 → 判定）
- `tests/test_kc/test_agent_task_eval.py`（3 测试）

**Agent Task 案例结构**（spec §12.3）：
```yaml
- task_id: AT-001
  query: "找出关于 X 的最新 Claim，要求至少 2 个独立 medium Evidence"
  expected_knowledge_units: [<ku_id_1>, <ku_id_2>]
  expected_citations: [<evidence_id_1>, <evidence_id_2>]
  expected_knowledge_modes: ["observed"]  # 判定 agent 是否识别
  expected_conflict_status: ["none"]
  success_criteria:
    min_units_returned: 2
    min_citations_valid: 2
    knowledge_mode_identified: true
    citations_match: true
```

**TDD**：
1. Agent eval 脚本读取 task yaml → 调用 agent runtime → 判定 success
2. 成功 task 数 / 总 task 数 = Success Rate
3. Citation Accuracy = 正确支撑的 Citation / 全部 Citation

**验收**：
- ≥10 agent task yaml
- `scripts/kc_agent_eval.py` 输出 Success Rate + Citation Accuracy
- ≥0.85 / ≥0.95 阈值可计算

**回滚**：N/A（评估脚本独立）

**依赖**：MCP stdio 入口（已有）

---

#### C-4 Observed/Synthesized 标签（G5）（K-2 加固版）

> **K-2 加固**：LLM 截断/解析失败 → fail-closed，禁止默认 fallback `observed`

**前置扫描**（L-2 加固）：
- `scripts/kc_knowledge_mode_scan.py`：扫描现有 23 种 schema 中声明的 knowledge_mode 字段

**Files**：
- `KnowledgeCandidate.knowledge_mode: Literal["observed","synthesized","unknown"]`（**unknown 为截断兜底**）
- `KnowledgeObject.knowledge_mode` 同上（round-trip 兼容）
- generator prompt 加 Observed Allowed Transform 检查
- `tests/test_knowledge/test_knowledge_mode.py`（5 单元 + **5 截断测试**）

**5 种截断测试场景**：
1. JSON 残缺（如 `{"knowledge_mode": "obser`）
2. 字段缺失
3. 值越界（如 `null` / 空字符串 / 非预期值）
4. 空白
5. 列表而非单值

**验收**：
- 5 单元 + 5 截断测试全过
- 截断时强制 `unknown` → quarantine → 不进默认检索
- Mode Leakage 错误注入（Synthesis 冒充 Observed）100% 被阻止

**依赖**：金标 conflict.yaml（C-3 已建）+ 前置扫描（L-2）

---

#### C-4.5 Claim/Structured Fact 双路径（Z-8）⭐ 新增

> **背景**：spec §3.5 "Claim 不是强制中间态" + "两条路径必须共享 Evidence + Context + Temporal + Integrity 契约"
> **决策**：C-4 完成后立即扩展，不延后到 B 段

**Files**：
- `src/kc/contracts/structured_fact.py`（StructuredFact dataclass + identity_key 算法）
- `src/kc/extraction/structured_extractor.py`（参数表 / 法规 / 代码定义专用抽取）
- `tests/test_kc/test_structured_fact.py`（4 测试）

**Structured Fact identity_key 算法**（spec §5 表）：
```
identity_key = "id-v1:" + sha256({
    "subject", "field", "value", "value_type",
    "context_id", "validity_id"
})
```

**TDD**：
1. `StructuredFact` 构造 + identity_key 确定性（同输入同输出）
2. `structured_extractor.extract(table)` 返回 `List[StructuredFact]`
3. Structured Fact 共享 Evidence 引用（不重复 Evidence）
4. Claim + Structured Fact 共存于同一 KU（spec §3.5 合并到 KU）

**验收**：4 测试通过；Generator prompt 增加 Structured Fact 抽取路径；spec §3.5 满足

**回滚**：StructuredFact 不破坏现有 Claim 路径，可独立启用

---

### 阶段 A：纪律 + 关键结构

> **目标**：把"能扩展、能演化、能审计"的能力加上，同时把规范纪律定下来
> **为什么 A 第二**：G3-G7 都是结构性改造，需要先有 C 段的 Evidence/Filter 作为前置；A 段规范同步定稿才能避免 B 段返工

#### A-5 命名/目录/契约/依赖 4 类规范定稿（L-1 加固：subagent 并行）

**Files**（4 文件，subagent 并行）：
- `docs/conventions/naming.md`
- `docs/conventions/directory.md`
- `docs/conventions/contract.md`
- `docs/conventions/dependencies.md`
- **v2.2 优化**：A-5 任务内追加 `docs/conventions/metric_threshold_change_adr.md`（指标阈值变更 ADR 模板，含固定数据集前后对比章节）

**验收**：
- 4 文档存在 + 本地 plan-audit 通过
- 新顶级目录 ≥3 提案必须先 ADR
- 预计 2 小时完成（4 subagent 并行）
- 指标阈值变更 ADR 模板存在（spec §15.3 末尾要求）

**延迟影响**：本任务不阻塞 C-1~C-4，独立子任务

---

#### A-0 delivery_report 强制机制（Z-6）⭐ 新增

> **背景**：spec §16 EX-3 "hard_gate_failures 非空 → next_phase_ready 必须 false"
> **决策**：C-0 之后立即建立，作为后续所有任务的强制交付机制

**Files**：
- `.superpowers/sdd/delivery_reports/template.yaml`（报告模板）
- `scripts/kc_check_delivery_report.py`（CI 校验脚本）
- `.superpowers/sdd/delivery_reports/`（每任务一份）
- `tests/test_kc/test_delivery_report.py`（3 测试）

**Template 字段**（spec §16.2 完整 9 项）：
```yaml
phase: "C-1 Evidence 一等公民"
changed_files: [...]
contracts_changed: [...]
tests_run: [...]
evaluation_dataset_version: "2026-08-26-29case"
metrics:
  real_data_span_accuracy: 0.97
  evidence_persistence_tests: "10 passed"
hard_gate_failures: []
migration_required: false
rollback_procedure: "删除 .index/evidence/ + WikiPage.evidence_refs 字段即可"
known_limitations: ["MCP semantic 路径不反查 evidence"]
next_phase_ready: true
```

**TDD**：
1. CI 校验脚本检查每个 commit 关联的 delivery_report 存在
2. 校验 9 个必填字段非空
3. `hard_gate_failures` 非空时 `next_phase_ready` 必须为 false（强制规则）

**验收**：
- 3 测试通过
- CI 集成：commit 时校验 delivery_report 存在
- A-0 之后所有 C/A/B 任务必须有 delivery_report

**回滚**：template 可调整，但 CI 校验严格

---

#### A-1 KnowledgeUnit 单独建模（G3）⚠️ 最高风险（F-3 整改版）

> **F-3 整改**：dry-run 前置 + 路线选择 B（KU 作为逻辑单元）+ 叙述类拆分策略待 dry-run 后定

**A-1 前置 dry-run（半自动）**：
- `scripts/kc_ku_dryrun.py` 统计现有页面 PageType 分布
- 抽样 20 个叙述类页面手工评估"是否需要拆分"
- 输出 backfill 成本估算（LLM token + 时间）

**Files**（基于 dry-run 结果）：
- `src/kc/domain/knowledge_unit.py`（独立 dataclass）
- `KnowledgeObject.ku_id` 字段（back-compat 默认指向 slug 自引用）
- `WikiPage.ku_id` 字段（同上）
- `tests/test_knowledge/test_knowledge_unit.py`（4 测试）

**叙述类拆分策略（dry-run 后用户决策 3 选 1）**：
- 选择 1：所有页面 = 1 个 KU（简单，spec 妥协）
- 选择 2：长页面 (>5 段) 触发 LLM 拆分（中等成本）
- 选择 3：仅对"答案不明确"页面 LLM 拆分（精准成本）

**验收**：
- 4 测试通过
- legacy 单层 KO 自动映射到 KU（Migration 脚本）
- spec §4.2 拆分/合并决策写入 `resolution_event`
- **关键**：dry-run 完成后由用户做 3 选 1 决策后再开工
- **v2.2 补位 #4**：resolution_event 必填 4 字段（规则版本/候选集/模型版本/输出理由）—— 缺规则版本 → fail-closed、缺模型版本 → fail-closed、缺候选集 → fail-closed、缺输出理由 → warn 但 quarantine、完整 → pass。详见 §A-3 验收补位

**回滚**：字段默认 None；旧 KO 链路仍工作；新链路灰度走

---

#### A-2 Temporal Validity 字段 + 派生（G4）

**Files**：
- `KnowledgeObject.valid_from/valid_to: datetime \| None` 字段
- `src/kc/compiler/temporal.py::derive_status(obj, query_time)` 派生函数
- `hybrid_search.py` 加 `temporal=current` 过滤（与 C-2 配合）
- `tests/test_knowledge/test_temporal.py`（5 测试 + L-6 加固）

**L-6 加固**：`valid_from = None` 的页面明确标记 `temporal_status="unknown"`，不进默认检索（spec §10 边界）

**验收**：5 测试；Default Retrieval Filter 同时检查 status + temporal

**依赖**：C-2 完成后做

---

#### A-3 Conflict 6 类型（G6）

**Files**：
- `src/kc/conflicts/classifier.py`（Context 维度判定 + temporal 维度判定）
- `Conflict.conflict_type: Literal["actual","conditional","temporal","perspective","none","unresolved"]`
- `tests/test_knowledge/test_conflict_classifier.py`（6 测试）

**K-5 加固**：Taxonomy 与 Context 8 维映射关系文档化
- `docs/migration/taxonomy_to_context_mapping.md`
- 旧 `category` → 新 `Context.domain`
- 旧 `taxonomy_sub` → 新 `Context.platform`
- Phase 4 batch 18 的 `taxonomy unknown` warn 标记为 missing Context.platform，由用户决策

**验收**：6 测试；spec §8.2 分类规则 100% 覆盖；Pseudo-conflict Rate 错误注入可计算
- **v2.2 补位 #4**：resolution_event 必填 4 字段（规则版本/候选集/模型版本/输出理由）—— `tests/test_kc/test_resolution_event_replay.py`（5 测试：缺规则版本→fail-closed、缺模型版本→fail-closed、缺候选集→fail-closed、缺输出理由→warn 但 quarantine、完整→pass）。spec §9 执行规则末尾要求

**依赖**：金标 conflict.yaml（C-3 已建）+ Temporal 字段（A-2）

---

#### A-4 Approval / 高风险审批流（G7）（H-1 + K-4 加固版）

> **H-1 整改**：保留两套 merge 路径，避免与现有 dedup_auto 冲突

**Files**：
- `src/kc/governance/approval.py`（Approval dataclass + CLI `python -m src.cli kc approve <id>`）
- `src/kc/resolution.py::apply_merge/split/supersede` 加 approved 检查
- `src/wiki/features/dedup_auto.py`（修改：增加 `--require-approval` 开关，默认 False 兼容历史；路线合并后默认 True）
- `tests/test_knowledge/test_approval.py`（3 测试）

**K-4 加固**：
- `merge-reviewed` 路径加 dry-run 预览：CLI 显示 "将合并 A→B，请审批"
- 提供 `python -m src.cli kc approve-batch <review_ids>` 批量审批
- 历史 108+ 页 merge 保留为 legacy，不强制 backfill Approval

**merge 双模式契约**：
- `merge-auto-high`（high confidence 自动）：标记 legacy，不进 spec §11.4 #4 审计范围
- `merge-reviewed`（需 Approval）：spec §11.4 #4 的标准路径

**验收**：3 测试；spec §11.4 #4（无审计 merge 数量=0）首次可测量；两套 merge 路径互不污染

**依赖**：Resolution Event 必须先存在

---

#### A-7 Wiki Query+Template 编译（Z-7）⭐ 新增

> **背景**：spec §12.4 "Wiki 通过 Query + Template 编译，不按单篇原文生成摘要"。当前 `wiki_projection.py` 是 1-page-per-source，**违反 R-7**
> **决策**：A 段结束前重写 wiki 写入路径

**Files**：
- `src/kc/views/wiki_template.py`（稳定模板定义）
- `src/kc/views/wiki_template_compiler.py`（Query + Template 编译器）
- `wiki_view` dataclass（spec §12.4 完整 6 字段）
- `tests/test_kc/test_wiki_template_compiler.py`（6 测试）

**wiki_view schema**（spec §12.4）：
```python
@dataclass
class WikiView:
    id: str
    topic_scope: dict          # {"concept_ids": [...], "context_filters": {...}}
    publication_version: int
    knowledge_unit_ids: list[str]
    rendered_hash: str
    generated_at: datetime
```

**TDD**：
1. `WikiTemplateCompiler.compile(topic, template, publication_version)` 返回 `WikiView`
2. 模板可配置：含 KU 列表 / Conflict 列表 / Evidence 列表 / Temporal 状态显示
3. 同 topic + 同 publication_version 重建后 `rendered_hash` 一致
4. 不同观点不被静默合并（spec §A7 Gate 要求）
5. 每个事实都有 Evidence 入口
6. 删除 Wiki 后从 Core 重建（与 B-3.5 集成）

**验收**：6 测试通过；替换现有 wiki_projection 写入路径（保留 legacy 兜底）；spec §A7 Gate 通过

**回滚**：保留 wiki_projection 作为 legacy 兜底；新路径与旧路径可并存

**依赖**：A-3 Conflict 6 类型 + C-1 Evidence + A-2 Temporal

---

### 阶段 B：补齐与归一

> **目标**：把"完整默认发布闭包 + 11 Gate + 高质量评估"全部到位
> **为什么 B 最后**：spec 11 个 Gate 需要前面 C+A 全部前置；过早建 Gate 是空架子

#### B-1 Semantic Support Check（spec §6 末尾）（H-3 + H-6 + K-2 加固版）

> **H-3 整改**：ON by default（spec §A5 强制），不再 OFF 绕过 Gate
> **H-6 整改**：成本上限 + 抽样策略
> **K-2 加固**：截断 fail-closed

**Files**：
- `src/kc/compiler/semantic_support.py`（LLM-as-judge 调用）
- `RUFLO_SEMANTIC_SUPPORT_ENABLED`（ON by default）
- `RUFLO_SEMANTIC_SUPPORT_COST_LIMIT`（默认 50 元/日）
- `RUFLO_SEMANTIC_SUPPORT_SAMPLE_RATIO`（默认 10 = 每 10 页抽 1 页全检）
- `tests/test_knowledge/test_semantic_support.py`（3 测试：开启时通过 / 关闭时跳过 / 截断 fail-closed）

**OFF 时的硬门槛**：
- Evidence Semantic Support Error 自动归类为 `unsupported`（保持 spec §11.4 #9 的硬门槛）

**成本估算**：
- 每页 ~500 input + ~200 output tokens × ¥0.01/1k ≈ ¥0.007/页
- 抽样 1/10 = 每 10 页 1 次 LLM 调用 ≈ ¥0.007/页
- 每日 50 元上限 ≈ 7143 页/日，远超当前 batch 规模

**验收**：开关切换行为正确；金标 `evidence_span.yaml` 命中率可测量；成本上限生效

---

#### B-2 11 个 Integrity Gate 实现（spec §11.2 完整版）

**Files**：
- `src/kc/integrity/gates/`（11 个 gate 模块，每个 1 文件）
- `src/kc/integrity/run_all.py`（流水线调用）
- `src/kc/integrity/gates/<n>_<name>.py`（Schema/Provenance/Evidence/Mode/Identity/Granularity/Context/Temporal/Conflict/Relation/Retrieval）
- `tests/test_knowledge/test_integrity_gates.py`（11 测试：每 gate 1 happy + 1 fail）

**K-6 加固**：每个 commit 涉及 `src/server/` / `src/cli.py` / `src/wiki/` 顶层 → 触发 `scripts/verify_serve.sh`
- 启动 serve，curl `/health` 200
- 启动 serve，curl `/ready` 200
- POST 1 次真实 `/api/v1/kc/compile` payload

**最大风险**：Gate 顺序冲突（Schema/Identity/Granularity 互相依赖），需先做依赖图

**验收**：11 测试 + spec §11.4 全部错误注入阻止率 100%；spec §14 A5 Gate 通过
- **v2.2 补位 #4**：resolution_event 必填 4 字段在 Integrity Gate 流水线内统一校验（与 A-1/A-3 任务的 resolution_event 写入配套）；详见 §B-2.5

**前置**：C+A 全段完成；金标数据集 ≥50 case（B-5 中段）

---

#### B-2.5 identity_key 总验收任务（spec §5 表）⭐ 新增（v2.2 重大补位 #1）

> **背景**：spec §5 表规定 13 个对象的 identity_key 输入字段；`src/kc/domain/ids.py` 当前仅 3 函数（document_id/block_id/evidence_for_quote）。审计发现 11 行 identity_key 散落到 A-1/A-3/C-4.5/B-2 各任务易遗漏。
> **决策**：B-2 完成后立即做统一校验任务，避免分散实施遗漏

**Files**：
- `tests/test_kc/test_identity_key_consistency.py`（13 测试：每对象 1 测试）
- `src/kc/domain/ids.py`（扩展：实现 13 行 identity_key 算法）
- `src/kc/integrity/check_identity_key.py`（集成到 B-2 流水线）

**13 行 identity_key 输入字段**（spec §5 表）：

| 对象 | identity_key 输入字段 | 当前实现 | 待补 |
|---|---|---|---|
| Source | `source_type, canonical_locator` | ❌ | ✅ |
| Raw Source | `raw_bytes_hash` | md5（Z-9 延后 sha256） | ⚠️ Z-9 |
| Canonical Document | `raw_source_id, parser_name, parser_version, correction_of` | 3/4 字段 | ✅ |
| Concept | `concept_type, canonical_name, identity_scope_id` | ❌ | ✅ |
| Knowledge Unit | `concept_id, question, unit_type, knowledge_mode, context_id, validity_id` | ❌ | ✅ |
| Claim | `subject, predicate, object, text, knowledge_mode, context_id, validity_id` | ❌ | ✅ |
| Structured Fact | `subject, field, value, value_type, context_id, validity_id` | ❌ | ✅ |
| Evidence | `document_id, block_id, source_span, source_hash` | 3/4 字段 | ✅ |
| Context | 9 维度字段 + policy_version | ❌ | ✅ |
| Validity | `valid_from, valid_to, derivation_policy_version` | ❌ | ✅ |
| Synthesis | `output_claim_id, derived_from, method, model, model_version, prompt_version` | ❌ | ✅ |
| Relation | `relation_type, from_ref, to_ref, context_id, validity_id` | ❌ | ✅ |
| Conflict | `statement_a_ref, statement_b_ref, context_a_id, context_b_id`（排序后） | ❌ | ✅ |

**TDD**：
1. 每对象 1 测试：同输入字段 → 同 identity_key
2. 输入字段缺失/越界/空 → 抛 `IdentityKeyError`（fail-closed）
3. 同一对象类型 identity_key 唯一（数据库级约束）
4. id-v1 算法（NFKC + 去空白 + 小写 + UTC RFC 3339 + Canonical JSON + 集合排序）单元测试

**验收**：
- 13 测试通过
- `src/kc/domain/ids.py` 实现 13 行 identity_key（除 Z-9 的 sha256）
- 与 A-1/A-3/C-4.5/C-1 各任务的实现一致（无散落）
- spec §14 A4-3 Gate 通过（确定性 identity_key 和唯一约束）

**回滚**：N/A（纯测试 + 工具库）

**依赖**：A-1 + A-3 + C-4.5 + C-1 全部完成（每个任务的 identity_key 实现已落地）

---

#### B-2.6 Knowledge Health Report（spec §11 末尾 + §14 A5-8）⭐ 新增（v2.2 重大补位 #2）

> **背景**：spec §11 末尾要求 Knowledge Health Report；§14 A5-8 显式验收。v2.1 路线 B-2 隐含但无显式任务。
> **决策**：B-2 完成后立即追加 Health Report 模块

**Files**：
- `src/kc/integrity/health_report.py`（生产环境质量分 + 失败样本 + 分阶段统计）
- `scripts/kc_health_report.py`（CLI 入口）
- `tests/test_kc/test_knowledge_health_report.py`（3 测试）
- `.index/health_reports/<date>.json`（每日快照）

**Health Report 输出 schema**：
```python
{
    "report_date": "2026-XX-XX",
    "quality_score": 0.85,           # 加权平均分
    "gate_failures": {
        "schema": 0, "provenance": 2, "evidence": 5,
        "mode": 1, "identity": 0, "granularity": 3,
        "context": 8, "temporal": 0, "conflict": 2,
        "relation": 0, "retrieval": 1
    },
    "failed_sample_ids": [
        {"object_type": "claim", "object_id": "claim_abc", "failed_gates": ["evidence"]}
    ],
    "phase_breakdown": {
        "candidate": 100, "verified": 850, "disputed": 5,
        "quarantined": 30, "rejected": 15
    },
    "metric_snapshots": {
        "identity_resolution_precision": 0.97,
        "merge_proposal_precision": 0.99,
        ...
    }
}
```

**TDD**：
1. `health_report.generate()` 输出符合 schema 的 dict
2. CI 集成：`scripts/kc_health_report.py` 写入 `.index/health_reports/`
3. quality_score 计算正确（加权：硬门槛错误权重 10、普通 Gate 错误权重 1）

**验收**：
- 3 测试通过
- CI 集成：每日定时任务（或手动触发）
- spec §14 A5-8 通过
- spec §11 末尾"Knowledge Health Report"实现

**回滚**：N/A（独立模块）

**依赖**：B-2 11 Gate 完成

---

#### B-3 默认发布闭包（spec §11.3）⭐ 终极目标（H-2 + K-1 加固版）

> **H-2 整改**：30 天过渡期 + CLI 显式确认 + legacy 兜底
> **K-1 加固**：3 项过渡策略

**Files**：
- `src/kc/publish/closure.py`（8 条件 AND 验证）
- `hybrid_search.py` 默认 filter 集成 closure 校验
- `src/cli.py` 加 `kc enable-closure --confirm` 子命令
- `src/cli.py` 加 `kc migrate-legacy` 子命令
- `tests/test_knowledge/test_publish_closure.py`（8 测试：每条件 1 happy + 1 fail）

**30 天过渡期策略**：
- 过渡期内：legacy 兜底 + warning 日志（每检索 1 次 warn 1 次）
- CLI 二次确认：`python -m src.cli kc enable-closure --confirm`
- 30 天后：用户必须执行 `python -m src.cli kc migrate-legacy` 显式迁移
- 迁移策略：`verified_at = ingestion_unix_ms`（机械化 backfill，可选）

**验收**：spec §14 A6 Gate 通过（Recall@5 ≥0.90, Precision@5 ≥0.80, Unsupported Fact=0）

---

#### B-3.5 Wiki 重建演练（Z-2）⭐ 新增

> **背景**：spec §14 A7 Gate "删除全部 Wiki 后从 Core 重建" + §17 D-18 部分
> **决策**：B-3 完成后立即做，避免 B-4 Publication Batch 与重建耦合

**Files**：
- `src/kc/views/wiki_rebuild.py`（从 Core 重建 Wiki 编译器）
- `scripts/kc_wiki_rebuild_test.py`（演练脚本：删 wiki/ → rebuild → diff）
- `tests/test_kc/test_wiki_rebuild.py`（5 测试）

**TDD**：
1. `wiki_rebuild.rebuild(project_root)` 从 `.kc/` Core 目录重建所有 wiki 页面
2. 重建前后页面 hash 完全一致
3. 删除 `wiki/` 目录后 rebuild 成功
4. 重建不依赖 `_ko_extra`（即 spec §3.3 Evidence First 不被破坏）
5. 重建日志记录每个页面的 `publication_version` + `ku_id`

**验收**：
- 5 测试通过
- 重建演练脚本可独立运行：`python scripts/kc_wiki_rebuild_test.py --project <id>`
- 演练报告输出 diff 统计（页面数 / hash / relations 数）

**回滚**：wiki/ 目录在演练前自动备份

---

#### B-3.6 Book 空视图重建（Z-4）⭐ 新增

> **背景**：spec §17 D-18 "Wiki 和 Book 可在空视图存储上完全重建"
> **决策**：与 B-3.5 合并演练，统一跑

**Files**：
- `src/kc/views/book_rebuild.py`（Book 重建）
- `scripts/kc_views_rebuild_test.py`（统一演练：删 wiki/ + book/ → rebuild → diff）
- **v2.2 优化**：B-3.6 任务内追加 Outline Proposal Engine schema（spec §12.5 + §14 A8-5）—— `src/kc/views/outline_proposal.py`（trigger/affected/migration/rollback mapping dataclass）+ `tests/test_kc/test_outline_proposal_engine.py`（4 测试：trigger/affected/migration/rollback mapping 完整性 + 不自动应用）

**TDD**：
1. `book_rebuild.rebuild(project_root)` 从 `.kc/book/` 重建 Book 目录
2. 重建前后 Book 页面 hash 一致
3. 删除 Book 后 rebuild 成功
4. Book 重建依赖 Knowledge Unit → Chapter 映射（spec §12.5），依赖 A-3 + A-7
5. `outline_proposal.create(trigger_ku_ids, affected_chapter_ids)` 返回 proposal dataclass（status="proposed"），不自动应用
6. `outline_proposal.apply()` 仅在 `status="approved"` 时修改 outline_version

**验收**：
- 与 B-3.5 一起跑演练
- 演练报告含 wiki/ + book/ 双重建结果

**回滚**：book/ 演练前自动备份

---

#### B-4 Publication Batch / 5 层水位（spec §5.13）

**Files**：
- `src/kc/publish/batch.py`（事务化水位切换）
- `tests/test_knowledge/test_publication_batch.py`（3 测试：原子切换、回滚、增量发布）

**K-7 加固**：`.index/evidence/` 加入 cache cleanup 白名单 + 测试覆盖 + `safe_write` 缓冲
- `src/maintenance/cache_cleanup.py` 加 `--dry-run` 默认开启
- `.index/evidence/` 在白名单配置中显式登记
- 删除路径必须经过 `safe_write` 缓冲

**验收**：旧版本可追溯；同一时刻 5 层视图 publication_version 一致

**风险**：高频 ingestion 时批次大小决策——借鉴 Phase 4 batch 18 经验

---

#### B-5 100 金标完成 + Evaluation 报告（spec §17 DoD）

> **F-2 决策**：阶段 2 金标 100 case 完整覆盖矩阵 + A0 Gate 通过

**Files**：
- 补全金标至 ≥100 case（29 → 100）
- 阶段 1 的 synthetic case 升级为 full（用户/agent 协作验证）
- 补充缺失维度的 case
- `docs/evaluation/baselines/<date>.json`（指标快照）
- meta-metric：标注一致性（K-3 加固：单人 re-test 稳定性）
- **v2.2 优化**：B-5 任务内追加 `scripts/kc_eval.py` 输出 `not_evaluable` 标记（分母=0 时不视为通过）

---

#### B-5.5 连续 20 次批量增量演练（spec §14 A9-7 + §17 D-19）⭐ 新增（v2.2 重大补位 #3）

> **背景**：spec §14 A9-7 "连续 20 次批量增量演练" + §17 D-19 "连续 20 次增量导入无重复 identity_key、无丢失版本、无非预期全量重编译"
> **审计发现**：v2.1 仅 B-5 隐含提及，未拆为独立任务

**Files**：
- `tests/test_kc/test_incremental_evolution_drill.py`（20 测试：每批量 1 个）
- `scripts/kc_incremental_drill.py`（演练脚本：连续 20 批量 × 100 raw = 2000 file fixture）
- `.index/drill_logs/<timestamp>.log`（演练日志）

**TDD**（20 个测试，每个验证一个批量）：
1. 批量 1-20：每个批量跑 100 raw source 文件
2. 每批量后校验：identity_key 数量与新源文件数量一致（无重复）
3. 每批量后校验：version 事件无丢失
4. 每批量后校验：增量 build 无全量重编译（diff 增量 < 阈值）
5. 累计 20 批量后校验：identity_key 总数 = 2000 个 unique

**验收**：
- 20 测试通过
- 演练脚本可独立运行：`python scripts/kc_incremental_drill.py --project <id> --batches 20`
- spec §17 D-19 通过

**回滚**：N/A（测试任务）

**依赖**：B-5 100 金标完成 + B-4 Publication Batch

---

#### B-5.6 5 类端到端演化演练（spec §14 A9-8 + §17 D-20）⭐ 新增（v2.2 重大补位 #3 续）

> **背景**：spec §14 A9-8 "5 类端到端（修正/撤回/Evidence 失效/Conflict 解决/supersede）" + §17 D-20 "演化结果全部符合金标"
> **审计发现**：v2.1 仅 B-5 提及"演化 case 覆盖矩阵"，未显式拆 5 类

**Files**：
- `tests/test_kc/test_evolution_e2e.py`（5 场景 × 3-5 fixture = 20 测试）
- `scripts/kc_evolution_drill.py`（演练脚本：5 类演化各跑一次）
- `.index/evolution_logs/<scenario>/<timestamp>.log`

**5 类演化场景**：
1. **来源修正**（spec §5.1 Correction Record）：原 Raw Source 内容修正 → 新 CanonicalDocument + Correction Record；旧 Raw Source 仍可访问
2. **来源撤回**（spec §5.12 Review Task）：Source Trust Profile.status → withdrawn；Evidence.status → withdrawn；stale 知识默认不返回
3. **Evidence 失效**（spec §6 + §11.3）：Evidence.invalidated_at 设置 → 依赖该 Evidence 的 KU 进入 stale；重新验证后可恢复
4. **Conflict 解决**（spec §5.11 + §8）：conflict.resolution 设置 → disputed KU 进入 verified；resolution_event 留痕
5. **supersede**（spec §10 + §11.1）：新旧版本建立双向 supersedes/superseded_by；旧版本降级 historical

**TDD**（每场景 3-5 测试）：
- 演化前快照 identity_key 列表
- 触发演化
- 演化后校验：每个对象状态符合 spec；金标数据集结果一致
- 重放 resolution_event 序列验证一致性

**验收**：
- 20 测试通过（5 场景 × 3-5 fixture）
- 演练脚本可独立运行
- spec §17 D-20 通过

**回滚**：N/A（测试任务）

**依赖**：B-5 100 金标 + B-2 11 Gate + B-3 closure + B-4 Publication Batch

**K-3 加固**：标注一致性 meta-metric
- 每个 case re-test 一致性（即使单人也要有 re-test 稳定性）
- 季度报告：标注者间一致性（如果多人）+ 单人 re-test 一致性
- 不一致 case 标 `confidence="low"`，不进核心分母

**验收**：spec §14 A9 Gate 通过（连续 20 次增量无重复 identity_key）；spec §A0 Gate 首次通过

---

## §3 路线仪表盘（H-4 决策）

每阶段结束更新到 `.superpowers/sdd/progress.md` 顶部「路线仪表盘」段。

| 指标 | 当前 | 目标 | 计算方式 |
|---|---|---|---|
| spec 21 对象覆盖率 | ~40% | 100% | dataclass 实现字段 / spec 字段总数 |
| spec 11 Gate 实现度 | ~10% | 100% | 已实现 Gate 数 / 11 |
| spec 16 指标可计算度 | 0/16 | 16/16 | 分母 > 0 的指标数 / 16 |
| 当前阶段 Gate 通过 | A0-A9 都未过 | A0-A9 全过 | spec §14 各 Gate 状态 |
| 现有页面 verified_at=0 比例 | ~100% | <5% | 机械化 backfill 进度 |

CI 校验：每次 commit 后 `scripts/kc_dashboard.py` 输出，失败不阻断 commit 但记录 warning。

---

## §4 风险地图与盲区

按 plan-audit §1（全面漏洞审计）扫描路线本身：

### 4.1 致命风险（会让路线失败）

| # | 风险 | 整改 | 状态 |
|---|---|---|---|
| F-1 | `_ko_extra` 多业务共用 | C-0 4 commit 演进 | ✅ 已纳入 |
| F-2 | 金标 29 case 违反 A0 Gate | 29→100 分阶段 + A0 Gate 延后 | ✅ 已纳入 |
| F-3 | KU backfill 工作量低估 | dry-run 前置 + 3 选 1 策略 | ✅ 已纳入 |

### 4.2 重大隐患（容易失败但不致命）

| # | 隐患 | 加固 | 状态 |
|---|---|---|---|
| H-1 | dedup_auto 与 §11.4 #4 冲突 | 双模式 merge + CLI 开关 | ✅ 已纳入 A-4 |
| H-2 | 6749 页被默认闭包过滤 | 30 天过渡 + CLI 确认 | ✅ 已纳入 B-3 |
| H-3 | Semantic Support OFF 绕过 Gate | ON by default + 成本上限 | ✅ 已纳入 B-1 |
| H-4 | 路线缺全局指标 | progress.md 仪表盘 | ✅ 已纳入 §3 |
| H-5 | C-1 测试数与 spec Gate 不对齐 | 5+3+2 测试组成 | ✅ 已纳入 C-1 |
| H-6 | LLM 成本失控 | 抽样 + 50 元/日上限 + token 估算 | ✅ 已纳入 B-1 |

### 4.3 加固任务（来自 Round 2 压力测试）

| # | 加固点 | 行动 | 状态 |
|---|---|---|---|
| K-1 | B-3 30 天过渡 | CLI 确认 + warning 日志 + migrate-legacy | ✅ 已纳入 B-3 |
| K-2 | C-4 fail-closed 截断 | 5 种截断测试 + quarantine 兜底 | ✅ 已纳入 C-4 |
| K-3 | 金标一致性 | meta-metric + re-test 稳定性 | ✅ 已纳入 B-5 |
| K-4 | dedup_auto CLI | --require-approval + dry-run + 批量审批 | ✅ 已纳入 A-4 |
| K-5 | Taxonomy 映射 | 文档化 mapping + Phase 4 batch 18 决策 | ✅ 已纳入 A-3 |
| K-6 | serve 验证脚本 | verify_serve.sh + CI 集成 | ✅ 已纳入 B-2 |
| K-7 | cache cleanup 白名单 | dry-run + 测试覆盖 + safe_write | ✅ 已纳入 B-4 |

### 4.4 v2.1 补位任务（Z-1~Z-9 路线盲区）

| # | 补位任务 | spec 来源 | 阶段位置 |
|---|---|---|---|
| Z-1 | Core 独立备份/版本化 API | §1 M-7 | C-0.5a |
| Z-2 | Wiki 重建演练 | §14 A7, §17 D-18 | B-3.5 |
| Z-3 | Agent Task 评估集 | §15 V-14, §17 D-15 | C-3.5 |
| Z-4 | Book 空视图重建 | §17 D-18 | B-3.6 |
| Z-5 | Core 备份恢复演练 | §17 D-22 | C-0.5b |
| Z-6 | delivery_report 强制机制 | §16 EX-3 | A-0 |
| Z-7 | Wiki Query+Template 编译 | §12.4 R-7 | A-7 |
| Z-8 | Claim/Structured Fact 双路径 | §3.5 P-5 | C-4.5 |
| Z-9 | Raw Source sha256 延后 ADR | §3.3 P-3 | §6 文档 |

### 4.4 优化疏漏（已纳入）

| # | 优化 | 状态 |
|---|---|---|
| L-1 | 4 规范 subagent 并行 | ✅ A-5 注明 |
| L-2 | C-4 前置 schema 扫描 | ✅ C-4 注明 |
| L-3 | delivery_report.yaml | ⏸ 待办（沿用 spec §16，本路线不重复） |
| L-4 | 5 任务一次重建演练 | ⏸ 待办（路线回顾时检查） |
| L-5 | C-1 测试数升级 | ✅ H-5 决策 |
| L-6 | valid_from=None 显式 unknown | ✅ A-2 L-6 加固 |

---

## §5 不可妥协的纪律

| 约束 | 来源 | 触发动作 |
|---|---|---|
| 每任务 ≤ 3 新文件 + 2 改文件 | absorption v1 §防漂移 #2 | 超限立即停下 review |
| 单 commit 一个逻辑切片 | AGENTS.md §Git | 验证后再 commit |
| WikiPage frontmatter round-trip 兼容 | AGENTS.md §Things to know | 任何新字段必须有 `.get(key, default)` |
| 改 `src/server/` / `src/cli.py` / `src/wiki/` 顶层必跑 serve | AGENTS.md §Things to know | K-6 验证脚本 |
| LLM 调用新增必有 OFF-by-default 开关 | absorption v1 §防漂移 #5 | `RUFLO_XXX_ENABLED=false` 默认（H-3 例外：B-1 改为 ON） |
| Plan-audit 两轮 + 人工复核后才能进编码 | absorption v1 §0 | 本路线 v2 已完成两轮 + Route B 9 项决策 |
| KC v2.1 spec §14 的 A0-A9 Gate 是不可降级门槛 | spec §17 DoD | 不达标即"未完成" |

---

## §6 不在路线里的事（明确延后）

| 不做 | 原因 | spec 来源 | ADR |
|---|---|---|---|
| Plugin Manager / SDK / Marketplace | spec 明确延后 | §2.4 + 本路线显式不吸收 | — |
| 自动 Book Planner | 降级为 Outline Proposal Engine | §12.5 | — |
| YAML Workflow loader | 与 ponytail 极简冲突 | 本项目哲学 | — |
| Faithfulness Score 默认开启 | 改 ON by default（B-1）但保持 50 元/日上限 | 本路线 H-3 决策 | — |
| 入库评分 4 档 | 与 `quality_settings.json` 冲突 | 本项目现状 | — |
| 自动 Tag Proposal | `tags validate` 够用 | 本项目现状 | — |
| **Raw Source sha256 永久只读（Z-9）** | 当前 md5 + TTL 7 天覆盖 99% 去重需求；sha256 升级涉及 6749 文件 rehash，成本与收益不匹配 | §3.3 P-3 | `docs/adr/2026-08-26-raw-source-sha256-defer.md`（待写） |

### Z-9 Raw Source sha256 延后详情

**触发条件**（任意一个即重新评估）：
- 业务出现"raw source 需要追溯 6 个月前版本"需求
- KC 合规审计要求 Raw Source 内容寻址
- Phase 4 batch 19+ 出现 Raw Source 误覆盖事故

**后果**：spec §3.3 P-3 偏离状态将保留到上述触发条件成立

**路线显式标注**：progress.md 路线仪表盘加"P-3 偏离（已 ADR 延后）"指标

---

## §7 进度时间线（v2.2 含 Z + 4 项重大补位）

```
Week 1-2:   C-0 Frontmatter Schema 演进（4 commit）
Week 2:     C-0.5a Core 备份 API + C-0.5b 备份演练（Z-1 + Z-5）
Week 3-4:   C-1 Evidence + C-2 Default Filter + C-3 金标 29 case
            + C-3.5 Agent Task 评估集 ≥10 case（Z-3）
            + C-4 Mode 标签 + C-4.5 Structured Fact 双路径（Z-8）
Week 5:     A-0 delivery_report 强制机制（Z-6）+ A-5 命名规范 4 文档（并行 subagent）
Week 6-7:   A-1 KU 建模（dry-run + 3 选 1）+ A-2 Temporal + A-3 Conflict 6 类
Week 8:     A-4 Approval + dedup_auto 双模式 + A-7 Wiki Query+Template 编译（Z-7）
Week 9-10:  B-1 Semantic Support + B-2 11 Gate
Week 11:    B-2.5 identity_key 总验收（v2.2 重大补位 #1）
            + B-2.6 Knowledge Health Report（v2.2 重大补位 #2）
Week 12:    B-3 默认发布闭包（含 30 天过渡）
Week 13:    B-3.5 Wiki 重建演练（Z-2）+ B-3.6 Book 重建（Z-4，含 Outline Proposal Engine schema）
Week 14:    B-4 Publication Batch / 5 层水位
Week 15-16: B-5 100 金标完整 + A0 Gate 通过
            + B-5.5 连续 20 次批量演练（v2.2 重大补位 #3）
            + B-5.6 5 类端到端演化（v2.2 重大补位 #3 续）
```

**总工作量**：13-16 周（单人）+ 4 subagent 短任务并行

**v2.1 → v2.2 增加任务**：
- B-2.5 identity_key 总验收（+0.5 周，含 13 行字段统一校验）
- B-2.6 Knowledge Health Report（+0.5 周，spec §11 末尾）
- B-5.5 + B-5.6 显式拆 A9-7/A9-8（+1 周，spec §14 + §17 显式条款）
- A-1/A-3/B-2 内 resolution_event 4 字段（+0.3 周，并入现有任务）

**总增加**：~2.3 周（v2.2 比 v2.1 多 ~16%）

---

## §8 配套文档关系

```
本路线 v2（本文件）
    ↓ 替代
docs/superpowers/plans/2026-08-26-knowledge-compiler-absorption.md（v1，pending → deprecated）
    ↓ 并行
docs/superpowers/plans/2026-08-21-ruflo-to-knowledge-compiler-execution-plan.md
（A/C 完成、B 部分进行中，本路线 B 段不重复 B-04/B-05）
```

**与 execution plan 的合并决策**：
- B-01/B-02/B-03：路线 v2 不重复（execution plan 已有进度）
- B-04 Runtime/Registry：本路线不接（execution plan 延后）
- B-05 生产安全：本路线不接（execution plan 延后）
- 新增：B-3 默认发布闭包 / B-4 Publication Batch / B-5 100 金标

---

## §9 Definition of Done（路线 v2.1 完成）

- [ ] spec 21 对象覆盖率 ≥95%
- [ ] spec 11 Gate 全部实现且 spec §11.4 硬门槛全部阻止
- [ ] spec 16 指标全部可计算（分母 > 0）
- [ ] spec §14 A0-A9 Gate 全部通过
- [ ] spec §17 DoD 全部条件满足
- [ ] `.superpowers/sdd/progress.md` 路线仪表盘 7 项指标全部达标
- [ ] 6749 现有页面 verified_at backfill 完成或用户决策保留 legacy
- [ ] `_ko_extra` 4 类业务数据全部迁移完成，仅剩 provenance 保留
- [ ] 默认发布闭包上线 30 天过渡期通过
- [ ] 路线仪表盘 CI 校验通过
- [ ] **Z-1** Core 备份 API + restore 一致性验证
- [ ] **Z-2** Wiki 重建演练通过（删 wiki/ → rebuild → diff 一致）
- [ ] **Z-3** Agent Task Success Rate ≥0.85 + Citation Accuracy ≥0.95
- [ ] **Z-4** Book 空视图重建通过
- [ ] **Z-5** Core 备份恢复演练通过
- [ ] **Z-6** delivery_report.yaml CI 校验通过，所有 C/A/B 任务有交付报告
- [ ] **Z-7** Wiki 通过 Query+Template 编译（替换 1-page-per-source 路径）
- [ ] **Z-8** Claim/Structured Fact 双路径并存
- [ ] **Z-9** Raw Source sha256 ADR 留位（明确延后）
- [ ] **v2.2 补位 #1** B-2.5 identity_key 13 行字段一致性校验通过
- [ ] **v2.2 补位 #2** B-2.6 Knowledge Health Report 输出符合 schema
- [ ] **v2.2 补位 #3a** B-5.5 连续 20 次批量演练零重复 identity_key
- [ ] **v2.2 补位 #3b** B-5.6 5 类端到端演化（修正/撤回/Evidence 失效/Conflict 解决/supersede）符合金标
- [ ] **v2.2 补位 #4** resolution_event 必填 4 字段（规则版本/候选集/模型版本/输出理由）通过 fail-closed 测试

**最终判断问题**（沿用 spec §17 末尾）：
> 系统是否在不污染事实层的前提下，把外部信息转化成了 Agent 可可靠调用、可追溯、可更新的知识？

如果答案是"能由测试、固定数据集、审计事件和重建演练共同证明"，MVP 完成。

---

## §10 plan-audit 自审记录

### Round 1（已通过）：3 致命 + 6 重大 + 6 优化 = 15 项
### Round 2（已通过）：7 个失效路径加固
### 人工复核（Route B 9 项决策已确认）：✅
### v2.1 补位（新增）：9 项 Z 盲区 → C-0.5a/b, C-3.5, C-4.5, A-0, A-7, B-3.5, B-3.6 + Z-9 ADR
### v2.2 补位（基于 spec 映射审计）：4 项重大 + 3 项优化
- 重大 #1：B-2.5 identity_key 总验收（13 行字段统一校验）
- 重大 #2：B-2.6 Knowledge Health Report（spec §11 末尾 + §14 A5-8）
- 重大 #3：B-5.5 + B-5.6 显式拆 A9-7（20 次批量）+ A9-8（5 类端到端）
- 重大 #4：resolution_event 必填 4 字段（规则版本/候选集/模型版本/输出理由）— 散落到 A-1/A-3/B-2
- 优化 #5：Evidence `computation_provenance` / `structured_provenance` 字段扩展（C-1 + B-2）
- 优化 #6：Outline Proposal Engine schema（B-3.6）
- 优化 #7：指标 not_evaluable 标记（B-5）+ 阈值变更 ADR 模板（A-5）

**v2.2 覆盖度校验**（基于 spec 映射审计 254 项具体目标）：
- 总数 254 项
- 路线覆盖 247 项 (97.2%)
- 明确延后 7 项（Z-9 + spec §2.4）
- 通过 Gate 隐含实现 3 项（B-7 / R-18 / O-11）
- 实际可执行覆盖率 97.1%（与 v2.1 校正后一致）
- 路线 v2.2 进一步消除 4 项"声明覆盖但实际未落地"风险

下一步：等待用户对路线 v2.2 整体确认。

---

## §11 v2.2 增量变更清单（相对 v2.1）

| # | 类别 | 变更 | spec 来源 | 严重度 |
|---|---|---|---|---|
| 1 | 新增任务 | B-2.5 identity_key 总验收（13 行字段统一校验） | spec §5 表 + §14 A4-3 | 🔴 重大 |
| 2 | 新增任务 | B-2.6 Knowledge Health Report | spec §11 末尾 + §14 A5-8 | 🔴 重大 |
| 3 | 新增任务 | B-5.5 连续 20 次批量增量演练 | spec §14 A9-7 + §17 D-19 | 🔴 重大 |
| 4 | 新增任务 | B-5.6 5 类端到端演化演练 | spec §14 A9-8 + §17 D-20 | 🔴 重大 |
| 5 | 验收补位 | A-1 + A-3 + B-2 内显式约束 resolution_event 4 字段必填 | spec §9 执行规则末尾 | 🔴 重大 |
| 6 | 字段扩展 | C-1 Evidence dataclass 加 `computation_provenance` / `structured_provenance` | spec §5.7 + §6 E-5/E-14/E-15 | 🟡 优化 |
| 7 | 任务补充 | B-3.6 Book 重建任务加 Outline Proposal Engine schema | spec §12.5 + §14 A8-5 | 🟡 优化 |
| 8 | 任务补充 | B-5 加 `not_evaluable` 标记输出 | spec §15.3 末尾 | 🟡 优化 |
| 9 | 任务补充 | A-5 加 `docs/conventions/metric_threshold_change_adr.md` 模板 | spec §15.3 末尾 | 🟡 优化 |

**v2.1 → v2.2 总变更**：4 项重大补位 + 3 项优化（已合并到现有任务）+ 2 项新任务（实际是 B-2.5 + B-2.6 + B-5.5 + B-5.6 共 4 新任务，但 B-2.6 可视为 B-2 子任务）

**总任务数**：v2.1 的 20 项 → v2.2 的 22 项（+B-2.5 + B-2.6 + B-5.5 + B-5.6 四个明确独立任务）

**覆盖率**：254 项中 247 项映射 (97.2%)，4 项"声明覆盖但实际未落地"全部消除

**时间线**：13-16 周（v2.1 的 12-14 周 + 2.3 周）
