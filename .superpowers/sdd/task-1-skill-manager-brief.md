### Task 1: Domain contract and safe package inspection

- Files: `src/skill_manager/__init__.py`, `src/skill_manager/types.py`, `src/skill_manager/manager.py`, `tests/test_skill_manager/test_package.py`
- Test: 先写 Source/Artifact/Deployment 类型、Skill 识别、`plugin.json` 拒绝、路径穿越、符号链接、大小/文件数限制和稳定 hash 测试。
- Acceptance: 非法包在写入 Library 前失败；相同输入得到相同 Artifact hash；不执行包内文件；出现 `plugin.json` 返回 `UNSUPPORTED_PLUGIN_TYPE`；保留 marker 和 source 自包含均被拒绝。
- Status: pending

