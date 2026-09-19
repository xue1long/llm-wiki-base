# ADR Index

记录本项目的重大架构决策。每条 ADR 一旦落地不可删除,只能通过新 ADR 推翻。

| ID | 标题 | 状态 | 日期 | 关联 plan |
|---|---|---|---|---|
| [2026-08-19-llm-kb-design-absorption](2026-08-19-llm-kb-design-absorption.md) | 从 LLM_Knowledge_base_v2 吸收 wiki 设计 | Proposed — plan-audit 四轮完成,所有致命缺陷 + 重大隐患已整改,待人工复核后进编码 | 2026-08-19 | [plan](../superpowers/plans/2026-08-19-llm-kb-design-absorption.md) |
| [2026-08-26-ku-split-strategy](2026-08-26-ku-split-strategy.md) | KU 拆分策略（路线 v2.2 §A-1 决策矩阵） | Proposed | 2026-08-26 | [plan](../superpowers/plans/2026-08-26-kc-spec-roadmap.md) §A-1 |
| [2026-09-06-unified-book-editorial-state](2026-09-06-unified-book-editorial-state.md) | Book 编辑状态为权威、TutorialPath 为阅读覆盖层 | Proposed | 2026-09-06 | [plan](../superpowers/plans/2026-09-06-unified-knowledge-book-remediation.md) |
| [2026-09-07-book-lineage-publication](2026-09-07-book-lineage-publication.md) | Book 发布结果登记到 SQLite lineage | Accepted | 2026-09-07 | — |
| [2026-09-08-unified-book-llm-pipeline](2026-09-08-unified-book-llm-pipeline.md) | 统一 Wiki-to-Book LLM 编译管线与项目级编辑规则 | Accepted | 2026-09-08 | [plan](../superpowers/plans/2026-09-08-unified-book-llm-pipeline.md) |
| [2026-09-13-provider-settings-portability](2026-09-13-provider-settings-portability.md) | Provider 设置页按目标架构移植 | Proposed | 2026-09-13 | — |
| [0010-skill-library-and-agent-deployment](0010-skill-library-and-agent-deployment.md) | Skill Artifact Library 与 Agent 部署隔离 | Accepted — v1 静态 Skill | 2026-09-13 | [plan](../superpowers/plans/2026-09-13-skill-plugin-manager.md) |
| [0012-v7-knowledge-reconciliation-plane](0012-v7-knowledge-reconciliation-plane.md) | V7 Knowledge Reconciliation Plane 设计 | Proposed | 2026-09-15 | — |
| [0015-v7-stage2-tail-residue-classification](0015-v7-stage2-tail-residue-classification.md) | V7 Stage 2 用 TAIL_RESIDUE 显式分类替代改 I5 容差 | Accepted | 2026-09-19 | [plan](../superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md) |

## 命名规范

- 文件名:`YYYY-MM-DD-<slug>.md`
- 状态:`Proposed` (初稿) → `Accepted` (实施完成) → `Superseded by <新 ADR>` (被推翻)
- 每条 ADR 必含:Context / Decision / Consequences / Alternatives / References

## 模板

新 ADR 草案请复制 [`_template.md`](_template.md)（含 Context / Decision / Rationale / Consequences / Trigger to Revisit / Alternatives / References / Implementation Notes 八个标准字段）。
