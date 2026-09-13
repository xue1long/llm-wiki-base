# ADR: Provider 设置页按目标架构移植

- **状态**: Proposed
- **日期**: 2026-09-13
- **触发**: 评估是否将 `D:/5-Project/open-design` 的设置页“模型与提供商”前后端直接复制到本项目。

## Context（背景）

`open-design` 使用 React/TypeScript 前端、Next/Node daemon、BYOK 配置和另一套 Provider API；本项目使用原生 JS、FastAPI、全局 `ProviderRegistry`，两者在 API 契约、配置作用域、密钥持久化和协议集合上均不一致。目标项目已有 Provider 设置页和 Provider CRUD/测试接口，因此本次目标是补齐契约和闭环，不是搬运另一套运行时。

## Decision（决策）

不直接复制 `open-design` 的 React/TypeScript 设置页、Node daemon 路由或 BYOK 配置模型。本项目继续使用原生 JS、FastAPI 和全局 `ProviderRegistry`，首期完善 Provider CRUD、默认 Provider、接口掩码凭据、保存后的连接测试和重启持久化。

Provider 配置和显式 default 的持久化真源只有 `ProviderRegistry`。设置页、CLI、Agent、Pipeline、Book 和其它运行入口必须通过同一套 default resolver；任何调用者不得自行读取 `RUFLO_LLM_PROVIDER` 或配置文件来决定默认 Provider。resolver 规则如下：

1. Registry 存在显式 default 且指向已注册 Provider：使用它。
2. Registry 存在显式 default 但目标不存在：报告配置错误并停止，不静默回退。
3. 没有显式 default 且 `RUFLO_LLM_PROVIDER` 指向已注册 Provider：作为旧环境兼容 fallback 使用。
4. 没有显式 default 且旧环境值指向不存在 Provider：报告配置错误，不静默选择其它 Provider。
5. 显式 default 和旧环境值都不存在：保持 Registry 现有的 legacy fallback 顺序（字面名称 `default`、持久化 Provider、首个 Provider）；没有 Provider 时报告无可用 Provider。

设置页设置默认时只调用 `ProviderRegistry.set_default()` 写入 JSON 显式 default，不再写入 `env` 文件。旧 `RUFLO_LLM_PROVIDER` 只读作兼容 fallback，不迁移、不反写、不提升为显式 default。CLI 等现有双写入口也必须收敛到同一规则；已有 `env` 文件不由本次功能自动删除。

## Contract（首期契约）

### 字段和更新语义

首期字段只保留：名称、类型、Preset、Base URL、API Key、默认聊天模型、默认嵌入模型。Preset 只存在于设置页交互，不落库。

| 字段 | 创建时缺省 | 更新时缺省 | `null` | 空字符串 |
|---|---|---|---|---|
| `name` | 必填，非空且路径安全、唯一 | 必填且必须等于原名称 | 拒绝 | 拒绝 |
| `type` | 必填 | 保留原值 | 拒绝 | 拒绝 |
| `base_url` | 空值允许，按类型默认值处理 | 保留原值 | 拒绝 | 显式清空 |
| `chat_model` | 空值允许 | 保留原值 | 拒绝 | 显式清空 |
| `embedding_model` | 空值允许 | 保留原值 | 拒绝 | 显式清空 |
| `api_key` | 缺省/空值表示未配置 | 缺省/空值表示保留旧值 | 拒绝 | 保留旧值 |

Provider 名称是不可变身份。当前按名称测试、删除和更新；编辑页不得改名，也不引入 rename 行为。更新接口必须区分“缺省、null、空字符串”，避免双模型表单或旧客户端造成非预期覆盖。

名称由后端统一 trim 和校验，不得包含 `/`、`\\`、控制字符或空白名称；同名更新才是更新，不同名必须视为新 Provider，不得隐式改名。

设置页未暴露的既有字段（`models`、`timeout_seconds`、`extra_headers`、`extra_body` 及未来兼容字段）在首期作为后端不透明数据保留；普通字段更新不得因重建 `ProviderConfig` 而丢失它们。

### Type 与 Preset 映射

canonical type 遵循目标项目已有 `ProviderRegistry`/provider factory：`openai`、`openai-compatible`、`anthropic`、`ollama`。OpenAI、Anthropic、Ollama 预设映射到对应 canonical type；MiniMax、Kimi、DeepSeek、GLM 只作为 UI preset，最终映射为 `type=openai-compatible` 加对应 Base URL/默认模型。四个品牌不新增后端 Provider 类型，Preset 不写入 Registry。

### API Key 安全语义

HTTP 列表和详情只返回固定掩码 `***` 或空字符串，不返回明文。更新请求中的 `***` 明确视为非法掩码回写并拒绝；前端留空表示保留旧密钥。本期不提供清除已有密钥的交互。保存、测试及错误展示不得将明文 API Key 写入响应、日志或错误详情；“接口掩码”不等同于磁盘加密，当前继续沿用本项目用户级配置的存储模型。

### Save → Test 与删除保护

保存成功和连接测试成功是两个独立状态。测试接口只接受 Provider name，服务端每次从 `ProviderRegistry` 重新读取完整配置，不接受临时 API Key、Base URL、type 或 model 覆盖。测试失败不回滚已保存配置，UI 必须明确显示“已保存、测试失败”。缺少连接测试所需聊天模型时，测试应返回可识别的配置错误，不能伪装成网络成功或静默使用另一个模型。

Provider 列表在 default resolver 成功时只标记实际解析到的 Provider；resolver 失败时仍返回 Provider 列表，但不标记任何 Provider，并返回可展示的 `default_error`。设置页不得在解析失败时自行猜测默认项；依赖有效 default 的删除操作必须失败并保留配置不变。

删除当前有效 default 必须由后端拒绝，而不只依赖前端禁用按钮；default 解析异常时也不得通过删除操作静默绕过配置错误。

## Rationale（理由）

复用交互意图和 Provider preset 即可获得目标项目的产品价值；直接复制会把另一套前端框架、运行时和配置语义一起引入，增加迁移风险且不能复用目标项目现有后端。

## Consequences（后果）

- 首期改造范围集中在当前原生 JS 设置页、Provider API、default resolver 和 Registry 配置语义。
- 全局 Provider 适用于当前用户级本地配置；暂不引入项目级覆盖。未来进入多用户/共享服务场景时，必须重新评估密钥隔离和配置作用域。
- API Key 继续由后端保存，列表/详情接口只返回掩码，更新时留空表示保留原密钥。
- 设置页首期不承担远端模型目录发现；该能力必须作为后续独立接口和交互评估。
- Provider default 模型字段与未来远端模型目录分离；模型发现不得改写用户显式 default，除非另行设计确认。

## Alternatives Considered（备选方案）

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 直接复制 `open-design` 前后端 | 视觉和交互可能更接近参考项目 | 技术栈、API、配置作用域和密钥语义不兼容 | ❌ 不采用 |
| 只复制前端组件 | 可复用部分交互 | React/TypeScript 组件不能直接接入原生 JS，且仍依赖另一套 API | ❌ 不采用 |
| 按目标架构重做首期闭环，吸收交互和 preset | 改动最小、可测试、与现有 ProviderRegistry 一致 | 需要重新实现页面绑定和接口细节 | ✅ 采用 |

## References（参考）

- `D:/5-Project/open-design/apps/web/src/components/SettingsDialog.tsx`
- `D:/5-Project/open-design/apps/daemon/src/routes/chat.ts`
- `D:/5-Project/open-design/packages/contracts/src/api/providerModels.ts`
- `src/server/routes/providers.py`
- `src/llm/registry.py`
- `src/agent/runtime.py`
- `src/cli_ext/book_cmd.py`

## Implementation Notes（实施笔记）

- 验收链路：添加 → 编辑 → 掩码回显 → 留空保留旧密钥更新 → 设默认 → 连接测试 → 删除非默认项 → 重启后仍存在。
- 必须补充 resolver 的五态矩阵测试：显式有效、显式悬空、legacy env 有效、legacy env 悬空、两者缺失。
- 必须验证 Settings API、Registry、Agent、Pipeline、Book 的实际 Provider resolution 一致；不接受只测设置页响应。
- 最低限度覆盖 `src/agent/runtime.py`、`src/pipeline/__init__.py`、`src/research/runner.py`、`src/server/ready.py`、`src/llm/embed_profile.py`、`src/cli_ext/book_cmd.py` 和 `src/kc/views/book/wiki/preflight.py` 等现有解析入口，消除调用者自行读取环境变量或配置文件的分叉。
- 必须补充 API Key 的 create/update 三态测试、不可改名测试、双模型非破坏更新测试、preset canonical 映射测试、后端 default 删除保护测试及保存/测试失败分离测试。
- 旧 JSON 缺少显式 default 字段时必须可读可保存，不丢失已有字段；旧 `env` 文件不得被自动删除。
- 本 ADR 只确定移植边界，不代表实时模型发现已经实现。
