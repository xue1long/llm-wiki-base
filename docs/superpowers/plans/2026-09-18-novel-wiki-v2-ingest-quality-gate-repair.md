# novel-wiki-v2 摄取质量门修复方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development when executing this plan task-by-task.

## Goal

修复 Wiki v2 的单文档摄取质量问题，使代表性文档
`raw/sources/视频音频转录教程/02进阶视频教程/大纲写作技巧.md` 的结果满足以下可验证契约：

- 产出 1 个 source 页、2 个 concept 页；不额外生成 `提纲的重要性`、`小说大纲写作技巧` 这类重复/变体页；
- concept 页严格使用项目当前解析到的 v3.0.0 模板，不出现旧的 `摘要/核心观点/引用与来源` 结构；
- 不把系统占位语写入正式页；证据不足时保留 source 页并给出可解释告警；
- taxonomy 关系按 taxonomy 规则校验，不被误报为普通 wiki 页断链；
- H2、lint、wiki-quality 对同一批页面得出一致结论；
- concept 页的关键事实覆盖原文四要素和核心论点，并保留 evidence 可追溯性；
- Wiki、KC bundle、vector publication intent 和 Book 输入不会出现互相矛盾的发布状态；
- 同一文档重复摄取不会产生第二套 source/concept/gap 结果；
- 不破坏现有 legacy/batch 路径、模板解析、关系写入和书籍编译契约。

本方案只修复根因，不把“质量门失败”简单改成通过。原始 ASR 噪声、来源元数据缺失和证据不足仍应保留为内容质量告警。

## Architecture

### 1. 以项目模板为唯一页面结构事实源

候选路径 `generate_from_candidate()` 继续负责生成槽位内容，但最终 body 必须经过当前项目模板的 `render_body()`。生成结果不能再退回旧的固定小节结构。必填槽位未填满时，页面不进入写入阶段；只允许保留确定性的 source 页和任务告警。

### 2. 生成约束与确定性校验分层

- Prompt 负责语义决策：一个主题的标题变体合并为一个 concept；子主题作为小节；没有证据不创建 entity/synthesis；taxonomy 只输出关系。
- 代码负责硬约束：槽位完整性、模板结构、合法枚举、页面重复、关系类型和引用目标。
- 不用通用字符串相似度自动合并概念页，避免把不同概念错误合并；只对明确的同标题/同候选主题做确定性处理，其余交给 prompt 和质量门人工复核。

### 3. 质量检查复用运行时解析规则

H2、`src/pipeline/reconcile.py` 和 `src/wiki/features/batch_gate.py` 共用同一套 target classification 结果：普通页面、路径型页面、别名、taxonomy、gap、ambiguous、unresolved 必须得到一致结论。taxonomy 关系先由 `TaxonomyRegistry` 校验，再决定是否需要 wiki 页；普通页面引用仍必须解析到真实页面、别名或明确 gap。

taxonomy 的持久化 canonical target 保留现有兼容格式 `taxonomy-<slug>`，因为现有 ingest、Book sync 和测试已经依赖该形式；输入侧允许 `taxonomy/<name>`，但在进入 relation、reconcile 和检查器前统一规范化为 `taxonomy-<slug>`。taxonomy 不是 wiki page，不得进入普通页面创建或普通页面断链统计。

### 4. 处理深度和页面类型建立单一契约

当前 deterministic source writer 写入 `processing_depth: source`，而 core/lint/generator 的允许值不一致。修复时保留 source 页的存储语义，但不把 `source` 加入 LLM response schema。统一采用 page type + depth 联合校验：LLM 生成页只允许 `concept|memory|operation`，确定性 source 页允许 `source`，stub 页允许 `stub`；旧页面保持读取兼容，不静默改写为 `concept`。

### 5. 质量门只报告真实问题

跨类型的 source 页与 concept 页允许同名，因为它们代表不同对象；同一 page type 内的重复标题仍然报警。质量报告需要区分：真实断链、可解析的路径链接、合法 taxonomy 关系、未解析普通引用和重复标题。

### 6. 发布状态必须收敛

CandidateReviewer、CandidatePromoter、Generator、Writer、Vector publication 和 KC finalize 必须遵守同一状态矩阵。生成页被裁剪后，KC manifest 的最终 `page_ids`、publication status 和 Book 可见性必须与实际 Wiki 页面一致；失败时只允许 `staged/quarantined/pending`，不得假报 `published`。

## Tech Stack

- Python 3.11+
- 现有 `WikiPage`、项目模板 resolver/renderer、`TaxonomyRegistry`、wikilink resolver、lint 和 wiki-quality 检查器
- pytest，使用现有 provider stub/fake，不新增依赖、不调用真实 LLM
- 代表性 smoke test 通过现有 HTTP ingest API 或同步 `run_ingest()` 执行

## Spec

- 项目模板契约：`knowledge/novel-wiki-v2/.wiki-templates/*.md`
- Wiki 规范：`docs/guides/wiki-spec.md`
- 摄取规范：`docs/guides/novel-wiki-ingest-spec.md`
- 本次实测记录：`.memory/feedback-novel-wiki-v2-single-ingest-2026-09-18.md`
- 质量门判断：`.memory/feedback-novel-wiki-v2-quality-gate-judgment-2026-09-18.md`

## Global Constraints

- 先测试后实现；每个任务保持一个可独立验证的逻辑切片。
- 不修改本次实测原始文档，不用手工修页面来掩盖流水线缺陷。
- 单元测试不得依赖网络或真实 LLM；真实 smoke 只在最终验收阶段运行。
- 复用已有 resolver、renderer、taxonomy registry 和 writer，不新增平行抽象。
- 目标解析必须扩展现有 `target_resolver.py`/`reconcile.py` 组合，不新建第二套页面解析器。
- 不把 `source` 加入 LLM 的 processing-depth response enum；所有深度校验必须按 page type 联合判断。
- 旧页面仍可读；新写入页面必须满足统一后的契约。
- 代码阶段按任务提交独立 commit；本计划阶段不进入编码、不创建分支、不 push。

## Task 1: 固化代表性文档的输出契约

**Files:**

- Modify: `tests/test_pipeline/test_ingest_generate_commit_split.py`
- Modify: `tests/test_pipeline/test_generator.py`
- Modify: `tests/test_pipeline/test_quality_gate.py`
- Create if the existing fixtures cannot express the case: `tests/fixtures/novel_wiki_v2_outline_source.md`

**Tests first:**

1. 用现有 fake provider 返回当前文档的最小证据化候选和带变体标题的生成响应。
2. 断言最终候选结果只包含 source `大纲写作技巧-280f64ec`、concept `大纲写作技巧`、concept `大纲四要素`。
3. 断言 `提纲的重要性` 是正文小节/关系，而不是独立页面；`小说大纲写作技巧` 不作为独立变体页写入。
4. 断言 concept body 的标题来自当前项目模板必填槽位，且不包含系统占位语。
5. 断言 source 页可在下游 concept 不合格时单独保留，并产生 warning，而不是写入不合格 concept。
6. 断言 `大纲四要素` 覆盖时间、地点、人物、主要内容；`大纲写作技巧` 覆盖大纲作为写作蓝图和避免失去方向等核心论点。
7. 断言关键槽位内容带有 evidence_refs/来源回指；没有作者、平台、URL、案例的地方不得由生成器补造。
8. 另测 LLM 返回 `小说大纲写作技巧` 变体的反例：变体不得落盘，结果必须为 `NEEDS_HUMAN_REVIEW`，不能静默标记为通过。

**Implementation:**

- 先定位 candidate analyzer/generator 的真实入口，避免为测试复制一套 pipeline。
- 将“页面数量/主题合并/不扩张页面”的断言放在生成结果到 writer 的边界，而不是只测 prompt 字符串；同时把内容级 gold assertions 固定为本 fixture 的语义契约。
- 测试只固定这个文档的语义契约，不把所有文档的 concept 数量硬编码为 2。

**Verification:**

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib tests/test_pipeline/test_ingest_generate_commit_split.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_quality_gate.py -q
```

## Task 2: 修复 candidate 生成与模板渲染边界

**Files:**

- Modify: `src/pipeline/generator.py`
- Modify: `src/pipeline/ingest.py`
- Tests: the Task 1 tests plus `tests/test_wiki/test_templates_renderer.py`

**Implementation:**

1. 让 `generate_from_candidate()` 的所有 page type 都使用 `list_resolved(paths.root)` 得到的项目模板和对应 required slots；禁止 candidate 路径输出旧版固定小节作为最终 body。
2. 保留确定性 slot autofill（source、references 等）但移除“缺槽位就写系统占位语”的正式写入路径。
3. 在 slot 层产生明确 verdict：`FILLED`、`DECLARATIVE_ABSENCE`、`EMPTY`、`PLACEHOLDER`。只有 `FILLED` 和模板允许的 `DECLARATIVE_ABSENCE` 可进入 writer；不要通过最终 Markdown 字符串猜测槽位状态。
4. 在 writer 前增加最小 fail-closed 行为：某个 concept 缺必填槽位时丢弃该 concept，并把原因回传到任务 warning/quarantine；source 页仍可写入。
5. 明确 source-only 边界：analyzer 解析失败、source_id 不匹配、CandidateReviewer rejected、CandidatePromoter 失败等上游失败仍进入失败/quarantine；只有已通过候选审核、但下游页面生成或结构校验失败时才允许 source-only。
6. 不改变已有 `render_body()` 对普通空槽位的单元测试语义；只改变正式摄取提交前的质量门，使占位 body 不能落盘。
7. 修正 candidate 生成结果中 `processing_depth` 的联合校验：LLM schema 保持 `concept|memory|operation`，source/stub 由系统确定性 writer 产生。

**Verification:**

```powershell
python -m pytest --import-mode=importlib tests/test_wiki/test_templates_renderer.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_generate_commit_split.py -q
```

## Task 3: 收紧语义生成规则，减少重复页和幽灵引用

**Files:**

- Modify: `src/pipeline/generator.py`
- Modify: `src/pipeline/wiki_rules_prompt.py`
- Tests: `tests/test_pipeline/test_generator_constraint.py`, `tests/test_pipeline/test_generator.py`

**Implementation:**

当前实测的变体页是在 candidate render 结果中出现的，因此只修改已有 `CANDIDATE_RENDER_PROMPT` 和共享 wiki rules，不新增独立 planner：

- 对同一概念的标题变体先合并；本例中 `小说大纲写作技巧` 合并到 `大纲写作技巧`。
- `提纲的重要性` 属于 `大纲写作技巧` 的论据/小节，除非原文提供独立、可复用且证据充分的概念，否则不创建独立页。
- 仅创建原文能支持的 page type；普通教程素材默认不扩张为 entity/synthesis。
- `taxonomy_of` 只使用项目 taxonomy 中存在的值；taxonomy target 不得当作需要创建的普通 wiki 页面。
- 引用优先使用本次响应中实际定义的页面、现有索引页或 source 页；不猜造 slug。

代码侧采用三态保护，不新增 candidate schema 字段：

1. 同一批次精确重复 id/title：确定性去重；
2. 已存在的 `SlugAliasRegistry` 明确声明 alias：归并到 canonical page；
3. 仅标题相似但无法由 candidate title 或既有 alias 证明同一：保留 `NEEDS_HUMAN_REVIEW`，阻止完全通过，不做模糊自动合并。

最终 unresolved 普通引用继续进入 gap ledger；只有合法 gap 有完整来源和原因时才允许进入 review 状态。

**Verification:**

```powershell
python -m pytest --import-mode=importlib tests/test_pipeline/test_generator_constraint.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_wiki_book_sync.py -q
```

## Task 4: 统一 H2、taxonomy、duplicate-title 和 processing-depth 规则

**Files:**

- Modify: `src/maintenance/checks/h2_break_links.py`
- Modify: `src/cli_ext/wiki_quality_cmd.py`
- Modify: `src/wiki/core/types.py`
- Modify: `src/wiki/features/lint.py`
- Modify: `src/wiki/features/target_resolver.py`
- Modify: `src/wiki/features/batch_gate.py`
- Modify: `src/pipeline/reconcile.py`
- Modify: `src/pipeline/generator.py`
- Modify: `src/pipeline/ingest.py` only where taxonomy target normalization conflicts with the chosen canonical representation
- Modify: `docs/guides/wiki-spec.md`
- Modify: `docs/guides/novel-wiki-ingest-spec.md`
- Tests: `tests/test_maintenance/test_h2_break_links.py`, `tests/test_wiki/test_ndg_lint_consistency.py`, `tests/test_wiki/test_taxonomy_registry.py`, `tests/test_pipeline/test_quality_gate.py`, `tests/test_pipeline/test_ingest_generate_commit_split.py`

**Implementation:**

1. 扩展现有 `target_resolver.py`，让它返回统一分类结果；H2、`reconcile.py` 和 `batch_gate.py` 复用该结果。覆盖 `[[sources/...]]`、`[[concepts/...]]`、bare id、alias、title、ambiguous 和 unresolved；不再各自维护只认 frontmatter id 的 resolver。
2. taxonomy relation 先按 `TaxonomyRegistry` 验证，并把 `taxonomy/<name>` 输入规范化为兼容的 `taxonomy-<slug>` canonical target；合法 taxonomy 不计入普通页面断链、普通 gap 或反向 wiki page 创建，非法 taxonomy 明确报告为 taxonomy 错误。
3. `wiki-quality` 的 duplicate title 统计按 `(page_type, normalized_title)` 分组；source 与 concept 同名不再误报，同类型重复仍报错。该项属于诊断质量，不改变外部 unresolved 的语义。
4. 在 `src/wiki/core/types.py` 定义 page type + processing depth 联合校验：generator response schema 只允许 `concept|memory|operation`；source writer 的 `source`、stub writer 的 `stub` 由系统路径产生；lint、batch gate、writer 复用同一谓词。保留旧页面读取兼容，不静默修改存量页面。
5. `reconcile.py` 的 `collect_missing_slugs()` 和 `batch_gate._gate_reconcile()` 必须用同一分类结果：合法 taxonomy 不是 gap，合法 path link 不是 broken link，普通未解析引用必须带 `referenced_by` 和 raw hint 进入 gap ledger。
6. 必须修正文档中的 wikilink 语法冲突：明确 bare slug、`directory/slug`、taxonomy namespace 的输入和持久化形式；测试只引用统一后的规范。

**Verification:**

```powershell
python -m pytest --import-mode=importlib tests/test_maintenance/test_h2_break_links.py tests/test_wiki/test_ndg_lint_consistency.py tests/test_wiki/test_taxonomy_registry.py tests/test_pipeline/test_quality_gate.py -q
```

## Task 5: 闭合 KC/Wiki/Vector/Book 状态与幂等边界

**Files:**

- Modify: `src/pipeline/ingest.py`
- Modify: `src/kc/mainline.py`
- Modify: `src/kc/views/book/materialize.py`
- Tests: `tests/test_pipeline/test_ingest_generate_commit_split.py`
- Tests: `tests/test_kc/test_mainline_publication.py`
- Tests: `tests/test_kc/test_book_materialize.py`
- Tests: `tests/test_kc/test_book_lineage_manifest.py`
- Tests: `tests/test_cli_ext/test_book_cmd.py`

**Implementation:**

1. 固化状态矩阵：

   | 状态 | Wiki | KC bundle | Gap/review | 任务结果 |
   |---|---|---|---|---|
   | 完整通过 | 合格页已写入 | published | 无未解释问题 | succeeded |
   | source-only | source 已写入 | staged/quarantined | 记录 concept 失败原因 | succeeded-with-warning/review |
   | 普通引用缺失 | 合格页已写入 | 按产品策略 staged/ready | gap ledger 有来源和原因 | review |
   | 结构不合格 | 不写入不合格页 | 不得 published | quarantine | failed/review |
   | 向量失败 | Wiki 可保留 | staged/pending | 可恢复 | 不得假报 published |

2. 防止 CandidatePromoter 已经写入 KC bundle 后，下游 concept 被丢弃却仍被 Book 当成已发布对象；最终 manifest 的 `page_ids` 和 publication status 必须来自实际提交结果，Book materializer 只消费已发布/可见状态的 bundle，不消费 staged/quarantined bundle。
3. 对 source-only、concept 被丢弃、vector 失败和 writer 异常各写一个测试，验证 index、log、quarantine、gap ledger、KC manifest 没有互相矛盾。
4. 对同一 source 连续摄取两次，断言 source id、concept canonical id、gap 数量、KC bundle 状态和 vector intent 不膨胀。

**Verification:**

```powershell
python -m pytest --import-mode=importlib tests/test_pipeline/test_ingest_generate_commit_split.py tests/test_kc/test_mainline_publication.py tests/test_kc/test_book_materialize.py tests/test_kc/test_book_lineage_manifest.py tests/test_cli_ext/test_book_cmd.py -q
```

## Task 6: 完成隔离实例 smoke 和回归验收

**Files:**

- No changes to the original raw source

**Implementation/verification:**

1. 用临时项目目录套用 `novel` 模板，复制一份代表性 source，运行真实单文档摄取；不覆盖现有 `knowledge/novel-wiki-v2/wiki/` 实测结果。
2. 检查 `wiki/index.md`、`wiki/log.md`、`.index/quarantine/`、gap ledger 和生成页面。
3. 运行：

```powershell
python -m src.cli lint --no-cache --project <temp-project>
python -m src.cli tags validate --all --project <temp-project>
python -m src.cli wiki-quality --project <temp-project> --strict
python -m src.cli book show --project <temp-project> --json
python -m src.cli book build --project <temp-project> --json
python -m pytest --import-mode=importlib tests/test_e2e/test_ingest_happy_path.py -q
```

4. 验收标准：
   - 页面数量为 3（1 source + 2 concept）；
   - lint 无 `INVALID-PROCESSING-DEPTH`、`MISSING-SECTION`、placeholder 错误；
   - H2 真实 unresolved 普通引用为 0；合法 taxonomy 不计为 broken link；
   - quality gate 不因 source/concept 同名失败；
   - 第二次摄取同一 source 不产生第二个 source、重复 concept、重复 gap 或第二个可发布 KC bundle；
   - Book dry-run/build 只看到最终实际发布的 KC/Wiki 对象；
   - 原始 ASR 噪声和 provenance 缺失仍以内容告警呈现，而不是被错误标记为系统结构通过。

## Plan Audit — Round 1: 全面漏洞审计

| 等级 | 位置 | 风险 | 修复/验证 |
|---|---|---|---|
| 重大 | Task 2 | source-only 与上游 candidate rejected 的边界仍可能被误实现 | 用失败状态矩阵和四个失败点测试明确边界 |
| 重大 | Task 3 | Prompt 仍可能返回语义变体 | 变体不得落盘，进入 `NEEDS_HUMAN_REVIEW`；fixture 必须测试反例 |
| 重大 | Task 4 | taxonomy canonical 形式与旧页面不一致 | 固定 `taxonomy-<slug>` 持久化格式，输入 namespace 统一规范化 |
| 重大 | Task 4 | 多个检查器仍可能使用不同 target 解析上下文 | H2/reconcile/batch gate 全部复用 `target_resolver` 分类结果 |
| 重大 | Task 4 | `source` 被错误加入 LLM depth enum | LLM 只允许 concept/memory/operation，source/stub 由系统 writer 产生 |
| 重大 | Task 5 | KC 已 promote 但 concept 被丢弃 | manifest 的最终 page_ids/status 以实际提交结果为准，并做发布测试 |
| 重大 | Task 5/6 | 同一 source 重试后产生重复 page/gap/bundle | 增加连续两次摄取的幂等断言 |
| 重大 | Task 1 | 结构通过但知识遗漏或补造 | 增加四要素、核心论点、evidence 和来源字段 gold assertions |
| 优化 | Task 4 | duplicate-title 仍可能影响报告消费者 | 保持报告字段不变，只调整分组维度并补测试 |
| 优化 | Task 6 | 真实 smoke 受外部 LLM 波动影响 | 单元测试使用 fake provider，smoke 只做最终行为确认 |

## Plan Audit — Round 2: 压力测试推演

### 场景 A：LLM 返回空 pages

预期：重试仍遵守现有预算；最终只生成 source 页并标记“空摄取” warning，不伪造 concept，也不因数量不足写 placeholder。覆盖 Task 2 和现有空提取测试。

### 场景 B：LLM 返回三个同主题变体，但每页槽位都完整

预期：prompt 约束要求合并；代码只删除精确重复，不做危险 fuzzy 合并。若仍返回语义变体，变体不得落盘，质量门进入 `NEEDS_HUMAN_REVIEW`/quarantine，而不是宣称完全通过。覆盖 Task 1/3 的回归响应。

### 场景 C：body 使用 `[[sources/foo]]`，relation 使用 `taxonomy-写作技法`

预期：前者按生产路径解析；后者由 taxonomy registry 校验，不产生普通 page 断链。两者都不进入 unresolved gap。覆盖 Task 4。

### 场景 D：body 使用真正不存在的 `[[提纲的重要性]]`

预期：仍报告真实 unresolved；不能因为“本例希望 3 页”而自动创建 ghost page。覆盖 Task 1/3/4。

### 场景 E：concept 缺一个项目模板必填槽位，但 source 完整

预期：该 concept 不写入；source 写入并带 warning/quarantine；index 只列实际写入页；KC manifest 不得把被丢弃 concept 标记为 published。覆盖 Task 2 和 Task 5。

### 场景 F：旧页面仍使用旧 processing_depth 或旧链接格式

预期：读取兼容；新 lint 只报告真正不合法的新写入值；升级不会批量改写或删除旧页面。覆盖 Task 4。

### 场景 G：source 和 concept 同名，但同一 type 内另有两个同名 concept

预期：跨类型同名不报警；同类型重复仍报警。覆盖 Task 4 duplicate-title tests。

### 场景 H：模板被项目覆盖且必填槽位与 bundled 不同

预期：测试从临时项目模板读取，不把 bundled 模板字段写死；生成、lint、质量门解析到同一项目模板。覆盖 Task 1/2/5。

### 场景 I：同一 source 连续摄取两次

预期：source id、canonical concept id、gap 数量、KC bundle 和 vector intent 不膨胀；第二次运行只报告已存在/幂等结果。覆盖 Task 5/6。

### 场景 J：KC promote 成功但 Wiki writer 或 vector 失败

预期：KC bundle 保持 staged/pending，不能进入 published；Wiki、index、vector intent 具备可恢复状态，不能出现“Book 可见但 Wiki 不存在”的孤儿对象。覆盖 Task 5。

## Exit Criteria

只有同时满足以下条件才进入编码完成声明：

- Round 1/2 风险都有对应测试或明确保留的告警行为；
- 相关测试通过，且全量测试没有新增失败；
- 隔离 smoke 达到 3 页输出和质量门标准；
- 质量报告能区分真实问题与当前已确认的误报；
- 内容级 gold assertions、KC/Wiki/Vector/Book 状态矩阵和二次摄取幂等测试通过；
- 代码变更后运行 `graphify update .`，并在 `.memory/` 记录最终修复结果。

本计划完成后先停在方案阶段；执行时按 Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 顺序，每个任务通过测试后再进入下一个任务。
