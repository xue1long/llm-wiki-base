# 全量 Book Preview 安全整改方案审计报告

日期：2026-09-10  
审计对象：`docs/superpowers/plans/2026-09-10-safe-full-book-preview-remediation.md`  
审计目标：判断方案能否在不影响原有功能的前提下，实现 `knowledge/novel-wiki` 的 1255 页全量 Book `preview -> apply-from` 发布。

## 一、第一轮审计结论（历史结论）

结论：**方向可行，当前方案不可直接进入编码，审计结论为“有条件通过，整改后复审”。**

方案抓住了本次事故的主要方向：将 LLM 从结构和 provenance 的控制者降级为正文生成器，并把 full-scope 新路径与旧 pilot/structured 路径隔离。这能显著降低本次出现的 JSON 结构失败，也不会天然破坏现有功能。

但方案仍缺少四个发布级闭环：

1. 批次结果如何合并为一个完整 preview release；
2. resume 如何保证模式、provider、prompt 和 snapshot 不漂移；
3. 自动验收如何识别“结构完整但内容无效”的正文；
4. 预算、重试和运行时限如何在每个批次调用前被严格计算。

在这四项补齐前，方案只能证明“更容易生成正文”，不能证明“最终一定得到可发布 Book”。

## 二、审计基线

原始目标的不可削弱条件：

```text
1255/1255 knowledge pages covered
179/179 chapters complete
automated acceptance = pass
preview release is complete
apply-from reuses the exact same release
CURRENT.json changes only during apply-from
LanceDB remains a separate operation
pilot and existing Book paths remain unchanged
```

本次真实 preview 的证据：21 次 MiniMax 调用后只有 9 个章节 complete，release 为 partial；失败响应包括纯 Markdown、字符串数组和缺少 `sections` 的对象，同时触发 900 秒运行时限。因此本审计不能只检查“能否避免 JSON 解析错误”，还必须检查完整性、质量、恢复和最终发布一致性。

## 三、第一性原理审计

### 3.1 目标拆解

全量 Book 不是单一的“调用 LLM”问题，而是四个独立问题的合取：

```text
数据边界正确
∧ 正文生成完成
∧ provenance 可验证
∧ release 原子发布
```

当前方案对数据边界和原子发布已有基础设计，对正文生成提出了更稳妥的 plain-text 路径，但 provenance 的语义覆盖和 batch-to-release 合并仍未闭环。

### 3.2 方案中正确的第一性原理决策

- LLM 不应拥有 page ID、chapter ID、source_page_ids 和发布状态的写权限；
- full-scope 不应复用 pilot curation；
- preview 和 apply-from 必须是同一个 release；
- partial release 不得成为 `CURRENT`；
- Book 与 LanceDB 是两个不同的一致性边界。

这些原则应保留。

### 3.3 第一性原理缺口

“把所有 page ID 挂到一个 compiler-owned section”只能证明页面被引用，不能证明正文确实吸收了页面内容。若原始目标的“全量”只要求页面进入 Book，这一做法可接受；若要求每页知识都被正文有效表达，则需要增加内容覆盖指标或抽样审计。

**判定：部分满足。**

## 四、批判性思维审计：问题清单

### ① 致命缺陷

#### C1：批次与最终 release 的合并边界未定义

- 位置：Task 3“每批结束返回可恢复状态”和 Task 4“生成 complete preview release”。
- 风险：如果每个批次都生成 release，最后可能有多个互不完整的 release；如果只写 batch state，又没有明确的最终 materialize 步骤，`apply-from` 没有可提升对象。
- 场景：前 10 个批次成功，最后一个批次成功后进程崩溃。resume 能看到章节状态，但没有明确哪个命令负责重新构建 manifest、acceptance report 和唯一 preview release。
- 整改：增加“finalize release”阶段。所有章节完成后，由固定 snapshot + batch state 一次性生成唯一 candidate release；批次目录永远不能被 `apply-from` 直接提升。

#### C2：resume 身份键不完整，可能复用错误正文

- 位置：Task 3 只提到 snapshot ID、prompt hash 和 batch state；未明确 output mode、provider、model、rules hash 和编译器版本必须参与身份校验。
- 风险：同一 snapshot 在 structured、plain_text、不同 provider 或修改过 book.rules.md 后可能误复用旧章节。
- 场景：先用 MiniMax structured 模式生成失败状态，再切换 plain_text 并执行 `--resume`；系统错误地把旧结果当作新模式结果。
- 整改：定义不可变 `run_signature = snapshot_id + scope + output_mode + provider + model + rules_hash + prompt_version + compiler_version`，任何字段变化都必须新建 run，禁止 resume。

### ② 重大隐患

#### M1：plain-text 正文缺少可量化质量门

- 位置：Task 2 只要求“可读性”和非空正文，Task 4 仍主要验证结构和 provenance。
- 风险：纯文本可以是重复、空泛、截断或只复述一个页面，但仍被标记 complete。
- 场景：模型返回 200 字泛化介绍，编译器成功包装全部 source_page_ids，自动验收 pass，但 Book 实际没有覆盖知识内容。
- 整改：增加最小正文长度、截断标记、重复率、标题/段落结构、输入页面覆盖抽样和禁用占位符检查；人工抽样仍可不作为硬阻塞，但自动硬门必须拒绝明显无效正文。

#### M2：预算估算没有明确重试预留和批次前置阻断

- 位置：Task 3 仅写“调用数不超过 358”，未定义每批的 worst-case calls 和剩余预算判断。
- 风险：179 次最低调用加上网络重试、空响应重试后可能超过上限，执行中途才耗尽预算。
- 场景：前 100 章平均每章 1.3 次调用，剩余预算不足以完成下一批，但系统仍启动新批次。
- 整改：每批开始前计算 `minimum_calls`、`retry_reserve`、`remaining_budget`；不足时在首次 provider 调用前阻断。每批只允许消耗 manifest 分配的预算。

#### M3：900 秒批次边界没有可执行的停止语义

- 位置：Task 3“每批 10～15 章”“每批独立执行”，但未明确 compiler 如何在章节之间停止。
- 风险：代码仍可能在一个进程内处理完整 179 章，重新触发本次运行时问题；或在章节中途退出而没有清晰状态。
- 场景：batch-size=15，但第 15 章请求开始时已接近超时，进程被杀死，state 既没有 complete 也没有可重试标记。
- 整改：增加明确的 `batch_id`/`batch_cursor` 和“下一章调用前检查 deadline”；超过 deadline 不再发新请求，保存 `pending` 状态并正常退出。

#### M4：provider 能力与输出模式没有真正闭环

- 位置：方案提出 provider capability，但 Compatibility Contract 没有定义能力来源、缓存和 unknown 的实际行为。
- 风险：实现者可能继续向 MiniMax 发送 `json_object`，或在 plain_text 模式下误走旧解析器。
- 场景：CLI 传入 `--output-mode plain_text`，compiler 仍使用旧 `parse_llm_json`，导致本次错误重现。
- 整改：在 compiler 入口做显式模式分派；plain_text 分支的测试必须断言没有调用 JSON parser；structured 分支保持旧测试不变。

#### M5：人工抽样不是硬阻塞，但没有定义最低质量阈值

- 位置：方案把人工 review 定为非硬阻塞。
- 风险：结构自动验收通过后，低质量正文仍可被 apply-from 发布。
- 场景：179 章全部形式上 complete，但抽样发现大量重复、乱码或明显偏题；由于人工结果不影响发布，仍然进入 Book。
- 整改：保留人工 review 非硬阻塞，但增加“发布建议”阈值：抽样失败超过阈值时 release 状态为 `quality_warning`，要求显式二次确认，不自动 apply。

#### M6：source coverage 的验收口径未固定

- 位置：Goal 使用 1255/1255，plain-text section 又将所有 page IDs 统一挂载。
- 风险：页面计数覆盖与正文事实覆盖混为一谈，导致审计报告无法说明“全量”到底完成了什么。
- 场景：manifest 显示 coverage=1.0，但 170 页内容只存在于 metadata，没有在正文中出现可检验的要点。
- 整改：manifest 分开记录 `page_assignment_coverage`、`body_generation_coverage` 和可选的 `content_evidence_sample_coverage`，禁止用一个 coverage_ratio 覆盖三种含义。

#### M7：并发/多进程写入冲突未覆盖

- 位置：Task 3 引入跨进程 resume，但未规定锁粒度和单 writer 规则。
- 风险：两个终端同时 resume 同一 run，互相覆盖 batch state 或重复调用。
- 场景：操作者误开两个命令窗口；两个进程都认为同一批次未完成，同时发送相同章节请求。
- 整改：run 级锁 + batch claim 状态；已有运行锁时 fail-closed，并输出当前 PID、run ID 和恢复命令。

#### M8：失败章节的重试分类不完整

- 位置：Task 3 只区分 transport retry 和内容格式；plain text 模式新增了截断、空正文、模型拒答、违规内容等类型。
- 风险：不可恢复错误被重复调用，浪费预算；可恢复错误又被永久标记 failed。
- 场景：MiniMax 返回 `<think>` 加正文，当前清洗器未处理，系统把可修复响应判为失败并重试。
- 整改：定义有限状态：`retryable_transport`、`retryable_empty`、`terminal_invalid`、`terminal_policy`、`complete`；每一类对应唯一动作和最大次数。

### ③ 优化疏漏

#### O1：没有明确 live canary 的通过标准

- 位置：Task 5“检查正文可读性、失败率、实际调用数”。
- 风险：小批量结果好坏依赖主观判断，无法自动决定是否进入全量。
- 整改：规定 3～5 章全部 complete、0 个结构/截断错误、0 个 provider 错误，且人工抽样通过后才能放行。

#### O2：没有指定失败响应和敏感日志的保留策略

- 位置：Task 5 仅写 release evidence。
- 风险：诊断需要原始响应，但原始响应可能含外发内容；长期保留又扩大数据暴露面。
- 整改：失败响应默认只保留 hash、错误类型和最小脱敏片段；原文按本地保留期限清理，禁止进入 Git。

#### O3：没有明确 output mode 的 WebUI/manifest 向后兼容字段

- 位置：Files and Responsibilities 未列出 manifest schema 版本变化。
- 风险：WebUI 读取旧 release 时假设字段必有，导致旧 pilot 无法显示。
- 整改：新增字段全部 optional；manifest 增加 schema version；旧 release 缺字段时按 structured/pilot 默认解释。

#### O4：没有把“provider 配置已加载”与“provider 可实际生成”区分开

- 位置：preflight 仍可能只验证 provider 名称和配置存在。
- 风险：API key 存在但模型、endpoint 或 response timeout 不可用，真实批次才发现。
- 整改：不做大规模调用前，增加一次显式小批量 canary；preflight 只做无网络检查，不能宣称 provider ready。

## 五、终局思维审计

从最终发布结果倒推，必须回答：

1. 最终唯一的 preview release 在哪里生成？当前方案没有明确 finalize seam。
2. apply-from 如何证明 179 章来自同一 snapshot、同一 prompt 版本和同一 provider？当前缺少 run signature。
3. 进程在第 90 章崩溃后，下一次如何知道第 90 章是否可复用？当前状态字段和 pending/failed 语义不够完整。
4. 发布后 WebUI 看到的是哪个 release？方案未明确旧 pilot 与新 full release 的默认选择字段。
5. 如果正文质量不合格，如何阻止发布？当前自动质量门过弱，人工 review 又不硬阻塞。

终局判定：方案已经保护了“不能错误切 CURRENT”和“不能自动更新 LanceDB”，但还没有充分证明“最终必然得到完整且有用的 Book”。

## 六、系统思维审计

### 正向闭环

```text
Wiki snapshot
  -> deterministic chapters
  -> provider text generation
  -> compiler metadata injection
  -> batch state
  -> final release acceptance
  -> apply-from
  -> CURRENT
```

### 系统性断点

- provider 输出模式与 compiler parser 之间仍存在契约断层；
- batch state 与 release manifest 之间缺少 finalize 连接；
- resume 身份与 prompt/provider/model 配置之间缺少不可变绑定；
- 全局 retry/circuit breaker 与 batch budget 之间没有明确预算协调；
- 人工 review、自动 acceptance 和发布状态之间没有统一的质量决策模型；
- 多进程 resume 的锁和 claim 状态没有闭环。

这些断点说明问题不是单个提示词，而是跨模块状态机没有完整定义。

## 七、第二轮压力测试

| 故障路径 | 连锁反应 | 当前兜底 | 判定 | 必须加固 |
|---|---|---|---|---|
| MiniMax 返回纯文本 | JSON parser 失败，章节 failed | plain-text 方向可修复 | 部分覆盖 | 明确 compiler 分支和正文校验 |
| MiniMax 返回空/截断正文 | 重试消耗预算，仍可能 partial | 有 batch state | 部分覆盖 | deadline 前置检查、重试分类 |
| 429/5xx 连续发生 | batch 运行时耗尽 | 全局 retry | 不足 | batch 预算和时间预算联动 |
| 进程在章节中途崩溃 | state 与 release 不一致 | resume | 不足 | pending/claim/finalize 状态机 |
| 两个进程同时 resume | 重复调用、互相覆盖 state | 未定义 | 未覆盖 | run lock + batch claim |
| book.rules.md 在批次间变更 | 旧正文与新规则混合 | 未定义 | 未覆盖 | rules hash 纳入 run signature |
| provider/model 在批次间变更 | 内容风格和契约漂移 | 未定义 | 未覆盖 | provider/model 纳入 run signature |
| source Wiki 在批次间变更 | provenance 和正文不一致 | snapshot ID | 部分覆盖 | 每批校验 snapshot，变更即新 run |
| 全部章节结构 complete 但正文空泛 | 低质量 Book 被发布 | 人工 review 非硬阻塞 | 不足 | 自动质量门 + quality warning |
| apply-from 指向 partial release | 错误发布 | 现有 promotion gate | 已覆盖 | 增加 finalize-only release 类型 |
| LanceDB 更新失败 | Book 与向量状态不同步 | 独立操作 | 已覆盖 | 发布后明确 vector status |

压力测试结论：原方案的 rollback 设计能防止数据灾难，但不能保证任务最终成功；需要把“可恢复”进一步定义为“可恢复到同一个 release 构建上下文”。

## 八、必须整改的方案增补

进入编码前必须把以下内容写入原方案：

1. **Run manifest**：固定 `snapshot_id/scope/output_mode/provider/model/rules_hash/prompt_version/compiler_version/budget_cap`。
2. **Finalize release**：batch state 只存章节结果；全部完成后才生成唯一 complete preview release。
3. **Resume signature**：任一运行上下文变化都禁止 resume。
4. **Plain-text contract**：明确不经过 JSON parser，正文清洗、截断、空响应和 `<think>` 处理规则。
5. **质量硬门**：非空、未截断、最小长度、重复率、占位符和章节正文完整性检查。
6. **预算硬门**：每批开始前检查最低调用数、重试预留和剩余预算。
7. **批次锁**：单 run 单 writer，重复运行 fail-closed。
8. **Canary gate**：3～5 章全部通过后才允许全量；canary 失败不影响 pilot。
9. **旧路径回归矩阵**：`book build`、pilot、legacy structured、`apply-from`、WebUI 旧 release 全部验证。
10. **发布证据**：记录唯一 preview release ID、manifest hash、snapshot ID、调用数、质量门结果和 vector status。

## 九、四角度最终评分

| 角度 | 评价 | 结论 |
|---|---|---|
| 第一性原理 | 正确隔离 LLM 与 compiler，但正文语义覆盖定义不足 | 7/10 |
| 批判性思维 | 已解决 JSON 失败方向，但遗漏 finalize、resume identity、质量门 | 5/10 |
| 终局思维 | 能防止误发布，尚不能证明最终必得 complete Book | 5/10 |
| 系统思维 | 兼容性边界清晰，但跨模块状态机仍有断点 | 6/10 |

综合判断：**6/10；整改后有较大概率达成原始目标，按当前文本直接实施则不能判定达标。**

## 十、第一轮审计结论（已完成整改）

审计状态：`整改后复审`。

批准进入下一阶段的条件：完成第八节 10 项增补，并重新执行第一轮漏洞审计；至少用 fake provider 完成一次“中断 → resume → finalize → apply-from”的全链路测试后，才允许进入 MiniMax 小批量 canary。

当前不批准：

- 直接全量真实 preview；
- 对 partial release 执行 apply-from；
- 将人工 review pending 状态忽略为质量通过；
- 修改 pilot 或全局 structured provider 行为。

## 十一、第二轮压力测试与整改后复审

### 11.1 压力测试矩阵

| 场景 | 预期行为 | 整改后判定 |
|---|---|---|
| provider 返回 Markdown、数组、空响应或截断文本 | plain-text 分支不走 JSON parser；空/截断/无效正文进入有限状态，不写 complete | 通过 |
| 429/5xx 或单次响应超时 | 仅按有限 retry 分类处理；每次请求前检查 deadline 和剩余预算 | 通过 |
| 进程在章节中途崩溃 | 已完成章节持久化；未完成章节为 pending；下次只能 resume 同一 run | 通过 |
| 两个进程同时 resume | run 级锁和 batch claim 只允许一个 writer，另一个 fail-closed | 通过 |
| provider/model/rules/prompt/output mode/config 变化 | `run_signature` 不一致，禁止复用旧 state | 通过 |
| 批次完成但没有全部章节 | 只能停留 staging，不能形成可提升 release | 通过 |
| 所有章节形式完成但正文低质 | 200 字、2 段、截断/占位符/控制字符/重复率硬门拒绝 complete | 通过 |
| batch state 直接传给 apply-from | 只接受 finalize 生成的 complete release | 通过 |
| snapshot 在 preview 后变化 | finalize/apply-from 重新校验并拒绝漂移 | 通过 |
| canary 失败 | 立即停止新 full-scope 路径，不影响旧 pilot | 通过 |

### 11.2 整改结果

本轮已将以下原先存在的解释性条款改为可执行约束：

1. 增加 `run_schema_version` 和不含 API key 的 `provider_config_fingerprint`，并纳入 `run_signature`；
2. 明确 batch state 与 publishable release 的边界，只有 `finalize` 才能生成唯一 complete preview release；
3. 固化 `--max-batches 1` 的真实停止语义，deadline 检查发生在每次 provider 请求之前；
4. 固化预算公式：`minimum_calls = unfinished_chapters`，`retry_reserve = unfinished_chapters * (max_attempts - 1)`，所有 transport retry 计入 `max_attempts`，预算不足在首次调用前阻断；
5. 固化正文质量硬门：去空白后至少 200 字、至少 2 段、无截断/占位符/异常控制字符，重复段落比例不超过 50%；
6. 固化 canary 放行：3～5 章全部完成，0 个 provider/超时/截断/格式/质量失败，0 次重复调用，并完成一次人工抽样。

### 11.3 整改后复审结论

四个角度复审结果：

- 第一性原理：通过。LLM 只负责正文，结构、provenance、完整性和发布由 compiler 控制；
- 批判性思维：通过。已覆盖最可能导致重复计费、状态污染和错误发布的故障路径；
- 终局思维：通过。已能从 1255/1255、179/179 倒推至唯一 preview release，再由 `apply-from` 原子切换；
- 系统思维：有条件通过。旧路径隔离、批次状态、预算、锁和发布门禁已闭环，但实现阶段仍必须提供测试证据。

最终评分：**8.5/10，方案可进入编码整改和 fake-provider 验证；尚未批准直接进行 MiniMax 全量调用。**

复审状态：`通过（带实现证据前置条件）`。

进入真实 canary 前必须完成：

- fake provider 的“中断 → resume → finalize → apply-from”链路测试；
- deadline、预算预留、锁、签名漂移、质量硬门和 finalize-only 测试；
- 原有 structured/pilot/legacy 路径回归测试。
