# Project Memory Index

- [2026-09-09 Book LLM republish 加固](feedback-book-llm-republish-hardening-2026-09-09.md) — 严格章节对象契约、有限重试反馈、Provider/预算终止分类、实际调用点预算元数据与持久化大纲最低预算预阻断；`CURRENT.json` 继续 fail-closed
- [2026-09-09 novel-wiki Book 预算根因](feedback-novel-wiki-book-budget-root-cause-2026-09-09.md) — max_attempts 默认 3 与 pilot max_retries=1 不一致，3 次全局调用预算被重试耗尽；已统一默认值并通过 31 个相关测试

- [2026-09-08 功能分支合并方案整改](feedback-merge-plan-audit-2026-09-08.md) — 远端 main 动态冻结、干净 worktree 分批验证、Batch 4.1 元数据归属、squash 后整体回滚、Graphify 与代码合并解耦、Luna 并行审查上限 2

- [2026-09-08 Unified Book 管线整改](feedback-unified-book-remediation-2026-09-08.md) — plan 无正文/无 LLM，apply 验收证据先于 CURRENT 切换，实例规则缺失时 fail-closed

- [2026-09-07 Unified Book 真实 Provider 试读](feedback-unified-book-real-provider-pilot-2026-09-07.md) — MiniMax-M3 连通，但章节 JSON 解析未通过；修复 Provider 工厂 None 包装和嵌套 sidecar 路径校验，未发布

- [2026-08-18 标签规范化+确定性字段整改完成](feedback-tag-normalization-complete-2026-08-18.md)
- [2026-08-18 标签规范化整改](feedback-tag-normalization-2026-08-18.md)
- [2026-08-18 0xC0000142 复发](feedback-host-process-spawn-0xC0000142-recurrence-2026-08-18.md)
- [2026-08-18 系统架构审计](feedback-architecture-audit-2026-08-18.md)
- [2026-08-18 系统架构实测](feedback-system-architecture-2026-08-18.md)
- [2026-08-29 GBrain 兼容 Wiki 生产链路](feedback-gbrain-compat-2026-08-29.md)
- [2026-08-31 A8 Block 身份确定性](feedback-a8-stable-block-identity-2026-08-31.md)
- [2026-09-01 run_batch 拆分 + kc↔knowledge 边界重构实施交接](handoff-2026-09-01-batch-and-boundary.md) — read first when picking up the two approved plans
- [2026-09-01 batch crash 测试宿主隔离](feedback-batch-crash-test-host-2026-09-01.md)
- [2026-09-04 novel-wiki 质检修复完成 + 并行 risk-remediation 计划重叠](feedback-novel-wiki-quality-fix-2026-09-04.md) — 续跑 risk-remediation 计划前先读
- [2026-09-04 risk remediation Task 0/1](feedback-risk-remediation-task1-2026-09-04.md)
- [2026-09-05 Wiki-to-Book V3.2 安全整改 + V4 计划起草](feedback-wiki-to-book-v4-plan-2026-09-05.md) — 启动 wiki-to-book V3.2 编码或 V4 计划评审前必读
- [2026-09-06 Book 叙事化单章样例](feedback-book-narrative-sample-2026-09-06.md) — MiniMax sample and full-book gating decision
- [feedback-wiki-to-book-v4-implementation-2026-09-05.md](feedback-wiki-to-book-v4-implementation-2026-09-05.md) — V3/V4 implementation and acceptance evidence
- [feedback-wiki-to-book-boundaries-2026-09-05.md](feedback-wiki-to-book-boundaries-2026-09-05.md) — external ingest paths, lineage digest consistency, encyclopedic provider wiring
- [2026-09-06 书系整改 + 真实 baseline](feedback-book-series-target-baseline-2026-09-06.md) — 三本主教程真实 baseline 失败，全套 dry-run/旧指针/跨书安全门落地；pilot 与 reader-task 记录为 not-applicable
- [2026-09-06 Wiki 与 Book 产品用途评估](feedback-product-purpose-wiki-book-2026-09-06.md) — Wiki 是写作时检索的主产品；Book 仅作为有条件的专题学习发布层
- [2026-09-06 Unified Book rule-only pilot](feedback-unified-book-rule-pilot-2026-09-06.md) — 12 个真实页面/2 章 pilot 通过规则质量门，Book 策展允许只覆盖 Wiki 子集
- [2026-09-06 Unified Book implementation pass 2](feedback-unified-book-implementation-pass2-2026-09-06.md) — TutorialPath、结构化正文、stale/partial 发布保护、预算审计和最小 UI 已落地；758 KC tests passed
- [2026-09-06 Unified Book implementation pass 3](feedback-unified-book-implementation-pass3-2026-09-06.md) — 统一 LLM 调用预算、显式外部授权、敏感级别前置阻断、CURRENT 失败演练；762 KC tests passed
- [2026-09-06 Unified Book implementation pass 4](feedback-unified-book-implementation-pass4-2026-09-06.md) — 确定性 release acceptance 报告、统一 freshness 派生、自动门与人工批准分离；765 KC tests passed
- [2026-09-06 v2 → ruflo-kb 数据迁移决策锁定](feedback-v2-to-ruflo-migration-decisions-2026-09-06.md) — video-notes-wiki 实例 + capture 模板 + 5 重视频 ID 追溯 + D1-D8 全部默认建议；启动 PoC/Phase 1 编码前必读
- [2026-09-06 v2 迁移 Plan-Audit Round 1](2026-09-06-v2-to-ruflo-migration-audit-r1.md) — 3 致命 + 7 重大 + 9 优化；❌ 必须整改；根因是 V5 严格白名单不写 _ko_extra + ruflo-kb tag 强校验与 v2 不兼容
- [ADR-0008 V6 Wiki Schema 扩展](0008-v6-wiki-schema-extension-for-v2-migration.md) — 用户选路径 X；PR 1（V6 9 字段）+ PR 2（tag 命名空间）+ PR 3（migration tools）；修复 Round 1 致命缺陷 ①-1 + ①-2
- [2026-09-06 v2 迁移 Plan-Audit Round 1 综合报告](2026-09-06-v2-to-ruflo-migration-audit-r1-comprehensive.md) — 21 个问题（4 致命 + 8 重大 + 9 优化）；综合 subagent 深入审核，新增 ①-2 type 冲突 + ①-4 vector rebuild 不存在 + ②-1 slug_aliases 格式反向 + ②-7 capture marker 未实现；❌ 必须整改
- [2026-09-06 v2 迁移 Plan-Audit Round 2 压力测试](2026-09-06-v2-to-ruflo-migration-audit-r2-stress.md) — 12 失败路径 + 4 连锁 + 9 兜底 + 8 临界点 + 26 加固方案；⚠️ 需加固 8 项 P0 才能进入 Phase 0 PoC（5.25 天工作量）
- [2026-09-06 v2 迁移根因分析](2026-09-06-v2-migration-root-cause-analysis.md) — 21+26+26 问题中只有 3 项真架构缺陷（V5 白名单 + capture type + tag 不兼容），其他 23 项是实施细节/文档疏漏；方案**架构正确**
- [2026-09-07 Unified Book 主题分组安全整改](feedback-unified-book-theme-group-remediation-2026-09-07.md) — 修复一页一节退化；显式主题 section、来源闭包校验、章节级去重提示词；相关 33 测试 + 全部 KC 773 测试通过
