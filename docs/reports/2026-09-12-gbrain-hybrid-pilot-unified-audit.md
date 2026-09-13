# GBrain Hybrid 统一方案合并审计

审计对象：`docs/superpowers/plans/2026-09-12-gbrain-hybrid-pilot-unified.md`  
结论：**合并结构成立；可作为唯一编码入口，但必须先满足文档中的 P0 门禁。**

## 合并后重点检查

| 检查项 | 结果 | 说明 |
|---|---|---|
| 运行时发现与搜索启用顺序 | PASS | runtime ready → source/index ready → hybrid |
| 未安装 GBrain 的跨机路径 | PASS | 项目目录、用户目录、显式安装均有路径 |
| 自动安装副作用 | PASS | 搜索不触发；只由 setup/用户确认触发 |
| 代码、Brain 数据、凭证边界 | PASS | 三者分离，不写入 `knowledge/` |
| 初次导入与增量同步 | PASS | CLI 初次导入，MCP 增量，reconcile 保最终一致 |
| 关闭/失败回退 | PASS | local fallback、stale、kill switch、旧版本回滚 |
| source/path 隔离 | PASS | 项目独立 source、manifest 映射、ownership 检查 |
| 版本与供应链 | CONDITIONAL | 必须补齐 reviewed tag/commit 和真实安装证据 |
| embedding/hybrid 真实性 | CONDITIONAL | 必须配置可达 embedding 并验证 100% coverage |
| WebUI 异步生命周期 | CONDITIONAL | 实现时必须证明 setup/enable 不阻塞搜索且可恢复 |

## 仍需重点防范的 8 个失败场景

1. 显式路径存在但不是 GBrain：必须 fail-closed，不能切换到另一份代码。
2. 两个 setup 同时触发：必须由锁和幂等 job 保证最多一份正式运行时。
3. clone/install 中断：临时目录可清理，不能写出 ready 状态。
4. reviewed ref 被错误配置为 `master`：必须在配置校验阶段拒绝。
5. GBrain 运行时 ready 但 embedding 不可用：只能 degraded/local，不能进入 hybrid。
6. source 已存在但不属于当前项目：不得自动接管，必须停止并提示修复。
7. MCP 返回字段变化：严格 schema 校验，整批回退 local。
8. 关闭后旧 job 完成：通过 `config_epoch` 防止远程状态回写 ready。

## 放行结论

方案已经把“依赖发现/安装”和“项目索引/搜索”串成一个明确的门禁链，未发现新的结构性致命缺陷。进入编码前仍不可省略：reviewed ref/commit、真实 embedding、无敏感 fixture、安装 smoke test，以及并发/中断/失败回退测试。
