# ruflo-kb 文档导航（INDEX）

> **维护状态**：2026-08-03 由「文档 ↔ 代码」逐项核验后整理。本页所列「规范 / 评估 / 方案」类文档均已与实际代码核对一致。
> **项目真名**：`ruflo-kb` v2.0.0（仓库目录为 `LLM-Wiki`）。
> **真相源原则**：知识库内容的唯一真相源是磁盘上的 Markdown 文件；代码中的 `wiki_rules_prompt.py` 由 `scripts/sync_wiki_spec.py` 从 `guides/wiki-spec.md` 自动生成（禁手改）。

---

## 一、快速上手（先看这三份）

| 文档 | 一句话用途 |
| --- | --- |
| [project-brief.md](project-brief.md) | 项目一页纸：真名/版本、28 个 CLI 子命令、10 个核心依赖、本地优先架构 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 完整架构：CLI / HTTP API / MCP / Web UI → Services → 摄取 → WikiPage → 派生索引 |
| [guides/wiki-spec.md](guides/wiki-spec.md) | 内容规范真源：Frontmatter 字段、8 类页面类型、标签受控命名空间 |
| [guides/module-map.md](guides/module-map.md) | 模块地图：33 个顶层包分层 + 接线状态（✅已接线 / 🟡已写好未接线） |

---

## 二、规范与约束（开工 / PR 评审前必读）

- [CONSTRAINTS.md](CONSTRAINTS.md) — 编码规范、禁用技术栈、Wiki 输出格式（含**真实标签 API 表**与值域约束）。
- [wiki-template-field-guide.md](wiki-template-field-guide.md) — 模板字段填写指南（历史文档）。

---

## 三、核心模型与流程（写给要改代码的人）

- [guides/wiki-model-overview.md](guides/wiki-model-overview.md) — **WikiPage 数据模型**：18 字段、8 类 PageType、Relation 关系模型、标签、序列化互转。
- [guides/ingest-pipeline-overview.md](guides/ingest-pipeline-overview.md) — **摄取流程全景**：采集 → 预过滤 → 分析 → 生成 → 质量治理五件套 → 提交落盘 → 索引 + 报告 + 指标。

---

## 四、评估与方案（决定做什么、怎么做）

- [evaluations/tag-namespace-evaluation.md](evaluations/tag-namespace-evaluation.md) — 标签系统现状评估（结论：前缀受控 + `TAG_VALUES` 值域已接线但**覆盖不全**）。
- [evaluations/semantic-taxonomy-feasibility.md](evaluations/semantic-taxonomy-feasibility.md) — STS（语义分类系统）方案可行性（建议演进而非新建）。
- [evaluations/audit-2026-08-03-semantic-taxonomy-plan.md](evaluations/audit-2026-08-03-semantic-taxonomy-plan.md) — STS 执行计划审计。
- [superpowers/plans/2026-08-02-ingest-pipeline-completion.md](superpowers/plans/2026-08-02-ingest-pipeline-completion.md) — 摄取流程完善方案（接线 KOS 组件、补全覆盖值域强制）。
- [superpowers/plans/2026-08-03-wiki-spec-sync.md](superpowers/plans/2026-08-03-wiki-spec-sync.md) — wiki-spec 与代码同步方案 v2.0（决策门 G0/G1/G2 已裁决）。
- [superpowers/plans/2026-08-02-knowledge-os-evolution.md](superpowers/plans/2026-08-02-knowledge-os-evolution.md) — KOS 演进方案（原方案）。
- [KNOWLEDGE_OS_EVOLUTION_FEASIBILITY_REPORT.md](KNOWLEDGE_OS_EVOLUTION_FEASIBILITY_REPORT.md) — KOS 演进可行性报告。
- [guides/structure-optimization-proposal.md](guides/structure-optimization-proposal.md) — **项目结构优化方案**（4 agent 深读全量模块后综合：接线断裂 / 页面类型矛盾 / 死代码 / 分层 / 分阶段迁移）

---

## 五、信任锚点（文档 ↔ 代码核验报告）

> 这层是「证明上面的文档没骗你」——都经过实测代码核对，并记录了已纠正过的系统性误判（如 `MANDATORY_PAIRS` 实际非空、`TAG_VALUES` 已接线）。

- [evaluations/constraints-consistency.md](evaluations/constraints-consistency.md) — 重新校验 `CONSTRAINTS.md`：揪出 §3.4 三处会让开发者报错的 API 错误 + 4 处行号偏差。
- [evaluations/project-brief-consistency.md](evaluations/project-brief-consistency.md) — 校验 `project-brief.md`：整体一致，含 D1（CLI 数 21→28）与 D2（值域强制措辞）修正记录。
- [evaluations/wiki-spec-consistency.md](evaluations/wiki-spec-consistency.md) — `wiki-spec.md` 与当前代码一致性核验。
- [evaluations/wiki-spec-sync-audit.md](evaluations/wiki-spec-sync-audit.md) — 同步方案的独立第三方批判审计（发现 F1/F2 致命缺陷）。
- [evaluations/meta-audit-2026-08-03.md](evaluations/meta-audit-2026-08-03.md) — 元审计（对审计流程本身的复盘）。

---

## 六、技术债务

- [TECH_DEBT_CHECKLIST.md](TECH_DEBT_CHECKLIST.md) — 17 项技术债务清单（含 #11 前缀说明文案重复、页面类型三套矛盾等）。

---

## 七、其他历史文档（本批未重校，备查）

- **历史方案计划**：`superpowers/plans/`（40+ 份，按日期前缀，2026-07-xx 为主）。
- **前端设计**：`web-design-proposal.md`、`web-design-execution-plan.md`、`superpowers/FRONTEND_DESIGN.md`。
- **能力 / 架构报告**：`project-capabilities-report.md`、`codebase-graph-report-2026-07-27.md`、`design-doc-driven-pipeline.md`。
- **摄取 / 接入规格**：`guides/novel-wiki-ingest-spec.md`、`guides/adding-llm-provider.md`。
- **Bug 记录**：`bug/`、`search-browse-bug-report.md`。

---

## 八、使用建议（组合姿势）

1. **让 AI 改代码前** → 先读 `CONSTRAINTS.md`（边界）+ 对应评估 / 方案（范围），避免无依据发挥。
2. **做重构 / 新功能前** → 读 `tag-namespace-evaluation` / `semantic-taxonomy` / `ingest-pipeline-completion` 确定方案与优先级。
3. **怀疑某文档过时了** → 拿**第五节核验报告**当标尺重新核对，而不是凭记忆；代码改动后回这些报告看哪里该同步。
4. **要改 wiki 内容规范** → 改 `guides/wiki-spec.md` 真源，再跑 `scripts/sync_wiki_spec.py` 重新生成代码侧提示词（勿手改生成物）。
