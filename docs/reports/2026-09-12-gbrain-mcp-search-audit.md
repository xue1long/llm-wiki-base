# GBrain MCP 搜索替代方案审计报告

审计对象：`docs/superpowers/plans/2026-09-12-gbrain-mcp-search-adapter.md`

审计目标：判断该方案能否达成原始目标——“通过 MCP 调用 `D:\5-Project\gbrain-master` 的 gbrain，替代本项目的搜索功能”。

审计方式：第一性原理、批判性思维、终局思维、系统思维四轮交叉审查；包含漏洞审计和失败压力测试。

原始替代目标审计状态：**不通过，不得按“替代方案”直接进入编码。**

目标修订状态：用户已将目标收敛为“GBrain MCP 可选 hybrid 搜索试点”。按新目标，方案方向**有条件可行**，但当前文本仍须完成 P0/P1 整改后才能进入编码或灰度。

## 一、结论摘要

### 最终判断

**按原始目标衡量：当前方案不能达成。**

当前方案可以作为一个“可回退的 GBrain hybrid 搜索试点”，但它把原始目标从“替代本项目搜索”缩小成了：

> 仅在 `hybrid`、无类型过滤、数据已经同步且 path 可闭环时，尝试调用 GBrain；失败时继续用本地搜索。

这是一种安全的接入方案，但不是完整替代方案。原始目标至少还缺少数据同步/所有权、结果语义等价、全模式覆盖和最终切换门禁。

### 评分

| 维度 | 得分 | 判断 |
|---|---:|---|
| MCP 传输接入可行性 | 7/10 | gbrain 确实提供 stdio MCP `search`，本项目也已有 MCP SDK |
| 当前方案可编码性 | 5/10 | 主流程清楚，但真实结果契约和路由位置仍有断点 |
| 安全回退能力 | 7/10 | 有显式映射、超时和本地回退方向，但缺少熔断/并发控制 |
| 搜索结果兼容性 | 3/10 | gbrain 是 chunk 结果，本项目是 Wiki 文件结果；path/content/filter 尚未闭合 |
| 数据一致性与新鲜度 | 1/10 | 方案没有同步和删除传播方案 |
| 对原始“替代”目标的完成度 | 3/10 | 只覆盖部分 hybrid 请求，且始终保留本地搜索 |
| **总体放行结论** | **不通过** | 可作为试点草案，不能作为替代实施方案 |

## 二、已核实的事实

### 本项目

- `src/server/routes/search.py` 暴露 `POST /api/v1/projects/{project_id}/search`。
- `src/services/search.py` 支持 `hybrid`、`keyword`、`vector` 三种模式。
- 服务层会先执行本项目自己的 `vector_readiness(...)`；语义搜索未 ready 时，直接返回空结果，不进入 `hybrid_search(...)`。
- 语义结果会经过 `_filter_actionable(...)`；该过滤器需要根据结果的 `path` 读取本地 Wiki frontmatter，并检查 `用途/可执行` 标签。
- `page_type` 过滤同样依赖本地 Wiki 文件和 frontmatter。
- 当前本项目已有 `mcp==1.28.1`，MCP server 位于 `src/mcp_server/`，但它目前是本项目 HTTP API 的 MCP 包装，不是 GBrain client。

### gbrain

- `src/mcp/server.ts` 的 stdio 入口由 `gbrain serve` 提供；CLI 帮助确认 `serve` 是 stdio MCP server。
- gbrain 的 `search` operation 是只读操作，参数是 `query`、`limit`、`offset`、本地调用可用的 mode；stdio 调用默认 `remote=true`。
- stdio server 从 `GBRAIN_SOURCE` 读取默认 source；`search` 本身不声明 `source_id` 参数。
- gbrain 的 `SearchResult` 实际字段包括：`slug`、数字型 `page_id`、`title`、`type`、`chunk_text`、`chunk_source`、`chunk_id`、`chunk_index`、`score`、`stale`，以及可选 `source_id`、`content_flag` 等。
- gbrain 搜索结果没有本项目约定的 `path` 和 `content` 字段；它返回的是 chunk 级结果，不是本地 Wiki 文件级结果。
- gbrain 支持 source 级隔离，但 source 属于 Brain 内的第二维；仅配置一个 source map 不能自动证明 Brain、source、Wiki project 三者内容等价。

## 三、第一性原理审查

### 原始目标拆解

要真正“用 gbrain 替代本项目搜索”，至少必须同时成立：

1. **数据相同**：gbrain 能看到本项目当前所有可检索页面。
2. **数据及时**：新增、修改、删除、归档和恢复会在可接受延迟内反映到 gbrain。
3. **范围相同**：每个 `project_id` 只能检索对应 Brain/source，不能跨项目泄漏。
4. **语义相同**：本项目现有 `hybrid`、`keyword`、`vector`、type/actionable 约束不能被静默改变。
5. **结果可用**：调用方仍能得到 `path/title/content/score/source/evidence`，且链接到本地 Wiki 的行为不坏。
6. **可用性不差**：GBrain 不可用时系统能明确降级；GBrain 可用时不会因本地 vector readiness 误阻断。
7. **最终可切换**：经过验收后可以关闭本地搜索，而不是永远双轨运行。

当前方案只覆盖了第 3、部分第 5、第 6 和回滚方向；第 1、2、4、7 没有闭环。

### 第一性原理结论

方案的核心错误不是“少写了一个字段”，而是没有先确定**谁是搜索数据的唯一事实源**：

- 如果 ruflo-kb 继续负责 ingest 和 Wiki 写入，gbrain 必须有可靠的同步链路。
- 如果 gbrain 成为事实源，ruflo-kb 的本地 Wiki、frontmatter 过滤和本地向量就不能继续作为隐含必需品。
- 如果两边都保留为事实源，就不是替代，而是双索引系统，必须定义一致性和冲突策略。

方案目前选择了“双轨读取 + 失败回退”，但没有定义双轨数据如何保持一致。因此它解决了“怎么调用”，没有解决“调用到的东西是不是应该被调用”。

## 四、批判性思维审查

### P0 致命缺陷

#### P0-1：没有数据同步闭环，无法保证搜索的是当前知识库

- 位置：方案“5. 数据前提”和 Task 4。
- 问题：方案只要求 GBrain 中“必须已有”页面，没有新增/修改/删除/归档同步机制。
- 反例：用户在 ruflo-kb ingest 新文档后，Wiki 已写入，但 GBrain 未导入；远程搜索返回旧结果或空结果，方案却把远程调用视为成功。
- 后果：搜索替代的核心事实不成立，且错误是静默的。
- 必须整改：增加数据同步方案。最低要求是 ingest 成功后的可靠 outbox/队列同步到 GBrain，覆盖 upsert、delete、archive、restore，并定义 freshness lag 门禁；或者明确把 GBrain 设为唯一写入源并重构本地 Wiki 依赖。

#### P0-2：当前本地 vector readiness 会在 GBrain 路由前阻断远程搜索

- 位置：当前 `src/services/search.py` 的执行顺序；方案“4. 当前搜索契约的保留”。
- 问题：现有服务先检查本地 `vector_readiness`，未 ready 时直接 `results=[]`；方案没有明确把 GBrain 路由移到这个 gate 之前。
- 反例：本项目 LanceDB 尚未重建，但 GBrain 已有完整 embedding。调用仍然返回空结果，GBrain 根本不会被调用。
- 后果：GBrain 不能替代本项目搜索，只能在本地搜索已 ready 时作为旁路。
- 必须整改：将 readiness 拆成 `local_ready` 与 `remote_ready`；在后端选择阶段先决定远程路径。只有选择 local 时才使用本地 vector gate；远程失败后回退 local，再执行 local gate。

#### P0-3：方案测试契约与 gbrain 实际返回契约不一致

- 位置：Task 1 的 `test_gbrain_result_is_normalized`。
- 问题：测试伪造 `content` 和 `slug="wiki/a"`，而 gbrain 实际返回 `chunk_text`、`slug`、`type`、`source_id`，没有 `path` 和 `content`。
- 反例：测试通过，但真实调用解析 `content` 时失败，或把 chunk slug 当成本地文件 path。
- 后果：最关键的适配测试没有测试真实协议。
- 必须整改：测试 fixture 必须来自 gbrain `SearchResult` 实际字段；明确 `chunk_text -> content` 的截断规则，并明确如何由 `(type, slug)` 或本地索引解析 canonical path。

#### P0-4：没有定义 chunk 结果到 Wiki 文件结果的确定性映射

- 位置：方案 Adapter 的 `path/title/content` 映射，以及“path 无法闭环则回退”。
- 问题：gbrain 返回 chunk，不返回本项目的 `wiki/concepts/foo.md` 路径；本项目的 Wiki 路径还受 `PageType`、schema custom type、slug/id 规则影响。
- 反例：同一个 slug 在不同 source 存在，或 custom type 页面不在四个默认目录；Adapter 无法仅凭 `slug` 构造安全 path。
- 后果：actionable 过滤可能误放行、误过滤，或者远程结果全部被丢弃；source scope 也可能与本地文件不一致。
- 必须整改：采用本地 canonical index/`page_path_for(...)` 做确定性映射，并校验 `source_id + slug + type`；custom type 无法闭合时禁止远程结果进入当前搜索契约。

### P1 重大隐患

#### P1-1：远程空结果被当作成功，不会回退本地

- 位置：方案“远程失败回退本地”的定义。
- 问题：协议成功且返回 `[]` 时，方案没有规定这是“确实无匹配”还是“索引落后/source 错配/embedding 失效”。
- 反例：GBrain source 配错但 MCP 正常，所有查询返回空数组，系统不会触发本地回退。
- 后果：出现静默零召回。
- 整改：灰度阶段必须 shadow compare；当 remote empty 而 local non-empty 时记录 `remote_empty_mismatch` 并使用 local。正式切换前必须证明远程空结果的可信度。

#### P1-2：单请求启动一个 Bun/PGLite 进程，缺少并发上限和熔断

- 位置：Task 2 明确选择“单次请求单次 stdio 会话”。
- 问题：高并发搜索会创建多个 gbrain 进程；gbrain 文档本身提到孤儿进程会竞争 PGLite 写锁。
- 反例：WebUI 搜索输入框触发并发请求，多个请求同时启动 Bun，超时后残留子进程，后续 ingest 受锁竞争影响。
- 后果：搜索、摄取和服务进程互相拖垮。
- 整改：至少复用现有 `get_circuit_breaker(...)`，增加有限并发 semaphore、明确子进程终止验证和 fail-fast；若采用单请求进程，只能作为低并发 PoC，并设置并发验收上限。

#### P1-3：命令、参数和 cwd 由环境变量控制，仍构成任意子进程执行面

- 位置：`RUFLO_GBRAIN_COMMAND`、`RUFLO_GBRAIN_ARGS`、`RUFLO_GBRAIN_CWD`。
- 问题：不使用 shell 只能防止 shell 拼接，不能防止配置被替换为任意可执行文件或任意工作目录。
- 反例：服务运行环境中的配置被改为另一个程序，搜索请求触发该程序并继承服务权限。
- 后果：本地服务权限扩大为任意进程启动。
- 整改：默认固定 `bun` + 固定 gbrain repo root；配置只允许操作员级配置文件或 allowlist 路径，启动前校验命令真实路径、cwd 存在且位于允许根目录。

#### P1-4：方案没有处理 gbrain 的 embedding 外发和成本边界

- 位置：Open Risks 仅把 embedding 费用作为提醒。
- 问题：gbrain hybrid search 可能调用其 embedding provider；查询文本可能离开本机。
- 反例：用户输入包含未公开的写作资料，远程搜索在 gbrain 侧触发外部 embedding API。
- 后果：数据合规、隐私和成本不可控。
- 整改：启用开关前明确 provider/data residency；提供 keyword-only 或本地 embedding 的验证路径；在运行状态中暴露是否发生远程 embedding。

#### P1-5：没有全量功能替代，原始目标被静默缩小

- 位置：Global Constraints 与后端选择。
- 问题：`keyword`、`vector`、带 `type` 的请求永远走本地。
- 反例：调用者看到 `RUFLO_SEARCH_BACKEND=gbrain`，以为所有搜索换后端，但不同参数组合实际命中两个算法和两个数据源。
- 后果：行为不可预测，难以宣称替代完成。
- 整改：文档和 API diagnostics 明确“hybrid-only pilot”；若要达成全量替代，必须为所有模式定义等价语义或明确废弃旧模式并迁移调用方。

#### P1-6：测试目录的 mcp stub 可能导致新 Adapter 在 collection 阶段失败

- 位置：`tests/test_searcher/conftest.py` 与根 `tests/conftest.py`；方案 Task 1。
- 问题：根测试配置会 stub `mcp`，`test_searcher/conftest.py` 只恢复 lancedb/pyarrow，没有恢复真实 mcp；新测试若导入 `mcp.client`，可能拿到不完整 stub。
- 反例：单测代码正确，但 pytest 在 collection 阶段报 `mcp.client` 不存在。
- 后果：方案第一步无法执行。
- 整改：在测试宿主增加最小真实 mcp restore，或把 MCP SDK 导入延迟到 Adapter 调用路径，并增加独立 collection smoke test。

### P2 优化疏漏

#### P2-1：配置没有接入现有 `src/config.py`

直接在 service/adapter 读取多个 `os.environ` 会绕过项目现有 Settings 约定，测试隔离、默认值和运行时重载行为不一致。应将搜索后端配置集中到现有配置模块。

#### P2-2：验收指标不可量化

“20 条代表性查询”不足以证明替代。至少应记录 remote/local 的 Recall@K 或人工相关性、空结果差异、P95 latency、错误率、fallback rate、freshness lag 和跨 source 泄漏数。

#### P2-3：没有版本与工具能力探测

只假定工具名 `search` 和字段形状，未规定 MCP `tools/list` 能力探测、gbrain 版本兼容范围或 schema drift 告警。

#### P2-4：没有定义结果去重策略

gbrain 是 chunk 级返回，本项目当前结果是文件级返回。多个 chunk 属于同一 Wiki 页面时，需要按 canonical path 去重并决定最高分、融合分数或保留证据；方案没有规定。

## 五、终局思维审查

### 终局状态一：真正替代成功

最终应当能够做到：

- ruflo-kb ingest 的页面在 freshness SLA 内进入 GBrain；
- 本地搜索关闭后，所有被支持的搜索请求仍能得到等价结果；
- `path/title/content/evidence` 仍可被 WebUI、写作检索和引用逻辑消费；
- source/project 隔离可证明；
- GBrain 故障时系统有明确“降级运行”状态，而不是静默错误；
- 回滚只切换后端，不需要恢复丢失的数据。

当前方案的终局仍然是：

```text
ruflo-kb ingest → 本地 Wiki/LanceDB
                    ↓ 未定义同步
                 GBrain 独立 Brain

搜索请求 → 部分走 GBrain，部分走本地
```

这不是单一搜索事实源，而是两个未定义一致性的索引。因而终局不闭合。

### 终局思维结论

方案必须先选择下列一条路线：

| 路线 | 终局含义 | 需要增加的内容 |
|---|---|---|
| A：GBrain 作为检索副本 | ruflo-kb 仍是事实源 | ingest outbox、增删改同步、freshness SLA、重放和删除传播 |
| B：GBrain 作为事实源 | 搜索和写入都以 GBrain 为准 | 写入/读取边界重构、本地 Wiki 降为缓存或导出物 |
| C：仅做搜索增强 | 不宣称替代 | 把方案名称和验收目标改成“可选远程检索后端” |

当前文档实际走的是 A 的读取部分 + C 的回退策略，却没有 A 的同步部分；因此不能按原始替代目标放行。

## 六、系统思维审查

### 关键链路

```text
HTTP 搜索请求
  → project_id 解析
  → 后端选择
  → source 映射
  → Bun 子进程
  → MCP initialize
  → gbrain search
  → chunk 结果
  → path/页面映射
  → actionable/type 过滤
  → 统一结果
  → WebUI/写作调用方
```

当前方案对“子进程 → MCP → 结果解析”描述较多，对“数据写入 → 同步 → 检索一致性”和“chunk → Wiki page → 安全过滤”描述不足。系统风险集中在两端，而不是 MCP transport 本身。

### 系统级连锁风险

1. 本地 ingest 成功但 GBrain 未同步。
2. 远程搜索返回合法空数组。
3. 方案把合法空数组当作成功。
4. 本地 fallback 不触发。
5. WebUI 展示“没有结果”。
6. 操作者误判为知识库没有内容，而不是远程索引落后。

这是当前方案最危险的静默失败链。

### 压力测试问题清单

| 场景 | 连锁反应 | 当前方案覆盖 | 判定 | 加固方案 |
|---|---|---|---|---|
| 本地 vector 未 ready、GBrain ready | service 先返回空，远程永不执行 | 未覆盖 | P0 | 远程路由先于 local readiness |
| GBrain source 配错但 MCP 正常 | 合法空结果不触发回退 | 未覆盖 | P1 | shadow compare + empty mismatch fallback |
| 新页面只写入 ruflo Wiki | GBrain 永久旧索引 | 未覆盖 | P0 | outbox 同步 + freshness gate |
| 页面被删除/归档 | GBrain 继续返回陈旧页面 | 未覆盖 | P0 | delete/archive 事件同步 + tombstone |
| gbrain 返回多个 chunk | 同一页面重复占满 topK | 未覆盖 | P1 | canonical path 去重策略 |
| custom type 页面 | 无法从 type/slug 得到本地路径 | 部分提到 path 闭环 | P0 | canonical index 映射，失败即拒绝远程 |
| 50 个并发搜索 | 50 个 Bun/PGLite 子进程竞争资源 | 仅写“先测量” | P1 | semaphore + breaker + 进程终止验证 |
| Bun/gbrain 不在服务 PATH | 每次启动失败并打满日志 | 有本地回退 | P2 | 启动前 preflight + 失败缓存 |
| gbrain 工具字段升级 | parser 抛错，全部请求回退 | 有异常回退 | P2 | tools/list/schema probe + drift metric |
| embedding provider 外发 query | 隐私/费用边界被触发 | 仅列为 open risk | P1 | provider/data residency gate |
| 本地过滤读取不到远程 path | 远程结果全被过滤或安全标签失效 | 只写“path 闭环” | P0 | 先 canonicalize，再允许过滤/返回 |

### 压力测试临界点

- **零同步时长**：第一次 ruflo Wiki 变更后，替代目标立即失效；因此同步不是优化项，而是 P0 前提。
- **零本地 vector readiness**：如果远程路由仍在 local readiness 之后，远程替代在该临界点完全失效。
- **并发超过单进程承载量**：单请求启动模型在低并发可行；一旦超过可接受子进程数，延迟和锁竞争会非线性恶化。
- **远程空结果比例上升**：没有 shadow/empty mismatch 监测时，系统无法区分“真实无结果”和“索引故障”。
- **path 映射覆盖率低于 100%**：一旦远程结果不能闭合，当前 actionable 过滤不再有可靠输入；不能以部分映射宣称替代。

## 七、必须整改的 P0/P1 门禁

### P0：不完成不得编码/灰度

1. 明确终局路线 A、B 或 C；若坚持原始“替代”目标，不能选择只读旁路的 C。
2. 定义并实现数据同步闭环，至少覆盖 upsert、delete、archive、restore、失败重放和 freshness lag。
3. 把远程 backend 选择放到 local vector readiness 之前，拆分 local/remote readiness。
4. 用 gbrain 实际 `SearchResult` 字段重写 Adapter contract 和测试 fixture。
5. 定义 `(source_id, slug, type, chunk_id)` 到本地 canonical Wiki path 的确定性映射和去重规则。
6. 证明 actionable/type 过滤不会因远程 path 或 frontmatter 缺失而失效；无法证明时拒绝远程结果。

### P1：进入灰度前必须完成

1. 增加 shadow compare：remote/local 同时检索但只返回一个结果集，记录召回差异。
2. 增加 remote-empty/local-nonempty 检测，避免合法空数组造成静默零召回。
3. 增加 semaphore、现有 circuit breaker、超时后的子进程终止验证。
4. 固定并 allowlist gbrain executable/cwd；环境变量只作为受控配置输入。
5. 将配置纳入 `src/config.py`，统一默认值和测试隔离。
6. 增加真实 MCP payload、collection smoke、source isolation 和 stale data 测试。
7. 规定量化门槛：建议至少 100 条查询、Recall@10 不低于本地基线的 95%、P95 延迟不高于本地基线 2 倍、远程错误率低于 1%、freshness lag 小于 5 分钟、跨 source 泄漏为 0；最终数值应在实施前由操作员确认。

## 八、修订后的最小可行路线

如果目标暂时降级为“可控试点”，最小路线是：

1. 先实现 C 路线，文档明确“不替代，只提供可选远程 hybrid backend”。
2. 使用真实 gbrain result fixture 完成 parser、path 映射和 chunk 去重。
3. 保留本地 backend 为默认；remote 只在完整数据/映射 preflight 通过后启用。
4. 远程空结果与本地非空结果自动降级本地，并记录指标。
5. 用 semaphore + circuit breaker 限制单机并发。
6. 通过 100 条查询和 freshness/隔离测试后，再决定是否进入 A 路线的数据同步工程。

如果坚持原始“替代”目标，则必须把数据同步和最终切换门禁加入当前计划，不能只修改 Adapter。

### 复审状态

本轮仅审计方案，未对被审方案做整改，因此“整改后第三轮复审”尚未执行。按审计门禁，当前结论保持：**不通过，不得进入编码**。完成 P0/P1 整改后，必须重新执行对照审计并更新本报告结论。

## 九、最终验收判定

| 验收项 | 当前方案 | 判定 |
|---|---|---|
| 能启动并调用 gbrain MCP | 设计上可以 | 条件通过 |
| 保持现有 HTTP API | 目标是保持 | 条件通过 |
| 真实返回字段兼容 | fixture 与实际不符 | 不通过 |
| 远程结果可映射为本地 Wiki path | 未定义算法 | 不通过 |
| 本地 vector 未 ready 时仍可远程搜索 | 当前执行顺序不允许 | 不通过 |
| 新旧数据保持一致 | 无同步方案 | 不通过 |
| 所有搜索模式均被替代 | 只覆盖 hybrid | 不通过 |
| GBrain 故障安全回退 | 有方向，但空结果/并发未覆盖 | 条件通过 |
| 可量化证明远程质量 | 仅 20 条查询，无阈值 | 不通过 |
| 可安全回滚 | 配置回滚方向成立 | 通过 |

### 审计结论

**方案不具备“达成原始替代目标”的充分条件。**

在用户确认的试点目标下，原方案的窄范围、默认本地、显式开启、失败回退设计可以保留；但它仍不是“拿来即编码”的方案。试点版本至少要先补齐真实 MCP payload、结果映射、远程空结果保护、并发限制和 readiness 路由顺序，并把验收口径固定为“试点可控性”，而非“搜索替代完成”。

**允许的下一步：**按本报告 P0/P1 修订试点方案，完成后再进入小范围编码或灰度。

**不允许的下一步：**直接按当前计划实现 Adapter，并以“调用成功 + 有 fallback”宣称搜索替代完成。

## 十、审计证据位置

- 本方案：`docs/superpowers/plans/2026-09-12-gbrain-mcp-search-adapter.md`
- 本项目搜索服务：`src/services/search.py`
- 本项目搜索路由：`src/server/routes/search.py`
- 本项目 MCP server：`src/mcp_server/main.py`
- gbrain MCP server：`D:\5-Project\gbrain-master\src\mcp\server.ts`
- gbrain search operation：`D:\5-Project\gbrain-master\src\core\operations.ts`
- gbrain SearchResult：`D:\5-Project\gbrain-master\src\core\types.ts`
- gbrain 检索实现：`D:\5-Project\gbrain-master\src\core\search\hybrid.ts`
- 测试 stub 约束：`tests/conftest.py`、`tests/test_searcher/conftest.py`
