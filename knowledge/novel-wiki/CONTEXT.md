# CONTEXT.md — novel-wiki Glossary

> novel-wiki 子项目专用词表。
> 与仓库根 `CONTEXT.md` 互补：根词表是 ruflo-kb 平台通用概念；本文档是网文写作知识库的领域术语。
> 跨库术语以本词表为权威。

## Page model

| Term | Canonical meaning | _Avoid_ |
|---|---|---|
| `Frontmatter` | YAML 顶部 `---` 块的 V6 严格白名单（18 键 + `template_version`）。机器消费的主入口。 | 元数据、metadata |
| `Template slot` | 模板槽位，body 内 `## xxx` 标题 + `<!-- slot:xxx -->` 锚点。是**人读+LLM生成**的章节结构，不进 frontmatter。 | 章节、section、body section |
| `Template version` | 模板版本号（`novel-wiki-template-version`），独立于 `NOVEL_WIKI_FIELD_SCHEMA_VERSION`。 | 模板编号 |
| `Slot registry` | `.wiki-templates/index.yaml`，声明每个模板的 required/optional slots、min_references、min_relations 等 lint 阈值。 | 模板索引、slot index |
| `_ko_extra` | WikiPage 上 V6 白名单之外的扩展字段落点。不进白名单，由 lint 而非白名单校验。 | extra、metadata extension |

## Page types

| Term | Canonical meaning | _Avoid_ |
|---|---|---|
| `source` | 原始素材归档页。一手证据。 | 原文、原素材 |
| `entity` | 实体页。sub-type 见下。 | 实体（无 subtype）|
| `concept` | 抽象概念/技法页。网文知识库的主力类型（占比~70%）。**必须填 `适用阶段`**。 | 方法论、技巧 |
| `synthesis` | 跨源综合页。lint 强制 ≥2 viewpoints。 | 综合、综述 |

## Entity sub-types（V7 新增）

| Term | Canonical meaning | _Avoid_ |
|---|---|---|
| `entity_subtype: person` | 真实历史人物或网文圈内知名作者。例：李白、唐家三少、今越。 | 人物、author |
| `entity_subtype: work` | 具体作品（小说名 / 书名）。例：佛本是道、斗破苍穹。 | 作品、novel |
| `entity_subtype: platform` | 网文发布平台/网站/出版社。例：起点中文网、创酷中文网。 | 平台、site |
| `entity_subtype: site` | 非网文属性的站务/社群/论坛。例：作家联盟群、书评区。 | 站点、社区 |

`entity_subtype` 是 frontmatter V7 白名单字段（不进 `_ko_extra`）。

## Stage（适用阶段，concept 模板必填）

| Term | Canonical meaning | _Avoid_ |
|---|---|---|
| `开篇` | 故事开篇到第一卷前期（万字以内）。黄金三章、凤头。 | 开头、序章 |
| `前期` | 升级练功/铺世界观/引出金手指。 | 早期 |
| `中期` | 主线推进/支线展开/中期高潮。 | 中盘 |
| `高潮` | 主要矛盾爆发/决战/收束。 | 高潮段 |
| `收尾` | 结局/伏笔回收/读者预期兑现。 | 结局 |
| `通用` | 跨阶段适用的兜底值。CI 迁移期默认填此项。 | 全部、任意 |

## Relations

| Term | Canonical meaning | _Avoid_ |
|---|---|---|
| `references` | A 引用 B（B 是 source / 原始素材）。concept → source 的主链路。 | 引用、cite |
| `referenced_by` | A 被 B 引用（B → A）。references 的反向。 | 被引用 |
| `taxonomy_of` | 分类关系。target 必须 `taxonomy/<name>` 命名空间。 | 分类、tag |
| `is_part_of` | A 是 B 的一部分。例：家破人亡复仇法 is_part_of 开篇写法。 | 属于、属于 |
| `supported_by` | A 被 B 支撑。例：限制金手指 supported_by 冲突矛盾。 | 被支持 |
| `caused_by` | A 由 B 导致。例：主角挫折 caused_by 金手指限制。 | 起因 |
| `x-*` | 自定义关系。需在 `.wiki-templates/index.yaml` 的 `relations.custom` 注册。 | 自定义 |

**21 → 6 收敛**：被砍掉的 14 个低频关系（contains / supersedes / superseded_by / derives / derived_from / analogous_to / depends_on / required_by / opposite_of / causes / contradicts / 等）已 deprecated，不出现在 V7 index.yaml。

## Taxonomy 受控枚举

`taxonomy.md` 维持 6 大类 35 项的受控集合：
- 写作技法（11 项）
- 题材体系（10 项）
- 平台规则（6 项）
- 读者与市场（4 项）
- 案例与素材（4 项）
- 心态与职业（3 项）

**Sunset 日期**：2026-12-31。在此之前 CI 对 taxonomy target 仅 warn 不 reject；之后硬 reject。迁移期内老页可带 `_ko_extra.migration_pending: true` 豁免。

## 用途/可执行（治理标签）

| Term | Canonical meaning | _Avoid_ |
|---|---|---|
| `用途/可执行` | 受控标签，挂在 concept 页的 `tags` 上。表明本页通过了人工审核，**默认写作检索会命中**。 | 可执行、approved |
| `审核记录` | `.index/reviews_resolved.json` 中的人工审核记录，包含 `page_id / reviewer / decision / decided_at`。**当前未实现**，见 ADR-004。 | review、approval |

⚠️ **已知 gap**：`用途/可执行` 审核通道在本轮重写（V7）中**未实现**。当前所有 concept 页都不应授予此标签。后续 follow-up（ADR-004）单独 RFC。

## Cross-references

- 仓库根词表：`CONTEXT.md`
- Frontmatter 规范：`docs/guides/wiki-spec.md`
- V4 → V6 字段收敛：ADR-002
- 模板与 frontmatter 解耦：ADR-003
- 后续 follow-up：ADR-004（待起）
- 模板目录：`knowledge/novel-wiki/.wiki-templates/`