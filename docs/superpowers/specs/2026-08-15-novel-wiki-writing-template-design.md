# 写作知识库场景模板方案（novel-wiki v3）— 设计

> 状态：design 初稿，待 plan-audit 两轮审查 + 人工复核后方可进入编码（项目工作流门）。
> 本文档由独立第三方审计驱动：方案成立依据是审计实测数据，不是设计意图自述。所有"为什么"都指向可复测的基线值。

## 1. 背景与审计结论（为什么推翻原方案）

对 `knowledge/novel-wiki/`（网文写作知识库，1364 raw 教程文件）的模板栈做独立审计，实测基线：

| 问题 | 实测 | 根因指向 |
|---|---|---|
| wikilink 断链 | **55.1%**（584/1059） | LLM 自创 slug；"参考来源/相关概念"强制 wikilink 但无引用-产出对账 |
| tap rate | **0.5%**（7 source 页 / 1364 raw） | 99.5% 素材未摄入；"参考来源"必然断链 |
| concept 项目覆盖零采纳 | 局限与风险 0 页 / 信息冲突 0 页 | 可选槽（`?`）无强制、无统计、不可验证 |
| taxonomy_sub 隐性类型 | 40+ 自由字符串 | 4 类 PageType 一桶装，无受控分类轴 |
| synthesis 产出 | **0** | 对比表形态错位 + 人工门无人审 |
| source 全文污染 | 7/7 内嵌 ASR 错乱转录 | 模板无防原文机制；prompt 禁令未执行 |
| 旧英文 tag 前缀 | 205/384 页 | 前缀中文化未迁移存量 |
| 非法 relations | 10 页 `related_to`（不在 17 型内） | 对账层未覆盖 relations[].target |
| entity 弱填充 | 80%（89/111） | 实体模板百科化，无写作域语义 |

**审计结论**：不存在"为网文写作设计的场景模板"——现有栈是通用百科模具 + 零采纳的项目覆盖。模板每一部分都在写作域出现可量化失效，且失效同向：写作域需要**程序化、情境化、分歧化、时效化**知识，模板只提供**百科化、单一权威、静态化**结构。本方案按此逐项重建。

## 2. 目标与非目标

### 目标
- 为 novel-wiki 交付一套**写作域场景模板**（bundled 级资产 + 项目级落地），让 4 类 PageType 通过三重约束（taxonomy 枚举 / tags 正交 / 模板槽）承载写作知识。
- 全量重摄入 1364 raw，用门禁闸门保证**新产出质量可验证**，验收 = M1–M11 实测指标而非文档字数。
- 建立引用-产出对账、gap 清单、指标上报，让"断链、槽位失效、类型塌缩"成为可检测信号。

### 非目标（明确排除）
- 不建 schema 自定义类型（保持 source/entity/concept/synthesis 4 类 + 强约束）。
- 本轮不做个人创作资产层（大纲/人物卡/世界观）——独立后续任务。
- 不重渲染/重分类存量页的既有内容（存量由全量重摄入自然重建）。
- 不改 relations 17 型集合（仅补对账执行）。

## 3. 已确认决策全景（grilling 收敛，18 项）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 知识库定位 | c 分层混合（公开知识层 + 个人资产层；资产层本轮留白） |
| D2 | 交付形态 | c 资产 + 实测同步交付，验收=实测指标 |
| D3 | 类型体系 | b 保持 4 类 + 强约束 |
| Q6 | 验证闭环 | c 双轨（新摄入硬门禁 + gap 清单 + 指标上报） |
| Q7 | 存量处置 | b 全量重摄入重建 |
| Q8 | 强约束实现 | d 三者组合：taxonomy 管分类轴 / tags 管正交维度 / 模板槽管内容结构 |
| Q9 | 重摄入执行 | a 分批 + 门禁闸门（每批 ≤20，不过不进下一批） |
| Q10 | 个人资产层 | a 本轮留白 |
| Q11 | concept 模板 | a 3 槽必填：适用场景 / 反模式与常见错误 / 证据强度 |
| Q12 | 其余模板 | c 三个都改：source 转录质量+防全文 / entity 写作价值 / synthesis 分歧汇聚 |
| Q13 | tags | a 收紧（情绪/场景阶段受控枚举）+ 新增两轴（读者群/、平台/） |
| Q14 | 指标 | c 指标表 v2（M1–M11） |
| Q15 | taxonomy 分法 | a 知识类型一级 + 细分二级 |
| Q16 | 断链处理 | c 重试一次 + gap 清单 |
| Q17 | synthesis 生成 | b 自动生成 + lint 质量门 |
| Q18 | 批次顺序 | c 缺口优先 + 主题推进 |
| Q19 | 资产确认 | a 全部确认 |

## 4. 场景模板资产 v3.0.0

### 4.1 schema.md（项目级，写入 novel-wiki 根目录）

保持 4 类（与 bundled general 一致，不声明自定义类型）；新增写作域 Conventions 说明。

```markdown
# Wiki Schema

## Page Types
| type | directory |
|------|-----------|
| source | wiki/sources |
| entity | wiki/entities |
| concept | wiki/concepts |
| synthesis | wiki/synthesis |

## Conventions
- 页面使用 YAML frontmatter 和 [[wikilink]] 交叉引用。
- 分类轴：category/taxonomy_sub 必须落入 taxonomy.md 受控枚举（见项目 taxonomy.md）。
- 可信度：UGC 来源页面必须打 素材/ugc + 可信度/ugc 双 tag。
```

### 4.2 purpose.md（项目级，写作域改写——替代通用"可持续维护的知识库"）

```markdown
# Project Purpose — 网文写作知识库

## Goal
- 构建"可检索、可执行、可证伪"的网文写作知识库：外部教程（技法/题材/平台规则/读者市场）沉淀为结构化页面，供写作时按场景检索。
- 区分：可执行的技法（如何写）与情境化事实（题材读者期待、平台规则）与案例素材（原文片段+出处）。

## Key Questions
1. 这个技法什么时候用、什么时候不用？（适用场景/反模式）
2. 这个知识来自哪里、可信度多高、有哪些矛盾观点？（证据强度/分歧）
3. 检索时用户要的是"如何写开篇"，不是"开篇的定义"。（procedure 优先）
```

### 4.3 taxonomy.md（受控分类轴，Q15=a）

```markdown
# Taxonomy

## 写作技法
- 选题与立意
- 大纲与结构
- 开篇与黄金三章
- 人物塑造
- 情节与冲突
- 爽点与情绪
- 节奏与悬念
- 文笔与语言
- 对话与描写
- 世界观设定
- 修改与打磨

## 题材体系
- 玄幻
- 仙侠
- 都市
- 科幻
- 悬疑推理
- 历史军事
- 游戏竞技
- 女频现言
- 女频古言
- 女频玄幻
- 流派变体

## 平台规则
- 签约
- 上架
- 全勤与福利
- 推荐与曝光
- 审核与合规
- 版权与运营

## 读者与市场
- 读者心态
- 市场趋势
- 数据分析
- 作者运营

## 案例与素材
- 作品案例
- 片段与金句
- 桥段与梗
- 诗词素材

## 心态与职业
- 写作心态
- 习惯与方法
- 职业规划
```

- `TaxonomyRegistry` 已支持 taxonomy.md 解析/注入/validate（`src/wiki/taxonomy_registry.py`）；**`fields validate` 接入 taxonomy 门禁是 Phase 1 新建能力**（审计确认 `cmd_fields_validate` 现无 taxonomy 校验——B-O3/H10 修正）。全量重摄入后批内新页 100% 落入枚举（M3，批内口径）。

### 4.4 tags 正交维度（Q13=a）

| 前缀 | 状态 | 受控枚举 |
|---|---|---|
| `情绪/` | 收紧 | 爽、虐、甜、燃、悬疑、惊悚、治愈、热血、轻松、沉重 |
| `场景阶段/` | 收紧 | 开篇、发展、高潮、结局、日常、战斗、情感、悬疑 |
| `读者群/` | **新增** | 男频、女频、全年龄、青少年、中老年 |
| `平台/` | **新增** | 起点、番茄、晋江、纵横、飞卢、QQ阅读、掌阅 |
| `题材/ 功能/ 角色/ 事件/ 实体/ 状态/ 素材/ 可信度/` | 保留 | 现有语义不变（`素材/ugc`、`可信度/ugc` 等） |

- 枚举落地：写入 taxonomy.md 的 tags 枚举节——**独立解析**（不与 `## 分类` 共用正则，防污染分类命名空间；plan 1.4 落地），`tags validate` 扩展校验枚举值，未枚举即违规。
- 旧英文前缀（`genre/` 等 205 页）由全量重摄入自然消解（M8），不写迁移脚本。

### 4.5 页面模板 v3.0.0（写作域槽全部必填；entity 别名槽为唯一可选——可选槽零采纳的教训仅约束"写作域新增槽"，不约束本就语义真实的 entity 别名）

> **格式契约（F3 整改）**：`## 标题` **独占一行**（标题行禁止出现任何标记）；`<!-- slot:NAME -->` 放章节 body；语义说明用 `<!-- … -->` HTML 注释独立成行（parser 剥离，不影响渲染）；禁止 `#` 行内注释。解析期断言：模板任何 `## ` 行不得包含 `slot:`。

**concept.md**（Q11=a）：
```
<!-- wiki-template-version: 3.0.0 -->
<!-- wiki-template-type: concept -->

## 定义

<!-- 概念的准确定义，以来源表述为准 -->

<!-- slot:definition -->

## 主要特点

<!-- 2-3 个核心特征/构成要素 -->

<!-- slot:characteristics -->

## 适用场景

<!-- 何时用/何时不用；技法页填适用题材/读者群/阶段，概念页填适用语境 -->

<!-- slot:context -->

## 反模式与常见错误

<!-- 新手错法/套路反噬/边界条件 -->

<!-- slot:anti_patterns -->

## 证据强度

<!-- 来源性质（UGC/书/官方）、已知矛盾观点 -->

<!-- slot:evidence -->

## 例子

<!-- slot:examples -->

## 相关概念

<!-- slot:related_concepts -->

## 参考来源

<!-- slot:references -->
```

**source.md**（Q12=c）：
```
<!-- wiki-template-version: 3.0.0 -->
<!-- wiki-template-type: source -->

## 来源元数据

<!-- 来源类型/平台/作者/URL/获取时间/任务ID -->

<!-- slot:source_meta -->

## 转录质量

<!-- 人工撰写/OCR/ASR + 可读性评级；ASR 强制标注 -->

<!-- slot:transcription_quality -->

## 摘要

<!-- slot:summary -->

## 关键观点

<!-- 每条含原文定位 -->

<!-- slot:key_points -->

## 可信度声明

<!-- UGC/书籍/官方 + 依据 -->

<!-- slot:credibility -->
```

**entity.md**（Q12=c）：
```
<!-- wiki-template-version: 3.0.0 -->
<!-- wiki-template-type: entity -->

## 基本信息

<!-- slot:basic_info -->

## 简介

<!-- slot:summary -->

## 写作价值

<!-- 范例手法/可复用写法/避坑点；人物→塑造手法，作品→结构文风，平台→投稿上架参照 -->

<!-- slot:craft_value -->

## 别名

<!-- 无则省略（entity 唯一可选，语义真实） -->

<!-- slot:aliases? -->

## 相关引用

<!-- slot:related -->
```

**synthesis.md**（Q12=c，分歧汇聚）：
```
<!-- wiki-template-version: 3.0.0 -->
<!-- wiki-template-type: synthesis -->

## 议题与分歧点

<!-- slot:topic -->

## 各方观点

<!-- 每条附 [[来源]] + 可信度；lint 强制 ≥2 条 -->

<!-- slot:viewpoints -->

## 共识

<!-- slot:consensus -->

## 证据对比

<!-- slot:evidence_comparison -->

## 待定与结论

<!-- slot:conclusion -->
```

> 版本与 lint 联动（H3 整改）：v3.0.0 **只落 novel-wiki 项目级模板**，bundled 保持 2.0.0 不动（bundled 是平台所有项目的默认模板，改写会污染全平台）。lint `LINT-MISSING-SECTION` 版本门按项目解析出的模板版本判定——项目级 v3.0.0 新页按新必填槽检查；存量 2.0.0 页仍按 ≥2.0.0 检查（向后兼容）。全量重摄入后 novel-wiki 页面均为新版本（Q7=b 使"必填槽"可行——此前被 1150 旧页否决的约束本次可用）。

## 5. 验证闭环设计（Q6=c 双轨 + Q16=c）

### 5.1 引用-产出对账（Phase 1 实现；"F3"此处指历史术语——novel-wiki-ingest-spec §三的 Generator 根因，与 §11.1 的 F3=模板格式是不同编号体系）

1. Generator 产出后，代码校验 `relations[].target` + body wikilink 是否 ∈ 产出 ∪ 已有索引。
2. 未解析 slug → 缺失清单塞回 prompt **重试一次**（Q16=c），让 LLM 自修。
3. 重试后仍断 → 记入 `.index/knowledge_gaps.json`，页面入库（链接保留，gap 标记）。

### 5.2 gap 清单（`.index/knowledge_gaps.json`）

```json
{ "slug": "装逼打脸", "title": "装逼打脸", "alias": null, "type": "concept", "raw_hint": null, "referenced_by": ["wiki/concepts/xxx.md"], "created_at": 0, "status": "open|resolved|suppressed" }
```

- 状态流转：open →（批量生成/提升）resolved；人工判定无效 → suppressed。
- 驱动 Phase 4 批次顺序（Q18=c：首批补"被引用但无 source 页"的 raw，直接消解断链源头）。

### 5.3 门禁闸门（Q9=a；复审 D 修订——Phase 4 中门禁并入 pre-commit）

每批（≤20 raw）完成后顺序执行，全过才进下一批：
1. `fields validate`（taxonomy 枚举 + frontmatter 契约）
2. `tags validate`（前缀 + 枚举值）
3. `lint`（含 RAW-PASTE 强化、MISSING-SECTION 升 ERROR、synthesis 质量门、占位符检测）
4. 断链对账（批内产出引用必须解析；未解析进入 gap，禁止静默）

> **执行时序（复审 D 修订）**：Phase 3 实测用批后门禁（1.5）；**Phase 4 全量摄入中，上述四项并入 phase4_batch 的 pre-commit gate**（门禁失败 = 零写入，天然原子），1.5 批后门禁在 Phase 4 中被取代（保留用于 dry-run）；M5 归属 pre-commit gate；崩溃后续跑对整批（含已 done 文件）重跑门禁（`pending_gate` 批级状态）。

### 5.4 lint 检查强化（Phase 1 实现，plan-audit 第一轮修订）

> **修订说明**：不再新增 `LINT-RAW-LEAK` 规则——`src/wiki/features/lint.py` 已有 `LINT-RAW-PASTE`（含全文章节检测 `_FULLTEXT_SECTION_RE`、双阈值 `_load_raw_paste_thresholds`、fence-aware），本方案在其上强化并修正口径，避免双规则并存。

| 检查 | 判定（修订后） | 级别 |
|---|---|---|
| RAW-PASTE 强化 | **source 页**：全文章节头命中（`_FULLTEXT_SECTION_RE`）**或超长未引用段**（阈值收紧至 source 摘要合理上限——source 摘要预期 300–800 字，T_source 从 2000 收紧至 **800**（或按 quality_settings 校准），**不可收紧至 300**（300 会误报正常摘要，正是 H7 原问题）；1.6 移除 `main_content` 槽后此兜底才有效，否则 M7 对"覆盖范围内"新页空转假绿，F5×H7 交叉整改）；**非 source 页**：超长未引用段落（阈值从 `.index/quality_settings.json` 读，不硬编码 300） | 升 ERROR（原 WARNING） |
| synthesis 质量门 | **不依赖 frontmatter `sources` 计数**（pipeline 产出的 synthesis `sources` 恒为单条，F1 整改）；解析渲染后 body 的 `## 各方观点` 章节，其内 `[[wikilink]]` 解析成功 <2 个即报；仅对模板声明 ≥3.0.0 的 synthesis 页生效 | ERROR |
| MISSING-SECTION | 升 ERROR（原 WARNING）；**版本门按项目解析出的模板版本判定**（v3.0.0 只落项目级，bundled 保持 2.0.0，H3 整改）；存量 2.0.0 页仍按 ≥2.0.0 检查 | 升 ERROR |
| 占位符检测 | body 含 `（系统占位` / `待补充` / `见下游概念页` / `来源未提供具体例子`（可配置列表）——**新增检测用 substring 包含判定**（现有 `_READABILITY_PLACEHOLDERS` 是整 body 相等判定且仅 4 个值，语义不同，需新增独立检查而非扩展该集合） | ERROR |
| tags 枚举校验 | tag 值不在受控枚举（枚举单一真源 = taxonomy.md tags 节，H4 整改） | ERROR |
| relation 类型校验 | `relations[].type` 不在 17 型 + `x-*` | ERROR |

### 5.5 指标上报

每批后生成批次报告（写 `.index/batch_reports/` 或 log.md 追加）：M1/M4/M6/M7 逐批值，M11 gap 存量趋势。

## 6. 指标表 M1–M12（验收基准，对照审计基线；plan-audit 第一轮修订后）

| # | 指标 | 审计基线 | 目标 | 测量 |
|---|---|---|---|---|
| M1 | **未登记断链率**（body wikilink + relations target，解析集合 = 磁盘页 ∪ SlugAliasRegistry ∪ 索引；gap 不算断链） | 55.1%（584/1059） | 重摄入批内 0；全库 <5% | 对账脚本（1.8 批内测量 API） |
| M2 | **深引用率**（被 ≥1 个**非 source 页** `sources` 引用的 raw 占比，**排除"同 raw 自产页"**——每 raw 生成的 entity/concept 页 `sources` 恒列自身 raw，计入则 M2 恒 ≈100% 成新重言式，复审 C 修订；source 页自身引用不计——原 tap rate 是重言式，F7 整改） | 0.5%（7/1364） | ≥80%（**或 0.2 验算后修订口径**，复审 F） | 对账脚本（metrics.py） |
| M3 | taxonomy 覆盖（批内新页 category/sub 100% 枚举；存量豁免，门禁只查批内） | 40+ 自由值 | 100% | fields validate（批内） |
| M4 | 必填槽通过率（lint MISSING-SECTION = 0 + 占位符检测 = 0；批内） | 覆盖零采纳（0/264） | 100% | lint（批内子集） |
| M5 | 门禁批批通过率（写时 NDG + 批后新门禁，批内作用域） | 未测 | 100% | 批后校验 |
| M6 | synthesis 产出数 | 0 | 每 100 raw ≥5（依赖 Phase 4.5 聚合） | 目录计数 + 聚合任务 |
| M7 | source 全文污染（`_FULLTEXT_SECTION_RE` 命中） | 7/7 | 0（覆盖范围内，范围外残留显式记录） | 对账脚本 |
| M8 | 旧英文 tag 前缀 | 205/384 | 0（覆盖范围内；存量由 cascade 重建消解） | tags validate |
| M9 | 非法 relations 类型 | 10 页（13 处） | 0（覆盖范围内） | 对账脚本 |
| M10a | 每批文件数 | 未统计 | ≤20 md/批 | 批次日志 |
| M10b | 每批 LLM 调用数/Token/费用/时长 | 未统计 | 预算上限内（Phase 0 定基线） | 批次报告成本字段 |
| M11 | gap 批均净增（趋势指标，非绝对存量；净增 >5/批 触发暂停审查） | 未建 | ≤5/批，终验净减或平稳 | gap 清单统计 |
| M12 | 向量检索可用性抽查（serve 后 3 主题查询命中） | 无向量库（`init_vector_store_for_paths` 未调用） | 3/3 命中 | 检索脚本 |

## 7. 任务拆分 Phase 0–5（plan-audit 第一轮修订后，细节见对应 plan）

- **Phase 0 基线复测 + 盲区统计**：0.1 复测 M1–M12（新口径）；0.2 盲区 B1–B10（backlog 分类/成本抽样/stub 与 immutable 数量/tag 分布/别名条目）；0.3 **index 重建对齐**（实测 index 15 条 vs 磁盘 382 页，367 个 LINT-ORPHAN 必须先清）。→ 验收：基线 JSON + B1–B10 数值 + index 对齐。
- **Phase 1 平台改造**（TDD，plan-audit 第一轮后任务集）：
  1. **项目级**模板 v3.0.0（**bundled 保持 2.0.0 不动**——bundled 是平台默认模板，改写污染全平台）+ generator 静态槽表同步 + field-guide/wiki-spec 文档同步
  2. `lint`：RAW-PASTE 强化（source 按章节头/非 source 按阈值）、synthesis 质量门（wikilink≥2）、MISSING-SECTION 升 ERROR + 版本门按项目模板、占位符检测、tags 枚举校验、relation 类型校验
  3. 引用-产出对账（集合含 SlugAliasRegistry）+ 单调用闭环重试 + gap 清单（含质量过滤迁移/统一 slug 归一）+ 废除自动建 stub
  4. `fields validate`/`tags validate` taxonomy/tags 枚举**单一真源**门禁 + 批模式（文件引用修正：`tags_cmd.py` 不存在，实住 `fields_cmd.py`）
  5. 门禁闸门：**复用 NDG/batch_reconcile**（非新建平行门禁）+ **批内作用域** + lint_wiki 直接调用
  6. **source 页确定性构建器同步 v3.0.0 槽**（转录质量/可信度代码判定）
  7. **write_page is_immutable 守卫 + updated_at 比对**
  8. **批内测量 API**（M1/M4/M6/M7 按页面集合）
- **Phase 2 场景模板落地 novel-wiki**：写 `schema.md`（§4.1）、`purpose.md`（§4.2）、`taxonomy.md`（§4.3 + §4.4 tags 枚举**独立节**）、`.wiki-templates/*.md` 项目级副本（v3.0.0，废弃零采纳可选槽）。
- **Phase 3 实测首轮**：缺口优先选 1–2 批（20–40 raw，**扩展名白名单**）摄入，用 1.8 批内 API 验证 M1（批内未登记断链 0）、M4（100% 槽填充）、M7（无全文污染）；RAW-PASTE 阈值用真实批次校准。失败即修 Phase 1，不进入 Phase 4。→ 验收：首轮指标达标。
- **Phase 4 全量分批重摄入**：批执行器（状态机/崩溃续跑/熔断暂停）+ **每批 cascade 清理再摄入**（reingest_source，重建非累积）+ 存量旧页处置（backlog 跳过项）+ **向量重建**（init_vector_store_for_paths + upsert）+ 门禁数据 git 跟踪 + gap 趋势维护（M11）。→ 验收：M2≥80%、M8/M9=0（覆盖范围内）、M11 批均净增≤5。
- **Phase 4.5 多源 synthesis 聚合**：同主题 raw 的 claims 聚合 → 分歧汇聚页（sources ≥2）→ 质量门。→ M6 计数源。
- **Phase 5 终验**：M1–M12 全量复测（含 M12 向量检索抽查），对照 §6 出验收报告。个人资产层另立任务。

## 8. 与现有机制的关系

| 机制 | 现状 | 本方案动作 |
|---|---|---|
| `SchemaRegistry`（schema.md 自定义类型） | 能力完备（reading/personal/research 已用） | **不用**（D3=b），但 schema.md 保留 4 类 + Conventions |
| `TaxonomyRegistry`（taxonomy.md） | 解析/注入/validate 已存在 | 写入写作域枚举，启用 validate 门禁 |
| 模板 resolver（project→user→bundled） | 三级优先级 | 项目级副本 v3.0.0；bundled 保持 2.0.0 不动（H3）；不改 resolver（4 类不变） |
| lint（MISSING-SECTION / 断链） | 版本门硬编码 ≥2.0.0 | 版本门改按项目解析的模板版本判定；MISSING-SECTION 升 ERROR；占位符/synthesis 质量门/relation 类型/tags 枚举（§5.4 六行） |
| 引用-产出对账（历史审计编号 F3，与 §11.1 的 F3=模板格式是不同编号体系） | 部分实现（stub 兜底） | 完整实现：relations + wikilink + SlugAliasRegistry + 单调用重试 + gap |
| heat/stubs/dedup/md5 幂等 | 现有 | 沿用；幂等仅内存 7 天 TTL，重摄入靠 gap/人工清单去重 |

## 9. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 新模板 LLM 填充质量不达标（首轮实测失败） | Phase 3 门：不达标不进入 Phase 4，回头修模板槽措辞/提示词 |
| 全量重摄入成本失控 | M10a 每批 ≤20 + M10b token/费用/时长实测基线；预算超限即停；熔断器 OPEN 时暂停等待（不吞错） |
| 词条膨胀复发 | M6 阈值 + gap 清单（未解析引用不再自动建 stub，转 gap 含质量过滤）+ M11 批均净增熔断 |
| synthesis 自动生成质量差 | lint 质量门（各方观点 wikilink ≥2）；不达标页进 gap 待人工；多源聚合走 Phase 4.5（pipeline 单 raw 产出 synthesis `sources` 恒为单条，F1 整改） |
| 重摄入覆盖已有手工修正 | 1.7 write_page is_immutable 守卫 + updated_at 比对（代码实现，非纸面声明）+ 每批前 git 快照 |
| 重摄入累积膨胀（非重建） | Phase 4 每批 cascade 清理再摄入（reingest_source：cascade_delete 旧产出 + 删向量） |
| 门禁被存量污染 | 批内作用域（1.8 批内测量 API + 1.5 门禁只查批内新页）；Phase 0.3 index 重建前置 |
| 断链重试烧钱无效 | 对账集合含 SlugAliasRegistry；重试为单调用内闭环反馈（不整链重跑）；幻觉 slug 批量 suppressed |
| 批崩溃/重启失忆 | 批状态机落盘 `.index/batch_build_state.json`（崩溃续跑；统一文件名，O5）+ 门禁数据 git 跟踪（需 gitignore 白名单放行） |
| 向量检索失效 | Phase 4 向量重建（init_vector_store_for_paths + upsert）+ M12 抽查 |
| 回滚 | 每批摄入前 `git` 快照 + `.index/batch_build_state.json` 门禁数据入 git（需 gitignore 白名单放行）；模板/代码改动在 Phase 1 独立 commit，可 revert |

## 10. 审查门（项目工作流）

- **第一轮（全面漏洞审计）已完成（2026-08-15）**：两个并行独立审计（Phase 1 模板/lint 契约；Phase 3–4 门禁/批次闭环），全部发现与整改见 §11。整改后已**再次执行第一轮审计**（复审子代理逐条核验 F1–F8），发现并修复 F3（§4.5 模板格式）与 F5 衍生（source 页 RAW-PASTE 锚点）等残留。复审结论见 §11.6。
- **第二轮（压力测试推演）**：Phase 1 完成、本 spec 整改后再执行（模拟失败路径：批中断、LLM 超时/限流、熔断 OPEN、gap 爆炸、人工缺位）。
- 人工复核后进入编码；编码按 TDD-per-task + 每任务独立 commit。
- 领域术语维护：写作域分类（题材体系/写作技法等）如需沉淀进 `CONTEXT.md`，在 Phase 2 一并处理。

---

## 11. plan-audit 第一轮整改记录（2026-08-15）

> 两个并行独立审计报告（A：Phase 1 模板/lint 契约；B：Phase 3–4 门禁/批次闭环）的合并处置记录。每条：问题 → 裁定 → 已改位置。

### 11.1 致命缺陷（合并去重后 8 项）

| # | 问题 | 裁定 | 已改位置 |
|---|---|---|---|
| F1 | synthesis 质量门 `sources≥2` 与所有现有生成路径互斥（pipeline 产出 synthesis `sources` 恒为单条）→ 每个 synthesis 页必被自己质量门拦下，M6 不可达 | 采纳：质量门改"各方观点章节内 wikilink 解析 ≥2"；多源聚合独立为 Phase 4.5 | spec §5.4、§6 M6、§7；plan 1.2、Phase 4.5 |
| F2 | M1"批内 0 断链"与 gap 合法出口自相矛盾，gap 批永不过验收 | 采纳：M1 改为"未登记断链率"（gap 不算断链）；M11 改趋势指标（批均净增 ≤5） | spec §6 M1/M11；plan 验收目标、Phase 4 |
| F3 | 模板格式错误：slot 注释写在 `##` 标题行内，parser 只扫 section body → 新槽识别不到、注释泄漏进正文 | 采纳：标题独占行、注释进 body、HTML 注释、解析期断言 | spec §4.5（修订）；plan 1.1 |
| F4 | 版本门 3.0.0 + backlog 跳过（duplicate/tiny/long_docs 不重摄入）→ 旧污染页永不清理，M7/M8 终验不可达 | 采纳：Phase 4 存量旧页处置任务；M7/M8 口径=覆盖范围内；B1 统计 backlog | spec §6、§7；plan Phase 4、0.2 |
| F5 | source 模板新必填槽（转录质量/可信度）与 ingest.py 确定性 source 构建器脱节 → 必填槽填占位、lint 只查标题假绿 | 采纳：1.6 source 构建器同步新槽（代码判定转录质量/可信度） | spec §7；plan 1.6 |
| F6 | taxonomy 落盘后存量 364+ 页（category=''）fields validate 全红——门禁无批内作用域 | 采纳：门禁只校验批内新产出页；1.8 批内测量 API；0.3 index 重建 | spec §6、§7；plan 1.5、1.8、0.3 |
| F7 | M2 tap rate 重言式（每个 raw 被自身 source 页引用即 100%） | 采纳：M2 改"深引用率"（被 ≥1 个非 source 页引用） | spec §6 M2；plan 0.1 |
| F8 | write_page 无 is_immutable 守卫且全库 0 immutable 页，豁免无落点 | 采纳：1.7 write_page 守卫 + updated_at 比对（代码实现） | spec §7、§9；plan 1.7 |

### 11.2 重大隐患（采纳处置摘要）

| # | 问题 | 裁定 |
|---|---|---|
| H1 | `_SLOT_TO_HEADING` 未注册新槽 → v3.0.0 页全槽误报 MISSING-SECTION | 采纳：扩展映射或改从模板 section 取 heading；加映射测试 |
| H2 | MISSING-SECTION 是 WARNING，门禁"任一 ERROR"拦不住 M4；占位符假绿 | 采纳：升 ERROR + 新增占位符检测 + batch_gate 直接调 lint_wiki |
| H3 | v3.0.0 写入 bundled 污染全平台默认模板 | 采纳：**bundled 保持 2.0.0**，v3.0.0 只落项目级；版本门按项目模板判定 |
| H4 | tags 枚举双重真源 + 收紧误伤存量 | 采纳：单一真源（taxonomy.md）+ 一致性测试 + 新旧值并集过渡 |
| H5 | 新门禁与既有 NDG 门禁双轨未定义 | 采纳：复用 ndg_gate/batch_reconcile，新门禁只补缺失项，写明时序 |
| H6 | 重试需整链重跑 + 对账未含 SlugAliasRegistry | 采纳：单调用内闭环反馈 + 对账集合含别名注册表；M10b 成本字段 |
| H7 | RAW-LEAK 与 RAW-PASTE 重复、source 豁免矛盾、300 字误报散文槽 | 采纳：不新增规则，强化 RAW-PASTE（source 章节头/非 source 阈值），阈值从 quality_settings 读 |
| H8 | 生成器静态槽表未同步 → 新槽零语义引导 | 采纳：三处静态槽表 + `_auto_fill_deterministic_slots` 同步 + 槽集一致性测试 |
| H9 | 存量 100 个 stub entity 页无处置任务 | 采纳：Phase 4 cleanup_stub_pages.py 清理；gap 写入继承质量过滤（blocklist/上限/doc-title） |
| H10 | plan 引用不存在的 tags_cmd.py；fields validate 无 taxonomy 校验 | 采纳：Files 改 fields_cmd.py；批模式；taxonomy 校验接入 read_page 后 |
| H11 | 幂等自锁（重投被 7 天内存判重）+ Phase 4 无执行器 | 采纳：批执行器 + 状态机落盘 + 执行路径定死；批报告含"实际 vs 清单"对账 |
| H12 | slug 归一不一致（normalize_id_chars vs _slugify）→ 假断链 | 采纳：统一归一函数，三处共用 |
| H13 | 项目无向量库（无 .index/lancedb），直跑脚本不写向量 | 采纳：Phase 4 向量重建 + M12 抽查 |
| H14 | index.md 15 条 vs 磁盘 382 页，367 个 LINT-ORPHAN 噪声 | 采纳：0.3 index 重建对齐 |

### 11.3 优化疏漏（采纳摘要）

- O1 废弃 `wikilink.create_stub_if_missing`（无调用者）→ plan 1.3-6。
- O2 gap 结构补 title/alias/type/raw_hint → plan 1.3-3。
- O3 模板注释统一 HTML 注释（`render_for_prompt` 剥离）→ plan 1.1。
- O4 `wiki_rules_prompt.py` 是 sync 脚本生成物：改 wiki-spec.md → 跑 `sync_wiki_spec.py` → 提交生成物 → plan 1.4。
- O5 taxonomy strict 解析 + tags 枚举节独立（防污染分类命名空间）→ plan 1.4-4、2.1。
- O6 `.index` 门禁数据入 git（回滚可续跑）→ plan Phase 4-6。
- O7 扩展名白名单（1361 md + 3 json）→ plan Phase 3/4。
- O8 验收命令带 `--project` 作用域 → plan 1.1 验收。

### 11.4 信息盲区（已并入 Phase 0.2）

B1 backlog 分类统计｜B2 每批成本实测｜B3 stub/immutable 数量｜B4 平台其他项目清单｜B5 存量 tag 分布｜B6 slug_aliases 条目｜B7 lint 规则版本门控范围｜B8 synthesis 触发率｜B9 taxonomy_sub 存量清单｜B10 重试对断链降幅实验。

### 11.5 整改完成声明与复审要求

- 本 spec §4.5/§5.4/§6/§7/§9 与对应 plan 已按上表全部修订（2026-08-15）。
- **整改后复审**：按 plan-audit 流程，需再次执行第一轮审计确认 F1–F8（§11.1）已修复；随后执行第二轮压力测试推演。复审通过前不进入编码。

### 11.6 整改后复审记录（2026-08-15，第二轮独立复审）

> 两个并行复审子代理（A：F1–F8 逐条核验；B：H1–H14 + O1–O8 + 新矛盾扫描），基于整改后最终文本核验。结论与处置如下。

**F1–F8 核验（复审 A）**：F1/F2/F4/F6/F7/F8 已修复；F3 曾"部分修复/声明失实"（§4.5 模板片段未按标准格式改）——**本次已重写 §4.5 全部模板片段**（`## 标题` 独占行、slot 进 body、HTML 注释、解析期断言）并修正 §4.5 标题矛盾、§10 编号；F5 修复引入"source 页 RAW-PASTE 锚点失效"新空白——**本次已在 §5.4/plan 1.2 补"超长未引用段兜底 + T_source 收紧至 800"**。

**H1–H14 核验（复审 B）**：12 项已修复；H3 残留（§8 旧表述、版本门公式自比）与 H11 残留（幂等绕过、双执行器、双状态文件）——**本次已修**（§8 lint 行、plan 1.2-2 公式、plan Phase 4-2 包装 phase4_batch + 统一 batch_build_state.json + 幂等绕过路径）。

**新矛盾 N1–N18 处置（复审 B）**：

| 编号 | 问题 | 处置 |
|---|---|---|
| N1 | plan 1.2-2 版本门公式自比 | 已改：页声明版本 ≥ 项目解析模板版本 |
| N2 | spec §8 残留"bump 3.0.0 + 4 条新规则" | 已改：版本门按项目模板 + §5.4 六行 |
| N3 | 1.6 转录质量无源可判 | 已改：ASR 信号=`GPU 加速转录生成`标记；OCR 不臆断；credibility 复用 `_is_ugc_carrier` |
| N4 | 1.8 与 0.1 两套测量口径 | 已改：0.1 基线脚本调用 metrics.py 共用核心 |
| N5 | Phase 4.5 聚合输入无存档 | 已改：输入 = 已落盘 concept 页（证据强度/反模式槽 + sources），非 claims |
| N6 | stub 100 vs 实测 165 | 已改：165 = entities 100 + concepts 65，全库口径 |
| N7 | stub→gap 一次性转换与 M11 冲突 | 已改：存量 stub 删除/归档（不走转 gap），处置批 M11 单独豁免口径 |
| N8 | 双执行器/双状态文件 | 已改：batch_executor 包装 phase4_batch；统一 batch_build_state.json |
| N9 | §10 引用不存在的 §11.6 | 本记录使引用成立 |
| N10 | T_source 收紧 300 误报 300–800 字摘要 | 已改：收紧至 800（quality_settings 可校准） |
| N11 | 并发编辑致声明失真 | 本记录为最终编辑锁定后的冻结快照 |
| N12 | spec §5.2 gap 示例未同步 | 已改：示例补 title/alias/type/raw_hint |
| N13 | plan 2.2 验收命令名错误 | 已改：`wiki-templates list --project` |
| N14 | 编号 F9/B-* 无定义 | 已改：1.3-6 改 H9；Phase 3-3 改 F5×H7；B-* 标注审计-B 内部编号 |
| N15 | §4.4 aliases 机制 vs 独立文件 | 已改：统一"独立解析，不与 ## 分类 共用正则" |
| N16 | M2 分母 1364 vs 1361 | 已改：分母 1361（排除 3 json）；0.1 标题 M1–M12 |
| N17 | 0.3 验收表述破损 | 已改：index 条目 == 磁盘 382 页（含 stub），orphan 归零 |
| N18 | §8 引用-产出对账 F3 编号 | 已改：标注历史审计编号，与 §11.1 F3 区分 |

**复审结论**：F1–F8 全部闭环（含 F3 文本级修复与 F5 衍生兜底）；H1–H14 全部闭环；N1–N18 全部处置。无单点致命项遗留。**本文档自此进入编辑锁定**——后续任何修改需重开复审记录；下一步按 plan-audit 流程执行第二轮压力测试推演。

### 11.7 第二轮压力测试推演记录（2026-08-15）

> 两个并行压力测试子代理（A：执行期故障；B：数据与治理面）基于编辑锁定文本 + 源码只读核验。本记录为最终结论与编码前置条件。

#### 11.7.1 关键代码事实（实测核验，含对子代理结论的独立复核）

| # | 事实 | 核验 |
|---|---|---|
| T1 | `retry_with_backoff`（src/pipeline/retry.py）全 `src/` 树**无调用者**；`get_circuit_breaker("llm")` 无接线；`record_failure` 仅在队列路径（queue/service.py）调用 | ✅ 复核属实（grep 全树） |
| T2 | `reingest_source` 前置要求 source 页存在（找不到 → ValueError，services/ingest.py:361-366）；novel-wiki 仅 7/1364 有 source 页 → **1357 个 raw 走 reingest_source 必炸** | ✅ 与磁盘 7 source 页吻合 |
| T3 | 幂等：`check_and_mark` 无调用者（暂不自锁）；`remove_hash` **已被 queue/service.py 调用**（失败/DEAD_LETTER 后清缓存，复审 J 修正）但 `clear` 无调用者；`task_hash = md5(file:rel::project)` **无重建轮次维度** | ✅ 复核属实（修正后） |
| T4 | 向量库 `store.py` 硬编码 **384-dim**，维度不符时 `_migrate_schema_if_needed` **静默 drop 表**；平台文档/AGENTS.md 写 1536-dim（文档滞后） | ✅ 复核属实（store.py:51/94-120） |
| T5 | `.gitignore:33` 忽略 `.index`、`:35` 忽略 `.llm-wiki` → "门禁数据 git 跟踪"纸面化 | ✅ 复核属实 |
| T6 | 断链 55.1%（584/1059，**251 个 distinct targets**）复现；归一后**可对齐 0/251** → 存量断链是"合法但未摄入的 raw 引用 + raw 名幻觉 hash"，非格式问题 | ✅ 缺口优先批次（Q18）对象确认 |
| T7 | **P2 证伪**（子代理 B 称"旧前缀 205/非法 relation 10 无法复现、tags/relations 全空"）：独立复核 `Select-String` 实测 382/384 页有 tags、205 页旧前缀、10 页 `related_to`——子代理读取/解析方式在 CJK frontmatter 上失败，**审计基线可复现，M8/M9 基线有效** | ✅ 复核证伪子代理结论 |

#### 11.7.2 致命缺口（合并去重后 6 项，全部为"声称存在但代码/流程不存在"的系统级接线问题）

| # | 缺口 | 触发/连锁 | 加固（P0，编码前置） |
|---|---|---|---|
| C1 | LLM 重试/熔断纸面化：429/5xx/断连无退避分类，直跑路径零自愈 | 429 风暴 → 40 连发 → 限流加剧 → abort → 无冷却重启循环 + 费用×2-3 | 接线 `retry_with_backoff` 到唯一 LLM 调用点（429 读 Retry-After / 422 分类 / transient 退避）；直跑路径接线 breaker；abort 后自动等待恢复，禁止无冷却重启 |
| C2 | `reingest_source` 前置条件 + 删除/入队非同一事务 | 1357/1364 首摄文件 ValueError 必炸；崩溃在 cascade_delete 后、enqueue 前 → 旧页永久丢失无恢复 | 每 raw 分支：有 source 页→cascade+重建，无→直接 run_ingest；删除+入队改补偿事务（pending_deletion 状态）；定死直跑路径 |
| C3 | M2≥80% 与 M6≈68 页算术冲突（深引用仅来自聚合页，需每页 ≥16 raw） | 全量跑完终验必不达标；且 M2 无批内测量（1.8 只测 M1/M4/M6/M7）→ 方向性错误 69 批后才暴露 | Phase 0.2 用 3–5 批实测推算 M2 可达性；不可达则改 M2 定义（纳入非 source wikilink→source）或放大聚合或降阈值；1.8 扩展 M2 |
| C4 | 批后门禁 + 崩溃续跑 → 门禁作用域收缩放行未复检页；回滚不完整（.index 不入 git） | 已 commit 未过门禁页静默放行；回滚只还原 wiki 页，状态/对账/向量不还原 → 续跑误判 done | 门禁并入 pre-commit gate（失败=零写入）；或批级 `pending_gate` 状态续跑整批重跑；gitignore 白名单放行门禁文件；回滚=checkout+向量重建脚本化 |
| P1 | 门禁数据 git 跟踪纸面化（T5） | 回滚丢状态、续跑错位、gap 清单丢失致缺口优先批次失效 | 同 C4：gitignore 白名单放行 `batch_build_state.json`/`knowledge_gaps.json`/`batch_reports/`；lancedb 依赖"每批 upsert 可重放" |
| P4 | 幂等绕过纸面（T3）+ 向量维度冲突（T4） | 重建批 hash 与首摄相同被判重/静默吞；384 vs 1536 首 upsert 静默 drop | `task_hash` 加重建轮次维度（`reingest:{batch}:{raw}`）或 executor 显式 `remove_hash`/`clear`（代码级）；M12 前加向量维度校验 + provider 一致性检查 |

#### 11.7.3 重大与优化加固（挂靠既有 Phase，编码时落地）

- **P1 级**：failed 文件 owner+自动重投+同文件 3 批失败转 blocklist 告警（Phase 4）；422 标记 permanent_failed 移出重试（Phase 1 接线）；M1 防博弈——suppressed 二次确认+记录原因+终验独立抽样 N 个 suppressed slug 断言（Phase 1.3/Phase 5）；执行路径定死（直跑）+ kill -9 各阶段崩溃注入测试矩阵（Phase 4）；batch_build_state.json 三写者统一 schema（加 version）+ 写锁（Phase 4）；backlog 阈值 8000→16000（>16000 走 chunked，Phase 0.2 B1）。
- **P2 级**：现有 `existing_wiki_index` 注入本批重建 slug 清单防引用漂移（Phase 1.3）；文档口径同步——状态文件统一 `batch_build_state.json`、M12 抽查读 store 实际维度（Phase 5）。

#### 11.7.4 边界临界点（可行 → 失效）

gap>345 条（suppressed 积压）/ 人工审批延迟 >5 批 / 产出 0 页批占比 >0（需"产出 0 页=失败"断言）/ 向量维度首 upsert 即炸 / 批失败率 100%（LLM 中断 >20min）/ 累计失败+误延期 >272（M2 数学不可达）。

#### 11.7.5 编码前置声明（plan-audit 第二轮结论）

**方案当前不能直接进入编码**。必须先完成 11.7.2 的 P0 六项加固（C1 接线、C2 执行模型重写、C3 M2 可达性验算、C4 门禁时序、P1 gitignore、P4 幂等/向量），并在 Phase 0.2 扩容：基线可复现性核对（T7 已证伪 P2，仍需记录口径）、B11 向量维度/provider、B12 断链消解路径分类（251 distinct targets 按"未摄入 raw 引用 / 幻觉 hash"分类）、stub 引用关系图、硬预算数字。P0 完成后需重开一轮复审（确认 P0 落地）再进入编码。

### 11.8 P0 加固整改记录（2026-08-15）

> §11.7.2 六项致命 P0 加固已整改进对应 plan 任务。本记录为整改映射与复审要求。

| P0 项 | plan 整改落点 |
|---|---|
| C1 LLM 重试/熔断接线 | **新增任务 1.9**：接线 `retry_with_backoff` 到唯一 LLM 调用点（429 读 Retry-After / 422 永久隔离 / transient 退避）；直跑路径 breaker `record_failure/success`；executor 顶层按 breaker 暂停整批；禁止无冷却重启 |
| C2 reingest_source 前置崩溃 | **Phase 4 重写（2/3/4）**：定死直跑路径（唯一执行路径，队列降级只读）；每 raw 分支（有 source 页→cascade+重建，无→首次 run_ingest；ValueError 走首次摄入）；删除/入队补偿事务（pending_deletion 状态）；禁止"先删后建"裸窗口 |
| C3 M2/M6 算术冲突 | **0.2 扩容**：M2 可达性验算（B12 分类 + 3–5 批实测），不可达则定稿修订口径；**1.8 扩展**：metrics.py 含 M2 批内测量，Phase 3/4 每批报告 M2 累积 |
| C4 门禁时序 | **Phase 4-5**：四项门禁并入 pre-commit gate（失败=零写入）；保留批级 `pending_gate`，续跑整批重跑门禁；消除"已提交未过门禁"窗口 |
| P1 gitignore 架空 | **Phase 4-6**：`.gitignore` 白名单放行 `batch_build_state.json`/`knowledge_gaps.json`/`batch_reports/`；回滚=checkout+向量重建双动作脚本化 |
| P4 幂等/向量 | **Phase 4-7**：`generate_task_hash` 加重建轮次维度 或 executor 显式 `remove_hash`/`clear`；**Phase 4-9**：向量维度校验（B11），禁止 `_migrate_schema_if_needed` 静默 drop；**Phase 5**：M12 抽查前校验维度一致 |

**Phase 0.2 扩容**（B11/B12/stub 引用关系图/硬预算/M2 验算）与 **Phase 5 终验独立抽样**（B5 防博弈：suppressed 二次确认 + 终验抽样 N 个断言）已入 plan。

**P0 落地复审（编码前必须）**：按 §11.7.5，P0 整改后需重开一轮复审——确认 plan 任务 1.9 接线、Phase 4 分支/补偿事务/pre-commit 门禁、0.2 M2 验算与硬预算已真实落地（有代码/TDD 测试/验收断言），方可进入编码。复审结论记录于此节后续。

### 11.9 P0 落地复审记录（2026-08-15）

> P0 六项加固整改后的独立复审（对照 §11.8 逐条核验 + 新矛盾扫描）。结论与处置如下。

**P0 六项核验**：C1/C2 **已实质落地**（与代码事实吻合：retry_with_backoff 死代码修复对象精确、reingest_source ValueError 前置有改造对象）；C3/C4/P1/P4 **部分落地**（主体有文本落点，存在未钉死/未同步项）。

**新矛盾 A–J 处置**（全部已修订）：

| 编号 | 问题 | 处置 |
|---|---|---|
| A【高】 | 0.1 前向依赖 1.8 的 metrics.py（执行顺序矛盾） | 已改：**metrics.py 核心在 Phase 0.1 创建**，1.8 只扩展批内子集参数（0.1/1.8/依赖图三处同步） |
| B【高】 | Phase 4 §4 队列术语与直跑定死冲突 + pending_deletion 不在状态枚举 | 已改：状态枚举并入 `pending_deletion`；§4 去队列术语（"重跑重建"替代"重入队"）；补 batch_build_state.json 写锁 + schema version |
| C【中】 | M2 引用作用域未钉死（同 raw 自产页致恒 ≈100%） | 已改：spec §6 + plan 0.1 M2 定义**排除同 raw 自产页** |
| D【中】 | 门禁三表述并存 + spec §5.3 未同步 | 已改：Phase 4 中 1.5 批后门禁由 pre-commit gate 取代（1.5 保留 Phase 3/dry-run）；M5 归属 pre-commit；pending_gate 存于 batch_build_state.json 批级字段；**spec §5.3 同步** |
| E【中】 | 1.9 接线点清单不完整（budgeted/QualityJudge） | 已改：Files 补 `lib/budgeted.py`、`quality/judge.py`；明确 **provider 层统一封装优先**（覆盖全部 4 处调用点）+ 接线覆盖测试 |
| F【低】 | 顶层/§6 M2 无修订口径 caveat | 已改：plan 验收总目标 + spec §6 M2 补"或 0.2 验算后修订口径" |
| G【低】 | P1/P4 "或"二选一未钉死 | 已改：P1 钉死 **gitignore 例外规则**；P4 钉死 **task_hash 重建轮次维度为主**、remove_hash/clear 为兜底辅 |
| H【低】 | 新声称无落点项 ×6 | 已改：写锁落点（Phase 4-2）；suppressed `reason` 字段 + 人工 SLA（Phase 4-10）；`scripts/rollback_batch.py`（Phase 4-6）；预算自动暂停（Phase 4-12）；recovery_timeout 取 breaker 60s 机制（1.9）；抽样 N=50 或 gap 10%（Phase 5） |
| I【低】 | 两层重试交互未说明 | 已改：1.9-5 传输层在外/内容层在内，嵌套顺序分别验收 |
| J【低】 | T3 remove_hash 描述失准、`idempotency_cache.clear()` 无模块符号 | 已改：spec §11.7.1 T3 修正（queue/service.py 已调用 remove_hash）；plan `get_idempotency_cache().clear()` |

**P0 落地复审结论**：六项 P0 加固 + 新矛盾 A–J 全部处置完毕（plan/spec 文本均已修订，无遗留"声明失实"项）。**plan-audit 完成标准达成**——两轮审查完成、问题分级输出、致命项全部整改并复审通过（F1–F8/H1–H14/N1–N18/C1–C4/P1/P4/A–J）。**可进入编码**：编码从 Phase 0（基线复测 + metrics.py 核心 + 盲区统计 + M2 验算）起步，遵守 TDD-per-task + 每任务 reviewer。
