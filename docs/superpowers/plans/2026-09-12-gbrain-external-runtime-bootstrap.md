# GBrain 外部运行时发现与受控引导安装方案（历史草案）

> 本文已与项目级索引管理和 hybrid 搜索方案合并。后续以 [`2026-09-12-gbrain-hybrid-pilot-unified.md`](2026-09-12-gbrain-hybrid-pilot-unified.md) 为唯一实施入口；本文保留作为历史审计上下文。

状态：方案阶段，未进入编码  
目标：支撑“GBrain MCP 可选 hybrid 搜索试点”跨电脑运行，不依赖固定绝对路径。  
GBrain 默认仓库：`https://github.com/garrytan/gbrain.git`（2026-09-12 从当前 GBrain 工作树读取）。

## 1. 结论先行

可以实现，但不建议使用 Git submodule 作为主方案。

采用一个很小的“GBrain 外部运行时管理模块”：

```text
解析配置 → 探测已存在的 GBrain → 校验运行能力
                         ↓ 未找到/不可用
              用户显式确认后 clone + 安装 + smoke test
                         ↓ 失败
                    保持本地搜索可用
```

搜索请求本身不自动联网、不自动 clone、不自动执行依赖安装。自动拉取只发生在用户点击“安装/初始化 GBrain”或明确打开“允许自动安装”后。

## 2. 为什么不直接用 Git submodule

Git submodule 只能解决“代码跟着仓库走”，不能解决：

- Bun 与依赖是否已安装；
- GBrain 的 Brain 数据、source 和 embedding 配置；
- 用户机器上的 GitHub 网络权限；
- 项目目录只读、路径改变、多个 Ruflo 项目共用一个 GBrain；
- GBrain 版本升级、损坏恢复和本地搜索回退。

因此，Git submodule 可以作为开发者固定版本的可选方式，但不作为用户运行时的唯一安装机制。

## 3. 目录与配置

### 3.1 推荐目录

项目内优先使用：

```text
<ruflo-project>/
├─ external/
│  └─ gbrain/                 # 可选：项目自带/项目级运行时
├─ .llm-wiki/
│  └─ gbrain-runtime.json     # 稳定配置，不写机器绝对路径为主
└─ .index/
   └─ gbrain-runtime/
      └─ state.json           # 探测、版本、错误状态
```

共享安装位置使用操作系统用户目录，例如 Windows：

```text
%LOCALAPPDATA%\ruflo-kb\external\gbrain\<ref>/
```

GBrain 代码目录与 GBrain Brain 数据目录分离。`knowledge/` 只属于 Ruflo 知识库，不作为外部项目安装目录，也不把 GBrain 数据写入其中。

### 3.2 解析优先级

从高到低：

1. `.llm-wiki/gbrain-runtime.json` 中的 `path`；
2. `RUFLO_GBRAIN_HOME`；
3. 项目内 `external/gbrain`；
4. 项目内 `.external/gbrain`；
5. 用户级托管目录；
6. 仅当用户显式打开“允许使用 PATH 中的 GBrain”时，才检查 PATH 中的 `gbrain` 命令；默认不信任 PATH 中的同名可执行文件。

只扫描这些明确目录，不递归扫描整块磁盘，不根据目录名猜测任意可执行文件。配置中明确指定的路径如果存在但校验失败，应报告 `invalid_configured_runtime` 并停止解析，不得静默跳到另一份可能不是用户指定的 GBrain。

建议配置：

```json
{
  "enabled": false,
  "repository": "https://github.com/garrytan/gbrain.git",
  "ref": "<reviewed-tag-or-commit>",
  "install_mode": "managed",
  "project_relative_path": "external/gbrain",
  "auto_install": false,
  "source_map": {}
}
```

`project_relative_path` 可跨电脑复用；绝对 `path` 只作为本机覆盖项，不写入可提交配置。

## 4. 运行时校验

发现目录后必须校验，不以“目录存在”为成功：

1. 存在 `package.json`、`src/cli.ts` 和锁文件；
2. 可调用 `bun`；
3. `bun run src/cli.ts --version` 成功，并记录版本/commit；
4. `bun run src/cli.ts serve` 能完成 MCP initialize；
5. 对配置的 source 执行一次只读状态/搜索 smoke test；
6. 嵌入服务不可用时标记 `degraded`，不得伪装成 hybrid ready。

状态只允许：`missing`、`found`、`installing`、`ready`、`degraded`、`failed`。错误写入稳定错误码，不记录密钥、完整环境变量或查询正文。

## 5. 自动拉取流程

### 5.1 触发方式

提供 CLI 和 WebUI 两个入口：

```text
python -m src.cli gbrain runtime-status
python -m src.cli gbrain setup
python -m src.cli gbrain setup --install
```

WebUI 搜索页只显示状态和按钮：

- 未找到：`安装 GBrain`；
- 已找到但不可用：`修复/重新验证`；
- 可用但未启用：`开启 GBrain 搜索`；
- 已启用：显示 source、版本和健康状态。

### 5.2 安装步骤

1. 使用固定 allowlist 中的仓库 URL，默认只允许 `garrytan/gbrain`；自定义仓库必须在配置文件中显式设置并显示风险提示。
2. 让用户确认网络访问、代码下载和依赖安装。
3. 获取安装锁；同一项目或共享托管目录已有安装任务时复用/等待，不并发 clone 同一目标。
4. clone 到临时目录，不直接写入目标目录。
5. 校验仓库来源、目标 ref、关键文件和版本。
6. 若 Bun 不存在或版本不满足，停止并给出安装指引；不在本流程中隐式安装 Bun。
7. 执行锁文件约束的 `bun install`；默认优先使用不执行额外脚本的安全模式。
8. 运行 MCP initialize 与只读 search smoke test。
9. 全部成功后原子移动到托管目录，写入 `state.json`。
10. 任一步失败，删除本次临时目录并保留本地搜索；不得留下半安装目录被下次误判为 ready。

仓库校验至少包括：规范化 URL 必须匹配 allowlist、HEAD 必须等于 reviewed commit（或 reviewed tag 解析出的 commit），默认不拉取 Git submodule；若未来需要 submodule，必须单独审核其来源和锁定版本。

更新不是每次启动自动执行。升级必须走显式 `gbrain upgrade`，先预览 ref/版本变化，再下载到新目录，验证通过后切换；旧版本在新版本确认 ready 前保持可回滚。

## 6. 与搜索试点的关系

该模块只负责“找到并启动 GBrain”，不负责替代搜索服务：

- GBrain 可执行文件缺失：本地搜索；
- GBrain 版本不匹配：本地搜索并显示修复入口；
- MCP 启动失败/超时：本地搜索；
- embedding 不 ready：不得宣称 hybrid ready，默认本地搜索；
- source 映射缺失：本地搜索；
- 用户关闭 GBrain：本地搜索。

已有的 `src/wiki/features/gbrain_compat.py` 继续负责 Wiki path、slug、wikilink 和 relations 兼容，不把发现/安装逻辑塞进该文件。

## 7. 安全与运维门禁

- 子进程使用参数数组和 `shell=False`，禁止拼接 shell 命令；
- 默认仓库和 ref 必须可审计，禁止 WebUI 输入任意 URL 后直接执行；
- 不在搜索请求中隐式联网或安装；
- 不执行来源不明的安装脚本；需要脚本时必须单独提示并记录；
- `external/` 和托管运行时目录默认加入 `.gitignore`；
- GBrain 代码、Brain 数据、embedding 凭证分别管理；
- 安装失败可回滚到旧版本或本地搜索；
- 安装、升级、修复使用项目级/托管目录级锁，进程崩溃后通过临时目录和状态超时恢复；
- 日志只记录路径类别、版本、错误码、耗时，不记录 token/密钥/查询正文。

## 8. 最小实施任务

### Task 1：运行时契约与解析器

新增 `src/integrations/gbrain/`，对外只暴露 `api.py` / `types.py`：

- `resolve_runtime()`：按优先级找路径；
- `validate_runtime()`：检查文件、Bun、版本和 MCP；
- `runtime_status()`：输出脱敏状态；
- `setup_runtime()`：执行显式 clone/install/probe。

测试：路径优先级、相对路径跨机器、显式错误路径 fail-closed、目录伪装、PATH 同名程序、缺 Bun、错误 ref、配置损坏。

### Task 2：CLI 与配置持久化

新增 `runtime-status/setup/upgrade`，配置写入 `.llm-wiki/gbrain-runtime.json`，状态写入 `.index/gbrain-runtime/state.json`。

测试：dry-run、用户拒绝、断网、clone 中断、安装失败、重复 setup 幂等、并发 setup、进程崩溃恢复、旧版本保留。

### Task 3：接入现有 GBrain 搜索 Adapter

将 Adapter 的启动目录从固定绝对路径改为 `resolve_runtime()` 结果；仍保留 source 显式映射、超时、错误回退和默认关闭。

### Task 4：WebUI 状态与显式初始化

搜索页增加状态卡和按钮，但不把首次搜索变成安装触发器。按钮 API 返回任务状态，前端轮询状态；安装期间搜索继续走本地。

### Task 5：真实跨机器验收

至少验证三种环境：

1. 项目内已有 `external/gbrain`；
2. 项目内没有 GBrain，但用户级托管目录已有；
3. 两处都没有，显式安装后自动 clone、安装、MCP initialize、搜索成功。

同时验证：断网、拒绝安装、错误版本、embedding 不可用、旧版本回退和本地搜索不受影响。

## 9. 验收标准

- 运行时代码中不再依赖 `D:\5-Project\gbrain-master` 等绝对路径；
- 项目移动到另一台电脑后，使用项目相对目录可自动发现；
- 没有 GBrain 时，用户显式确认后可完成 clone/install/probe；
- 搜索页面从不因 GBrain 缺失而崩溃或卡死；
- 安装/升级失败后不产生半安装 ready 状态；
- GBrain 不 ready 时，100% 请求可回退本地搜索；
- 搜索请求本身不触发网络下载或依赖安装；
- 所有路径解析、失败回退、版本校验和真实 MCP smoke test 有自动化证据；
- 真实 GBrain embedding ready 后，才允许开启 hybrid 开关。
- 两个安装请求同时到达时最多产生一份目标运行时，不能出现互相覆盖的半成品。
- 配置路径存在但不是经过校验的 GBrain 时，系统必须 fail-closed 并继续本地搜索。

## 10. 方案边界

本方案解决“GBrain 代码在哪里、如何安全启动”的问题，不自动解决：

- GBrain embedding 服务部署；
- GitHub 不可访问时的离线安装包分发；
- GBrain Brain 数据跨电脑迁移；
- 多个 Ruflo 项目共用同一 GBrain source 的权限治理。

这些属于后续运维/数据治理问题，不能通过路径探测器假装解决。

## 11. 进入编码前的 P0 门禁

以下条件全部满足才进入编码：

1. 确认 GBrain 的 reviewed ref/tag，而非跟随浮动 `master`；
2. 确认目标机器允许 GitHub clone、Bun 安装和 MCP 子进程；
3. 提供不敏感的 Ruflo fixture，验证真实导入、source 映射和搜索；
4. 为 embedding 配置可达服务，并通过 100% coverage 的 readiness 检查；
5. 先完成运行时 resolver/setup 的单元测试和一次真实安装 smoke test。

网络不可用或用户拒绝安装时，验收结果必须是“安装未完成但本地搜索仍可用”，不能把自动下载当作系统启动必需条件。

在这些条件未满足前，可以实现“发现/状态/本地回退”，但不应实现自动导入 `knowledge/` 或把 GBrain 标记为 hybrid ready。
