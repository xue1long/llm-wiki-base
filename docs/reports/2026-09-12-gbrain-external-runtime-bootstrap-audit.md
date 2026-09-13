# GBrain 外部运行时引导安装方案审计

审计对象：`docs/superpowers/plans/2026-09-12-gbrain-external-runtime-bootstrap.md`  
审计方式：第一轮全面漏洞审计 → 方案整改 → 第二轮压力测试 → 整改后复核  
审计结论：**方向可行，具备进入实现设计的条件；仍需在编码前锁定 reviewed ref/commit 和测试 fixture。**

## 1. 第一轮全面漏洞审计

| 等级 | 漏洞位置 | 失败场景与后果 | 整改 |
|---|---|---|---|
| 重大 | 运行时路径优先级 | 配置路径损坏后静默采用另一份 GBrain，可能连接错误 Brain/source | 明确配置路径校验失败时 fail-closed，不静默换源 |
| 重大 | PATH 探测 | 恶意或过期的同名 `gbrain` 被优先启动 | PATH 仅在用户显式允许时检查，默认不信任 |
| 重大 | Git ref | `master` 内容变化导致未审计代码进入运行时 | 必须使用 reviewed tag/commit，并校验 HEAD |
| 重大 | 安装目标 | 安装中断留下半目录，下次被误判为可用 | 临时目录 + 安装锁 + 原子移动 + 状态机 |
| 重大 | 并发安装 | 两个 WebUI 请求同时 clone/install，互相覆盖或破坏 node_modules | 项目/托管目录级互斥锁，重复请求复用或等待 |
| 重大 | 依赖安装 | Bun 缺失或 install script 执行失败使首次安装卡死 | Bun 作为前置依赖显式校验；默认限制安装脚本并报告明确错误 |
| 重大 | 网络与供应链 | GitHub 断网、仓库改名、DNS/代理异常导致 setup 失败 | 固定 allowlist、超时、错误码、本地搜索回退；不把 setup 当启动必需 |
| 重大 | 配置注入 | 配置写入任意 Git URL 或任意本地可执行目录 | 默认只允许 canonical repo；自定义必须显式配置并提示；运行时完整校验 |
| 优化 | 数据边界 | GBrain 代码、Brain 数据、embedding 凭证混在项目目录，迁移/备份误传 | 三者分离，`knowledge/` 不作为外部运行时目录 |
| 优化 | 状态一致性 | state 显示 ready 但 MCP/embedding 实际不可用 | ready 必须包含版本、MCP initialize、source/search smoke test；embedding 不可用只能 degraded |

上述问题均已写入方案整改，未保留需要靠运行时猜测的关键行为。

## 2. 第二轮压力测试

| 压力路径 | 预期反应 | 兜底判定 |
|---|---|---|
| 用户拒绝网络安装 | setup 结束为 cancelled，搜索继续 local | 覆盖 |
| 没有 Git | setup 失败并给安装指引，不触碰知识库 | 覆盖 |
| 没有 Bun | setup 失败并给安装指引，不隐式安装 Bun | 覆盖 |
| GitHub 不可达 | 临时目录清理，状态 failed，搜索 local | 覆盖 |
| clone 到错误仓库 | allowlist/HEAD 校验失败，不能变 ready | 覆盖 |
| ref 指向浮动 master | P0 配置拒绝，必须 reviewed ref/commit | 覆盖 |
| 安装进程被杀 | 下次发现锁/临时目录，清理后可重试；旧版本不丢失 | 覆盖，需测试证明 |
| 两个 setup 同时触发 | 一个执行，另一个等待/复用，不覆盖目标 | 覆盖，需测试证明 |
| 目标目录只读 | setup 失败，显示可选用户级托管目录，搜索 local | 覆盖 |
| 本地目录被伪装 | 关键文件、origin、HEAD、MCP probe 任一失败则 fail-closed | 覆盖 |
| GBrain 启动但 embedding 不可用 | 标记 degraded，禁止 hybrid ready，搜索 local | 覆盖 |
| MCP 超时/协议变更 | 单次 probe 失败，保留旧版本或 local fallback | 覆盖 |
| 搜索期间首次安装 | 不允许隐式触发安装，搜索不被阻塞 | 覆盖 |
| WebUI 关闭/刷新 | setup job 状态持久化，后台结束后可回读；未完成不标 ready | 部分覆盖，需实现测试 |

## 3. 整改后复核

### 已消除的 P0 设计缺口

- 不再依赖 `D:\5-Project\gbrain-master`；
- 不把 GBrain 代码当作本项目 Git submodule 的唯一来源；
- 不在搜索请求中隐式下载、安装或执行远程代码；
- 不以目录存在判断可用，必须经过版本和 MCP probe；
- 不把失败的外部依赖变成本地搜索不可用；
- 不允许浮动版本和未审计仓库进入 ready 状态；
- 不允许并发安装产生半成品 ready 状态。

### 进入编码前仍必须确认的事实

1. 选择并记录 GBrain reviewed tag/commit；当前已确认仓库 URL，但尚未锁定生产 ref。
2. 明确目标机器的 Git、Bun 和网络前置条件；本方案不隐式安装 Bun。
3. 提供不敏感的 Ruflo fixture，验证真实 source、slug、路径映射和 embedding。
4. 设计 WebUI 异步 setup job 的状态 API；本方案只规定行为，不伪造实现细节。

## 4. 最终审计结论

方案通过“设计级 P0 审计”，但不等于功能已实现，也不等于 GBrain 已在所有电脑可安装。编码前门禁是：reviewed ref/commit、真实 embedding、非敏感 fixture、安装失败回退和并发/中断测试全部具备证据。
