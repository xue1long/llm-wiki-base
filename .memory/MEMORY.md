# Project Memory Index

- [2026-09-14 V7 extract Stage 4–7 实施](feedback-v7-extract-stages4-7-2026-09-14.md) — 主题聚类/概念去重、五槽位填充、关系抽取、checkpoint+retry 写盘和 source→concept 审计均已落地；V7 `46 passed, 2 skipped`，pipeline `658 passed, 2 skipped`

- [2026-09-14 V7 extract Stage 1/3 收尾](feedback-v7-extract-completeness-2026-09-14.md) — 修复 doc_classifier fixture/filename hint 回归；新增 completeness checker 与测试；V7 `32 passed, 2 skipped`，pipeline `644 passed, 2 skipped`

- [2026-09-13 Agent Skill Manager 方案整改](feedback-skill-plugin-manager-plan-2026-09-13.md) — `Source→Artifact→Deployment→Agent`；v1 仅本地静态 Skill、Codex 首发、JSON CLI/HTTP/WebUI 共用核心；plugin.json 拒绝、显式确认、loopback/token、补偿回滚与 partial_failure
- [2026-09-13 Skill Manager Task 1 实施](feedback-skill-manager-task1-2026-09-13.md) — 本地静态 Skill 只读检查、稳定 hash、plugin.json/marker/路径穿越/符号链接/大小和文件数门禁；9 个聚焦测试通过

- [2026-09-12 GBrain 增强项修复](feedback-gbrain-enhancements-repair-2026-09-12.md) — 逐项完成 job 路径兼容、manifest 新鲜度、删除墓碑恢复、运行时检查缓存；GBrain restore 只传 slug，专项回归 61 passed

- [2026-09-12 GBrain 控制面实现记录](feedback-gbrain-control-plane-implementation-2026-09-12.md) — 运行时发现/校验、显式 setup、原子状态落盘已实现；搜索与导入等待 embedding 门禁

- [2026-09-12 GBrain Hybrid 统一方案](../docs/superpowers/plans/2026-09-12-gbrain-hybrid-pilot-unified.md) — 合并外部运行时发现/安装与项目级索引/hybrid 搜索；runtime ready → index ready → hybrid，缺失/失败始终 local fallback
- [2026-09-12 GBrain 外部运行时引导安装方案](feedback-gbrain-external-runtime-bootstrap-plan-2026-09-12.md) — 不采用 Git submodule 作为唯一方案；项目/用户级目录发现 + 显式确认 clone/install + reviewed ref + 原子切换 + 本地搜索回退；两轮审计通过设计门禁
- [2026-09-12 GBrain P0 真实能力验证](feedback-gbrain-p0-capability-validation-2026-09-12.md) — CLI/stdio MCP/批量导入/基础源隔离通过；嵌入覆盖率 0%，MCP put_page 被 Ollama 连接失败阻断，P0 未通过；测试源已清理
- [2026-09-12 GBrain MCP 可选 hybrid 搜索试点](feedback-gbrain-mcp-search-plan-2026-09-12.md) — 目标已从全量替代收敛为默认本地、显式开启、失败回退的 hybrid 试点；显式 project→source 映射；实施计划见 docs/superpowers/plans/2026-09-12-gbrain-mcp-search-adapter.md
- [2026-09-12 GBrain 项目级索引管理试点方案](feedback-gbrain-managed-index-pilot-plan-2026-09-12.md) — 每项目独立 source；CLI 初次导入 + MCP 增量/搜索；异步 durable job、snapshot reconcile、ready gate、关闭回退 local；方案已完成两轮审计和整改后复审
- [2026-09-12 GBrain 项目级 hybrid 试点多角度审计](feedback-gbrain-managed-index-pilot-multi-angle-audit-2026-09-12.md) — 六角度综合 6/10；CLI/MCP 双路径一致性、reconcile 状态机、MCP 写权限/会话模型、绝对质量和成本门槛仍是 P0/P1；建议先做最小 MVP
- [2026-09-12 GBrain MCP 搜索替代方案审计](feedback-gbrain-mcp-search-audit-2026-09-12.md) — 四角度审计结论不通过；缺同步闭环、真实结果契约、chunk→Wiki path 映射和 readiness 顺序，当前只能作为可选 hybrid 试点

- [2026-09-10 novel-wiki Book 4 项收益全部落地](feedback-novel-wiki-book-readability-shipped-2026-09-10.md) — A 目录分桶 / B 章名 / C preface / D 写作技法 77→7 主题章 均已 WebUI 实测 PASS；含 3 条落地路径、8 个坑（中文码点陷阱、write_text 换行符、outline sha 同步、--apply 默认 pilot 覆盖 baseline）
- [2026-09-11 novel-wiki 写作知识库整改方案 v3](feedback-novel-wiki-remediation-v3-2026-09-11.md) — 按 Ponytail 必须整改项将方案从 656 行压缩为 218 行，保留 6 个必要任务，延后完整治理、synthesis/Book 联动和多级 rollout
- [2026-09-11 novel-wiki Task 5 canary 与恢复](feedback-novel-wiki-task5-2026-09-11.md) — 3 个真实 raw canary 通过；写入失败可见、raw 不变、续跑恢复；修复 LanceDB 删除返回值和相对 root lineage reservation；全库 pending=1206，限写作索引受控放行

- [2026-09-10 novel-wiki Book 可读性整改 rollout 执行](feedback-novel-wiki-book-rollout-2026-09-10.md) — 实践中发现 3 个脚本 bug + 1 个 rollout guide 缺漏 (默认 scope=pilot 覆盖了 179-chapter baseline); 修复 + 回滚 baseline + Task 0 (53 个真名卷) 全部生效；Task 3/4 部分生效，full_knowledge rebuild 待行
- [2026-09-10 novel-wiki Book 可读性整改 (4 Task + rollout)](feedback-novel-wiki-book-readability-2026-09-10.md) — 发现 outline `: ` vs `_ ` key lookup 漏判 (Task 0 关键 bugfix,179/179 填上 volume_id) + 8 大真名章节重组 + 12 测试 + 351 行 rollout 文档;操作员可跑 LLM apply 完成
- [2026-09-10 novel-wiki 全量 Book 发布](feedback-novel-wiki-fullbook-published-2026-09-10.md) — `full_knowledge` 范围 179 章节全部 complete，release `f728939909c44bdf9d7efb6e26760c9d` 已切换 CURRENT，6 次 resume 累计约 132 次 MiniMax 调用
- [2026-09-10 状态汇总层接入 WebUI](feedback-status-summary-webui-2026-09-10.md) — 新增只读项目状态 API、状态页项目选择和 RAW/KC/Wiki/Book 生命周期面板；16 个相关测试通过

- [2026-09-10 v2 → ruflo-kb 迁移执行](feedback-v2-migration-execution-2026-09-10.md) — 并行实现并完成内容迁移、哈希与 H1/H2/H4/H5 验收；向量重建待 embedding provider

- [2026-09-09 novel-wiki Book 重新发布](feedback-novel-wiki-book-republish-2026-09-09.md) — MiniMax preview/apply 均在 4 次上限内，2 次实际调用；release `e3843bfbbc8343bab5c4ef63964c1801` 已切换 CURRENT，manifest 哈希回读一致
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
- [2026-09-09 Book preview → promotion 实施](feedback-book-preview-promotion-2026-09-09.md) — `--apply-from` 复用同一 preview release、人工审批非阻塞、预算前置估算、vector 状态拆分；完整 KC/CLI 回归 836 passed
- [2026-09-09 Book 章节响应契约修复](feedback-book-response-contract-repair-2026-09-09.md) — MiniMax `list[str]` 响应触发形状感知重试反馈；仍保持 fail-closed provenance 校验
- [2026-09-09 Book 发布完成](feedback-book-release-2026-09-09.md) — preview release `5aa755f...` 自动验收通过并经 `--apply-from` 发布；LanceDB 独立未更新
- [2026-09-13 GBrain Claude Code 外部 Host 试点](feedback-gbrain-claude-host-pilot-2026-09-13.md) — 路线 B 真实 MCP 门禁通过；受限 recall/search/get_page/remember 桥接、项目 scope、来源校验和 local/auto/gbrain 后端已落地；GBrain 跨 Claude 会话记忆闭环通过，Claude/MCP 常驻 session 仍后置
- [2026-09-13 Provider 设置页移植边界](feedback-provider-settings-portability-2026-09-13.md) — open-design 设置页不可直接复制；本项目首期保留原生 JS + FastAPI + 全局 ProviderRegistry，模型发现后置
- [2026-09-13 Agent Skill Manager v1 实施](feedback-skill-plugin-manager-plan-2026-09-13.md) — 静态 Skill Library、Artifact/Deployment 分离、HTTP/JSON CLI、Settings Skills 页已落地；插件/GitHub/更新删除后置，真实 Codex 目标仍需冒烟
