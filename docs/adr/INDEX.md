# ADR Index

记录本项目的重大架构决策。每条 ADR 一旦落地不可删除,只能通过新 ADR 推翻。

| ID | 标题 | 状态 | 日期 | 关联 plan |
|---|---|---|---|---|
| [2026-08-19-llm-kb-design-absorption](2026-08-19-llm-kb-design-absorption.md) | 从 LLM_Knowledge_base_v2 吸收 wiki 设计 | Proposed — plan-audit 四轮完成,所有致命缺陷 + 重大隐患已整改,待人工复核后进编码 | 2026-08-19 | [plan](../superpowers/plans/2026-08-19-llm-kb-design-absorption.md) |
| [2026-08-26-ku-split-strategy](2026-08-26-ku-split-strategy.md) | KU 拆分策略（路线 v2.2 §A-1 决策矩阵） | Proposed | 2026-08-26 | [plan](../superpowers/plans/2026-08-26-kc-spec-roadmap.md) §A-1 |

## 命名规范

- 文件名:`YYYY-MM-DD-<slug>.md`
- 状态:`Proposed` (初稿) → `Accepted` (实施完成) → `Superseded by <新 ADR>` (被推翻)
- 每条 ADR 必含:Context / Decision / Consequences / Alternatives / References

## 模板

新 ADR 草案请复制 [`_template.md`](_template.md)（含 Context / Decision / Rationale / Consequences / Trigger to Revisit / Alternatives / References / Implementation Notes 八个标准字段）。