### Task 3: Import, plan and compensating deployment

- Files: `src/skill_manager/sources.py`, `src/skill_manager/manager.py`, `tests/test_skill_manager/test_install.py`
- Test: 本地目录适配、Artifact hash 变化、import/deploy 分离、幂等部署、非托管冲突、托管内容冲突、安装失败恢复和 partial failure。
- Acceptance: import 不写 Agent；deploy 只接受已验证 Artifact；任何冲突不改目标；失败不伪报成功，必要时返回每个目标的补偿结果。
- Status: pending

