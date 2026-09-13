# GBrain 项目级 hybrid 搜索试点多角度审计报告

审计对象：`docs/superpowers/plans/2026-09-12-gbrain-search-managed-index-pilot.md`

审计目标：判断“WebUI 开关 → 自动导入当前项目 Wiki → GBrain hybrid 搜索 → 失败回退本地”的设计是否能以可接受的复杂度、安全性和运维成本落地。

审计角度：第一性原理、批判性思维、奥卡姆剃刀、终局思维、全局思维、二八法则。

审计依据：当前 ruflo-kb 源码、当前 `knowledge/` 项目结构、GBrain MCP/CLI 源码与方案正文。图谱查询因本机 `uv` 启动器失败未使用，结论不依赖图谱输出。

## 一、最终结论

### 判定

**方向可行，方案暂不完全放行。**

它已经从“简单加按钮”升级为一个基本完整的索引副本方案，但仍有 4 个必须在编码前冻结的 P0/P1 问题：

1. CLI 初次导入与 MCP 增量写入存在两套数据处理路径，尚未证明 slug、frontmatter、chunk 和 embedding 语义一致。
2. 增量同步的正确性依赖周期性 reconcile，但 reconcile 周期、失败重放、删除语义和“何时允许继续使用旧索引”没有形成完整状态机。
3. GBrain 写入权限、source 绑定、MCP stdio 会话生命周期和 PGLite 并发模型仍是实现前提，不是已验证事实。
4. 质量标准主要是“相对本地基线”，缺少脱离本地基线的可接受质量、成本和延迟上限。

### 评分

| 维度 | 得分 | 判定 |
|---|---:|---|
| 第一性原理 | 8/10 | 核心问题识别正确，但同步和索引副本边界仍需冻结 |
| 批判性思维 | 6/10 | 风险覆盖较多，仍有关键运行时假设未证实 |
| 奥卡姆剃刀 | 5/10 | 对试点来说偏重，双传输、hint、reconcile、job、rebuild 同时存在 |
| 终局思维 | 7/10 | 明确 Wiki 是事实源、GBrain 是副本，但未定义试点退出条件 |
| 全局思维 | 7/10 | 已覆盖 UI/API/同步/搜索/回退，监控和运维成本还不完整 |
| 二八法则 | 6/10 | 核心 20% 已找到，但实施任务仍包含较多可后置能力 |
| **总体放行** | **6/10** | 可作为修订中的试点方案，暂不直接编码 |

## 二、第一性原理审查

### 2.1 把目标还原成不可缺少的事实

用户真正需要的不是“一个按钮”，而是：

```text
用户选择一个项目
  → 明确授权复制该项目知识
  → GBrain 得到可检索且范围正确的索引
  → 搜索返回能回到本地 Wiki 的结果
  → 知识变化后不会长期返回旧内容
  → 任一环节失败时用户仍能搜索
```

因此最低必要条件只有七项：

1. 项目边界确定：只读当前 project 的 Wiki。
2. 数据复制可重复：相同页面不会无限重复，变化页面能更新。
3. 删除可传播：删除/归档页面不会继续被远程返回。
4. 索引可判定 ready：不能用“命令退出码 0”代替内容完整性。
5. 结果可闭环：GBrain chunk 必须映射回本地 Wiki path。
6. 搜索可回退：远程空结果、超时、协议异常和 stale 都不能造成静默零召回。
7. 操作可逆：关闭搜索不删除本地事实源，能立即回到 local。

当前方案对 1、4、5、6、7 覆盖较好；对 2、3 的设计方向正确，但实现细节仍不足以证明闭环。

### 2.2 必须存在与可以后置

| 能力 | 是否核心 | 评审结论 |
|---|---|---|
| 项目级开关 | 必须 | 保留 |
| 异步初次导入 | 必须 | 保留 |
| source 隔离 | 必须 | 保留 |
| ready gate | 必须 | 保留 |
| MCP 搜索和本地回退 | 必须 | 保留 |
| 删除/归档同步 | 必须 | 不能后置，否则会返回陈旧知识 |
| 周期性 reconcile | 必须 | 作为正确性底线保留 |
| 写入事件 hint | 非核心 | 后置；先用周期 reconcile 保证正确 |
| 独立 rebuild API | 非核心 | 后置；先让 enable/retry 支持重建 |
| 独立 job 查询 API | 可选 | 可由 status API 先覆盖 |
| 多套增量传输 | 非核心 | 需要简化为一个权威写入路径 |
| 100 条查询质量评测 | 试点门 | 保留，但增加绝对门槛 |

第一性原理结论：方案的骨架正确，但“导入通道如何保持语义一致”和“同步何时算完成”是核心事实，不能留到编码时猜。

## 三、批判性思维审查

### P0-1：两套导入路径可能产生两个不同的知识库

**方案位置：**3.1、5.1、5.2。

初次导入使用 GBrain CLI `import`，增量 upsert 使用 MCP `put_page`。这两个入口虽然最终都写 GBrain，但可能在以下方面不完全相同：

- frontmatter 规范化；
- slug 推导；
- wikilink/relation 处理；
- chunker 版本；
- content hash；
- embedding 和 provenance 标记；
- source path 的记录方式。

**失败场景：**初次 CLI import 为 `concepts/a`，增量 MCP put_page 发送了不同 slug 或未携带同样的 frontmatter，GBrain 同时出现旧页面和新页面；搜索结果看似成功，实际出现重复和陈旧内容。

**必须整改：**选择一个 canonical payload builder，并让 CLI 初次导入与 MCP 增量都使用相同的 canonical slug、正文和 frontmatter 规则；至少做“CLI 导入后再 MCP upsert 同一页面”的 byte/hash/page-count 回归测试。

### P0-2：reconcile 的时间和状态语义没有冻结

**方案位置：**5.2、5.3、9、10。

方案写了周期性 reconcile 和 freshness lag < 5 分钟，但没有规定：

- reconcile 的实际调度周期；
- job 超时后何时变为 stale；
- 一页失败时是否整库 stale；
- 已有 ready 索引能否继续服务；
- 远程索引落后多少分钟必须强制 local；
- 删除同步失败时是否允许返回其他远程结果；
- reconcile 期间是继续服务旧索引还是切 local。

**失败场景：**增量删除失败，但状态仍为 ready；用户搜索命中已删除页面。或者一次 reconcile 只失败 1 页，系统把全部 GBrain 标为不可用，造成不必要的本地回退。

**必须整改：**定义明确状态机：`disabled → queued → syncing → ready → stale → failed`，并规定每个状态的搜索行为、freshness 上限、失败粒度和恢复动作。至少把“删除失败”列为强制 stale，把“单页 upsert 失败”列为可观测的 partial/stale，而不是模糊处理。

### P1-1：GBrain MCP 写权限和 source 绑定仍是假设

**方案位置：**3.1、5.2、Task 0。

已知 GBrain 有 `put_page`、`delete_page`、`restore_page`，但“当前 ruflo worker 能否通过 stdio MCP 获得写 scope、source 是否由环境固定且对每个操作生效”必须实际验证。`sync_brain` 本身是 `localOnly`，不能作为 MCP 同步工具。

**失败场景：**搜索 MCP 可以调用，但增量 `put_page` 被 scope 拒绝；或者环境 source 未被 dispatch context 正确采用，页面写入 default source，造成跨项目污染。

**整改：**Task 0 必须是硬门：真实调用 `tools/list`、受控测试 source 的 `put_page/delete_page/restore_page`、source list/status 和跨 source 查询；未通过就禁止把增量 MCP 写入列入方案，只能使用已验证的 CLI 或新增 GBrain bulk sync operation。

### P1-2：MCP 搜索会话生命周期没有设计

**方案位置：**3.1、6、Task 4。

方案写“受控 stdio MCP 会话”，但没有明确是：

- 每次搜索启动一个 Bun 进程；
- 每个项目一个长连接；
- 全局一个 GBrain serve 进程；
- 还是通过 HTTP MCP 复用连接。

**失败场景：**搜索高峰期每个请求拉起 Bun/PGLite，出现启动延迟、文件锁竞争、孤儿进程和 embedding/DB 资源争用；P95 直接超过质量门。

**整改：**在 Task 0 冻结会话模型。试点至少要有每项目/每 GBrain 实例的单写锁、有限并发读、超时终止、孤儿进程清理和 circuit breaker。若采用每请求进程，必须先用真实 50 并发压测证明可接受。

### P1-3：相对基线的 Recall 门槛可能掩盖绝对质量不足

**方案位置：**9.2。

`Recall@10 ≥ local baseline 的 95%` 只能证明“不比本地差太多”，不能证明 GBrain 结果值得启用。如果本地基线本身只有 50%，GBrain 47.5% 也能通过。

**整改：**使用脱敏人工标注 gold set，同时保留相对基线：

- gold Recall@10 设绝对下限；
- 不低于 local baseline 的 95%；
- 关键查询类别分别统计；
- 远程空结果和路径映射失败单独计入错误率。

### P1-4：成本门槛缺失

当前 workspace 已有约 4,447 个 Wiki Markdown 页面。初次导入和 embedding 可能触发大量外部调用，但方案只写“开启前提示费用”，没有：

- 页面数/字节数预估；
- embedding 成本上限；
- 超限是否阻止开启；
- 失败后是否允许继续导入；
- 重建是否重新计费。

**整改：**enable 前先做 dry-run 预估，显示页面数、总字节数、预计 embedding 量和预计费用；超过配置上限时只允许显式 rebuild/管理员确认。

### P1-5：source ownership 证据不足

方案要求“发现同名但非本项目 source 时不得自动接管”，但没有定义 GBrain source 哪些字段是可信的 ownership marker。

**失败场景：**状态文件丢失后，系统按相同 source ID 重新接管另一个项目曾使用的 source。

**整改：**source 创建时写入不可变 ownership marker（项目 UUID hash、ruflo project ID、canonical root fingerprint）；状态丢失但 marker 不匹配时进入 `needs_rebind`，禁止自动启用。

### P2：其他批判性问题

| 问题 | 后果 | 建议 |
|---|---|---|
| `ready` 与本地 vector readiness 的语义变化 | 旧客户端可能误解 `ready=false` | 文档明确字段语义，增加兼容诊断字段 |
| 远程 chunk 只保留最高分片段 | 丢失页面其他上下文 | 试点先保留 snippet，后续评估全文/多 chunk 聚合 |
| GBrain soft delete 与本地 archive 不完全等价 | 远程保留恢复窗口 | manifest 记录 tombstone，测试恢复/过期行为 |
| CLI stdout 进度解析未定义 | 进度面板不准确 | 只依赖 JSON/退出码，进度允许粗粒度 |
| 失败重试没有预算/退避细节 | GBrain 或 embedding 故障时重试风暴 | 指数退避、上限和熔断 |

## 四、奥卡姆剃刀思维审查

### 4.1 当前方案为什么偏重

对于“可选 hybrid 试点”，当前方案同时引入：

- 项目配置文件；
- 运行状态文件；
- durable job；
- CLI 初次导入；
- MCP 增量 upsert/delete/restore；
- EventBus hint；
- 周期 reconcile；
- rebuild API；
- job API；
- search adapter；
- WebUI 轮询；
- 100 条质量评测；
- 多类 source/embedding/path gate。

其中很多能力是合理的，但它们叠加后，试点的失败面从“搜索接入失败”扩大成“第二套知识同步系统运行失败”。

### 4.2 最小可行方案

建议把试点拆成两层：

#### MVP-1：可控验证

只保留：

1. 一个项目一个 source；
2. WebUI enable/disable/status；
3. 异步初次导入；
4. 单一权威导入通道；
5. ready gate；
6. MCP read search；
7. path manifest、chunk 去重、本地回退；
8. 固定周期 reconcile；
9. 关闭立即 local。

先删除或后置：事件 hint、独立 rebuild API、独立 jobs API、复杂 source 删除 UI、跨多种传输的优化。

#### MVP-2：运行优化

只有 MVP-1 稳定后再增加：

- 页面写入事件 hint；
- MCP 增量写入；
- 长连接/连接池优化；
- 更细的进度和重试控制；
- 自动 source 清理。

### 4.3 剃刀结论

“CLI 初次导入 + MCP 增量 + MCP 搜索”不是最小方案，而是混合架构。最小安全方案应先固定一个导入权威路径；如果 GBrain CLI 能以 hash 跳过未变化页面，则初期可用 CLI 周期性 reconcile + MCP 删除补偿，先不引入每页 MCP upsert。

## 五、终局思维审查

### 5.1 正确的终局模型

```text
Wiki = 唯一事实源
GBrain = 可重建的检索副本
Local = 永久安全回退
WebUI 开关 = 项目级路由意图，不是数据所有权转移
```

这个终局模型是正确的，避免了 GBrain 和 ruflo 双写争夺事实源。

### 5.2 当前缺失的终局决策

方案没有规定试点结束后如何处理：

- GBrain 质量长期不达标，是保留、关闭还是清理；
- GBrain 质量达标，是继续双路由还是成为默认远程 backend；
- 本地索引是否仍永久保留；
- GBrain source 是否有生命周期和存储上限；
- 项目迁移、复制、删除后 source 如何处理；
- GBrain 版本升级后是否需要全量重建。

**整改：**增加试点退出矩阵：

| 结果 | 动作 |
|---|---|
| 质量/成本不达标 | 保持 local，保留或按管理员确认清理 source |
| 质量达标但稳定性不足 | 继续 opt-in，不改默认 |
| 质量、稳定性、成本均达标 | 评估是否扩大项目范围，不自动全局切换 |
| 项目删除/迁移 | source 进入 orphan/needs review，不自动硬删除 |

终局结论：方案的“副本 + 回退”定位正确，但必须增加退出策略，否则试点会永久积累 GBrain source 和维护成本。

## 六、全局思维审查

### 6.1 端到端链路

```text
用户点击
  → WebUI 确认
  → auth middleware
  → project resolve
  → config/state 原子写入
  → job 调度
  → Wiki snapshot
  → GBrain source/import/embed
  → manifest/reconcile
  → ready gate
  → MCP search
  → chunk 去重/path 映射
  → 本地 frontmatter 过滤
  → files/content 回读
  → WebUI 展示
```

这条链路中，真正的系统级风险集中在中间四段：

1. `project resolve → snapshot`：是否扫描错项目；
2. `source/import/embed`：是否导入了错误 source 或未生成向量；
3. `manifest/reconcile → ready`：是否把部分成功误判为完整；
4. `MCP result → path/filter`：是否返回无法回读或绕过本地安全过滤的结果。

### 6.2 系统性雪崩路径

```text
导入部分失败
  → 页面数统计仍接近预期
  → 错误未进入 ready gate
  → GBrain 被标为 ready
  → 远程空结果/陈旧结果出现
  → fallback 未触发
  → 用户以为知识库没有内容
```

所以“ready gate 不仅检查进程成功，还必须检查 content hash、source、embedding、映射覆盖率和删除 tombstone”。

### 6.3 全局缺口

- 监控指标没有明确落在哪个现有 metrics 模块；
- 没有定义同步任务对 GBrain DB 锁和本地 ingestion queue 的资源预算；
- 没有定义服务关闭时如何等待/终止 GBrain worker；
- 没有定义 GBrain home 磁盘满、embedding 限流、网络代理失败时的状态转换；
- 没有定义项目复制后如何避免复用旧 source ID。

全局结论：不能只验证“按钮能点、搜索有结果”，必须验证数据生命周期和运行资源生命周期。

## 七、二八法则审查

### 7.1 最有价值的 20%

以下 5 项贡献约 80% 的用户价值和风险控制：

1. 项目独立 source；
2. 异步初次导入；
3. ready gate；
4. MCP search + 结果 path 映射；
5. 任意异常自动回退 local。

### 7.2 最有价值的风险控制 20%

以下 5 项能覆盖约 80% 的严重事故：

1. 禁止前端传入目录/命令；
2. source isolation；
3. content hash + 删除 tombstone；
4. remote-empty/local-nonempty 检测；
5. 关闭和 stale 的立即 local 回退。

### 7.3 建议延后的 80% 工作

- EventBus hint；
- 独立 rebuild API；
- 独立 job endpoint；
- 复杂的 source 清理流程；
- 长连接优化；
- 全量 WebUI 进度细节；
- 多种远程部署拓扑。

这些不是没有价值，而是不应阻塞第一轮验证。第一轮先证明“数据能安全复制、结果能安全返回、失败能回退”。

## 八、必须整改的 P0/P1 门禁

### P0：编码前必须冻结

1. **统一导入权威路径**：明确 CLI 与 MCP 是否都保留；若都保留，提供同一 canonical payload builder 和一致性测试。
2. **冻结同步状态机**：明确 reconcile 周期、freshness 上限、partial/stale/failed 行为、删除失败行为和服务重启恢复。
3. **完成真实能力验证**：验证 GBrain source 创建/绑定、MCP 写 scope、source 固定、CLI import、embedding、delete/restore 和跨 source 隔离。
4. **冻结会话/并发模型**：明确 GBrain MCP 进程复用、写锁、搜索并发、超时终止、孤儿进程清理和 circuit breaker。

### P1：进入灰度前必须完成

1. 增加 dry-run 成本/页面/字节数预估和预算上限。
2. 质量门同时使用 gold set 绝对 Recall 和 local 相对基线。
3. 实现 source ownership marker 和 `needs_rebind` fail-closed 状态。
4. 增加跨项目、部分导入、删除失败、关闭旧 job、重启恢复和磁盘/embedding 限流测试。
5. 将指标落到现有 metrics：sync duration、freshness lag、mapped ratio、fallback reason、remote-empty mismatch、embedding cost estimate、orphan process。

## 九、修订后的最小落地路线

### Phase 0：只做契约和真实 preflight

- 不改 WebUI；
- 用测试 source 验证 CLI import 和 MCP 写/读；
- 生成真实 payload fixture；
- 确认同机部署和 GBrain home；
- 证明 source isolation 和删除/恢复语义。

### Phase 1：最小试点

- 项目级配置/状态；
- enable/disable/status；
- 异步初次导入；
- 单一权威导入路径；
- ready gate；
- MCP search adapter；
- path manifest、去重、local fallback；
- WebUI 开关和状态。

### Phase 2：一致性加固

- 周期 snapshot reconcile；
- 删除 tombstone；
- 重启恢复；
- stale/freshness；
- 成本和性能指标。

### Phase 3：增量优化

- 写入事件 hint；
- MCP 增量 upsert；
- 长连接复用；
- 进度细化。

## 十、最终验收判定

| 问题 | 判定 |
|---|---|
| 能否实现 WebUI 开关 | 可以 |
| 能否自动把当前项目 Wiki 导入 GBrain | 可以，但初次导入应由后端异步 worker 执行 |
| 能否在 ready 后使用 GBrain hybrid 搜索 | 可以，前提是 MCP/search/source/path 契约真实验证通过 |
| 能否保证后续知识不陈旧 | 设计方向可以，当前同步状态机和通道一致性仍需补齐 |
| 能否安全回退本地 | 可以，方案设计正确 |
| 当前方案是否过度设计 | 是，建议把 hint/rebuild/复杂 job API 后置 |
| 当前方案是否可直接编码 | **不建议**，先完成 P0 门禁 |

### 审计结论

**这是一个可实现的方向，但当前版本更像“完整目标架构草案”，还不是最小可交付试点。**

推荐批准的目标是：

> 为单个项目建立一个默认关闭、异步构建、可验证、可回退的 GBrain hybrid 检索副本。

不推荐直接批准的目标是：

> 同时上线 CLI 初次导入、MCP 增量写入、事件 hint、周期 reconcile、复杂 job 状态和多项目长期运营。

完成 P0/P1 修订后，再进入编码；编码顺序应从 Phase 0 开始，而不是先做 WebUI 按钮。
