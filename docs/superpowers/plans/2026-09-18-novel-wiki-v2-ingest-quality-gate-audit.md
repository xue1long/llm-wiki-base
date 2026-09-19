# novel-wiki-v2 摄取质量门修复方案审计报告

## 结论摘要

**结论：有条件通过，暂不批准直接编码。**

原方案能够修复本次实测中的一部分确定性结构问题，尤其是：

- concept 页面没有遵循项目 v3.0.0 模板；
- H2 将合法的路径型 wikilink 误报为断链；
- source/concept 同名被重复标题检查误报；
- `processing_depth=source` 在不同层的合法值不一致；
- 生成结果包含系统占位语。

但它还不能可靠达成“摄取质量改善且质量门结论可信”这一原始目标，原因是：

1. 方案没有闭合生产链路中的 `reconcile → gap ledger → batch gate → KC bundle/publication`；
2. 语义去重仍主要依赖 LLM Prompt，无法保证稳定结果；
3. 处理深度的修复方向可能把 `source` 错误暴露给 LLM 生成层；
4. 验收标准偏结构，缺少对原文覆盖度、事实性和证据绑定的可量化验证；
5. 方案文件中已有一个实际不存在的文件路径，说明还未达到可直接执行的精度。

综合判断：

| 目标 | 达成把握 | 判断 |
|---|---:|---|
| 修复当前样例的模板/占位/误报问题 | 75% | 基本可行，但需补齐实现入口 |
| 稳定合并重复概念、避免幽灵页 | 45% | Prompt 约束不足以保证 |
| 让各质量门对同一事实得出一致结论 | 40% | 目前仍漏掉 reconcile 和 batch gate |
| 不破坏 KC、向量、书籍编译链 | 35% | 缺少跨层一致性验收 |
| 提升实际知识摄取质量 | 50% | 结构有覆盖，语义质量指标不足 |

当前方案综合成熟度约为 **55%～60%**。达到编码门槛前，至少需要完成“必须整改项”。

## 一、第一性原理审查

### 1. 原始目标被拆得不够准确

知识摄取的第一性目标不是“让 `wiki-quality --strict` 返回 0”，而是：

> 在不制造事实、不丢失证据、不制造重复概念的前提下，把原文转换成可检索、可维护、可追溯的知识页，并让质量门准确区分结构错误、内容不足和外部知识缺口。

原方案把以下代理指标放得过重：

- 固定为 3 页；
- H2 普通 unresolved 为 0；
- lint 无错误；
- wiki-quality 结构检查通过。

这些指标能说明“页面可写入”，不能单独说明“知识正确”。例如，LLM 可以生成 3 个结构完整但事实遗漏或错误的 concept 页，原方案仍可能判定通过。

### 2. 样例页数不是通用真理

对本篇文档，`1 source + 2 concept` 是合理的目标输出。但这只是该文档的语义判断，不是所有教程文档的固定规则。

原方案已经声明不把 3 页硬编码到所有文档，但 Task 1 的断言仍然需要明确边界：它必须是“该 fixture 的 gold contract”，而不是通用 pipeline 规则。否则后续会出现“为了通过回归测试压缩长文档知识”的反作用。

### 3. 真正需要守住的不可违背约束没有完整写出

至少还应增加四条内容级不变量：

- `大纲四要素` 必须覆盖时间、地点、人物、主要内容四个要素；
- `大纲写作技巧` 必须覆盖大纲作为写作蓝图、避免失去方向等核心论点；
- concept 中的关键事实必须能回指 candidate evidence；
- 原文未提供的平台、作者、URL、案例不能由 LLM 补造。

没有这些断言，方案主要是在修“页面形状”，不是在验“知识质量”。

## 二、批判性思维审查

### A. 致命缺陷

#### F1：方案引用了不存在的实现文件

位置：Task 4 的 `src/pipeline/batch_gate.py`。

实际文件是：

`src/wiki/features/batch_gate.py`

后果：执行者按计划无法定位目标文件；更重要的是，这说明方案尚未完成真实调用链核对。

整改：把文件列表改成真实路径，并在 Task 4 同时明确 `src/pipeline/reconcile.py` 和 `src/wiki/features/target_resolver.py` 是否需要修改。

#### F2：质量门一致性链路没有闭合

位置：Task 4 只覆盖 H2、lint、batch gate 的部分内容，没有覆盖 `src/pipeline/reconcile.py`。

事实：

- H2 在 `src/maintenance/checks/h2_break_links.py` 判断断链；
- 摄取过程在 `src/pipeline/reconcile.py` 的 `collect_missing_slugs()` 写 gap ledger；
- batch precommit 在 `src/wiki/features/batch_gate.py` 的 `_gate_reconcile()` 再次判断；
- 这些检查不是同一个入口。

后果：即使 H2 不再把 `[[sources/foo]]` 报错，`collect_missing_slugs()` 或 batch gate 仍可能把同一个 target 记成 gap 或 broken-link。方案宣称“质量门得出一致结论”但没有覆盖所有判定者，目标无法闭合。

整改：把 `src/pipeline/reconcile.py` 纳入 Task 4，建立一个共享的 target classification/resolution 结果；至少覆盖：普通页、路径型页、别名、taxonomy、gap、ambiguous、unresolved。

### B. 重大隐患

#### M1：taxonomy 的规范表示没有做最终决策

方案同时提到：

- Prompt 规范使用 `taxonomy/<name>`；
- 现有 ingest normalization 写成 `taxonomy-<name>`；
- 测试已有 `taxonomy-写作技法` 契约。

但方案没有决定最终 canonical representation，也没有给出迁移/兼容策略。

后果：H2 可能不报错，但 gap ledger、关系反向边、书籍编译或旧测试仍可能把 taxonomy 当普通 page。修复后只是“换一个地方报错”。

整改：在编码前明确唯一规范：

- taxonomy 是命名空间对象，不是 wiki page；
- 明确磁盘 relation target 的 canonical 形式；
- `TaxonomyRegistry`、生成器、reconcile、H2、batch gate、书籍编译和旧页兼容都使用同一形式。

#### M2：`processing_depth=source` 的修复方向可能扩大 LLM 生成范围

原方案倾向于把 `source` 加入所有允许集合，以保留 deterministic source writer 的当前值。

但 `src/pipeline/generator.py` 的 `PROCESSING_DEPTH_VALUES` 同时用于 LLM response schema。若直接加入 `source`，LLM 就可能生成 source 类型页面，和系统“每次确定性追加一个 source 页”的设计冲突。

整改：不要简单把 `source` 加进 LLM 的 processing-depth enum。应区分：

- LLM 可输出的知识处理深度：`concept | memory | operation`；
- 系统确定性 source 页的内部存储值；
- lint/batch 对 page type 与 depth 的联合校验。

如果最终确实保留 `processing_depth=source`，必须增加联合谓词，明确“只有 `PageType.SOURCE` 可以使用 source”，并禁止 concept/entity/synthesis 使用它。

#### M3：语义去重没有确定性兜底

方案明确拒绝 fuzzy merge，只依赖 Prompt 合并 `小说大纲写作技巧` 和 `大纲写作技巧`。

这在原则上避免误合并，但在工程上没有解决“LLM 又返回变体页”时怎么办。方案只说进入 review/quarantine，却没有定义：

- 什么规则判定是语义变体；
- 如何记录候选的 merge decision；
- 质量门是阻断整批、丢弃变体，还是保留并标记人工复核；
- 下一次重试是否使用同一 decision。

整改：不必做通用 fuzzy merge，但至少要有确定性状态机：

1. 精确 id/title 重复：确定性去重；
2. 候选明确声明 canonical topic/alias：合并到 canonical；
3. 仅相似但无法证明同一：保留为 `NEEDS_HUMAN_REVIEW`，禁止标记为完全通过；
4. 记录被合并/被隔离的 page id 和理由。

#### M4：模板 fail-closed 的执行顺序未定义

当前 `render_body()` 对必填空槽位会插入占位语；`generate_from_candidate()` 又会执行 retry、autofill 和 placeholder cleanup。

原方案说“writer 前丢弃缺槽 concept”，但没有明确检查点：

- 在 `render_body()` 前检查 slot，还是之后检查 body；
- 清洗占位语后变成空段，是否重新检查；
- “来源未详述此方面”是合法缺失声明还是系统占位语；
- source 页和 concept 页是否使用不同的缺失策略。

后果：实现者可能只加一个 body 字符串扫描，导致空标题仍落盘，或者把合法的“来源未详述”误判为占位语。

整改：增加明确的 slot-level verdict：`FILLED | EMPTY | DECLARATIVE_ABSENCE | PLACEHOLDER`。只允许 `FILLED` 和明确允许的 `DECLARATIVE_ABSENCE` 写入；不要用最终 Markdown 字符串反推槽位状态。

#### M5：KC promotion 与 Wiki page 生成之间存在跨层不一致

当前流程在 `CandidatePromoter().promote()` 后才调用 `generate_from_candidate()`。也就是说，KC bundle 已经写入 `.index/kc/bundles/`，之后 concept 页面仍可能因为槽位、引用或模板检查被丢弃。

后果：

- KC 对象、Wiki 页面、Book 编译输入可能描述不同的事实集合；
- 任务表面上 source-only，但 KC bundle 仍认为对象已 ready/staged；
- 后续 recover/rebuild 可能重新发布被质量门丢弃的知识。

整改：在验收中加入 KC/Wiki 一致性：生成结果裁剪后，KC manifest 必须记录最终 page ids 和状态；失败时 bundle 保持 staged/quarantined，不得被 Book 当作已发布数据。至少增加 `CandidatePromoter → generate → commit → finalize` 的端到端测试。

#### M6：`source-only` 兜底没有覆盖所有失败点

方案只讨论“concept 缺槽位时 source-only”。但 candidate pipeline 在 generator 前还有：

- analyzer JSON 失败；
- candidate source_id 不匹配；
- CandidateReviewer rejected；
- CandidatePromoter 异常；
- evidence block 不可绑定。

其中部分路径会直接 `_reject_candidate()` 抛异常，而不是进入 source-only。

整改：先定义源页保证的边界：哪些失败允许 source-only，哪些必须任务失败并 quarantine；把它写成状态表，不能只在 Task 2 文字中描述。

#### M7：零 unresolved 不是普适正确目标

原文自然可能提到库中尚不存在的概念。把 `unresolved ordinary refs = 0` 作为样例验收，可以掩盖真实知识缺口，或诱导系统创建 ghost page。

整改：验收应要求：

- 不存在“未登记且未解释”的 unresolved；
- 合法 gap 必须进入 gap ledger，包含 source、page、reason；
- 本样例的 `提纲的重要性` 应不再产生 gap，是因为它被判定为本页小节，而不是因为质量门强行清零。

### C. 优化疏漏

#### O1：duplicate-title 修复不在 strict 的实际出口上

`wiki-quality --strict` 当前主要根据 structural checks、BOM、重复 frontmatter 和旧时间戳决定退出码；duplicate-title 只是报告项，并不影响 strict 退出码。

因此 Task 4 修 duplicate-title 统计并不能直接改变本次 strict gate 的通过结果。方案应说明它是诊断质量修复，而非 strict gate 的主因。

#### O2：Task 3 的“actual analyzer prompt module only if...”违反可执行计划要求

计划不应保留“如果是某模块就改某模块”的开放分支。编码前必须通过调用链确定到底是 analyzer 创建变体，还是 candidate renderer 扩张页面，并固定文件和测试。

#### O3：文档规范修复不应是条件项

`docs/guides/wiki-spec.md` 与 `docs/guides/novel-wiki-ingest-spec.md` 已经存在 wikilink 语法冲突，而这正是运行时和检查器分叉的背景。Task 4 将文档更新写成“only if tests reveal”，会让已知规范冲突继续存在。

整改：把文档统一列为必做项，并在测试中引用唯一规范。

#### O4：缺少幂等和重复摄取验收

原始实例的关键特性包含 md5 dedup、source hash、alias 和 index。方案没有要求同一文档连续摄取两次后页面数、page id、KC bundle、vector chunk 是否稳定。

整改：Task 5 增加二次摄取测试，要求不产生第二套 concept 变体、不重复写 source、不膨胀 gap ledger。

#### O5：缺少全库基线与增量目标

本次测试目录有 133 个 raw 文档。方案只验证一个临时项目，无法证明修复不会使已有页面批量变成新的 lint/H2 错误。

整改：记录修复前后全库 baseline，至少对代表性文档分类抽样：短文、ASR、教程、长文、无证据文档、重复主题文档。

## 三、终局思维审查

终局不是“这一次测试通过”，而是新数据持续进入后，系统仍能稳定运行、可重试、可解释、可回滚。

### 当前方案的终局缺口

1. **没有定义旧页面治理策略。** 方案说旧页面可读，但没有说明旧页面是否继续参与 H2/lint、何时迁移、如何区分新旧质量结果。
2. **没有定义 quarantine 的终态。** 页面被丢弃后，用户在哪里看到原因，如何重试，修复后如何关闭旧 review item，没有验收。
3. **没有定义 KC bundle 的终态。** 生成失败/部分成功/向量失败/写盘失败时，KC、Wiki、index、vector 的状态组合没有矩阵。
4. **没有验证重试稳定性。** 同一 LLM 不同响应可能得到不同概念页；方案没有 canonical topic 或人工决策持久化机制。
5. **没有验证 Book 终局。** 方案声称不破坏书籍编译，但没有 `book show/build` 或 KC manifest 与 Wiki page ids 的验收。

### 终局所需的最低状态矩阵

| 状态 | Wiki | KC bundle | Gap/review | 任务结果 |
|---|---|---|---|---|
| 完整通过 | 已写入 | published | 无未解释问题 | succeeded |
| source-only | source 已写入 | staged/quarantined，不得 published | 记录 concept 失败原因 | succeeded-with-warning 或明确 review |
| 普通引用缺失 | 已写入合格页 | staged/ready 取决于产品定义 | gap ledger 有记录 | review，不是 silent pass |
| 结构不合格 | 不写入不合格页 | 不得发布对应对象 | quarantine/review 可重试 | failed 或 needs review |
| 向量失败 | Wiki 可保留 | staged，等待恢复 | pending/retry | 不得假报 published |

原方案没有这张状态矩阵，因此在终局层面只能保证“某次函数返回了页面”，不能保证系统状态收敛。

## 四、系统思维审查

### 实际系统链路

```text
Collector
  → Analyzer
  → CandidateReviewer
  → CandidatePromoter / KC bundle
  → Candidate Generator
  → normalize_generated_pages
  → deterministic source page
  → reverse relations
  → reconcile / gap ledger
  → rule quality gate
  → atomic writer / index / log
  → vector indexing
  → KC finalize / Book compiler
```

原方案主要覆盖了中间三段：Generator、H2、lint/quality report；但问题会在链路边界传播：

- Prompt 生成的 taxonomy target 进入 normalize 后被改名；
- H2 接受的 path link 仍要经过 reconcile；
- concept 被丢弃后 KC 已经 promote；
- source-only 仍要进入 index、vector、KC 状态；
- template version 影响 generator、lint、batch gate 三处。

因此这不是单模块 bug，必须把“目标解析”和“发布状态”做成跨层契约，而不是分别修几个检查器。

## 五、压力测试问题清单

| 场景 | 当前方案结果 | 结论 | 必须加固 |
|---|---|---|---|
| LLM 返回 3 个完整但相似概念 | 依赖 Prompt 合并；否则只进入未定义 review | 不稳定 | 增加 semantic-duplicate 状态和 deterministic disposition |
| concept 缺必填槽 | 计划丢弃 concept，但检查时点未定义 | 有实现歧义 | slot-level verdict + 原子写入测试 |
| taxonomy 合法但没有 wiki 页 | H2 计划豁免，reconcile 未覆盖 | 会残留 gap | 统一 taxonomy classification |
| `[[sources/foo]]` | H2 可修，reconcile 已有独立逻辑 | 可能出现双重结论 | 所有解析者共用测试矩阵 |
| `source` 被 LLM 返回 | 扩大 enum 后可能重复 source | 有回归风险 | page type/depth 联合校验 |
| CandidateReviewer rejected | 不一定走 source-only | 兜底不完整 | 明确失败状态矩阵 |
| KC promote 后 concept 被丢弃 | KC bundle 可能保留不一致对象 | 跨层污染 | KC manifest 与最终 pages 一致性测试 |
| 同文档二次摄取 | 方案未验收 | 可能重复变体/gap | 幂等回归测试 |
| 项目覆盖模板改槽位 | prompt、renderer、lint 可能不同步 | 有回归风险 | 临时项目自定义模板端到端测试 |
| 原文有真实外部概念 | 强求 unresolved=0 可能掩盖缺口 | 质量语义错误 | gap 允许但必须有解释和状态 |

## 六、编码前必须整改项

以下项目未完成前，不建议开始 Task 1：

1. 修正 Task 4 的真实文件路径；加入 `src/pipeline/reconcile.py`，并决定是否扩展 `src/wiki/features/target_resolver.py` 或统一使用 `wikilink.py`。
2. 明确 taxonomy canonical representation，以及 relation、reconcile、H2、batch gate、Book 的兼容规则。
3. 重新设计 `processing_depth` 的联合校验，不能简单把 `source` 放入 LLM enum。
4. 把 candidate 生成、source 追加、KC promotion、writer、vector、finalize 的状态关系写成测试矩阵。
5. 为本篇原文增加内容级 gold assertions：四要素覆盖、核心论点覆盖、证据引用、禁止补造来源信息。
6. 明确定义语义重复页的处理状态；Prompt 失败时不能既不合并、也不明确阻断，却仍允许“通过”。
7. 把 `wiki-spec.md` 与 `novel-wiki-ingest-spec.md` 的规范统一列为必做修复。
8. 增加二次摄取幂等测试、Book dry-run/build 测试和全库质量基线。
9. 明确 source-only、needs-review、failed、quarantined 的任务结果和用户可见审计信息。

## 最终判定

### 是否能达成原始目标？

**按当前文本：不能完全达成。**

更准确地说：

- 若原始目标仅是修复这次样例的模板缺失、占位符和 H2 误报，方案经过少量路径修正后大概率可以达成；
- 若原始目标是建立可持续、可解释、不会污染 KC/Book/Vector 的 Wiki v2 摄取质量闭环，当前方案还不够；
- 若原始目标还包括验证“内容是否正确摄取”，当前方案的结构测试远远不够，必须增加内容级 gold assertions 和人工复核基线。

**审计结论：条件通过，整改后复审；不批准直接编码。**

整改完成后的放行条件：上述 9 项必须项落入计划，且重新执行一次第一轮漏洞审计；随后再进行第二轮压力测试，确认所有失败场景都有明确状态和恢复路径。
