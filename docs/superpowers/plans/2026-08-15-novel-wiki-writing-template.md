# 执行方案 — 写作知识库场景模板 v3（novel-wiki，2026-08-15）

> 依据：`docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md`（设计 spec，18 项决策已收敛；§11 为 plan-audit 第一轮整改记录，本 plan 已按整改后文本重写）。每任务标注 Files / Tests / Implementation guidance / 验收 / commit。遵守 TDD-per-task + 一次一 commit + 每任务 reviewer 工作流。
>
> **plan-audit 第一轮结论（2026-08-15）**：原方案文本 8 项致命缺陷（F1–F8）已整改完毕——F1 synthesis 质量门互斥、F2 M1/gap 矛盾、F3 模板格式与 parser 不兼容、F4 backlog 跳过、F5 source 构建器脱节、F6 门禁无批内作用域、F7 M2 重言式、F8 is_immutable 无守卫。本 plan 为整改后版本，细节见 spec §11。
>
> **plan-audit 第二轮结论（2026-08-15，压力测试推演）**：6 项致命接线缺口（C1 LLM 重试/熔断纸面化、C2 reingest_source 前置崩溃、C3 M2/M6 算术冲突、C4 门禁时序、P1 gitignore 架空、P4 幂等/向量）——**本 plan 已按 spec §11.7.2 P0 加固整改**（任务 1.9、1.8 扩展、Phase 0.2 扩容、Phase 4 执行模型重写），整改后需重开复审确认 P0 落地再进编码。

## 执行顺序（依赖是硬约束）

```
Phase 0 基线复测 + 盲区统计（M1–M12 + B1–B12 + P0 验算）
   └─► Phase 1 平台改造（项目级模板 v3.0.0 / lint / 对账+gap / 枚举单一真源 / 门禁闸门 / source构建器 / immutable守卫 / LLM接线）
          └─► Phase 2 场景模板落地 novel-wiki（schema/purpose/taxonomy/tags/.wiki-templates）
                 └─► Phase 3 实测首轮（1–2 批，不达标不进入 Phase 4）
                        └─► Phase 4 全量分批重摄入（执行器·定死直跑路径，cascade 分支，门禁 pre-commit，存量旧页处置）
                               └─► Phase 4.5 多源 synthesis 聚合（跨批聚合，供 M6）
                                      └─► Phase 5 终验（M1–M12 复测 + M12 向量维度校验 + 独立抽样）
```

**验收总目标**（spec §6 整改后）：M1 未登记断链率 批内0/全库<5%｜M2 深引用率 ≥80%（**或 0.2 验算后修订口径**）｜M3 taxonomy 100%枚举（批内新页）｜M4 必填槽通过率 100%｜M5 门禁批批通过 100%｜M6 synthesis 每100raw≥5（依赖 4.5）｜M7 source 全文污染 0（覆盖范围内）｜M8 旧前缀 0（覆盖范围内）｜M9 非法 relation 0｜M10a 每批≤20 文件 + M10b 每批 token/费用/时长｜M11 gap 批均净增 ≤5（趋势指标，非绝对存量）｜M12 向量检索可用性抽查（维度校验前置）。

---

## Phase 0 — 基线复测 + 盲区统计

### 0.1 复测 M1–M12 实测当前值（口径 = spec §6 整改后；M12 向量抽查在 Phase 5 执行，Phase 0 只测 M1–M11）

- **Files**：`scripts/audit_wiki_baseline.py`（扩展；复用前轮审计测量逻辑）、**`src/wiki/features/metrics.py`（新建核心：M1/M2/M4/M6/M7 计算函数——在 Phase 0 创建，1.8 只扩展批内子集参数；N4/C3 闭环 + 复审 A 修订）**
- **Tests**：`tests/test_scripts/test_audit_wiki_baseline.py`（fixtures 迷你 wiki 断言各指标计算正确）、`tests/test_wiki/test_metrics.py`（核心函数）
- **Implementation guidance**：
  1. **创建 metrics.py 核心（复审 A 修订）**：`src/wiki/features/metrics.py` 在 Phase 0.1 新建，实现 M1/M2/M4/M6/M7 计算函数；0.1 基线脚本与后续门禁/终验**共用同一核心**，杜绝两套口径漂移。
  2. M1 未登记断链率：body wikilink + relations[].target 解析，集合 = 磁盘页 ∪ SlugAliasRegistry（`.llm-wiki/slug_aliases.json`）可解析 ∪ 索引；不在集合 = 断链（gap 另计，见 M11）。
  3. M2 深引用率：被 ≥1 个**非 source 页** `sources` 引用的 raw 占比，**且排除"同 raw 自产页"**（每 raw 生成的 entity/concept 页 `sources` 恒列自身 raw，若计入则 M2 恒 ≈100% 成新重言式——复审 C 修订）；**分母 = 1361 个 .md**（排除 3 个 download_progress.json，json 不可能被引用，N16）。
  4. M7 source 全文污染：`_FULLTEXT_SECTION_RE` 命中数；M8 旧英文前缀 tag 页数；M9 非法 relation 类型（非 17 型 + 非 `x-*`）。
  5. 输出 `.index/baseline_2026-08-15.json`，Phase 5 终验读同一文件做差值断言。
- **验收**：metrics.py 核心 + 基线 JSON 生成；**口径核对记录（0.2 B12 一并处理）**——实测 vs 审计基线差异：M1 断链 **17.2%**（276 distinct slug / 1600 链接，body+relations 每链接计数、断链 slug 去重）vs 审计 55.1%（584/1059，纯 body wikilink 每链接计数）——口径差异已记录；M2 深引用率 **0%**（0/1361，一致）；M6 synthesis 0（一致）；M7 全文污染 **6/7**（1 个 source 页无全文章节头）；M8 旧前缀 **205**（一致）；M9 非法 relation **31 处**（9 种类型：related_to 13 / related 9 / applied_to 2 等）vs 审计 10 页（仅 related_to 字面子集）——本次为完整检测；stub **165**（一致）。
- **Commit**：`chore(novel-wiki): metrics.py 核心 + 基线复测 M1-M11（新口径）`

### 0.2 盲区统计（B1–B12 + P0 验算，plan-audit 第一/二轮要求）

- **Files**：`scripts/audit_wiki_baseline.py` 扩展或 `scripts/audit_blindspots.py`（新建）
- **Tests**：同 0.1 测试目录
- **Implementation guidance**：统计并输出：
  - B1 backlog 分类：1361 raw md 中 tiny/duplicate_of/long_docs/unhandled_format 各多少（跑 `scripts/build_reingest_backlog.py` 或等价判定，**阈值以 16000 为准**——脚本 8000 与 generator 16000 不符，O1）；long_docs 数计入 M2 分母评估。
  - B2 每批成本：抽样 3–5 raw 实测单 raw 平均产出页数、LLM 调用数、token 消耗——**外推全量预算上限并定硬数字**（C1/P4 加固：M10b"超限即停"的触发值）。
  - B3 存量 stub 与 is_immutable 数量（实测 **165 页 stub = entities 100 + concepts 65** / 0 immutable）+ **stub 引用关系图**（哪些页引用 stub，决定 1.3 对账转 gap 的量）。
  - B4 平台其他项目清单：`~/.config/ruflo-kb/` 与 `knowledge/` 下哪些项目在用 bundled 模板、有无项目级/用户级覆盖（决定 H3 影响面）。
  - B5 存量 tag 值分布：`情绪/` `场景阶段/` 各旧值出现次数（决定枚举迁移成本）。
  - B6 slug_aliases.json 现有条目数（实测 novel-wiki 无该文件 → 0 条）。
  - B9 存量 category/taxonomy_sub 40+ 自由值清单。
  - B10 重试对断链率降幅：对 1 批旧页做一次"缺失 slug 反馈重试"实验，测降幅（A1 验证）。
  - B11 向量维度/provider 一致性：读 `src/vector/store.py` 实际维度（384）与当前 LLM provider embedding 维度（可能 1536）——**决定 M12 前是否需维度迁移或 provider 切换**（P4 加固；`_migrate_schema_if_needed` 静默 drop 表风险）。
  - B12 **断链消解路径分类（C3/压力测试）**：251 个 distinct targets 按"未摄入 raw 引用 / raw 名+幻觉 hash / 归一可对齐"分类——未摄入 raw 引用是缺口优先批次的正确对象（可直接匹配 raw），幻觉 hash 走 gap/suppressed；产出消解映射表供 Phase 4 批次规划。
  - **M2 可达性验算（C3 P0 加固）**：用 B12 分类 + 3–5 批实测推算 M2 深引用率是否可达 ≥80%；不可达则给出修订预案（改 M2 定义纳入"非 source 页 wikilink→source 页" / 放大 4.5 聚合 / 降阈值），在 Phase 0.2 结束时定稿 M2 口径。
- **验收**：B1–B12 全部有数值或明确"未统计原因"；M2 可达性验算有结论（可达 or 修订口径已定）；硬预算数字定稿；B1/B5/B12 影响 Phase 4 批次规划。
- **Commit**：`chore(novel-wiki): 盲区统计 B1-B12 + M2可达性验算 + 硬预算`

### 0.3 index 重建/对齐（B-O6，Phase 3 前置）

- **Files**：`src/wiki/features/indexer.py`（重建入口）、`scripts/rebuild_index.py`（新建，遍历磁盘重生成 index.md）
- **Tests**：`tests/test_scripts/test_rebuild_index.py`（磁盘 382 页 → index 条目数一致；重建后 LINT-ORPHAN 归零）
- **Implementation guidance**：实测 `wiki/index.md` 仅 15 条而磁盘 382 页（367 个 LINT-ORPHAN 噪声）——**必须先重建 index**，否则门禁全局 lint 第一步就被 orphan 淹没。重建后 lint LINT-ORPHAN 归零。（stub 页仍按常规页计入 index——stub 处置在 Phase 4，不阻塞本次对齐。）
- **验收**：index 条目数 == 磁盘页数（382，含 stub）；lint LINT-ORPHAN 归零。
- **Commit**：`chore(novel-wiki): index 重建对齐（清 LINT-ORPHAN 噪声）`

---

## Phase 1 — 平台改造（TDD，全部独立 commit）

> **全局决策（plan-audit H3）**：v3.0.0 写作域模板**只落 novel-wiki 项目级 `.wiki-templates/`**，**bundled 保持 2.0.0 通用版不动**（bundled 是平台所有项目默认模板，改写会污染全平台）。lint 版本门判定改为"按项目解析出的模板版本"而非全局常量。

### 1.1 项目级模板 v3.0.0（novel-wiki）+ 生成器槽表同步

- **Files**：
  - 模板资产：`src/templates/bundled/general/.wiki-templates/{source,entity,concept,synthesis}.md` **不动**；新建 `knowledge/novel-wiki/.wiki-templates/{source,entity,concept,synthesis}.md`（v3.0.0，spec §4.5 修正格式）
  - 生成器静态槽表：`src/pipeline/generator.py`（GENERATOR_PROMPT 槽 minimums、UNIFIED_PROMPT、CANDIDATE_RENDER_PROMPT、`_auto_fill_deterministic_slots`）
  - 文档：`docs/wiki-template-field-guide.md`（§3–§6 槽表、§7 全景表、§8 英文前缀修正、§9 校验链）、`docs/guides/wiki-spec.md`（模板章节 2.0.0→3.0.0 说明）
- **Tests**：`tests/test_wiki/test_templates_parser.py`（v3.0.0 解析）、`tests/test_wiki/test_templates_renderer.py`（新槽渲染）、新增"模板槽集 vs 提示词槽集一致性"测试（用 `required_slot_names()` 断言提示词模板段与解析模板槽集一致，防漂移）
- **Implementation guidance**：
  1. **模板格式（F3 整改）**：`## 标题` 独占一行；`<!-- slot:NAME -->` 放章节 body；语义说明用 `<!-- … -->` 独立注释行（HTML 注释，parser 剥离）；**禁止在 `## ` 行内写任何标记**。加解析期断言：模板任何 `## ` 行不得包含 `slot:`。
  2. 槽结构按 spec §4.5（concept 加 适用场景/反模式/证据强度；source 加 转录质量/可信度；entity 加 写作价值；synthesis 改分歧汇聚五槽）。
  3. `generator.py` 三处静态槽表 + `_auto_fill_deterministic_slots` 同步新槽；`_auto_fill` 移除旧 `extracted_concepts`/`comparison_dimensions` 引用（H8）。
  4. field-guide §8 英文前缀改为中文（A10 修正）；wiki-spec.md 模板章节 3.0.0 说明（O3 部分）。
- **验收**：`wiki-templates show concept --project novel-wiki` 显示 v3.0.0 新槽（O8：验收必须带 `--project` 作用域）；一致性测试通过；field-guide 与模板一致。
- **Commit**：`feat(novel-wiki): 项目级模板 v3.0.0 + 生成器槽表同步`

### 1.2 lint：版本门按项目模板 + MISSING-SECTION 升 ERROR + 新检查

- **Files**：`src/wiki/features/lint.py`、`tests/test_wiki/test_lint.py`
- **Tests**：新槽映射、版本门按项目解析、占位符检测、RAW-PASTE 合并语义；正反用例。
- **Implementation guidance**：
  1. **`_SLOT_TO_HEADING`（H1）**：扩展全部新槽映射（context/anti_patterns/evidence/transcription_quality/credibility/craft_value/topic/viewpoints/consensus/evidence_comparison）；**更彻底：`_heading_label` 改为从解析后的模板 `TemplateSection.heading` 取标题**（消除硬编码双源）。
  2. **MISSING-SECTION 升 ERROR**（H2）：版本门判定改为"**页声明版本 ≥ 项目解析出的模板版本**才检查该模板的必填槽"（H3；避免自比——`list_resolved(project_root)` 返回项目实际生效模板的版本，与页面文件头 `wiki-template-version` 比较）；存量 2.0.0 页仍按 ≥2.0.0 检查（向后兼容，不做 2.0.0→3.0.0 排除）。
  3. **占位符检测（H2）**：新增 ERROR——body **substring 包含** `（系统占位` / `待补充` / `见下游概念页` / `来源未提供具体例子`（可配置列表；与现有 `_READABILITY_PLACEHOLDERS` 整 body 相等判定不同，新增独立检查）。
  4. **RAW-PASTE 合并（H7 + F5×H7 交叉）**：**不新增 LINT-RAW-LEAK**；复用现有 `_FULLTEXT_SECTION_RE` + `_long_raw_text_run` + `_load_raw_paste_thresholds`（quality_settings.json 阈值）；source 页判定 = 全文章节头 **∪ 超长未引用段**（1.6 移除 `main_content` 后 T_source 从 2000 收紧至 **800**——source 摘要 300–800 字，收紧至 300 会误报正常摘要；以 quality_settings 为准可校准）；非 source 页按超长段判（fence-aware 已实现）。300 字阈值从 quality_settings 读，不硬编码。
  5. **synthesis 质量门（F1 整改）**：ERROR——解析渲染后 body 的 `## 各方观点` 章节，其内 `[[wikilink]]` 解析成功 <2 个（不依赖 frontmatter `sources` 计数）；仅对模板声明 ≥3.0.0 的 synthesis 页生效。
  6. **relation 类型校验（M9）**：`relations[].type` 非 17 型 + 非 `x-*` → ERROR。
  7. tags 枚举校验（枚举源见 1.4）。
- **验收**：构造各违规页 → lint 报对应 ERROR；v2.0.0 页仍受 MISSING-SECTION 检查；既有测试不回归。
- **Commit**：`feat(lint): MISSING-SECTION升ERROR + 占位符/合成质量门/relation类型 + 版本门按项目模板`

### 1.3 引用-产出对账 + gap 清单（含 SlugAliasRegistry 与质量过滤迁移）

- **Files**：`src/pipeline/ingest.py`（对账区 + stub 分支改造）、`src/pipeline/generator.py`（missing-slug 反馈参数）、新增 `src/wiki/features/knowledge_gaps.py`、`.index/knowledge_gaps.json`、`src/wiki/features/wikilink.py`（`create_stub_if_missing` 废弃判定）
- **Tests**：`tests/test_pipeline/test_ingest_crossref_p0.py` 扩展、新增 `tests/test_wiki/test_knowledge_gaps.py`
- **Implementation guidance**（spec §5.1–5.2 整改后）：
  1. **对账判定集合（H6）**：产出 ∪ 磁盘页 ∪ **SlugAliasRegistry 可解析** ∪ 索引（并集，别名优先）。
  2. **重试机制（H6）**：generator 增加 `missing_slugs` 反馈参数——**单次调用内闭环**（LLM 收到缺失 slug 清单后修正引用），**不整条流水线重跑**（不倍增 token）。
  3. **gap 记录（O6）**：`{slug, title?, alias?, type?, raw_hint?, referenced_by[], created_at, status}`；raw_hint 供 Phase 4 按 slug 定位 raw。
  4. **质量过滤迁移（H9）**：`knowledge_gaps.py` 写入函数继承既有 stub 质量机制——blocklist（`_get_stub_blocklist`）、硬上限（`_get_max_stubs_per_ingest`）、doc-title 变体剔除（`_rank_stub_candidates` 语义），防幻觉批灌入上千条噪声。
  5. **统一 slug 归一函数（B-H3）**：对账、stub 判定、wikilink 解析三处共用同一归一函数（`generator.py normalize_id_chars` vs `ingest.py _slugify` 的分歧必须统一）；必要时迁移旧 id（参考 `migrate_source_slugs_cmd.py`）——实测磁盘 id `语言-、-动作-、-神态结合描写`（保留 CJK 顿号）与自然 wikilink 归一不一致，是假断链来源之一。
  6. **废除自动建 stub（H9 整改）**：ingest 不再自动建 stub entity 页；`wikilink.create_stub_if_missing`（O1，无调用者）标注废弃。
  7. **存量 stub 处置（H9 + N7）**：Phase 4 前置用 `scripts/cleanup_stub_pages.py` **删除/归档** 165 个存量 stub（entities 100 + concepts 65）——**不走"转 gap 记录"分支**（165 条一次性转 gap 必然触发 M11"净增>5/批"暂停，且 stub 与 gap 语义重叠）；被删 stub 若被引用，引用按 1.3 对账转 gap（逐条计 gap，随处置批统计，M11 对处置批单独豁免口径）。
- **验收**：同一 raw 连跑两次 stub 不新增；构造幽灵引用 → 单调用内反馈修正；仍断 → 入 gap（结构含 title/raw_hint）；blocklist slug 不入 gap。
- **Commit**：`fix(pipeline): 对账含别名注册表 + 单调用闭环重试 + gap质量过滤，废除自动建stub`

### 1.4 taxonomy/tags 单一真源枚举门禁

- **Files**：`src/cli_ext/fields_cmd.py`（**非 tags_cmd.py——该文件不存在**，`cmd_tags_validate` 实住在 fields_cmd.py）、`src/wiki/tag_namespace.py`（TAG_PREFIXES/TAG_VALUES 改为从 taxonomy.md 读或反向）、`src/wiki/taxonomy_registry.py`（tags 枚举节独立解析）、`src/pipeline/wiki_rules_prompt.py`（经 `scripts/sync_wiki_spec.py` 生成，勿手改）、`docs/guides/wiki-spec.md`（tags 表加 `读者群/` `平台/`）、`tests/test_cli_ext/`、`tests/test_wiki/test_taxonomy_registry.py`
- **Tests**：单一真源一致性测试（生成器接受集 == 门禁枚举集）；tags 枚举节解析；未枚举 category/sub/tag → 报错；批模式（一次调用遍历目录）。
- **Implementation guidance**：
  1. **单一真源（H4）**：枚举只存 taxonomy.md（tags 节独立于分类节——用独立解析器或独立文件 `taxonomy_tags.md`，**不与 `## 分类` 共用正则**，避免 O5 污染分类命名空间）；`_normalize_tags`/`validate_tag_compliance`/提示词全部从 taxonomy.md 读取。
  2. **新增前缀（Q13）**：`读者群/`（男频/女频/全年龄/青少年/中老年）、`平台/`（起点/番茄/晋江/纵横/飞卢/QQ阅读/掌阅）注册进 TAG_PREFIXES + 提示词（经 sync 脚本）。
  3. **收紧过渡（H4）**：`情绪/` `场景阶段/` 新枚举与旧值（B5 统计）做**并集过渡**或显式迁移清单；门禁对存量页豁免（见 1.5 作用域）。
  4. **strict 解析（O5）**：门禁闸门用 `TaxonomyRegistry.from_project(strict=True)`；taxonomy.md 冒烟解析前置。
  5. **批模式（H10）**：fields/tags validate 支持一次调用遍历目录（1364 raw × 5–15 页不能逐页起子进程）。
- **验收**：`tags validate` 对 `读者群/男频` 通过、`读者群/其它` 报违规；一致性测试通过；wiki-spec.md 已同步（跑 sync_wiki_spec.py 后提交生成物）。
- **Commit**：`feat(wiki): taxonomy/tags 单一真源枚举门禁（新增读者群/平台前缀 + 批模式）`

### 1.5 门禁闸门（复用 NDG，批内作用域）

- **Files**：`scripts/batch_gate_check.py`（**复用既有**，非新建 batch_gate.py）、`src/wiki/features/ndg_gate.py`（P1–P7 写时门禁）、`src/wiki/features/batch_reconcile.py`（P6 slug 冲突）、`scripts/phase4_batch.py`、`tests/test_scripts/test_batch_gate.py`
- **Tests**：合格批/断链批/违规 tag 批/跨类型 slug 冲突批 → 门禁结果矩阵。
- **Implementation guidance**（H5）：
  1. **不新建平行门禁**：新门禁 = 既有 NDG 门禁（P1–P7 写时）∪ 本方案补项（wikilink 对账、枚举、新 lint 规则）；写明时序：写时 NDG 先行 → 批后新门禁（1.2 lint + 1.3 对账 + 1.4 枚举）→ 通过才进下一批。
  2. **批内作用域（F6）**：门禁只校验**批内新产出页**；存量页（category=''、旧 tag、旧前缀）豁免，由 Phase 4 处置。
  3. 直接调用 `lint_wiki()` 返回的 report 判定（不依赖 CLI 退出码，H2）；ERROR 即不合格。
  4. 输出批次报告 JSON（`.index/batch_reports/<batch>.json`，含 M1/M4/M6/M7 + **LLM 调用次数/Token 成本字段（M10，O4）**）。
- **验收**：对空批 dry-run 通过；构造违规批被拦；既有 NDG 测试不回归。
- **Commit**：`feat(scripts): 门禁闸门（复用NDG + 补项 + 批内作用域 + 批次报告含成本）`

### 1.6 source 页确定性构建器同步新槽（F5）

- **Files**：`src/pipeline/ingest.py`（source 页构建器，现只传 source_meta/summary/key_points/extracted_concepts/main_content）、`tests/test_pipeline/`
- **Tests**：构建器产出含 transcription_quality/credibility 槽；ASR 素材判转录质量正确（fixture 含"GPU 加速转录生成"标记 vs 人工文档）。
- **Implementation guidance**：
  1. source 构建器新增两槽，**由代码确定性填充**（不经 LLM），判定信号源明确（N3 闭环）：
     - `transcription_quality`：**ASR** = raw 头部/尾部含 `*此文档由 GPU 加速转录生成*` 标记（`src/pipeline/_pipeline_common.py` 去噪行现存信号）→ "ASR 转录，错漏需人工复核"；**人工撰写** = 无转录标记且非 UGC 载体 → "人工整理"；**OCR/未知** = 无信号时标记 "来源形态未知，按原始素材处理"（**不臆断 OCR**，OCR 无可靠信号）。
     - `credibility`：复用 `_is_ugc_carrier`（lint.py，判定 header 是否 UGC 平台载体）+ 素材类型信号：UGC 载体 → `可信度/ugc`；否则 `可信度/book` 或 `可信度/mixed`（按来源元数据）。
  2. 移除 `main_content` 槽（旧全文槽，lint `_SLOT_TO_HEADING` 中 `main_content: 正文内容` 映射同步删除）。
- **验收**：新摄入 source 页含两新槽且非占位；lint RAW-PASTE 对全文页报 ERROR。
- **Commit**：`fix(pipeline): source 构建器同步 v3.0.0 槽（转录质量/可信度代码判定）`

### 1.7 write_page is_immutable 守卫（F8/O7）

- **Files**：`src/wiki/storage/page_writer.py`（write_page 覆盖分支）、`src/pipeline/ingest.py`（commit 分支）、`tests/test_wiki/test_page_writer.py`
- **Tests**：对 is_immutable 页写回 → 拒绝并报错；`updated_at` 比对逻辑。
- **Implementation guidance**：
  1. `write_page` 覆盖写时检查 `is_immutable`：目标页 immutable 且非首建 → 拒绝（ERROR 日志）。
  2. `ingest.py` commit 分支：摄入前比对"旧页 `updated_at` vs raw mtime"，旧页被手工修改过（updated_at 更新）→ 跳过并记 log。
- **验收**：构造 immutable 页覆盖写被拒；手工修改页重摄入被跳过。
- **Commit**：`fix(wiki): write_page is_immutable 守卫 + 重摄入 updated_at 比对`

### 1.8 批内测量 API（F6 + C3 扩展；metrics.py 核心已在 0.1 创建，本任务只扩展）

- **Files**：`src/wiki/features/metrics.py`（**扩展**：批内页面集合参数，核心函数 0.1 已建）、`src/wiki/features/lint.py`（`lint_wiki` 增加 page_ids 子集参数）、`tests/test_wiki/test_metrics.py`（批内子集用例）
- **Tests**：页面集合（含断链/缺槽/全文页）→ 各指标计算正确；空集合 → 0；子集 lint 只扫指定页；M2 深引用率对集合计算正确。
- **Implementation guidance**：metrics.py 增加"对给定页面集合"模式（0.1 已建核心，此处不重复实现）；lint 子集模式——**门禁与验收测量必须基于"批内页面集合"而非全库**（全库 55.1% 断链/367 orphan 会淹没批内信号）；**M2 批内测量（C3 P0 加固）**：Phase 3/4 每批报告 M2 累积值（排除同 raw 自产页口径，0.1 定义）——杜绝"方向性错误 69 批后才暴露"。
- **验收**：Phase 3 验收脚本可对"本批页面集合"断言 M1/M2/M4/M7，而非全库扫描。
- **Commit**：`feat(wiki): 批内测量 API 扩展（M1/M2/M4/M6/M7 按页面集合）`

### 1.9 LLM 调用接线（C1 P0 加固，Phase 3 实测前置）

- **Files**：`src/pipeline/retry.py`（`retry_with_backoff` 现为死代码，无调用者）、`src/pipeline/generator.py`、`src/pipeline/analyzer.py`、`src/pipeline/c_grade_handler.py`、**`src/lib/budgeted.py`（BudgetedLLM 封装——analyzer 经此间接调用，复审 E 修订）**、**`src/pipeline/quality/judge.py`（QualityJudge.judge_batch，默认 OFF 但可开——复审 E 修订）**、`src/circuit_breaker.py`（llm breaker）、`scripts/phase4_batch.py`（直跑路径 record_failure/success）、`tests/test_pipeline/test_retry.py`
- **Tests**：429（读 Retry-After）/422（PermanentFailure 分类）/5xx/断连各路径；breaker OPEN 后暂停整批；直跑路径 record_failure 接线；**接线点清单覆盖测试（grep 断言所有 LLM 调用点已包 retry，防漏接 budgeted/judge）**。
- **Implementation guidance**（压力测试 C1/B2/O3 加固，复审 E/I 修订）：
  1. **接线 `retry_with_backoff`**：**优先选"provider 层统一封装"**（覆盖 generator/analyzer/budgeted/QualityJudge 全部 4 处调用点，避免逐点漏接）；若选逐点接线，清单必须含 4 处（generator.py:1706、c_grade_handler.py:185、analyzer 经 `lib/budgeted.py:106`、`ingest.py:581` QualityJudge.judge_batch）。429 读 Retry-After（现有解析器）、422 分类为永久失败、transient 指数退避——替换 generator 内部"重试间无退避"的 `MAX_GEN_ATTEMPTS` 循环。
  2. **422 隔离（B2）**：分类为 PermanentFailure 的文件标记 `permanent_failed` 移出重试并计入批次报告（每批空耗 2 次 LLM 的浪费消除）。
  3. **直跑路径接线 breaker（O3）**：`_ingest_one` 失败/成功时对 llm breaker `record_failure`/`record_success`；executor 顶层检查 breaker 状态，OPEN 时暂停整批并等待恢复——"熔断器 OPEN 暂停等待"从纸面变为真实。`recovery_timeout` **取既有 breaker 机制**（OPEN 60s → HALF_OPEN，2 成功恢复）。
  4. **无冷却重启禁止**：abort 后自动等待 recovery_timeout 再重试，禁止人工立即重启打满调用。
  5. **两层重试交互（复审 I 修订）**：1.3 内容层（missing_slugs 单调用闭环，修引用）与 1.9 传输层（retry_with_backoff，修网络/限流）**并存**——传输层在外（重试网络错误），内容层在内（一次成功调用内修引用）；嵌套顺序与计数分别在 1.3/1.9 验收断言。
- **验收**：构造 429/422/5xx fixture → 各走正确路径（429 退避、422 永久隔离、5xx transient）；breaker OPEN 后批暂停；retry_with_backoff 有调用者（非死代码）。
- **Commit**：`fix(pipeline): 接线 retry_with_backoff 到 LLM 调用点 + llm 熔断直跑接线 + 422 永久隔离`

---

## Phase 2 — 场景模板落地 novel-wiki

### 2.1 schema.md + purpose.md + taxonomy.md（含 tags 枚举节）

- **Files**：`knowledge/novel-wiki/schema.md`（spec §4.1）、`knowledge/novel-wiki/purpose.md`（spec §4.2）、`knowledge/novel-wiki/taxonomy.md`（spec §4.3 分类 + §4.4 tags 枚举，**tags 节独立文件 `knowledge/novel-wiki/taxonomy_tags.md` 或独立解析标记**）
- **Tests**：`tests/test_pipeline/test_schema_purpose_injection.py`（沿用注入链路测试）
- **Implementation guidance**：直接用 spec §4.1–4.4 落盘；确认 ingest 重读 project-root schema/purpose/taxonomy 链路；taxonomy.md 落盘后先跑冒烟解析（strict），防空/损坏静默放行（O5）。
- **验收**：`fields validate`/`tags validate` 读入枚举；taxonomy strict 解析通过。
- **Commit**：`feat(novel-wiki): 场景模板 schema/purpose/taxonomy 落盘`

### 2.2 项目级页面模板副本 v3.0.0

- **Files**：`knowledge/novel-wiki/.wiki-templates/{source,entity,concept,synthesis}.md`（1.1 已建，确认与 spec §4.5 一致）
- **Tests**：`tests/test_wiki/test_templates_resolver.py`（项目级优先级命中 novel-wiki）
- **Implementation guidance**：删除旧 `.wiki-templates/concept.md`（含零采纳的 limitations?/conflicts?/source_meta? 可选槽）。
- **验收**：`wiki-templates list --project novel-wiki` 显示项目级 v3.0.0；lint 对 3.0.0 模板解析正常。
- **Commit**：`feat(novel-wiki): 项目级页面模板 v3.0.0 确认（废弃零采纳可选槽）`

---

## Phase 3 — 实测首轮（门）

- **Files**：批次清单 `.index/batch_reports/batch_001.json`、spec 回填
- **Tests**：跑 1.5 门禁闸门 + 0.1 基线脚本断言
- **Implementation guidance**：
  1. 首批 = 缺口优先（被引用但无 source 页的 raw，≤20 文件，**只含 .md，过滤 download_progress.json 等**）。
  2. 摄入后跑门禁；验证 M1（批内未登记断链 0）、M4（100% 槽填充）、M7（无全文污染）、M6 触发（synthesis 页存在即可，聚合数量在 4.5）。
  3. **RAW-PASTE 阈值校准（F5×H7 交叉）**：用真实批次检查 `_long_raw_text_run` 对 v3.0.0 散文槽（适用场景/反模式/证据强度）是否误报；必要时在 `.index/quality_settings.json` 调 raw_paste 阈值——阈值不写死在代码。
  4. 任一不达标 → 回 Phase 1 修，不进入 Phase 4。
- **验收**：首批指标达标，批次报告（含成本字段）落盘。
- **Commit**：`chore(novel-wiki): 实测首轮批次报告（M1/M4/M7 达标）`

---

## Phase 4 — 全量分批重摄入（执行模型重写：P0 加固 C2/C4/P1/P4）

- **Files**：`scripts/plan_reingest_batches.py`（清单生成，**按 `_SUPPORTED_EXTENSIONS` 过滤 .md，排除 download_progress.json**）、`scripts/batch_executor.py`（新建，批执行器 + 状态机）、`scripts/cleanup_stub_pages.py`（复用）、`src/services/ingest.py`（`reingest_source` 分支改造 + `.index/batch_build_state.json`）、`src/utils/idempotency.py`（task_hash 重建轮次）、`src/vector/`（`init_vector_store_for_paths` + upsert + 维度校验）、`.gitignore`（门禁文件白名单）、`.index/batch_reports/*.json`、`.index/knowledge_gaps.json`
- **Tests**：`tests/test_scripts/test_plan_reingest_batches.py`（批次划分、扩展名过滤）、`tests/test_scripts/test_batch_executor.py`（状态机/崩溃续跑/熔断暂停/**kill -9 各阶段崩溃注入**）
- **Implementation guidance**：
  1. 批次顺序：缺口优先（Phase 3 已开，用 0.2 B12 消解映射）→ 主题目录推进；每批 ≤20 **md 文件**（扩展名白名单）。
  2. **定死执行路径（B6/C2）**：**直跑路径为唯一执行路径**（脚本进程内直接调用 `run_ingest`，不经队列——直跑无 worker，队列路径的 enqueue 空转会丢页）；队列路径降级为只读观察。`batch_executor.py` 包装既有 `phase4_batch.py`（复用其 generate→reconcile→NDG→commit 流程），新增：每 raw 状态机（**pending/in_progress/done/failed/permanent_failed/pending_deletion**——复审 B 修订，pending_deletion 并入正式枚举）+ 门禁挂载 + 崩溃续跑；**`batch_build_state.json` 写入加文件锁 + schema version 字段**（复审 H① 落点：三写者 services/ingest.py / services/files.py / executor 统一 schema，杜绝并发写丢失更新）。
  3. **每 raw 分支（C2 P0 加固）**：摄入前探测 source 页——**有 source 页** → `reingest_source`（cascade_delete 旧产出 + 删向量 + 重建）；**无 source 页**（1357/1364 首摄文件）→ 直接 `run_ingest` 首次摄入；`reingest_source` 抛 ValueError（源页被删）→ 走首次摄入分支而非 failed。
  4. **删除/重建补偿状态（C2 P0 加固，复审 B 修订——直跑模型下无"队列"术语）**：重建路径顺序改为"**重建调度成功 → 记 `pending_deletion` → cascade_delete → 记 done**"；崩溃在删除后、重建前 → 续跑时对 `pending_deletion` 文件**重跑重建**（直接调用 `run_ingest`，非"重入队"——直跑路径无队列）；**禁止"先删后建"的裸窗口**。
  5. **门禁并入 pre-commit（C4 P0 加固，复审 D 修订）**：fields/tags/lint/对账四项**并入 phase4_batch 的 pre-commit gate**（门禁失败 = 零写入，天然原子，消除"已提交未过门禁"窗口）——**Phase 4 中 1.5 的"批后新门禁"由 pre-commit gate 取代**（1.5 保留用于 Phase 3 实测与 dry-run，两处不并行）；M5"门禁批批通过率"归属 pre-commit gate；同时保留批级 `pending_gate` 状态（存于 `batch_build_state.json` 批级字段，executor 触发）——崩溃后续跑对**整批**（含已 done 文件）重跑门禁，杜绝门禁作用域收缩。
  6. **门禁数据 git 跟踪（P1 P0 加固，复审 G/H 修订）**：`.gitignore` **例外规则白名单放行**（`!.index/`、`!.index/batch_build_state.json` 等，钉死为 gitignore 例外规则而非 force-add）；`knowledge_gaps.json`、`batch_reports/` 同法放行；lancedb 不入 git，依赖"每批向量 upsert 可重放"；**新建 `scripts/rollback_batch.py`（回滚 = git checkout + 向量重建双动作脚本化，有落点）**。
  7. **幂等（P4 P0 加固，复审 G 修订）**：**钉死主机制 = `generate_task_hash` 增加重建轮次维度（`reingest:{batch}:{raw}`）**；`remove_hash`/`clear` 作为重建前兜底（辅，`get_idempotency_cache().clear()` 模块级符号，复审 J 修订）；禁止依赖 7 天内存 TTL。
  8. **存量旧页处置（F4）**：backlog 判定跳过/延期的 raw（duplicate/tiny/long_docs，阈值 16000 修正）对应旧页 → 归档或删除（复用 cleanup 脚本）；M7/M8 口径 = 覆盖范围内，范围外残留显式记录。
  9. **向量重建（H13）**：摄入前 `init_vector_store_for_paths` + **维度校验**（B11 结论：store 384 vs provider 可能 1536——不一致时先做维度迁移/切换决策，禁止 `_migrate_schema_if_needed` 静默 drop 表）；每批后向量 upsert。
  10. **gap 清单趋势维护（F3，复审 H 修订）**：open→resolved/suppressed，suppressed 提供**批量审批入口（CLI 子命令）+ 二次确认 + `reason` 字段记录**（B5 防博弈）；幻觉 slug 走别名注册表兜底或批量 suppressed；M11 按批净增/净减统计，净增超阈值（>5/批）触发暂停审查——**暂停有 owner（方案负责人）与恢复流程（人工 SLA 定义：审查周期 ≤3 工作日）**。
  11. **failed 文件治理（B1）**：failed 自动重投（重投前 `remove_hash` 或直接 run_ingest）；同一文件连续 3 批失败 → blocklist + 告警人工；批报告含 failed 清单，M10a 口径改为"实际完成数"。
  12. **预算检查（H④ 落点）**：每批后累计 token/费用与 0.2 B2 定稿预算比对，超限**自动暂停**（executor 顶层检查，非人工"超限即停"）。
  13. `is_immutable` 页摄入前跳过（1.7 守卫）；每批前 git 快照可回滚。
- **验收**：直跑路径全流程（kill -9 各阶段注入后续跑正确）；1357 首摄文件走首次摄入分支不炸；无"先删后建"裸窗口；门禁 pre-commit 零写入语义验证；M2 深引用率 ≥80%（或 0.2 修订后口径）；M8/M9 = 0（覆盖范围内）；M11 批均净增 ≤5。
- **Commit**：`feat(novel-wiki): 执行模型重写（直跑定死 + cascade分支 + 补偿事务 + pre-commit门禁 + 幂等轮次 + 向量维度）`

---

## Phase 4.5 — 多源 synthesis 聚合（M6 支撑，F1 整改）

- **Files**：`scripts/aggregate_synthesis.py`（新建）、`src/pipeline/`（跨批聚合入口）、`.index/batch_reports/` 消费
- **Tests**：`tests/test_scripts/test_aggregate_synthesis.py`（同主题 raw 的 claims 聚合 → 合成模板渲染 → sources ≥2 → 质量门通过）
- **Implementation guidance**：
  1. **输入明确（N5 闭环）**：按 taxonomy category（如"爽点与情绪"）聚合**已落盘的 concept 页**（读取其 `证据强度`/`反模式` 槽与 `sources` 字段，而非 claims——claims 无存档）→ 喂 synthesis 模板 → 生成"分歧汇聚"页（`sources` 含 ≥2 个独立 raw）；候选聚合主题由 gap 清单 + category 计数驱动。
  2. 产物过 1.2 synthesis 质量门（wikilink ≥2）；不达标进 gap；**聚合页作为独立批次 `batch_synthesis` 过 1.8 批内测量门禁**（聚合页不属于任何单个摄入批，其 M4/M5 归属定义为独立聚合批，每批聚合 ≤5 页）。
  3. M6 计数 = 本任务产出 + 批内自然合成；**首批阈值按首批可聚合主题数折算**（首批 20–40 raw ≈ 1–3 个聚合主题 → 首批验收 ≥1 页且质量门全过即可）；"每 100 raw ≥5"（≈68 页）仅在 Phase 5 终验按 1364 raw 换算。
- **验收**：首批聚合 ≥1 页且质量门全过；Phase 5 终验按 1364 raw 换算达标。
- **Commit**：`feat(novel-wiki): 多源 synthesis 聚合生成（分歧汇聚，sources≥2）`

---

## Phase 5 — 终验

- **Files**：`.index/baseline_2026-08-15.json`（复测）、plan/spec 回填、`.superpowers/sdd/progress.md`（账本更新）
- **Tests**：0.1 基线脚本差值断言（终验值 vs 基线值）
- **Implementation guidance**：复测 M1–M12（新口径）+ **M12 向量检索可用性抽查**（`python -m src.cli serve` 后对 3 个主题查询断言命中；**抽查前先校验向量维度与 store schema 一致**，P4）；**终验独立抽样（B5 防博弈，复审 H⑥ 修订）**：抽样 **N=50 或 gap 总量的 10%（取大者）** 个 suppressed gap slug，断言"页面确实不存在则仍计断链"——M1 报告同时输出 gap 剔除前后的原始断链数；M2 深引用率（0.2 定稿口径）；M7/M8 记录覆盖范围外残留；M6 按 4.5 换算；M11 批均净增趋势。
- **验收**：指标表全部达标或明确记录未达标项 + 后续任务挂账。
- **Commit**：`docs(novel-wiki): 终验报告 M1-M12 + progress 账本更新`

---

## 审查门

- **plan-audit 两轮已完成**：第一轮全面漏洞审计（F1–F8/H1–H14/N1–N18 整改闭环）+ 第二轮压力测试推演（C1–C4/P1/P4 六项致命 P0 加固已在本 plan 整改：1.9 LLM 接线、1.8 M2 扩展、0.2 扩容验算、Phase 4 执行模型重写）。
- **P0 落地复审（编码前必须）**：按 spec §11.7.5 与 §11.8，P0 整改后需重开一轮复审（确认 1.9 接线、Phase 4 分支/补偿事务/pre-commit 门禁、0.2 M2 验算已落地）方可进入编码。
- 人工复核后进入编码；编码遵守 TDD-per-task；每任务 reviewer；`src/server/` 或 `src/cli.py` 涉及时跑 `serve` + `/health`。
- 领域术语（写作技法/题材体系等分类轴）沉淀 `CONTEXT.md` 在 Phase 2.1。
