# novel-wiki 写作知识库整改优化实施方案

> **Revision:** v3（必须整改版）。v1 因目标、证据和状态边界不足被否决；v2 又因把首轮验证扩展成完整治理平台而被判定为过度工程化。本版只保留证明写作知识库有效所必需的整改。

## 1. 目标与边界

**目标：** 在真实写作任务中验证 novel-wiki 是否能让作者更快找到可采用的知识，并降低无效判断。

**首轮只证明四件事：**

1. 页面能区分“可执行知识”和普通资料。
2. 生成器不会为了数量制造低价值页面。
3. Wiki 与 Vector 的基本同步状态可判断。
4. 作者在真实问题中能找到并采用有效结果。

**本轮不做：** 全量 gap 清债、完整用途 taxonomy、synthesis 自动刷新、Book 联动、复杂索引快照、完整数据治理和多级全量发布。

**保留的不可删边界：** raw 只读；派生页写入原子；迁移和小批试运行可回滚；失败状态不能伪装成成功状态。

方案依据：[`purpose.md`](../../../knowledge/novel-wiki/purpose.md)、[`schema.md`](../../../knowledge/novel-wiki/schema.md)、[`novel-wiki-ingest-spec.md`](../../../docs/guides/novel-wiki-ingest-spec.md) 和 [`retrieval-contract.md`](../../../docs/architecture/retrieval-contract.md)。

## 2. 最小验收标准

任一必须条件不满足，首轮不放行常规摄取：

1. 实际写盘合同与文档一致：字段、时间格式、tags 来源和旧页面兼容边界均可复核。
2. 正式写作检索只返回带 `用途/可执行` 的页面；该标记必须有人工审核记录，未标记页面自动排除。
3. Generator 不再要求固定下游页面数量；没有证据和写作价值时可以只写 source 或不写下游页面。
4. `ready` 至少能反映 pending、失败、页面内容 hash 与 Vector 内容 hash 是否一致；不 ready 时，默认写作语义检索不返回语义结果，显式 keyword 模式仍可用。
5. 使用 15 个真实写作问题、5 个负例和 3–5 次作者任务完成首轮评测：正例至少 12/15 在 Top-5 找到可执行结果，负例至少 4/5 不返回可执行结果，作者任务至少 3/5 在两次查询内找到可采用答案。
6. raw 没有被删除；迁移、批处理和索引修复失败时均能停止并回滚或留下明确的未完成状态。

这些阈值只用于首轮 go/no-go，不代表生产质量上限。通过后是否扩充样本，依据失败类型和真实使用量决定。

## 3. 任务总览

| 任务 | 目的 | 结果 |
|---|---|---|
| Task 0 | 统一实际写盘合同，建立单份基线 | 已完成：合同和基线报告 |
| Task 1 | 让人工确认成为“可执行知识”的唯一入口 | 已完成：用途标记和可回滚迁移 |
| Task 2 | 去掉固定页面数量，复用现有知识模型 | 已完成：按证据生成页面 |
| Task 3 | 建立最小 Wiki/Vector 可用状态 | 已完成：可判断 ready / not ready |
| Task 4 | 用真实问题和作者任务验证价值 | 已完成：首轮评测报告（限定写作索引） |
| Task 5 | 小批试运行并作一次放行决定 | 已完成：canary 报告和受限 go/no-go |

所有代码任务沿用项目既有 TDD、定向测试和单逻辑 commit 约束；不新增第三方依赖，不修改 raw，不执行未经授权的删除。

## Task 0：统一写盘合同和基线

**Files:**

- Inspect: `src/wiki/core/types.py`
- Inspect: `src/wiki/storage/page_writer.py`
- Inspect: `docs/guides/wiki-spec.md`
- Inspect: `docs/architecture/novel-wiki-fields-template-2026-08-31.md`
- Modify only if mismatch is confirmed: the smallest affected implementation or document
- Create: `docs/reports/2026-09-11-novel-wiki-remediation-baseline.md`
- Test: reuse the nearest existing Wiki serialization and writer tests; add one focused regression test only when the mismatch is reproducible

**Steps:**

1. 对 `to_frontmatter_dict()`、`write_page()`、V4/V5 文档和真实页面样本做对照，记录允许字段、时间格式、tags 来源和 legacy 兼容边界。
2. 如果文档与实现冲突，先统一一处真实合同；不在本任务中扩展字段或重做 schema。
3. 在同一份 Markdown 报告中记录项目路径、Git commit、输入文件 hash、扫描命令和当前基线：页面数、用途标记覆盖、vector pending、断链和写盘版本。
4. 连续运行两次，确认报告的核心计数在同一 corpus 下稳定。

**Acceptance:** 合同冲突已经解决或明确列为阻断项；报告可重复生成；raw 未被修改。

## Task 1：人工确认可执行知识

**Files:**

- Modify: `knowledge/novel-wiki/purpose.md`
- Modify: `knowledge/novel-wiki/schema.md`
- Modify only if required: `knowledge/novel-wiki/.wiki-templates/concept.md`, `entity.md`, `synthesis.md`
- Modify: `src/wiki/features/tag_namespace.py`
- Modify: `src/wiki/features/review.py`
- Modify only if required: `src/wiki/core/types.py`
- Create: `scripts/migrate_page_usage.py`
- Test: `tests/test_wiki/test_tag_namespace.py`, `tests/test_wiki/test_review.py`, `tests/test_scripts/test_migrate_page_usage.py`

**Contract:**

- 只增加 `用途/可执行` 一个受控标签。
- 有该标签的页面必须存在人工审核记录：`page_id`、`reviewer`、`decision`、`decided_at`。
- 没有该标签的页面不进入默认写作检索；不再为首轮建立 `用途/参考` 和 `用途/案例` 两个额外分类。
- Generator 和 Analyzer 永远不能直接写入 `用途/可执行`。

**Steps:**

1. 先写标签唯一性、人工记录必填和模型越权失败测试。
2. 为存量页面提供 dry-run 清单；默认不授予可执行标记。
3. 只有人工审核后才 apply；迁移前保留页面快照，失败可回滚。
4. 复用现有 review 持久化结构；只增加完成人工决策所必需的字段，不增加 suppression 期限、完整审核工作流或第二套状态系统。

**Acceptance:** 新旧页面均能明确区分可执行集合；模型输出不能绕过人工确认；迁移失败不会改变 raw。

## Task 2：按证据生成页面，删除数量下限

**Files:**

- Modify: `src/pipeline/generator.py`
- Modify: `src/pipeline/analyzer.py` only if needed to stop direct actionable tagging
- Modify: `src/pipeline/ingest.py` only if needed to remove the quantity assumption
- Reuse: existing `KnowledgeCandidate.knowledge_mode`
- Test: existing generator/ingest tests plus one focused candidate regression test

**Behavior:**

- 删除“每个 raw 至少生成 1 个 source 和 2 个 entity/concept”的硬性要求。
- source、concept、entity 的既有来源和标题规则保持不变。
- 没有证据支持的内容可以只产生 source；没有可提炼知识时不产生下游页面。
- 生成器写入的页面不得带 `用途/可执行`；人工审核前保持未标记或普通资料状态。
- 不新增 `candidate_use` 和六个候选字段，避免与现有 `knowledge_mode` 并存。

**Acceptance:** 短背景资料不会凭空生成多个下游页面；有证据的写作知识仍能进入审核队列；数量不再作为质量指标。

## Task 3：建立最小 Wiki/Vector ready 状态

**Files:**

- Modify: `src/vector/pending.py`
- Modify: `src/services/search.py`
- Modify: `src/searcher/hybrid_search.py` only to honor the requested mode and current status
- Modify: `src/server/routes/search.py` only to expose the status outcome
- Test: `tests/test_vector/test_pending.py`, `tests/test_server/test_service_search.py`, and one search mode regression test

**Minimal state:**

使用现有 pending ledger，并在其现有状态数据中记录或计算：

- Wiki 页面内容 hash；
- 对应 Vector 内容 hash；
- 当前 embedding model 身份；
- pending / failed / unavailable 状态。

不新增删除集合、chunker 版本、row count、复杂 manifest 或多阶段发布协议，除非现有实现已经提供这些字段。

**Behavior:**

- `ready` 仅在没有 pending/failed、页面和 Vector hash 一致且 embedding model 一致时为真。
- 不 ready 时，默认写作 `hybrid` / `vector` 检索返回空结果和诊断状态；显式 `keyword` 仍可用。
- `mode` 必须真正传入底层搜索，不得只在返回值中回传。
- 默认写作检索只过滤 `用途/可执行` 页面。

**Acceptance:** Wiki 更新后未完成 Vector 发布时不会被误报为可用；失败状态不会被计入 ready；状态可通过测试和搜索响应解释。

## Task 4：用真实写作问题验证结果

**Files:**

- Reuse an existing evaluation runner if available; otherwise create `scripts/evaluate_writing_retrieval.py`
- Create: `docs/evaluation/writing_retrieval_cases.yaml`
- Create: `tests/test_searcher/test_writing_retrieval_evaluation.py`
- Modify: `docs/architecture/retrieval-contract.md` only for the minimal mode and acceptance contract
- Create: `docs/reports/2026-09-11-writing-retrieval-report.md`

**Evaluation:**

1. 由熟悉目标题材和写作流程的人编写 15 个真实写作问题和 5 个负例/应拒答问题。
2. 每个问题记录 expected actionable page、证据来源、是否应 abstain；不要求第三方仲裁和完整标注体系。
3. 用同一批问题分别运行当前基线和整改后结果，记录 commit、corpus hash、查询模式和结果来源。
4. 完成 3–5 次作者任务，记录查询次数、是否找到可采用答案、完成时间和采用/拒绝原因。

**Acceptance:**

- 15 个正例中至少 12 个在 Top-5 出现可执行结果；
- 5 个负例中至少 4 个不返回可执行结果；
- 3–5 个作者任务中至少 3 个在两次查询内找到可采用答案；
- provenance 对每个被采用结果可追溯；
- 报告明确样本量小，不能把首轮结果包装成普遍质量证明。

## Task 5：canary、回滚和一次放行决定

**Files:**

- Modify only if current shared writer lacks the guard: `src/wiki/storage/page_writer.py`
- Modify only if current rollback path lacks the guard: `scripts/rollback_batch.py`
- Reuse: existing batch executor, atomic writer, snapshot and pending mechanisms
- Test: nearest existing writer, rollback and batch executor tests; add only the missing failure regression
- Create: `docs/reports/2026-09-11-novel-wiki-remediation-final.md`

**Steps:**

1. 运行 3–5 个 raw canary，覆盖普通资料、可执行候选和案例素材三类输入。
2. 记录生成页面数、人工确认结果、pending、ready 状态、检索结果和作者任务结果。
3. 模拟一次写入失败或进程中断，确认 raw 未变、派生页不会半写入、pending 状态可继续处理或明确回滚失败。
4. 只做一次 go/no-go 判断；未通过则停在 canary，不自动扩大到 20、100 或全量。

**放行条件:** Task 0–4 的必须验收全部通过，且没有未解释的 raw 变更、写入失败或 ready 误报。放行后仍不自动开启全量摄取，由后续真实使用数据决定是否扩充评测和治理范围。

## 4. 延后事项

以下内容不进入本轮实施，只有真实失败证据出现后再单独立项：

- `用途/参考`、`用途/案例` 完整 taxonomy；
- 全量 gap、alias、namespace、路径和 stub 清理；
- 删除集合、chunker、row count 和复杂 snapshot manifest；
- 持久化 digest、immutable registry 和完整损坏恢复体系；
- synthesis 依赖闭包、冲突条件和刷新脚本；
- Book 输入过滤和联动验收；
- 50/15 大样本评测、双人标注、第三方裁决；
- 20/100/全量多级 rollout。

## 5. 方案状态与完成证据

**当前状态：** Task 0–4 已完成；Task 5 的 3 个真实 raw canary 通过，失败注入后可续跑恢复；全库普通资料仍有 1206 个 pending，因此只受限放行当前写作索引，不启动全量摄取。最终报告见 [`2026-09-11-novel-wiki-remediation-final.md`](../../reports/2026-09-11-novel-wiki-remediation-final.md)。

**完成证据：**

- 一份可重复的写盘合同与基线报告；
- 一份可回滚的用途迁移结果；
- 生成器无固定数量下限的回归测试；
- ready / not ready 和搜索 mode 的回归测试；
- 15+5 检索报告与 3–5 次作者任务记录；
- canary 报告、失败演练结果和一次 go/no-go 决策。

**不作为完成证据：** 页面数量、synthesis 数量、Book 编译成功、gap 总数下降或 lint 通过率单独上升。
