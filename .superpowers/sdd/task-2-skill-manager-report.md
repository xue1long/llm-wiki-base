# Task 2 实施报告：Library persistence and Agent discovery

日期：2026-09-13
范围：仅实现 `task-2-skill-manager-brief.md` 指定的 Library 持久化与 Agent 发现。

## 结果

- 新增 `SkillManagerStorage`：使用用户 `config_dir()/skill-manager`，按 Artifact、Deployment、manifest、operation 分开存储。
- 使用临时 JSON + `os.replace`，并通过跨线程/跨进程 manager lock 串行写入。
- 损坏 JSON 统一返回 `STATE_CORRUPT`；状态不猜测、不静默修复。
- 服务重启恢复 `queued/downloading/validating/installing` 为 `failed/server_restarted`。
- 新增 Codex/Claude 用户级默认目标、自定义目标边界校验和 `DeploymentMarker` round-trip。

## TDD 证据

### Red

先写 Task 2 测试后运行：

```text
$env:PYTHONPATH='.'; python -m pytest --import-mode=importlib tests/test_skill_manager/test_storage.py tests/test_skill_manager/test_agents.py -q
2 errors during collection: No module named src.skill_manager.storage / agents
```

### Green

实现后运行：

```text
$env:PYTHONPATH='.'; python -m pytest --import-mode=importlib tests/test_skill_manager -q
19 passed in 0.88s
python -m compileall -q src/skill_manager
PASS
```

## 边界

Task 2 不实现 Artifact 内容导入、部署复制、HTTP、CLI、WebUI、GitHub 或 Plugin 执行；这些留给后续任务。`AgentTarget` 只负责发现和路径校验，不能绕过 Task 3 的部署确认与 ownership 规则。

## Review

任务评审子任务超时后改为本地只读复核；`b8881fea` 范围符合 brief，无 Critical/Important 遗留。Windows `msvcrt.locking` 的同线程重入问题在 Task 3 集成时补为可重入层。
