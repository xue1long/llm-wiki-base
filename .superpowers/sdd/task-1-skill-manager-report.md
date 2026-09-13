# Task 1 实施报告：Skill domain contract and safe package inspection

日期：2026-09-13
范围：仅实现 `.superpowers/sdd/task-1-skill-manager-brief.md` 指定的 Task 1。

## 结果

Task 1 已完成。新增 `src.skill_manager` 深模块的最小领域契约和只读本地 Skill 包检查器，并根据任务评审补齐了安全边界：

- `SourceSpec`：来源定位，Task 1 只接受本地目录。
- `Artifact`：不可变的已验证 Skill 身份，身份由规范化内容 hash 派生。
- `Deployment`：不可变的 Artifact → Agent 目标部署记录类型；本任务不执行部署。
- `SourceInspection` / `FileEntry`：检查结果和确定性文件清单。
- `PackageValidationError`：带稳定 `code` 的拒绝错误。
- `inspect_source()`：只读检查和 hash 计算，不复制、不写 Library、不执行包内文件。
- `build_artifact()`：把检查结果转换为不可变 Artifact，不负责持久化。

## TDD 证据

### Red

先创建 `tests/test_skill_manager/test_package.py`，在任何实现文件存在前运行：

```powershell
$env:PYTHONPATH='.'; python -m pytest --import-mode=importlib tests/test_skill_manager/test_package.py -q
```

结果：

```text
ModuleNotFoundError: No module named 'src.skill_manager'
1 error during collection
```

这确认测试确实先于实现失败。

### Green

实现最小模块后，运行同一条聚焦命令：

```text
............                                                             [100%]
12 passed in 1.39s
```

覆盖内容：

1. Source / Artifact / Deployment 类型及冻结不可变性行为。
2. 合法 Skill 识别和根目录 `SKILL.md` 要求。
3. 相同内容、不同源目录得到相同 Artifact hash / artifact id。
4. 根目录和嵌套目录中的 `plugin.json` 均返回 `UNSUPPORTED_PLUGIN_TYPE`，不写 Library。
5. 公共包路径校验和越出 source root 的路径穿越拒绝。
6. 包内符号链接拒绝。
7. 单文件大小、总大小和文件数上限。
8. `.ruflo-skill-manager.json` 保留 marker 拒绝。
9. Source 与显式及默认 manager-owned root 重叠时拒绝，且包内脚本不会被执行。

## 静态验证

```text
python -m compileall -q src/skill_manager
compileall: PASS
whitespace: PASS
```

仓库环境中未安装 `ruff`，因此没有伪报 lint 结果；本任务未改变依赖配置。

## 变更文件

- `src/skill_manager/__init__.py`
- `src/skill_manager/types.py`
- `src/skill_manager/manager.py`
- `tests/test_skill_manager/test_package.py`
- 本报告文件

## 安全与实现说明

- 文件遍历固定排序，并将 POSIX 相对路径、文件大小和文件内容纳入 hash，避免源目录绝对路径影响身份。
- 源目录本身、目录项和文件项均拒绝符号链接；遍历不跟随链接。
- 对绝对路径、`..`、越出源根目录的路径统一返回 `PATH_TRAVERSAL`。
- marker 由后续 manager 独占生成，因此输入包携带 marker 时直接拒绝。
- Task 1 只读取和计算元数据；没有 `exec`、子进程、脚本解释器或安装动作。

## 风险与后续边界

- 当前 `Artifact` 只代表已验证内容及清单，还没有把内容复制到 Library；这属于 Task 2 / Task 3 的持久化与 import 实现。
- 当前只支持本地目录；GitHub、压缩包、commit pin、Claude target、HTTP、CLI、WebUI 和可执行 Plugin 均未实现，符合 brief 要求。
- 默认禁止 `config_dir()/skill-manager`，后续 Task 2 仍需把 staging 和 managed target 根目录显式接入 `forbidden_roots`，不能依赖调用方自行记忆。
- 当前使用默认的 5 MiB 总大小、1 MiB 单文件、256 文件限制；Task 2/3 若需要调整，应通过显式配置和测试变更，不能隐式放宽。
- 当前仅做 UTF-8 文本读取来解析可选的 frontmatter `name`；完整 frontmatter 合同不在 Task 1 范围内。

未实现后续任务。基础实现已提交为 `183d9996`，评审修复已提交为 `18bd9c49`。

## Fix round 1

评审发现并修复：嵌套 `plugin.json` 漏检、默认 Library root 未保护、总大小测试缺失、不可变性行为证据不足，以及路径校验只覆盖辅助参数。新增公共 `validate_package_path()`，由实际包文件收集路径调用；`inspect_source()` 默认拒绝用户配置目录下的 manager Library。

验证命令与结果：

```text
$env:PYTHONPATH='.'; python -m pytest --import-mode=importlib tests/test_skill_manager/test_package.py -q
12 passed in 1.39s
python -m compileall -q src/skill_manager
PASS
```

修复复审：5 个原始发现全部 `ADDRESSED`，未发现新的 Critical/Important；Task 1 可进入 Task 2。
