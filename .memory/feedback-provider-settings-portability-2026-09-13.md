# Provider 设置页移植边界

- 日期：2026-09-13
- 决策：不直接复制 `D:/5-Project/open-design` 的 React/TypeScript 设置页和 Node daemon 后端；本项目首期继续使用原生 JS、FastAPI、全局 `ProviderRegistry`。
- 首期范围：完善当前 Provider 设置页，支持 CRUD、默认 Provider、后端保存且接口掩码 API Key、保存后的连接测试；字段保持精简，不暴露 timeout/headers/body。
- 后续：实时模型发现作为独立功能，放在方案最后阶段。
- 依据：两个项目的前端技术栈、API 契约、配置作用域、密钥持久化和 Provider 协议集合均不一致；可复用交互意图和预设，不应整页复制。
- 复审整改：补充了 explicit default / legacy env 五态解析矩阵、API Key 缺省/null/空字符串三态、不可变且路径安全的 Provider name、preset 与 canonical type 分离、测试只按名称从 Registry 读取、隐藏字段保留、default_error 和后端删除保护。
- 状态：本次只修改 ADR/上下文文档，尚未修改业务代码；两轮 plan-audit 压力场景覆盖后，方案可进入编码。
