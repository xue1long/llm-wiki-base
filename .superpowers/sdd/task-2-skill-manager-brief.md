### Task 2: Library persistence and Agent discovery

- Files: `src/skill_manager/storage.py`, `src/skill_manager/agents.py`, `tests/test_skill_manager/test_storage.py`, `tests/test_skill_manager/test_agents.py`
- Test: 原子写入、损坏 JSON、用户配置目录、默认 Agent 发现、自定义路径越界和 marker round-trip。
- Acceptance: 无数据库；并发写入由 lock 串行；状态损坏 fail-closed；Artifact 与 Deployment 可分别读取；目标路径不会逃出允许根目录；服务重启后的遗留 operation 有明确 failed 状态。
- Status: pending

