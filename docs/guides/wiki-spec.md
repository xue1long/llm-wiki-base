---
rules:
  id:
    pattern: "^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-一-鿿]+|[a-z0-9-一-鿿]+)$"
    max_length: 64
    reserved: [index, log]
  frontmatter:
    required: [id, title, type, sources, created_at, updated_at]
    optional: [relations, tags]
    # V4 (ADR-002, 2026-08-31): the on-disk frontmatter is exactly 8 keys
    # — anything else is in-memory only on WikiPage (see §1.3 below) and is
    # NOT written to disk. The validator script
    # scripts/validate_novel_wiki_frontmatter.py is the source of truth for
    # enforcement.
  body:
    min_length: 1
    max_length: 50000  # 单个 body 最大字符数
    wikilink_syntax: "[[directory/slug]]"
    allowed_markdown:
      - bold
      - italic
      - headings
      - lists
      - wikilinks
---

# Wiki 规范（V4 · 2026-08-31）

## 0. 概述

本规范定义 Wiki 页面的**磁盘 frontmatter**（写入 `wiki/<type>/<id>.md` 的 YAML 部分）的字段集与行为。V4 收紧了 frontmatter：磁盘上**只允许 8 个键**，其他字段保留在内存 `WikiPage` 对象上供业务使用，但**不写入磁盘**。

### 0.1 V4 与 v2.2 的差异

| 维度 | v2.2 | **V4** |
|---|---|---|
| frontmatter 字段数 | 19 键（含 dead fields） | **8 键**（严格白名单）|
| `slug` 字段 | 写入 frontmatter | **不写入**（路径派生） |
| `grade` / `heat` / `processing_depth` / `workflow_state` | 写入 | **不写入**（内存模型）|
| `is_immutable` 守卫 | 写入 + 拒绝覆盖 | **完全删除** |
| `category` / `taxonomy_sub` | 写入 | **不写入**（用 `relations[taxonomy_of]`）|
| `related_entities` | 写入（始终 `[]`）| **不写入** |
| `_ko_extra` 镜像通道 | 写入 | **不写入** |
| `confidence` / `provenance` / `versions` / `lifecycle` / `lock_until`（V3 提议）| 提议从未实现 | **根本不接受** |

### 0.2 V4 不变性

- **frontmatter = 8 键严格白名单**：CI 拒绝任何非白名单字段
- **slug 永不存 frontmatter**：从 `<type_dir>/<id>` 派生
- **KO 写入层是终极守门人**：即使 LLM 输出 dead fields，写盘时也丢弃

---

## 1. 字段集（V4 · 8 键）

### 1.1 必填字段（6 项）

| 字段 | 类型 | 业务语义 |
|---|---|---|
| `id` | str | 文件系统唯一键；wikilink 路由 |
| `title` | str | 人类可读标题 |
| `type` | enum | `source` \| `entity` \| `concept` \| `synthesis`（4 选 1）|
| `sources` | list[str] | 原始来源路径（与 `raw/sources/...` 对应）|
| `created_at` | int (ms) | 物理创建时间 |
| `updated_at` | int (ms) | 物理更新时间 |

### 1.2 可选字段（2 项）

| 字段 | 类型 | 业务语义 |
|---|---|---|
| `relations` | list[dict] | 知识图谱边。21 个内置类型 + `x-*` 自定义 |
| `tags` | list[str] | 业务轻量标签 |

### 1.3 不写入 frontmatter 的字段（内存模型保留）

`WikiPage` dataclass 仍保留以下字段供业务逻辑使用，但**绝不写入磁盘**：

- `body` (str) —— Markdown body（页面正文，不算 frontmatter 字段）
- `grade` (str) —— A/B/C 评级（来自 KO confidence，但 V4 不持久化）
- `processing_depth` (str) —— concept/memory/operation（仅用于 stub 页面识别）
- `is_immutable` (bool) —— 保留字段定义但未启用守卫
- `heat` / `last_used_at` / `zombie_since` —— 热度衰减（未启用）
- `workflow_state` / `verified_at` —— 治理状态（未启用）
- `category` / `taxonomy_sub` —— 用 `relations[taxonomy_of]` 替代
- `custom_type` / `related_entities` —— schema.md 子类型机制未启用
- `_ko_extra` / `evidence_` / `decision_record` —— KO 镜像通道废弃
- `valid_from` / `valid_to` —— 时间窗口（未启用）
- `slug` —— 路径派生

### 1.4 字段填充规则

- **`grade`**：默认 `B`（内存模型）；render 层不计算（novel-wiki 场景不需要）
- **`slug`**：从 `<type_dir>/<id>` 派生，frontmatter 不存
- **`category`**：用 `relations[taxonomy_of]` 表达
- **`relations`**：21 个内置类型（references/referenced_by/contains/is_part_of/...） + `x-*` 自定义
- **`tags`**：无 type 约束，可含命名空间前缀如 `题材/玄幻`
- **`sources`**：与 `raw/sources/...` 路径对应（KO 写入时自动规范化）

### 1.5 ID 命名规则

ID 两种格式：
- **kebab-case slug**（含 CJK 支持）：如 `shuang-dian`、`ceo-romance`、`网络文学`
- **UUID v7** (`card_<13hex>_<8hex>_<slug>`)：v2.2+ 默认生成

字符集：
- ASCII `a-z`、`0-9`、连字符 `-`
- CJK 基本区 `U+4E00–U+9FFF`

**禁止**：大写 ASCII、下划线 `_`、Latin Extended、控制字符、`[` / `]`

### 1.6 type 系统（4 选 1）

| type | KB 目录 | 用途 |
|---|---|---|
| `source` | `wiki/sources/` | 原始素材引用 |
| `entity` | `wiki/entities/` | 实体（人物/平台/作品）|
| `concept` | `wiki/concepts/` | 抽象概念/技巧 |
| `synthesis` | `wiki/synthesis/` | 多源汇总 |

**删除**：`claim`（早期 KO 试点残留，迁移到 `source`）

---

## 2. Frontmatter 模板

```yaml
---
id: <与文件名一致，13-64 字符>
type: <source|entity|concept|synthesis>
title: <非空，≤80 字符>
sources: []                      # raw/sources/... 相对项目根；多源合并时多行
created_at: <Unix ms>
updated_at: <Unix ms>
relations: []                    # 21 类型 + x-* 扩展
tags: []                         # 业务轻量标签（无 type 约束）
---


```

### 2.1 反例（CI 拒绝）

| 反例 | CI 触发 |
|---|---|
| 保留 `tags:` 作为 frontmatter 顶层字段 | 报错（应转为 `relations[taxonomy_of]`） |
| `relations: target: 玄幻小说`（缺前缀） | 报错（必带命名空间前缀）|
| 写 `confidence` / `provenance` / `versions` / `lifecycle` / `lock_until` | 报错（V4 不接受）|
| 写 `grade` / `processing_depth` / `is_immutable` / `heat` 等 | 报错（V4 不写盘） |
| `slug` 手写且与路径不一致 | WARN + 覆盖 |

---

## 3. Body 规则

- `min_length`: 1 字符
- `max_length`: 50000 字符
- `wikilink_syntax`: `[[directory/slug]]` 或 `[[directory/slug|alias]]`
- `allowed_markdown`: bold / italic / headings / lists / wikilinks

---

## 4. 写盘协议

```python
from src.wiki.storage.page_writer import write_page

write_page(paths, WikiPage(
    id="my-page",
    title="My Page",
    type=PageType.CONCEPT,
    body="## 定义\n\n内容",
    sources=["raw/sources/source.md"],
    relations=[Relation(target="other-page", type="references", weight=1.0)],
    tags=[],
))
```

**V4 行为**：
- `WikiPage.to_frontmatter_dict()` 仅输出 8 键
- 内存模型上的 dead fields 不会出现在写入文件
- stub 页面（`processing_depth="stub"`）写入 `_stubs/` 目录
- 写入路径无 `is_immutable` 检查（覆盖允许）

---

## 5. 验证

### 5.1 V4 frontmatter 验证脚本

```
$ python scripts/validate_novel_wiki_frontmatter.py
[validate-v4] scanned=4892
[validate-v4] P0=0  ← 全部通过 V4 严格白名单
```

脚本：`scripts/validate_novel_wiki_frontmatter.py`

### 5.2 手工验证清单

1. frontmatter 必须有合法闭合符 `---\n...\n---\n`（不允许 `---` 黏在上一行）
2. 必填字段齐全：`id` / `title` / `type` / `sources` / `created_at` / `updated_at`
3. `type` ∈ `{source, entity, concept, synthesis}`
4. `id` 必须等于文件名 stem
5. 不含 V4 禁字段（`confidence` / `provenance` / `versions` / `lifecycle` / `lock_until`）
6. `relations` 中 `taxonomy_of` / `belongs_to_audience` / `hosted_on_platform` / `has_credibility` 的 target 必须带命名空间前缀

---

## 6. V4 迁移

### 6.1 已执行（2026-08-31）

- `knowledge/novel-wiki/wiki/` 4892 页全部迁移到 V4
- 迁移脚本：`scripts/migrate_novel_wiki_to_v4.py`（含 round-trip 验证）

### 6.2 字段转换

| 旧字段 | V4 转换 |
|---|---|
| `category: 写作技法` | `relations: [{target: taxonomy/写作技法, type: taxonomy_of}]` |
| `taxonomy_sub: 人物塑造` | `relations: [{target: taxonomy/人物塑造, type: taxonomy_of}]` |
| `tags: [题材/玄幻]` | `relations: [{target: taxonomy/玄幻, type: taxonomy_of}]` |
| `tags: [读者群/女性向]` | `relations: [{target: audience/女性向, type: belongs_to_audience}]` |
| `tags: [平台/飞书]` | `relations: [{target: platform/飞书, type: hosted_on_platform}]` |
| `tags: [可信度/ugc]` | `relations: [{target: credibility/ugc, type: has_credibility}]` |
| `type=claim` | `type=source`（文件移到 `wiki/sources/`）|
| `heat` / `is_immutable` / `last_used_at` / `zombie_since` / `related_entities` / `_ko_extra` | 删除 |
| `grade` / `processing_depth` / `workflow_state` / `verified_at` / `custom_type` | 保留为内存模型字段，不写盘 |

---

## 7. 关系类型（21 个内置）

### 7.1 知识图谱边（17 个）

| 类型 | 替的旧 tag 前缀 |
|---|---|
| `references` | — |
| `referenced_by` | — |
| `contains` | — |
| `is_part_of` | — |
| `supports` | — |
| `supported_by` | — |
| `derives` | — |
| `derived_from` | — |
| `analogous_to` | — |
| `depends_on` | — |
| `required_by` | — |
| `opposite_of` | — |
| `causes` | — |
| `caused_by` | — |
| `contradicts` | — |
| `supersedes` | — |
| `superseded_by` | — |

### 7.2 命名空间前缀（4 个，替代旧 tags）

| 类型 | target 命名空间 | 替代 |
|---|---|---|
| `taxonomy_of` | `taxonomy/<名>` | `category` / `taxonomy_sub` / `tags[题材/...]` |
| `belongs_to_audience` | `audience/<名>` | `tags[读者群/...]` |
| `hosted_on_platform` | `platform/<名>` | `tags[平台/...]` |
| `has_credibility` | `credibility/<name>` | `tags[可信度/...]` |

### 7.3 自定义 x-*

`x-*` 需在 `wiki/novel-wiki/relations.md` 注册，未注册触发 `LINT-UNKNOWN-RELATION-TYPE`。

---

## 8. stub 处理

- stub 页面（`processing_depth="stub"`）写入 `wiki/_stubs/`
- stub 由 KO 模型标注，写盘由 `page_writer` 路由
- stub 升级（materialize）从 `_stubs/<id>.md` 移到 `wiki/<type>/<id>.md`

---

## 9. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| [docs/architecture/novel-wiki-fields-template-2026-08-31.md](../architecture/novel-wiki-fields-template-2026-08-31.md) | novel-wiki V4 模板（与本文档一致）|
| [docs/adr/ADR-002-wiki-fields-long-term-evolution.md](../adr/ADR-002-wiki-fields-long-term-evolution.md) | ADR-002 V4 决策 |
| [scripts/validate_novel_wiki_frontmatter.py](../../scripts/validate_novel_wiki_frontmatter.py) | V4 验证脚本 |
| [scripts/migrate_novel_wiki_to_v4.py](../../scripts/migrate_novel_wiki_to_v4.py) | V4 迁移脚本 |

---

**生效日期**：2026-08-31
**Schema 版本**：`NOVEL_WIKI_FIELD_SCHEMA_VERSION = "4.0.0"`