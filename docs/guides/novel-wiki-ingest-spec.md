# LLM-Wiki 素材摄入 Ingest 执行规范 v2（适配 ruflo-kb）

> **定位**：本规范是 2026-08-01 对《LLM-Wiki 素材摄入 Ingest 执行规范（终极全集·正式上线版）》的独立审计结论之上的优化重写版。核心思路不是另起炉灶，而是把原方案的品类规范**翻译成宿主 ruflo-kb 的原语**（4 类 PageType / 命名空间 tags / 模板槽 / typed relations / lint / heat / stubs / dedup / md5 幂等），并补上缺失的执行层、质量门与数据清理。**不另建目录体系、不自定义 type、不发明 `[[raw/...]]` 链接语法。**

适配对象：`knowledge/novel-wiki`（宿主 ruflo-kb 平台｜双层 RAG｜Obsidian｜Claude Code Agent）。

---

## 一、双层架构落地（替换原方案铁律 1–5）

| 原方案条款 | 优化后落地 | 理由（对应审计缺陷） |
|---|---|---|
| 铁律1: raw 只读证据层 | **raw/ 只读由 git 强制**——raw 在仓库内被 git 跟踪，`git status`/`git diff` 即变更检测；违规在 git 里可追责 | 解决 F4：把"只读愿望"换成"git 兜底机制" |
| 铁律2: wiki 编译层 | wiki/ 四目录 `sources/ entities/ concepts/ synthesis/`（宿主既有） | 解决 F1：不再自建 writing_technique 等目录 |
| 铁律3: `[[raw/文件路径]]` 溯源 | **溯源走 `sources` frontmatter 字段 + `derived_from/supported_by` relations + `[[slug]]` 链接**，不是 `[[raw/...]]` | 解决 F2/A2：宿主 wikilink 语法是 `[[slug]]`，raw 路径归 `sources` 字段管 |
| 铁律5: 两类产物 | ① raw 只归 raw（不建页）② 提炼产物 = 宿主 4 类页面 | 语义清晰，无"两类结果"歧义 |

## 二、素材分类 → 宿主类型映射（替换原方案 A/B 类与全部自造 type）

**核心决策表**——原方案 6 种自造 type 全部被宿主 4 类吸收，不存在"无家可归"：

| 原方案产物/品类 | 宿主类型 | 落盘目录 | 判定说明 |
|---|---|---|---|
| 原始素材（A类，只归档） | —（不建页） | raw/ 对应子目录 | 不触发建词条 |
| 每个摄取任务自动生成的源页 | `source` | wiki/sources/ | 宿主自动产生，不依赖 LLM 决策 |
| 素材综述 / 主题汇总（B类） | `synthesis` | wiki/synthesis/ | **正是宿主 synthesis 语义**，原方案 F2 直接消解 |
| 写作技法 / 抽象概念 / 题材大类 | `concept` | wiki/concepts/ | 原 writing_technique → concept |
| 具体作品 / 人物 / 流派名 / 平台 | `entity` | wiki/entities/ | 原 book/book_concept 的具象物 → entity |
| 书籍总览 | `synthesis`（总览页） | wiki/synthesis/ | 原 book_overview → synthesis |
| 书籍细分概念 | `concept` | wiki/concepts/ | 原 book_concept → concept，`sources` 标注书+章节 |
| 摘抄索引（好句/案例） | `entity`（每条摘抄）或 `concept`（索引页） | wiki/entities/ 或 concepts/ | 用 `功能/摘抄索引` 之类 tag 区分，不建"汇总索引"专用目录 |
| 复盘 / 年度沉淀 / 领域对比 | `synthesis` | wiki/synthesis/ | 原 journal 沉淀 → synthesis |
| 写作复盘索引 | `synthesis`（索引即综述） | wiki/synthesis/ | 原 §3.8 的"复盘索引"有家可归 |

**决策四问（沿用 wiki-spec 启发式，零新增概念）**：

1. 是某个人/书/具体东西？→ `entity`
2. 是抽象可复用的方法/原则/大类？→ `concept`
3. 是多个 concept/entity 的对比/综述/汇总？→ `synthesis`
4. 是原始摄取文档？→ `source`

> 原方案 §3.1 阈值≥3、§3.5 阈值≥3 的"自动触发建综述"——**改为达到阈值只生成候选清单（走宿主 stubs 机制），synthesis 页一律人工确认后创建**。彻底堵住词条爆炸（F6）。

## 三、raw/ 目录（在现状上增量扩展，不重构）

现状 `raw/sources/` 已有 `01_新手入门/ 02_进阶技巧/` 等 **1361 个文件**（早期"4066"是把 wiki 页误计入 raw 的测量错误，见 §十口径修正），结构良好，**冻结不动**（`sources` 字段与 relations 都引用了这些路径，改动即断链）。

只按需新增**兄弟**目录，且只在真有素材时创建：

```
raw/
├── sources/          # 冻结，现有写作教程来源（不新增子类）
├── assets/           # 图片/音视频（新增，需配 .gitignore 或排除同步）
├── data_sheets/      # 原始表格/调研数据
├── legacy_notes/     # 旧平台笔记（迁移期用）
├── drafts/           # 个人创作草稿（与 wiki 无关）
├── journal/          # 个人日志/复盘
├── transcripts/      # 访谈/播客/录音转写
└── conversations/    # AI 对话日志（敏感，见合规节）
```

**命名规则**（新增，补审计盲区）：沿用宿主 slugify 规范——中文原字保留、NFC 标准化、连字符连接、禁止空格/emoji/控制符；改名必须发生在**引用建立之前**，落盘即冻结。

> **分层策略**：冻结的是现有 `raw/sources/`（已有引用写入）。**未来新增的 raw 树（assets/、transcripts/ 等）允许二级子目录**（如 `transcripts/interview/`、`transcripts/podcast/`），只要子目录在"首次建立引用之前"定型——引用一旦写入，路径即冻结。既保住现有路径稳定性，也保留原方案的分层粒度（如 `excerpts/sentences|cases|articles`）。

## 四、Tags 扩展（把原方案 frontmatter 模板翻译进宿主 tag 体系）

宿主已支持命名空间 tags（`题材/` `功能/` `角色/` `事件/` `情绪/` `实体/` `场景阶段/` `状态/`）。原方案的 `scene_tag` `emotion_tag` `resource_type` 等全部落入现有命名空间：

| 原方案字段 | 宿主落地 | 枚举示例 |
|---|---|---|
| `scene_tag`（适用场景） | `场景阶段/` | `场景阶段/开篇`、`场景阶段/战斗` |
| `emotion_tag` | `情绪/` | `情绪/甜宠`、`情绪/虐` |
| `resource_type`（素材品类） | **`素材/`（2026-08-01 已注册入 `TAG_PREFIXES`）** | `素材/ugc`、`素材/book`、`素材/excerpt`、`素材/transcript`、`素材/interview`、`素材/conversation` |
| UGC 可信度 | **`可信度/`（2026-08-01 已注册入 `TAG_PREFIXES`）** | `可信度/ugc`（网络UGC）、`可信度/book`（权威书）、`可信度/mixed` |
| 写作技法 category | `功能/` | `功能/写作技法`、`功能/题材综述`、`功能/摘抄索引` |

> 落实 UGC 可信度要求：用 `可信度/ugc` 强制标注，Lint 可校验（F6/H3）。

> **2026-08-01 前缀中文化**：12 个前缀已全部改为中文（题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度/读者群/平台），`TAG_PREFIXES`、Generator/Analyzer 提示词、JSON schema 描述、`wiki-spec.md` 均已同步（355+ 测试通过）。**旧英文前缀 tags（如 `genre/玄幻`）为 legacy**——由唯一规范化器 `tag_namespace.normalize_tags` 在 Generator / `commit_ingest`（pages + extra_pages）/ `cleanup_invalid_tags.py` 边界统一处理：可确定映射的自动映射（`func/教程` → `功能/教程`），无法安全映射的删除并记录审计（计划 `docs/superpowers/plans/2026-08-18-tag-normalization-remediation.md`）。

### 元数据承接（补回原方案 frontmatter 模板字段）

原方案每品类有专属 frontmatter（web_clip 的 `source_url/author/publish_date/fetch_time`，book 的 `author/core_position` 等）。宿主 frontmatter 是固定 schema，自定义字段不参与 `to_frontmatter_dict/from_dict` 往返（会被丢弃），因此按语义落到宿主原生位置：

| 原方案字段 | 宿主落点 | 说明 |
|---|---|---|
| `source_url` | 模板 body 的"来源与元数据"槽（concept/synthesis 加一个可选槽 `<!-- slot:source_meta? -->`）；source 页天然有 source-meta 槽 | 快照入库后 URL 仅作凭证，检索不依赖它 |
| `author` | **entity 页 + relation**——作者是具象实体，建 `entity` 页，用 `references`/`authored_by` 关系链回素材 | 比存字符串更有价值：可跨库聚合该作者全部作品 |
| `platform` / 站点 | tag（`素材/` 或新增 `src/` 命名空间） | 如 `src/知乎`、`src/公众号` |
| `publish_date / fetch_time / last_update` | body"来源与元数据"槽（ISO 日期文本） | 字段级强制需走 schema 迁移（`src/schemas/`），默认不启用 |
| `core_position`（书核心主张） | concept 定义槽 / synthesis 多方观点槽 | 本书主张本就是页面内容 |
| `scene_tag / emotion_tag` | `场景阶段/` / `情绪/` tag | 已在 §四 主表 |

> 若未来需要字段级强制校验（如 Lint 检查 `source_url` 非空），再考虑 schema 迁移新增字段；当前用模板槽 + `LINT-MISSING-SECTION` 兜底。

### 前缀治理与扩容规则（防"前缀不够用"与防爆炸）

**定位铁律：前缀是正交维度，不是分类树。** 每个前缀下的 tag 名完全自由（`题材/` 一个前缀即可装下所有流派）。层级、细分类、类型化联系一律走下述现成机制，**不造新前缀**：

| 需求 | 现成机制 | 例 |
|---|---|---|
| 维度下的小类 | tag 名内二级——前缀校验只看第一段（`parse` 用 `partition("/")`，name 可含斜杠） | `功能/写作技法/结构` |
| 对齐业务分类体系 | `category` / `taxonomy_sub` frontmatter 字段（WikiPage 原生支持，round-trip 正常） | category=`写作技法`, taxonomy_sub=`人物塑造` |
| 页与页的类型化联系 | `x-*` 自定义关系类型（17 内置 + 无限 `x-*`） | `x-改自`、`x-致敬` |
| 多维度并存 | 每页 0-N 个 tag，正交前缀并行 | `题材/玄幻` + `功能/写作技法` + `情绪/爽` |

**判断口诀**：问"这是**新维度**还是**新名称**？"——新名称归现有前缀，新维度才考虑新前缀。

**新增前缀硬性 checklist（4 条全中才允许）**：
1. 是**新的正交维度**（与现有 10 个语义不重叠）；
2. 预期使用量 **≥20 页**（不为一次性需求造维度）；
3. **无法用** tag 名二级 / `category` / `x-*` 关系表达（先在此三条里找替代）；
4. 过评审：同步修改 `TAG_PREFIXES` + generator/analyzer 提示词 + JSON schema 描述 + `wiki-spec.md` + 测试，一次性走完。

**扩容纪律**：
- 加前缀技术上永不锁死（3 行代码 + 提示词一行），真正的稀缺是"加太多"导致 LLM 选不准、索引碎片化、跨轴查询失效——目标**宁缺毋滥、保持正交**。
- **成批扩，不挤牙膏**（每次同步 5 处），优先名词性、短、正交的候选（如 `媒介/`、`读者/`），避免与现有轴语义重叠。
- 本规范下所有素材分类已收敛为：素材品类 → `素材/`（ugc/book/excerpt/transcript/… 靠名字区分）、可信度 → `可信度/`，**勿再按素材子类拆分前缀**。

## 五、Body 结构：模板驱动，不写死"7 大模块"

原方案 §4 的 7 大强制模块 → 落成**项目级模板**（宿主支持 `<project>/.wiki-templates/<type>.md` 覆盖 bundled）。**F2 最小可行实现（2026-08-01 已落地）**：

- **`<project>/.wiki-templates/concept.md`**：完全复用 bundled 的必填槽（定义/主要特点/例子/相关概念/参考来源），**追加 3 个可选模块**——`<!-- slot:limitations? -->`（局限与风险）、`<!-- slot:conflicts? -->`（信息冲突与多方观点）、`<!-- slot:source_meta? -->`（来源元数据，含 URL/作者/日期）。
- **entity / source / synthesis 不建项目模板**，回落 bundled（它们已有 source_meta/对比表等所需结构）。

**为什么可选而非强制（F2 约束）**：lint 的 `_SLOT_TO_HEADING` 映射是硬编码（`src/wiki/features/lint.py`），且模板改动会**反向作用于所有已声明 v2.0.0 的旧页**——若把"局限与风险"设为必填，1150 个旧 concept 页全部缺节，lint 立即爆 1000+ 条。可选槽方案经实测：`lint --no-cache` 前后均为 3 条 LINT-DUPLICATE、**零新增 MISSING-SECTION**，resolver 确认命中 project 级模板。

**局限与风险的"强制"时点（三选一，不可默认"Phase 4 后"）**：lint 的 `LINT-MISSING-SECTION` 判定对象是**所有声明 v2.0.0+ 的页**（对照当前解析模板），不是"只查新模板生成的页"。要把 `limitations` 改为必填槽，必须满足其一：

- (a) **全量重渲染**：把**所有产出 concept 的源**都重取，保证每页都含该节（成本高）；
- (b) **改 lint 版本门**：项目模板 bump 到 2.1.0，并让 lint 只检查声明版本 ≥ 2.1.0 的页（需改 `src/wiki/features/lint.py`）；
- (c) **放弃硬强制**：保持 `limitations?` 可选，靠模板引导 + 人工抽查，不设 lint 强制。

> **当前选 (c)。** Phase 4 只按 tap rate 覆盖部分源，不能保证所有 concept 页被重渲染；在走 (a)(b) 之前，不可宣称"强制"。

## 六、执行状态机（替换原方案全部"自动/定期/触发"悬空指令）

```
素材到达 → ①判定品类（第二节四问）
        → ②命名 + 落盘 raw/（第三节规则）
        → ③POST /api/v1/projects/<id>/ingest  {"source": raw路径}   （异步，立即返回 taskId）
        → ③' 轮询 task 状态至完成（GET /ingest/status/{task_id}），超时/失败重投
        → ④宿主 Collector→Analyzer→Generator 生成 4 类页面
        → ⑤门禁校验：fields validate + tags validate + lint（**新摄入页必须全过；存量页旧英文前缀 tag 走豁免清单**，见 Phase 1）
        → ⑥分级处置：
             source 页      → 自动过
             低价值/碎片     → 只留 raw + index 登记，不建页
             concept/entity → 直接过
             synthesis      → 需人工确认（候选先走 stubs）
        → ⑦报告：log.md + 周报模板
```

每步都有**幂等键**（宿主 md5(source+folder_context)），但**幂等边界有限**：`IdempotencyCache` 是内存字典 + 7 天 TTL + 服务重启即清空——只对"7 天内、同服务实例"的重复 POST 去重。**Phase 4 重摄取的都是数周前的旧文件，幂等必然失效**：去重必须靠人工清单（按 raw 是否已被引用），不依赖幂等。同一 slug 的源页会被 `write_page` 覆盖而非追加，但 Generator 会重跑（成本）并可能重新触发 stub 机制。

## 七、真实数据清理（Phase 1 必做，针对已观察到的污染）

| 问题 | 观测证据 | 处置 |
|---|---|---|
| **entity 占位页污染（头号问题）**：**538 个 stub entity 页（占 entities/ 48.5%）** + 约 41 个含"系统占位"槽的生成页。坏形态：tag 名（`func-教程`、`genre-现言`、`event-冲突`）、raw 路径被 slug（`raw-sources-01-新手入门--...-9163987c`）、双连字符路径残留（`女频男频--架空类...`）、前缀/后缀污染（`source-补充教程...`、`琴帝-entity`）、source 页错误 slug 引用（`1-写作选材之以小见大第-1-段-bafab45e`） | Phase 0 实测（2026-08-01）+ F3 分类脚本 | 见下方 F3 根因；Phase 1 清理必须配合"引用修复"，否则删 stub 即断链 |
| **raw/wiki 形态重复**：同 stem 同时存在于 `wiki/sources/` 与 `wiki/entities/` | `wiki/sources/必备资料20个签约条件新人必看2-b7b4ef23.md` 与 `wiki/entities/必备资料-20-个签约条件新人必看-2-b7b4ef23.md` | 保留 source 页（宿主设计如此），删除/降级 entity 占位页 |
| **`sources` 反斜杠路径**：`raw\sources\...` 在 POSIX 上是含反斜杠的单一文件名 | concept/synthesis 页的 `sources` 字段 | 短期接受；做一次规范化脚本（`\\`→`/`）并重写受影响页面，放入 Phase 4 |
| **摄取缺口（真实 tap rate 仅 22.8%）**：1361 raw 文件中仅 310 被任一 wiki 页 `sources` 引用（早期"66% 覆盖率"是 glob 把 wiki 页也算进 raw 的测量错误） | Phase 0 实测 | 建摄取欠账清单（≈1051 未触达 raw），按主题分批排期 |

## 八、质量门与合规（对应审计 H1–H6 与 F5）

1. **幂等**：一律走 ③ 的宿主 ingest API，禁止手工往 wiki/ 写页（绕过 idempotency 即污染源）。
2. **成本预算**：每批 ≤20 个 raw 文件（`raw 立即增量 + wiki 批量刷新` 的成本可控），单次会话超限即停，避免 Embedding 费用失控（H2）。
3. **词条泛滥**：靠宿主 `heat zombies` + 孤立页（无 relations）定期清理；synthesis 全部人工门（H3/F6）。
4. **merge 语义（政策，需机制兜底）**：词条更新 = 读取→合并→写回，绝不整篇覆盖；`is_immutable` 页不写回。**注意：宿主 `write_page` 默认整篇覆盖、写路径不强制 `is_immutable`**——这是操作纪律而非系统保证；如需系统级强制，需在写路径加 merge/immutable 守卫（代码任务，未排期）。
5. **合规**：`conversations/`、`journal/`、`transcripts/` 含隐私 → 不入 git / 不随 vault 同步（新增 `.gitignore` 排除）；`raw/assets/` 大媒体排除出 git。受版权书籍全文不公开（F5）。

## 九、Lint 增强清单（映射原方案 §6 的 9 项，标明可自动化程度）

| 原方案检查项 | 落地方式 | 自动化 |
|---|---|---|
| 1 未加工原文>300字 | 新增 lint 检查（body 长段无 blockquote/无 slot 引用标记） | ✅ 代码 |
| 2 缺 `[[raw/]]` 溯源 | 改查 `sources` 字段为空 或 无 `derived_from/supported_by` relation | ✅ 代码 |
| 3 raw 被修改 | git 状态/diff on raw/（git 兜底） | ✅ 工具链 |
| 4 raw/wiki 冗余副本 | `dedup auto` + 长度阈值 | ✅ 现有 |
| 5 失效链接 | lint 现有 + relations target 存在性 | ✅ 代码 |
| 6 词条泛滥 | heat zombies + 孤立页（无 relations）清单 | ✅ 现有 |
| 7 矛盾结论未立板块 | **人工**复核队列（模板含"信息冲突"槽，无法自动判真伪） | ⚠️ 半自动 |
| 8 缺强制模块 | `LINT-MISSING-SECTION`（v2.0.0+） | ✅ 现有 |
| 9 UGC 未标可信度 | 新增检查：带 `素材/ugc` 的页必须带 `可信度/ugc`。**前提：提示词加显式规则**——"来源为公众号/论坛/自媒体的页必须打 `素材/ugc` + `可信度/ugc`"，否则 LLM 不会自发打标，此检查查不到东西 | ✅ 代码 + 提示词 |

## 十、验收指标

| 指标 | 现状基线（2026-08-01 Phase 0 实测） | 目标 |
|---|---|---|
| raw tap rate（被任一 wiki 页 `sources` 引用的 raw 占比） | **22.8%**（310/1361） | ≥80% |
| 占位页 | **579**（21.6%，集中在 entities/） | 0（归档或替换） |
| grade C 页面 | **915**（34%） | <10%（以 A/B 为主） |
| `sources` 非空率 | **94.2%**（155 页为空） | 100% |
| 孤立页（无 relations） | **638**（23.8%） | <10% |
| LINT-DUPLICATE | **3 组 / 69 页**（占位 body 重复） | 0 |
| 带 `可信度/ugc` 的 UGC 页占比 | 0%（命名空间未启用） | 100%（对 UGC 素材）——**依赖提示词显式指令落地，否则此指标不可达** |
| 每批摄取成本 | 未统计 | ≤20 文件/批 |

> **指标口径修正**：raw→wiki "覆盖率" 不能用 `wiki页数/raw数`——一份 raw 会产出 1 个 source 页 + 多个 concept/实体/synthesis 页，该比值结构性 >100%（当前 197.1%），无意义。改用 **tap rate**（被引用 raw 占比）作为真实摄取进度。另：此前 4066 raw 数字是把 wiki 页误计入的测量错误，实际 1361。

### F3 Generator 根因（2026-08-01 排查结论）

**538 个 stub 全部源于同一机制**：`src/pipeline/ingest.py` 的 `missing = referenced_slugs − produced_slugs − existing_slugs`，对每个"被引用但未产出、且库里没有"的 slug 自动建 stub entity 页（grade=C）。**根因不是"清理不干净"，而是 Generator 的引用/产出不闭环**：

| 类别 | 数量 | 根因 | 修复指向 |
|---|---|---|---|
| clean（真实实体被引用但未产出） | **382** | LLM 在 relations/wikilink 里引用了实体，却未生成对应页；且 JSON schema 无"引用的 slug 必须 ∈ 产出∪已有"的后验校验 | 生成后加**引用-产出对账**（确定性代码，无 LLM）：未解析的引用要么抑制、要么标记重试，stub 只作最后兜底并设硬上限 |
| source_like（139） | source 页错误 slug | LLM 不按 `SOURCE_SLUG_MAP` 逐字复用，发明变体（内连字符/截断 hash/`第-1-段`）。`_replace_broken_source_wikilink` 只修**本次运行** body 里的 wikilink，不修 relation target、也不修对**历史 source 页**的引用 | 对账层覆盖 relations[].target + 全部历史 source slug（或走 `slug_aliases`） |
| 坏形态（tag/路径/前缀/后缀） | 16 | LLM 把 tag 名、raw 路径、`source-`/`-entity` 当页面引用；`_strip_type_prefix` 只处理引用、不校验生成页 id | 生成页 id 校验：拒绝/修复 tag 状、路径状、带类型前缀/后缀的 id |
| 系统占位槽 | ~41 | 必填槽空缺被 `_ensure_required_slots_filled` 用占位填充（LLM 弱槽） | 弱槽来源 = 部分 raw 太短/太偏，可接受；随再摄取替换 |

**对 Phase 1 的强制要求**：每个 stub 都因被引用而存在——**直接删 = 断链**。清理必须三件套：①跑一遍引用-产出对账，把"误引用"改成指向真实页或移除；②再删/归档 stub；③未来摄取靠对账层兜底，禁止再静默自动建 stub。

---

## 分阶段落地计划

- **Phase 0 基线审计**：跑 `lint`、`fields validate`、`tags validate`、`heat zombies`，产出污染清单与指标基线。**注意：前缀中文化后 `tags validate` 会对存量旧英文前缀 tag 报违规，属已知基线**（见 §四遗留说明）。→ 验收：得到第六/十节所有数字。
- **Phase 0.5 Generator 对账层（F3 修复，前置）**：在 `ingest.py` 加"引用-产出对账"——生成后校验每个 `relations[].target`/body wikilink 是否 ∈ 产出∪已有，未解析的引用抑制或标记重试；加生成页 id 校验（拒绝 tag 状/路径状/类型前缀/`-entity` 后缀的 id）；stub 改为最后兜底 + 硬上限。→ 验收：对同一 raw 连续摄取两次，stub 不再新增。
  > **必须排在 Phase 1 与 Phase 4 之前**——否则 Phase 1 清掉的 stub 会在 Phase 4 再摄取时被重新生成，方案自锁死结（BUG-A）。
- **Phase 1 数据清理**：归档/替换 entity 占位页；`dedup auto` 清冗余；**迁移/豁免旧英文前缀 tags**（`genre/玄幻`→`题材/玄幻` 批量改写，或对存量页出豁免清单，否则 §六.⑤ 门禁不可满足）。
- **Phase 2 模板落盘**：新建 `<project>/.wiki-templates/` 4 类型模板。→ 验收：新摄取页面触发 LINT-MISSING-SECTION 且字段齐全。
- **Phase 3 Lint 增强**：新增"未加工原文/溯源缺失/UGC可信度"检查项；**同步在 generator/analyzer 提示词加 UGC 打标显式规则**（否则第 9 项检查无输入、§十"可信度/ugc 100%"不可达）。
- **Phase 4 分批再摄取**：按主题批次重跑 raw，覆盖模板升级 + 修复反斜杠路径 + 补覆盖率。
- **Phase 5 合规**：**现状盘点**——列出已入库的第三方全文/隐私内容，决定保留 / `git rm --cached` + 排除同步；`.gitignore` 只对**新目录**生效（对已 git 跟踪的文件无效）；建立人工 synthesis 门。

---

## 附录：品类速查表（原方案 §3.1–3.13 的压缩执行版）

| 品类 | raw 落盘 | wiki 产物（宿主类型） | 关键 tag | 处理要点 |
|---|---|---|---|---|
| 3.1 摘抄/金句/事例 | raw/sources/（写作类）或 raw/excerpts/ | 单条不建页；积累后 concept 索引页 | `素材/excerpt` | 原文留 raw，wiki 只留少量引文 |
| 3.2 写作技巧短文 | raw/sources/ | concept | `素材/ugc`或`素材/book` + `功能/写作技法` | ≥2 篇走候选清单，synthesis 人工门 |
| 3.3 工具书 | 原书 raw/sources/ 或 raw/books/；转录+原PDF | synthesis（总览）+ concept（概念） | `素材/book` + `可信度/book` | 不整书入 wiki；章节定位写 `sources` |
| 3.4 UGC 网页 | raw/sources/ 或 raw/web_clips/ | concept / synthesis | `素材/ugc` + `可信度/ugc` | 快照完整保留；可信度强制标注 |
| 3.5 草稿/灵感 | raw/drafts/ | 不建页（只登记） | — | 周期扫描后走候选 |
| 3.6 访谈/播客 | raw/transcripts/ | concept / synthesis | `素材/interview` | 过滤口语冗余 |
| 3.7 世界观 | raw/worldbuilding/ | concept / synthesis | `素材/worldbuilding` | 仅稳态结论 |
| 3.8 写作练习 | raw/writing_practice/ | synthesis（复盘索引） | `素材/practice` | 复盘=综述 |
| 3.9 日志/复盘 | raw/journal/ | synthesis | `素材/journal` | 年度沉淀=综述 |
| 3.10 数据表 | raw/data_sheets/ | concept | `素材/data` | 只收结论不收全表 |
| 3.11 多媒体 | raw/assets/ | concept（解读） | `素材/asset` | 源文件只在 raw |
| 3.12 AI 对话 | raw/conversations/ | concept（成熟结论） | `素材/conversation` | 敏感，不入 git |
| 3.13 旧笔记 | raw/legacy_notes/ | concept / synthesis | `素材/legacy` | 分批提炼 |

> 全部产物落在宿主 4 类；synthesis 一律人工门。
