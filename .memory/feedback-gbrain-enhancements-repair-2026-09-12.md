# 2026-09-12 GBrain 增强项修复

- 低成本增强项逐项修复并单独提交：job 路径兼容、同步新鲜度字段、删除墓碑/恢复同步、运行时 ready 检查 30 秒进程内缓存。
- GBrain `restore_page` 只接受 `slug`；恢复流程必须先发送无 content 的 restore，再发送带 Markdown 的 put_page。该边界已增加回归测试。
- `get_runtime_status` 只缓存 ready 且路径仍存在的结果；installing/failed/路径消失继续实时验证，搜索任务仍执行独立运行时校验。
- 外部 GBrain 的 `sources status --json` 字段是 `embed_coverage_pct`；真实 MCP 协议版本为 `2025-06-18`，运行时版本 `0.42.58.0`。
- 当前专项回归为 61 passed；未执行外部数据库导入或写操作。
