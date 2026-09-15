# V7 文档抽取：确定性脚本与真实 LLM 职责边界调研

日期：2026-09-14  
范围：`src/pipeline/v7_extract/`、`scripts/extract_pilot.py`、`scripts/extract_full.py`、V7 测试、LLM provider 接口、V7 计划与现有试点/全量报告。  
约束：本次只读调研；未调用真实 LLM，未提交 Git。

## 结论摘要

当前 V7 的正确方向不是“全部交给 LLM”，而是把流程拆成三类：

1. **确定性脚本负责不可争议的结构、边界和副作用**：文件枚举与稳定抽样、编码读取、标题/章节/列表/时间戳计数、承诺数量与实际数量比较、JSON/schema/ID/引用关系校验、幂等去重、checkpoint、原子写盘、review 阻断和审计日志。
2. **真实 LLM 负责语义判断与内容生成**：低置信度文档分类、多主题边界与主题命名、概念去重的语义候选判断、五个概念槽位的来源约束填充、`refines`/`supported_by` 的语义关系判断。
3. **分类、主题和槽位必须双重校验**：LLM 只提交候选结构；确定性校验检查闭集、覆盖率、数量、来源证据、非空/非占位内容和跨字段一致性。任何校验失败都不能直接写入生产 Wiki，应进入重试、降级或人工 review。

当前实现距离这个边界还有明显缺口：

- `scripts/extract_pilot.py` 只调用无 `llm` 的 Stage 1/3/4/5 规则路径（`scripts/extract_pilot.py:100-130`），所以现有 pilot 实际是规则-only dry-run。
- `classify_doc()` 虽然接受 `llm`，但低置信度分支最终仍原样返回 heuristic（`src/pipeline/v7_extract/doc_classifier.py:240-260`）；Stage 1 的真实 LLM 分类尚未落地。
- Stage 4/5/6 已有 LLM 调用入口，但没有足够的语义质量门：主题只做有限的 item-id 过滤，槽位缺失时会静默填入模板式 fallback，关系抽取只做闭集和自环过滤（分别见 `topic_clusterer.py:81-105`、`slot_filler.py:79-119`、`relation_extractor.py:46-57`）。
- `AnthropicLLMClient.complete()` 把底层 provider 的 `LLMResponse` 对象直接返回（`src/pipeline/v7_extract/llm_client.py:139-159`），而 V7 阶段按字符串调用 `json.loads(str(response))`；底层 provider 契约明确返回 `LLMResponse`（`src/llm/base.py:7-19,26-67`）。真实 LLM 接入前必须先统一为 `response.content` 或改 V7 client 契约，否则 JSON 解析会把 dataclass 表示当作模型 JSON。

最重要的现实证据是现有 pilot 报告：50 个来源中 43 个被判定完整、生成 60 个 dry-run 页面，但 10 个严格人工抽查只接受 1 个（10%，门槛 80%），报告明确判定规则-only 主题和 fallback 槽位不可用于生产（`docs/superpowers/reports/2026-09-13-extract-pilot-report.md:3-10`）。因此当前不应进入 full apply；全量报告也明确保持 dry-run 且等待 pilot 审批（`docs/superpowers/reports/2026-09-14-extract-full-report.md:3-11`）。

## 一手代码证据与职责判定

### 1. 文档枚举、抽样、可重放：确定性脚本

`extract_pilot` 的职责应保持纯确定性：

- 只接受规定后缀并递归枚举 `raw/sources`（`scripts/extract_pilot.py:29,78-86`）。
- 使用显式 seed 的局部 RNG 抽样并排序结果，保证同一输入可复现（`scripts/extract_pilot.py:89-97`）。
- 每个文件独立处理，单文件异常转成结果中的 `error`，不让一个坏文件中止 pilot（`scripts/extract_pilot.py:100-160`）。
- pilot 只写请求的 JSON/Markdown 报告，不触碰 `wiki/`；这正是 dry-run 的安全边界（模块说明 `scripts/extract_pilot.py:1-5`，报告写入 `:71-75,237-241`）。

这些行为不需要 LLM。若交给 LLM，会损失可重放性，却不会增加语义准确性。

### 2. 文档分类：规则预筛 + 低置信度 LLM + 确定性闭集复核

V7 定义了七个互斥 `DocType`（`src/pipeline/v7_extract/doc_classifier.py:31-45`），分类错误会级联影响后续结构、主题和页面（模块说明 `:1-22`）。

应由脚本承担的部分：

- 文件名提示、空/标题-only、工具标记、聊天时间戳、编号列表、作者数、命名章节和 Markdown 标题计数（`doc_classifier.py:113-176`）。
- 分类结果的闭集校验：只能是七个 `DocType`，置信度必须在 `[0,1]`，并保留 rationale。
- 规则高置信度结果直接通过；规则低置信度结果才进入 LLM。

应由真实 LLM 承担的部分：

- 仅对结构信号冲突、边界模糊或规则置信度低于阈值的文档判断“主导结构/用途”，输出 `doc_type`、简短理由和可选置信度。
- LLM 不得新建类型，也不得改变确定性识别出的文件边界。

当前实现的阻断项是：`classify_doc()` 声明“低置信度交给 LLM”，但 `llm` 存在时仍直接返回 heuristic；注释也明确称真实 prompt 尚未实现（`doc_classifier.py:247-260`）。现有测试只证明规则 fixture 命中和“无 LLM 时保持 heuristic”（`tests/test_pipeline/test_v7_extract_doc_classifier.py:409-478`），没有证明真实 LLM 分类路径。

推荐双校验：

1. LLM 输出必须通过 JSON 解析、七值闭集和文档级结构约束。
2. LLM 分类与规则分类一致时接受；不一致时不让任一方静默覆盖，进入“分类冲突”人工队列或二次 LLM 复核。`incomplete`、`tool`、`qa_chat` 这类会改变后续切分方式的类型应提高为强校验项。

### 3. 完整性判断：确定性硬门 + LLM 只处理语义模糊处

确定性脚本应负责空内容、`incomplete` 硬拒绝、标题承诺数量与实际编号/章节数量比较、intro-only 标记和按类型的最小长度门槛（`src/pipeline/v7_extract/completeness_checker.py:57-79`）。这些是可审计的硬事实。

真实 LLM 可以处理“文本够长但语义上明显截断”“标题承诺与正文表达不规则”等模糊情况。当前接口确实只在 heuristic 拒绝且不是 `DocType.INCOMPLETE` 时尝试 LLM，并在 LLM 不可用/格式错误时回退 heuristic（`completeness_checker.py:36-54`）；LLM 结果也只接受布尔值 `complete` 和字符串理由（`completeness_checker.py:104-153`）。

建议保留 fail-closed 原则：确定性硬拒绝（空、明确正文缺失、`incomplete`）不能由 LLM 擅自放行；只有“长度/结构信号冲突”的软拒绝才允许 LLM 提议覆盖，并要求同时满足来源证据和人工抽样门槛。当前测试覆盖了规则拒绝、承诺数量缺口和一个 fake LLM 确认案例（`tests/test_pipeline/test_v7_extract_completeness_checker.py:29-89`），但尚未覆盖 LLM 覆盖错误拒绝的反例。

### 4. item 切分与结构保留：确定性脚本

`extract_pilot._extract_items()` 按 Markdown 标题或至少三个编号项切分，否则保留整篇为一个 item（`scripts/extract_pilot.py:163-179`）。item ID 直接包含来源相对路径和 section/item 序号，因此应由脚本生成并冻结，供 LLM 引用。LLM 可以解释 section 的语义，不应重新发明 item ID、修改字符边界或丢弃未分配 item。

### 5. 主题聚类：LLM 负责语义，脚本负责约束、覆盖和回退

主题是当前准确性瓶颈之一。`cluster_topics()` 已将 LLM 作为可选输入，并在没有有效结果时回到关键词 bucket（`src/pipeline/v7_extract/topic_clusterer.py:35-55`）。LLM prompt 要求输出 3-5 个主题和 item assignments（`:61-74`）。

脚本应负责：

- 输入 item 标准化和稳定 ID（`:48,142-149`）。
- 过滤未知 item、去重 item assignment，保证每个 item 至少被覆盖一次（`:81-98`）。
- 限制主题数量，短文不制造空主题，大批量文档保留 3-5 的边界（`:99-106`）。
- LLM 失败时使用规则回退；规则回退只应标记为低置信度候选，不应被当作生产语义结果（`:109-139`）。

真实 LLM 应负责：

- 判断主题边界、主题粒度、主题名称和同一主题下 item 的语义归属。
- 对章节型、清单型、聊天型文本区分“文档结构”与“知识主题”，避免把整篇压成“综合主题”或把标题词误当主题。

双重校验必须增加以下验收逻辑：

- item 覆盖率 = 被至少一个主题覆盖的唯一 item / 输入 item，要求 100%；重复归属需显式允许并记录。
- 主题数与类型约束符合文档策略；“综合主题”不是默认成功，而是低信息量告警。
- 每个主题至少有可解释的证据 item；主题标题不能只来自固定关键词命中。
- LLM 与规则/第二次独立 LLM 的主题边界不一致时进入 review，而不是直接采用首个响应。

现有 Stage 4 测试证明 103 个桥段能被规则 fallback 限制在 3-5 个主题且 item 不丢失，也证明 fake LLM assignment 可被接受（`tests/test_pipeline/test_v7_extract_stage4.py:19-52`）；但没有主题语义 gold label、边界准确率或“综合主题”告警指标。这与现有 pilot 的失败相符：五阶段被合并成“综合主题”、泛主题被过度拆分（`docs/superpowers/reports/2026-09-13-extract-pilot-report.md:16-23`）。

### 6. 概念去重：脚本做 ID/合并，LLM 做语义候选

确定性部分已较清楚：按 ID 或规范化标题匹配已有概念，合并 source IDs，保留首次 body，并给新冲突 ID 添加稳定数字后缀（`src/pipeline/v7_extract/concept_deduplicator.py:20-52,73-91`）。这部分必须由脚本执行，保证幂等。

LLM 只应回答“两个不同标题是否表达同一概念、是否为上下位/细化关系”，并返回候选及理由。脚本随后复核 source evidence、已有 ID、标题规范化结果和人工阈值；低于计划中的 85% 去重准确率门槛就进入 review queue，而不是自动合并。计划已将 103 桥段、已有 `kuo-ju-fa` 合并和 ≥85% 去重准确率列为 Stage 4 验收项（`docs/superpowers/plans/2026-09-13-novel-wiki-v7-template-extraction-pipeline.md:156-178`）。

### 7. 五个槽位：LLM 填内容，脚本锁结构、来源和非占位质量

五个概念槽位的名称是确定性契约：`definition`、`characteristics`、`examples`、`related_concepts`、`references`（`src/pipeline/v7_extract/slot_filler.py:14-20`）。

脚本应负责：

- 只允许契约中的槽位，丢弃模型发明的 key（`:79-83`）。
- 检查每个必填槽位非空、类型正确、无 JSON 污染、无 `slot:` marker、references 与来源 ID 可追溯。
- 对每个槽位保留 evidence span 或 source item ID；无法证实时填 `unknown/not_found` 状态并阻止自动发布，而不是伪造自然语言。
- 模板渲染、槽位顺序、页面 ID、页面类型和写盘由脚本负责（`ConceptPage.body`：`:31-56`；writer frontmatter：`wiki_writer.py:101-113`）。

真实 LLM 应负责：

- 从主题 item 和来源文本中抽取定义、特征、例子和相关概念，并在来源范围内做简洁归纳。
- 不能补写来源没有的事实；当前 prompt 已有“禁止编造来源事实”约束（`slot_filler.py:94-105`），但这不是可验证的质量门，必须配合 evidence 校验。

当前 fallback 是最大风险：缺失槽位会自动变成“需结合原文核对”“来源未提供……”等看似非空的文本（`slot_filler.py:147-157`）。这满足“字段非空”，却不满足“内容可用”；pilot 已观察到槽位只是 fallback 文本（`docs/superpowers/reports/2026-09-13-extract-pilot-report.md:21-23`）。因此 fallback 应改为显式状态，不计入成功页面。

双重校验建议：

1. 第一层：JSON/schema、五槽位完整性、字符串长度、禁止占位短语、source item ID 存在性。
2. 第二层：逐槽位 evidence entailment/覆盖检查。可以由确定性文本匹配先筛查，再对只剩模糊案例使用第二次 LLM judge；judge 不能直接生成正文。
3. 任一槽位证据不足，页面状态为 `needs_review` 或 `partial`，不进入自动写盘。

现有测试只验证五个 key 非空、fake JSON 能覆盖槽位、缺槽位会填 fallback 且不泄漏额外 key（`tests/test_pipeline/test_v7_extract_stage5.py:12-57`）；它没有把 fallback 与真实内容区分，也没有 evidence 精度/召回测试。

### 8. 关系抽取、写盘和安全：确定性门控优先

关系语义可交给 LLM，但输出必须经脚本闭集校验：只允许 `refines`/`supported_by`，过滤未知页、自环并去重（`src/pipeline/v7_extract/relation_extractor.py:12,37-57,60-101`）。现有 heuristic 只能依据标题/槽位字符串命中和少量 marker 推断关系（`:104-121`），应作为低置信度降级，不应假装等价于 LLM 语义关系。

写盘绝不应由 LLM 决定。`WikiWriter` 已具备 content filter 阻断、checkpoint、重试、原子写入、index 和 audit 行为（`src/pipeline/v7_extract/wiki_writer.py:49-99,101-113,137-172`）；敏感命中进入 review queue（`src/pipeline/v7_extract/content_filter.py:48-89`）。这些是确定性副作用边界，应在所有 LLM 失败路径之后仍然有效。

## 推荐 V7 流水线

```text
读取/哈希/稳定 item 边界（脚本）
        |
规则分类 + 规则完整性硬门（脚本）
        |-- 高置信度且无冲突 --> 继续
        `-- 低置信度/冲突 --> LLM 分类 --> 闭集 + 规则交叉校验 --> review 或继续
        |
结构切分与数量检查（脚本）
        |
LLM 主题聚类/命名/归属
        --> item 100% 覆盖、主题数量、证据 item、综合主题告警（脚本）
        --> 冲突时二次 LLM judge 或人工 review
        |
确定性 ID/标题候选去重（脚本）
        --> 语义同义候选由 LLM 判断
        --> 幂等合并/冲突后缀/人工门（脚本）
        |
LLM 填五个槽位
        --> schema/非空/非占位/source evidence 双校验（脚本 + judge）
        |
LLM 关系候选
        --> 闭集/存在性/自环/去重校验（脚本）
        |
内容安全 review --> 原子写盘 + checkpoint + audit（脚本）
```

推荐把每个阶段的输出分成 `candidate` 与 `validated` 两种状态。只有 `validated` 才能进入下一阶段；规则 fallback 产生的结果应带 `fallback_reason` 和低置信度，不应因为“字段有值”而伪装成 validated。

## 失败降级策略

| 失败类型 | 自动动作 | 是否可写生产 Wiki |
|---|---|---:|
| 文件不可读/编码异常 | 单文件记录 `error`，继续 batch；保留 source hash | 否 |
| 规则分类高置信度 | 直接采用规则结果，记录 rationale | 是，仍过 schema gate |
| 分类低置信度且 LLM 不可用 | 保留 heuristic candidate，标记 `needs_review` | 否 |
| LLM 分类 JSON/闭集/交叉校验失败 | 一次受限重试；仍失败进入 review | 否 |
| 主题 LLM 超时/格式错 | 规则主题仅用于 dry-run/人工辅助，标低置信度 | 否 |
| 主题 item 未覆盖或主题数越界 | 用未分配 item 的确定性回收；仍不满足则 review | 否 |
| 槽位缺失/仅 fallback/无证据 | 不把 fallback 当成功；页面置 `partial`/`needs_review` | 否 |
| 关系未知目标/自环/非法类型 | 丢弃非法边并记录计数；不影响页面主体 | 页面可写，但关系不写入 |
| provider 超时/429/5xx | 使用 provider/factory 的 retry；达到上限保存 candidate，不覆盖旧 Wiki | 否 |
| provider 没有默认配置或契约不匹配 | 启动前 fail-closed，提示配置/适配错误 | 否 |
| 内容安全命中 | 进入 review queue，writer blocked | 否，直到人工通过 |
| 写盘失败 | 按 writer 的 3 次重试和 checkpoint 记录 failed；不更新成功索引 | 否 |

provider 层已经提供统一 `LLMProvider.complete(messages, ...) -> LLMResponse` 和 `truncated` 信号（`src/llm/base.py:7-19,26-67`），factory 会统一包裹 retry/breaker（`src/llm/provider_factory.py:17-49`）。V7 适配层应使用这一契约，明确提取 `.content`、保留截断/usage/模型信息，并把解析失败与网络失败分开计数。Anthropic provider 的 `complete()` 也明确构造并返回 `LLMResponse`（`src/llm/anthropic_provider.py:67-170`）。

`FakeLLMClient` 适合作为单元测试 seam：按 `prompt_kind` 返回脚本响应并记录调用（`src/pipeline/v7_extract/llm_client.py:67-105`），现有测试已覆盖 abstract contract、FIFO 和 calls log（`tests/test_pipeline/test_v7_extract_llm_client.py:21-81`）。但 fake 不能证明真实 provider 的 response adapter、截断、超时或 retry 行为；这些需要 provider fake/HTTP fixture 的集成测试，仍不需要调用真实 LLM。

## 验收指标与门槛

现有计划给出了基础门槛：14 个分类样本（9 个已知 + 5 个盲测）≥90%，完整性覆盖 ≥80%（计划 `:125-149`）；103 桥段主题数 3-5、概念去重 ≥85%（`:156-178`）；五槽位准确率 ≥85%、`refines`/`supported_by` ≥80%、写盘失败重试和 checkpoint/audit（`:185-218`）；pilot 10 篇 spot-check ≥80%（`:222-246`）；全量写盘失败 <5%、反向索引 100%、预算 < $200（`:250-274`）；后续 A/B 准确率 ≥80%、召回率 ≥75%（`:304-323`）。

建议把验收改成可阻断发布的分层指标：

| 层 | 指标 | 建议门槛 |
|---|---|---:|
| 分类 | gold/盲测 exact accuracy | 已知 + 盲测 ≥90%；高风险类型（`tool`/`qa_chat`/`incomplete`）≥95% |
| 分类 | 规则与 LLM 冲突率 | 100% 被记录；0 个未 review 冲突进入生产 |
| 完整性 | false accept（截断文档被放行） | 0 |
| 完整性 | gold recall | ≥95%；边界样本单独报告 |
| 主题 | item 覆盖率 | 100% |
| 主题 | gold topic assignment / boundary accuracy | ≥85%；“综合主题”误用率 ≤5% |
| 主题 | 主题数量约束 | 100% 满足文档策略，越界 0 发布 |
| 槽位 | 五槽位 evidence-supported precision | ≥90% |
| 槽位 | 必填槽位 coverage | 100%；但 fallback 不计为成功 |
| 槽位 | 无来源事实/幻觉 | 0 个高置信度发布项；抽样发现即阻断该批 |
| 去重/关系 | 去重准确率；关系类型准确率 | 分别 ≥85%、≥80% |
| 可靠性 | provider parse/truncation/retry 测试 | 100% 有明确分类和降级，不丢 batch 状态 |
| 写盘 | 新写入 schema/安全/索引/审计 | schema 违规 0；反向索引 100%；audit 100% |
| 端到端 | 10 篇严格 spot-check | ≥80% 才允许扩大 pilot；pilot 未达标不得 full apply |

验收样本必须同时包含当前报告已经暴露的反例：五阶段教程、短但有实质内容的文档、作者职业生涯、语言规范、冲突/高潮/节奏复合主题、聊天记录和 20 条清单。仅用现有 7 个 synthetic classifier fixture 会高估规则准确性：测试声称 7 个 fixture 100% 命中（`tests/test_pipeline/test_v7_extract_doc_classifier.py:423-434`），但真实 50 篇 pilot 的严格接受率只有 10%。

## 对现有计划/验收记录的判断

计划将 Task 4-8 按“分类/完整性 → 主题/去重 → 槽位/关系/写盘 → pilot → full”拆分，方向正确（`docs/superpowers/plans/2026-09-13-novel-wiki-v7-template-extraction-pipeline.md:125-274`）。但当前状态证据仍显示：

- 计划中的 LLM fallback 与真实语义提取，代码目前只部分接入或仍为占位。
- Task 7 的实际 spot-check 已严重低于 80% 门槛，且失败模式正好集中在分类边界、主题语义和槽位可用性，而不是写盘可靠性。
- Task 8 的 full report 是 checkpoint 复用后的 dry-run 摘要，不是全量真实 LLM 质量验收；因此不能把“1362 个来源、0 errors、1480 pages”解释为内容准确率通过（`docs/superpowers/reports/2026-09-14-extract-full-report.md:3-11`）。
- 计划 Audit 仍把 human review 标为 pending，并把 LLM 成本、去重准确率和人工闸门列为开放风险（计划 `:395-407`）；completion evidence 也仍是 TBD/待补（`:411-443`）。

## 最小实施顺序建议

1. 先修 V7 provider adapter：`LLMResponse.content`、截断信号、异常分类和 fake provider 集成测试；在此之前不接真实 LLM。
2. 实现 Stage 1 真正的低置信度分类调用，并加入规则/LLM 冲突状态；保持高置信度规则路径不调用 LLM。
3. 将 Stage 4/5 的规则 fallback 改成显式低置信度 candidate；补 item 覆盖、主题证据、槽位 evidence 和非占位 gate。
4. 用不调用真实 LLM 的 fake/fixture 完成失败路径测试，再用受控的小样本真实 LLM pilot 做人工 gold 评估；只有严格接受率达到门槛才解锁 full apply。
5. full 阶段继续保留 `extract_full.py` 的 dry-run、500/批 checkpoint 和 retry；只有审批状态明确为 approved 时才允许写盘。当前代码已经在 `run_full(..., dry_run=False)` 直接阻断未批准 apply（`scripts/extract_full.py:32-48`），这个 fail-closed 约束应保留。

## 调研限制

- 本次未调用真实 LLM，也未修改代码或提交 Git。
- 本机 `C:\Python314\python.exe` 未安装 pytest，因此未执行 V7 定向测试；报告引用的是测试源码和已存在的 pilot/full 运行记录，不把测试“通过”作为本次新验证结论。
- graphify CLI 在本机出现 `uv trampoline failed to canonicalize script path`；按 graphify skill 的只读降级规则检查了现有 `graphify-out/graph.json`，但其当前 edges 为 0，故没有把图谱关系当作证据，最终结论均回到源码、测试和报告文件。
