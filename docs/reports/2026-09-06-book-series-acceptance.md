# 书系目标设计实施验收报告

日期：2026-09-06
分支：`codex/book-series-target`

## 验收范围
整改版目标：三本主教程 + 一个参考库；规则版默认；主教程允许受控 LLM 草稿；页面只保留一个 canonical 归属；旧 release 可读；失败只影响 staged release。

## 已落地链路
- Task 0：数据门与 `rule_only` fail-closed。
- Task 1：series/book manifest、状态与哈希/依赖契约，legacy 匿名兼容。
- Task 2：页面唯一 primary/chapter 归属、重复/无来源/冲突挂账。
- Task 3：卷章纲 schema、快照绑定、页面唯一归属校验。
- Task 4：叙事/百科模式、LLM preflight、证据与质量门。
- Task 5：章节来源、关系统计、跨书链接与阅读辅助。
- Task 6：连续学习链样例与 CLI dry-run/apply 保护。
- Task 7：WebUI Book 书系下拉、状态显示、三栏阅读与错误降级。

## 验证证据
定向书系/编译/服务/CLI/关系回归：`122 passed`。
Task 2 页面归属定向：`6 passed`；Task 4 模式与质量门：`33 passed`；Task 6 样例与 CLI：`15 passed`。
全仓 pytest 未通过：测试环境缺少 `mcp` 依赖，阻塞于 `tests/test_mcp_server/conftest.py` 导入，未把该环境问题误报为实现失败。
前端改动已执行 `git diff --check`；未引入新依赖。

## 故障场景验收
- 一本候选失败：Task 0 决策为 `cancel/reference`，系列不得伪造 ready。
- hard 参考库缺失或非 ready：manifest validator 进入失败门。
- series/outline/body/sidecar 哈希不匹配：服务返回不可用错误，旧指针不变。
- legacy release 缺少 series_id：以匿名单书读取，保留合法状态，不暴露旧 run_id。
- 空/未知/无来源/重复/跨书冲突页面：进入 assignment ledger，不进入主教程正文。
- LLM provider 缺失、敏感外发 preflight 失败、响应截断或证据无效：回退规则版或阻断 apply。

## 结论
整改后的核心目标已具备可执行实现，规则版与旧兼容链路可验证；完整发布仍需在安装 `mcp` 后补跑全仓测试，并在真实项目上完成 3–5 章 pilot 与人工读者任务验收后才允许正式 `--apply`。
