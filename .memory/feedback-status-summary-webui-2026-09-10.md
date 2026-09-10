# 状态汇总层接入 WebUI — 2026-09-10

- 新增只读接口 `GET /api/v1/projects/{project_id}/status-summary`，由 WebUI 适配层调用独立的 `src.status_summary`，不改摄取、KC、Wiki、Book 流程或 lineage 表结构。
- 状态页复用现有项目选择器，展示 RAW、KC、Wiki、Book 阶段计数和逐来源血缘状态；全局摄取队列仍单独展示。
- 浏览器响应隐藏项目绝对路径和数据库路径；缺失 lineage 数据库返回 `unavailable` 状态。
- 相关测试 16 个通过，JavaScript `node --check` 和 Python compileall 通过；当前环境没有可执行的 `ruff` 命令。
