# Wiki 模板字段契约指南（Field Guide）

> 适用版本：wiki-template-version **2.0.0** / wiki schema **v2.3+**（Plan 25 + Plan 27）
> 依据源码：`src/wiki/templates/bundled/*.md`、`src/pipeline/generator.py`、`src/pipeline/wiki_rules_prompt.py`、`src/wiki/templates/parser.py`、`src/wiki/templates/renderer.py`
> 最后更新：2026-07-27

本文档回答三个问题：**四个模板各有哪些字段（slot）？每个字段应该怎么填？LLM / 人工编辑时要遵守什么规则？**

---

## 1. 模板机制速览

- 每种 `PageType`（`source` / `entity` / `concept` / `synthesis`）对应一个 Markdown 模板，模板 = **章节标题 + `<!-- slot:NAME -->` 占位符**。
- **必填判定**：slot 名不带 `?` 且不在 `<!-- if:X -->` 块内 ⇒ 必填（由 `parser.required_slot_names()` 计算）。带 `?` 或包在 `if` 块内 ⇒ 可选，为空时**整个章节（含标题）被丢弃**。
- **生成流程**：LLM 不直接写 Markdown，而是返回 `slots: {name: 内容}` JSON；代码用 `render_body()` 把 slot 内容装配进模板，产出最终 body。
- **模板解析优先级**（三级，高覆盖低）：
  1. `<项目>/.wiki-templates/<type>.md`
  2. `~/.config/ruflo-kb/wiki-templates/<type>.md`
  3. `src/wiki/templates/bundled/<type>.md`（内置默认）

---

## 2. 通用填写规则（适用所有 slot）

| 规则 | 说明 | 违反后果 |
|---|---|---|
| 非空 | 每个 slot 值 trim 后 ≥ 1 字符；列表至少 1 条有实质内容 | 字符串值由 provider JSON schema 拒绝（`minLength: 1`）；**列表形状由代码归一并在校验层检查**（`_is_present`：空列表/全空元素视为缺失 → 触发 retry） |
| 禁止占位敷衍 | 不得填 `...`、`（空）`、`（待补充）`、`placeholder`、`TBD` 等 | 校验器 REJECT 并触发 1 次 retry |
| 无内容时的正确写法 | 必填 slot 确实无信息时，写一句说明性短句（如「无相关引用」），而不是占位符 | — |
| 篇幅 | 1–3 句话，或 1–3 条短 bullet（列表值会被渲染成 `- ` 项） | — |
| 跨页引用 | 可用 `[[slug]]` wikilink；slug **必须逐字复用**已有索引或 SOURCE_SLUG_MAP 中的值，禁止自创变体 | 断链（H2 审计报 ERROR） |
| 不得增删 slot | 不能发明模板中不存在的 slot 名 | ⚠️ prompt 声称"schema 拒绝额外 key"，但**实际 schema 用 `additionalProperties: {type: string, minLength: 1}`，并不拒绝额外 key**；多余 slot 会被 `compute_slot_fill_status` 记为 `extra`（仅信息性），渲染时因模板中无对应 marker 而被**静默丢弃**。规则仍应遵守：多写的内容不会出现在页面上 |
| 主题边界 | 多实体来源时，A 的论断/评价/局限不得写到 B 的页面；如需对比须显式写明并注明出处 | 知识污染 |
| 语言 | 用户可见字段默认简体中文；slug 可用 CJK 原字或 ASCII kebab-case，专有名词保持原文（如 OpenAI、Transformer） | — |
| 系统占位符 | `（系统占位：此项由系统补齐，请人工补充）` 是 retry 失败后的**系统兜底产物**，出现即表示需要人工补写 | 生成时写 WARN 到日志；⚠️ 注意 `lint` **不会**检测占位符文本（`LINT-MISSING-SECTION` 只查章节标题缺失，占位页章节齐全故不报警）——发现占位符需靠人工或 grep |

---

## 3. source 模板（来源页）

**语义**：原始摄取的文档/URL 本身。每个摄取任务自动产生一条，`id` 为确定性 slug（`{NFC 文件名 stem}-{md5(路径)[:8]}`，v2.4 起），**不由 LLM 决定**。

| 章节 | slot | 必填 | 应填什么 | 格式建议 | 常见错误 |
|---|---|---|---|---|---|
| `## 来源元数据` | `source_meta` | ✅ | 原始来源的元信息：文件路径或 URL、摄取时间、任务 ID、文档类型等 | 键值式短行或 bullet（`任务 ID` 字段用于审计追溯） | 漏掉路径/任务 ID；把摘要内容写进来 |
| `## 摘要` | `summary` | ✅ | 全文 2–4 句概括：讲了什么、核心立场/结论 | 1 段短文 | 复制原文首段；写成逐段流水账 |
| `## 关键观点` | `key_points` | ✅ | 来源中最重要的 3–7 条论点/事实（对应 Analyzer 的 `key_facts`） | bullet 列表，每条 1 句 | 观点与摘要重复；超长引用原文 |
| `## 抽取的概念` | `extracted_concepts` | ✅ | 本次摄取从该来源抽出的 concept/entity 页清单 | bullet + `[[wikilink]]` 指向对应页面 | 用纯文本不加 wikilink；链接 slug 自创变体导致断链 |

---

## 4. entity 模板（实体页）

**语义**：具象实体——**有名字、可数、可唯一标识**的对象。人物、组织、具体作品、地点、特定流派名。
反例：`网络文学`（题材大类）❌ entity → ✅ concept；`佛本是道`（具体作品）✅ entity。

| 章节 | slot | 必填 | 应填什么 | 格式建议 | 常见错误 |
|---|---|---|---|---|---|
| `## 基本信息` | `basic_info` | ✅ | 实体的身份卡：是什么类型的实体（人物/作品/组织…）、归属、时代/平台等关键属性 | 键值式 bullet（类型：…；所属：…） | 写成长篇简介（那是 summary 的事） |
| `## 简介` | `summary` | ✅ | 2–3 句话说清这个实体是谁/是什么、为何重要（在来源语境下） | 1 段短文 | 抄百科而非依据来源；把别的实体的评价搬进来（违反主题边界） |
| `## 别名` | `aliases?` | ⬜ 可选 | 别名、简称、旧称、英文名 | bullet 或逗号分隔 | **没有别名时硬编**；应省略该 key 或返回 `[]`（整节会被丢弃） |
| `## 相关引用` | `related` | ✅ | 来源中与该实体直接相关的引述/提及，以及相关页面链接 | bullet + `[[wikilink]]`；无引用时写「无相关引用」 | 填 `（待补充）` 被拒；引用与实体无关的内容 |

---

## 5. concept 模板（概念页）

**语义**：抽象概念——**可跨页复用、不依附具体作品**的主题/技巧/原则/题材大类。如 `画面感`（写作技巧）、`长生`（主题）、`仙侠小说`（题材大类）。
判定启发式：「它是一个抽象的方法/原则/类别吗？」→ concept。

| 章节 | slot | 必填 | 应填什么 | 格式建议 | 常见错误 |
|---|---|---|---|---|---|
| `## 定义` | `definition` | ✅ | 该概念的准确定义：1–2 句，以来源的表述为准 | 1 段短文 | 用「众所周知」式泛泛而谈；定义里塞例子 |
| `## 主要特点` | `characteristics` | ✅ | 概念的 2–3 个核心特征/构成要素 | bullet 列表 | 特点与定义逐字重复；罗列超过 3 条以上的碎片 |
| `## 例子` | `examples` | ✅ | 来源中出现的具体例子（作品片段、场景、用法） | bullet，1–3 条 | 编造来源中没有的例子 |
| `## 相关概念` | `related_concepts` | ✅ | 与之关联的其他概念页 | bullet + `[[wikilink]]`，逐字复用已有 slug | 新造 slug（如把 `qi-dai-gan-chuangzuo` 缩写成 `qi-dai-gan`）导致断链 |
| `## 参考来源` | `references` | ✅ | 支撑本页的来源页链接 | bullet + `[[source-slug]]`（用 SOURCE_SLUG_MAP 中的确定性 slug） | 自己拼 source 页文件名 |

---

## 6. synthesis 模板（综述页）

**语义**：跨页综合分析——对多个 concept/entity 的**对比、综述、汇总**。如「仙侠 vs 玄幻对比」。只有当来源确实支撑跨主题比较时才生成。

| 章节 | slot | 必填 | 应填什么 | 格式建议 | 常见错误 |
|---|---|---|---|---|---|
| `## 对比维度` | `comparison_dimensions` | ✅ | 本综述从哪些维度展开比较（如题材边界、力量体系、读者预期） | bullet，2–4 条 | 维度与后文对比表脱节 |
| `## 综述` | `overview` | ✅ | 总起段：比较对象是谁、核心异同一句话结论 | 1 段短文 | 写成各对象的独立介绍拼贴 |
| `## 涉及的概念` | `involved_concepts` | ✅ | 参与对比的页面清单 | bullet + `[[wikilink]]` | 漏列实际比较的对象 |
| `## 对比表` | `comparison` | ✅ | 按维度逐项对比的内容 | Markdown 表格或结构化 bullet | 只有单方信息（没有形成对比）；把 A 的结论安到 B 头上 |
| `## 结论` | `conclusion` | ✅ | 对比得出的判断/适用场景建议 | 1–3 句 | 结论未被前文对比支撑 |

---

## 7. 必填/可选 slot 全景表

全部 20 个 slot 中**仅 1 个可选**（`entity.aliases`），其余 19 个必填：

| PageType | 必填 slots | 可选 slots |
|---|---|---|
| source | `source_meta`, `summary`, `key_points`, `extracted_concepts` | — |
| entity | `basic_info`, `summary`, `related` | `aliases` |
| concept | `definition`, `characteristics`, `examples`, `related_concepts`, `references` | — |
| synthesis | `comparison_dimensions`, `overview`, `involved_concepts`, `comparison`, `conclusion` | — |

---

## 8. slot 之外的页面字段（frontmatter 契约）

slot 只构成 body。完整 WikiPage 还有 frontmatter 字段：

| 字段 | 必填 | 填写规则 |
|---|---|---|
| `id` | ✅ | 与文件名一致（不含 `.md`）。两种合法格式：kebab-case slug（支持 CJK 原字）或 UUID v7 `card_<13hex>_<8hex>_<slug>`。禁止大写 ASCII、下划线、`[`/`]`；保留字 `index`/`log` 不可用；≤ 64 字符。source 页 id 由代码确定性生成，LLM 不得改 |
| `title` | ✅ | 显示标题，简体中文；不带文件扩展名 |
| `type` | ✅ | `source` \| `entity` \| `concept` \| `synthesis`，遵守第 3–6 节的语义判定 |
| `sources` | ⬜ | 该页内容出处（raw 路径或 URL），由 pipeline 自动写入 |
| `relations` | ⬜ | 跨页关系列表 `{target, type, weight 0.0–1.0, context}`。`type` 限 17 种内置（`is_part_of`/`contains`/`references`/`referenced_by`/`causes`/`caused_by`/`contradicts`/`supports`/`supported_by`/`supersedes`/`superseded_by`/`depends_on`/`required_by`/`analogous_to`/`opposite_of`/`derived_from`/`derives`）或已注册的 `x-<name>`，禁止自创 |
| `grade` | ⬜ | 质量分级 A/B/C（Analyzer 建议） |
| `processing_depth` | ⬜ | 处理深度（Analyzer 建议） |
| `is_immutable` | ⬜ | 是否不可变页面 |
| `tags` | ⬜ | 受控命名空间 `prefix/name`；可用前缀：`genre/` `func/` `char/` `event/` `mood/` `entity/` `scene_phase/` `status/` |
| `heat` / `last_used_at` / `zombie_since` | ⬜ | 热度追踪字段，由系统维护，勿手改 |

---

## 9. 校验与兜底链（谁在强制这份契约）

1. **JSON Schema（provider 层）**：`slots` 必须存在、每值 `minLength: 1`、`type` 强制 enum、缺 `id/type/title/slots` 直接拒。
2. **代码校验 + 1 次 retry**（`generator._call_with_slot_retry`，最多 2 次调用）：按 `required_slot_names()` 检查必填 slot，缺失时把缺失清单塞回 prompt 重问。
3. **占位兜底**：retry 后仍缺 → 填 `（系统占位：此项由系统补齐，请人工补充）` 并 WARN 写入 `log.md`。
4. **Lint 兜底**：`python -m src.cli lint` 对 `wiki-template-version >= 2.0.0` 页面触发 `LINT-MISSING-SECTION` WARNING（v1 旧页不受影响）。
5. **审计**：H2 检查断链（wikilink 指向不存在的文件，ERROR）；H4 检查 id 格式（WARNING）。

---

## 10. 人工编辑 / 自定义模板注意事项

- **改内容**：直接编辑 `wiki/<type>s/<id>.md` 的 slot 章节即可；不要删掉文件头部的 `<!-- wiki-template-version -->` / `<!-- wiki-template-type -->` 注释（lint 靠它识别版本）。
- **改模板**：`python -m src.cli wiki-templates edit <type>`（复制到用户级）或加 `--project <id>`（项目级）。可在模板中补充注释为团队提供逐字段说明——parser 会剥掉 HTML 注释，不影响渲染。
- **新增 slot**：改模板加 `<!-- slot:NAME -->` 后，新摄取页面即要求 LLM 填充；已有页面不受影响，重摄取源文件可让旧页升级。
- **可选章节**：用 `<!-- slot:NAME? -->` 或 `<!-- if:LABEL -->…<!-- /if:LABEL -->` 包裹；`<!-- include:_base.md -->` 支持片段复用（深度 ≤ 3）。
- **替换占位符**：发现 `（系统占位…）` 时，重新对该 raw 文件执行 `POST /api/v1/projects/<id>/ingest`，Generator 会用真实抽取内容覆盖。
