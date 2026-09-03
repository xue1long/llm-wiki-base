# novel-wiki 字段模板（V4 · 8 键 · 2026-08-31）

> **本文档仅描述 `knowledge/novel-wiki/` 项目的字段终态。**
> **不构成 ruflo-kb 通用 `WikiPage` 模型的字段冻结**——通用模型见
> [docs/guides/wiki-spec.md](../../guides/wiki-spec.md)。
>
> ## ⚠️ V4 与旧版本不兼容
>
> | 版本 | 字段数 | 与存量兼容 | KO 写入路径 |
> |---|---|---|---|
> | v2.2 | 19 | — | 历史 |
> | V3 (deprecated) | 16 | 否 | 未实施 |
> | V3-slim | 14 | 部分 | 暂缓 |
> | **V4（本版）** | **8** | **否（全量重建）** | **必同步改造** |
>
> **字段集 = 8 键**（7 必填 + 1 必填数组）。
> 设计起点：从"业务真正需要表达什么"出发，**不**从"现状兼容什么"出发。
>
> 配套脚本：
> - `scripts/backfill_novel_wiki_slugs.py`（已废止——V4 不存 slug）
> - `scripts/validate_novel_wiki_frontmatter.py`（V4 校验脚本，待重写）
>
> 设计决策追溯：[ADR-002](./ADR-002-wiki-fields-long-term-evolution.md)（accepted）

---

## 0. 字段评估与精简结论

> **方法**：从"novel-wiki 作为网文素材 KB，需要表达什么"出发，重新审视 4892 个存量页面。
> 原则——**保留业务价值，删除工程复杂度**。

### 0.1 必填字段（8 键）

| # | 字段 | 类型 | 必填 | 业务语义 | 与 v2.2 对应 |
|---|---|---|---|---|---|
| 1 | `id` | str | ✅ | 文件系统唯一键；wikilink 路由 | = v2.2 |
| 2 | `title` | str | ✅ | 人类可读标题 | = v2.2 |
| 3 | `type` | enum | ✅ | 路由 + KB 目录 | = v2.2（砍 claim） |
| 4 | `relations` | list | ✅ | 知识图谱边 | = v2.2（保留21 类型）|
| 5 | `tags` | list | ✅ | 业务轻量标签 | = v2.2 |
| 6 | `sources` | list | ✅ | 原始来源路径 | = v2.2 |
| 7 | `created_at` | datetime (ISO 8601) | ✅ | 物理创建时间 | = V5（v4 仍为 ms int）|
| 8 | `updated_at` | datetime (ISO 8601) | ✅ | 物理更新时间 | = V5（v4 仍为 ms int）|

### 0.2 删除的字段（11 键 · 不计成本全删）

| # | 字段 | v2.2 现状 | 删除理由 |
|---|---|---|---|
| 1 | `slug` | 派生 / 35.7% | **从文件路径派生，不需要存 frontmatter** |
| 2 | `grade` | 派生 / 100% = B | **网文素材不需要 A/B/C 评级**（场景：找素材 ≠ 评素材） |
| 3 | `category` | 必填 / 84% | **用 `relations[taxonomy_of]` 替代**（统一命名空间） |
| 4 | `taxonomy_sub` | 可选 / 84% | **用 `relations[taxonomy_of]` 替代** |
| 5 | `processing_depth` | 必填 / 100% | **KO 二级路由不需要**——业务查询靠 type 即可 |
| 6 | `custom_type` | 必填 / 87% 空 | **schema.md 子类型机制未启用** |
| 7 | `workflow_state` | 可选 / 99% = draft | **wiki 不存治理状态**——治理走外部流程 |
| 8 | `verified_at` | 可选 / 100% = 0 | **与 workflow_state 配对删除** |
| 9 | `heat` | 必填 / 100% = 50 | **热度系统未运行**——永远是固定值 |
| 10 | `is_immutable` | 必填 / 100% = false | **编辑守卫未启用**——永远是固定值 |
| 11 | `last_used_at` | 必填 / 100% = 0 | **与 heat 配对** |
| 12 | `zombie_since` | 必填 / 100% = null | **与 heat 配对** |
| 13 | `related_entities` | 必填 / 100% = [] | **KO 模型字段未启用**——永远是空 |
| 14 | `_ko_extra` | 0.2% | **KO 镜像通道废弃** |
| 15 | `confidence` | 0% (V3 提议) | **从未使用**——V4 根本不加 |
| 16 | `provenance` | 0% (V3 提议) | **从未使用**——V4 根本不加 |
| 17 | `versions` | 0% (V3 提议) | **从未使用**——V4 根本不加 |
| 18 | `lifecycle` | 0% (V3 提议) | **从未使用**——V4 根本不加 |
| 19 | `lock_until` | 0% (V3 提议) | **从未使用**——V4 根本不加 |

### 0.3 type 系统（4 选 1）

| type | KB 目录 | 用途 | 存量页面 |
|---|---|---|---|
| `source` | `wiki/sources/` | 原始素材引用 | 约 3500 页 |
| `concept` | `wiki/concepts/` | 抽象概念/技巧 | 约 1200 页 |
| `synthesis` | `wiki/synthesis/` | 多源汇总 | 约 100 页 |
| `entity` | `wiki/entities/` | 实体（人物/平台/作品）| 0 页（保留）|

**删除 `claim` 类型**：早期 KO 试点残留（100 页），迁移到 `source`。

---

## 1. 标准模板（V4 · 8 键 · 可直接复制）

```yaml
---
id: <与文件名一致>
type: <source|entity|concept|synthesis>
title: <非空，≤80 字符>
relations: []
tags: []
sources: []
created_at: <ISO 8601 datetime>   # V5
updated_at: <ISO 8601 datetime>   # V5
---

<Markdown body，含 [[wikilinks]]>

```

### 1.1 字段填充规则

- **`id`**：必须等于文件名（不含扩展名），kebab-case 或 CJK 直用
- **`type`**：4 选 1，决定 KB 目录位置
- **`title`**：展示标题
- **`relations`**：知识图谱边数组，详见 §2
- **`tags`**：业务轻量标签数组（无 type 约束）
- **`sources`**：原始来源路径数组（`raw/sources/...` 相对项目根）
- **`created_at`** / **`updated_at`**：V5 ISO 8601 datetime（YAML `!!timestamp` 原生标量）

### 1.2 关键约束

- **不允许 `slug` 字段**——从 `<path` 派生，frontmatter 不存
- **不允许 `grade` 字段**——业务不需要
- **不允许 KO 镜像字段**（`processing_depth` / `workflow_state` / `verified_at` / `_ko_extra`）——wiki 不存治理
- **不允许 V3 提议字段**（`confidence` / `provenance` / `versions` / `lifecycle` / `lock_until`）——从未使用
- **不允许 `related_entities`**——永远是空

---

## 2. 关系体系（21 类型）

### 2.1 内置 17 类型（知识图谱边）

| relation type | 业务语义 |
|---|---|
| `references` | 引用 |
| `referenced_by` | 被引用 |
| `contains` | 包含 |
| `is_part_of` | 属于 |
| `supports` | 支持 |
| `supported_by` | 被支持 |
| `derives` | 派生 |
| `derived_from` | 源出 |
| `analogous_to` | 类似 |
| `depends_on` | 依赖 |
| `required_by` | 被依赖 |
| `opposite_of` | 对立 |
| `causes` | 导致 |
| `caused_by` | 被导致 |
| `contradicts` | 矛盾 |
| `supersedes` | 替代 |
| `superseded_by` | 被替代 |

### 2.2 命名空间前缀（4 个 · 替代旧 tags / taxonomy_sub / category）

| relation type         | target 命名空间          | 替的旧字段                  |
| --------------------- | -------------------- | --------------------------- |
| `taxonomy_of`         | `taxonomy/<名>`       | `category` / `taxonomy_sub` / `tags[题材/...]` |
| `belongs_to_audience` | `audience/<名>`       | `tags[读者群/...]` |
| `hosted_on_platform`  | `platform/<名>`       | `tags[平台/...]` |
| `has_credibility`     | `credibility/<name>` | `tags[可信度/...]` |

**迁移规则**：所有 `category: 玄幻` 替换为 `relations: [{target: taxonomy/玄幻, type: taxonomy_of}]`。

### 2.3 自定义 x-* 扩展

- `x-*` 需在 `wiki/novel-wiki/relations.md` 注册
- 未注册触发 `LINT-UNKNOWN-RELATION-TYPE`

---

## 3. 真实场景示例（4 种 type）

### 3.1 示例 1：concept（写作技巧）

**源页面**：`knowledge/novel-wiki/wiki/concepts/yy-小说中的角色关系处理.md`

```yaml
---
id: yy-小说中的角色关系处理
type: concept
title: YY小说中的角色关系处理
relations:
  - target: taxonomy/写作技法
    type: taxonomy_of
    weight: 1.0
  - target: taxonomy/人物塑造
    type: taxonomy_of
    weight: 1.0
tags: []
sources: []
created_at: 1787122944434
updated_at: 1787122944434
---

## 定义
...

```

### 3.2 示例 2：synthesis（多源汇总）

**源页面**：`knowledge/novel-wiki/wiki/synthesis/题材体系-多源分歧.md`

```yaml
---
id: 题材体系-多源分歧
type: synthesis
title: 题材体系的多源分歧
relations:
  - target: 东方玄幻
    type: references
    weight: 1.0
  - target: 仙侠小说
    type: references
    weight: 1.0
  - target: taxonomy/题材体系
    type: taxonomy_of
    weight: 1.0
tags: []
sources:
  - raw/sources/01_新手入门/借鉴素材写作套路征文类别与主线设定.md
  - raw/sources/01_新手入门/借鉴素材套路.md
created_at: 1787243109006
updated_at: 1787243109006
---

## 立场对比
...

```

### 3.3 示例 3：source（原始素材）

**源页面**：`knowledge/novel-wiki/wiki/sources/1写作选材之以小见大第1段-xxxx.md`

```yaml
---
id: 1写作选材之以小见大第1段-xxxxxxxx
type: source
title: (1)写作选材之以小见大第1段
relations:
  - target: taxonomy/教程
    type: taxonomy_of
    weight: 1.0
  - target: taxonomy/写作
    type: taxonomy_of
    weight: 1.0
tags: []
sources:
  - raw/sources/07_看电影学写作/1写作选材之以小见大第1段.md
created_at: 1787290014426
updated_at: 1787290014426
---

## 内容摘要
...

```

### 3.4 示例 4：entity（实体 · 占位）

```yaml
---
id: 起点中文网
type: entity
title: 起点中文网
relations:
  - target: platform/起点
    type: hosted_on_platform
    weight: 1.0
tags: []
sources: []
created_at: <ISO 8601 datetime>   # V5
updated_at: <ISO 8601 datetime>   # V5
---

## 简介
...

```

---

## 4. 反例（**不要这么写** · 7 项）

| # | 反例 | 原因 |
|---|---|---|
| 1 | 写 `slug:` 字段 | 路径派生，frontmatter 不存 |
| 2 | 写 `grade:` 字段 | 业务不需要 |
| 3 | 写 `category:` / `taxonomy_sub:` 字段 | 用 `relations[taxonomy_of]` 替代 |
| 4 | 写 `processing_depth:` / `workflow_state:` / `verified_at:` | wiki 不存治理 |
| 5 | 写 `heat:` / `is_immutable:` / `last_used_at:` / `zombie_since:` | 死字段 |
| 6 | 写 `related_entities:` / `_ko_extra:` | KO 镜像废弃 |
| 7 | 写 `confidence:` / `provenance:` / `versions:` / `lifecycle:` / `lock_until:` | V3 提议字段，从未使用 |

---

## 5. V4 实施步骤（不计成本全量重建）

### 5.1 全量迁移流程（WT-V4）

```
Step 1: 全量迁移脚本（一次性）
   ↓
Step 2: 死字段删除
   ↓
Step 3: category/taxonomy_sub → relations 迁移
   ↓
Step 4: type=claim 重新打标为 source
   ↓
Step 5: slug 从 frontmatter 删除
   ↓
Step 6: frontmatter 闭合符 bug 修复（写盘脚本）
   ↓
Step 7: 验证脚本（V4 schema）
   ↓
Step 8: KO 写入路径改造
```

### 5.2 KO 写入路径改造清单

```python
# src/pipeline/writer.py  (待改)
def write_wiki_page(page: WikiPage) -> None:
    frontmatter = {
        "id": page.id,
        "title": page.title,
        "type": page.type,
        "relations": page.relations or [],
        "tags": page.tags or [],
        "sources": page.sources or [],
        "created_at": page.created_at,
        "updated_at": page.updated_at,
        # ⚠️ 不写 slug / grade / category / taxonomy_sub
        # ⚠️ 不写 processing_depth / workflow_state / verified_at
        # ⚠️ 不写 heat / is_immutable / last_used_at / zombie_since
        # ⚠️ 不写 related_entities / _ko_extra
        # ⚠️ 不写 confidence / provenance / versions / lifecycle / lock_until
    }
    body = build_body(page)
    # ⚠️ frontmatter 必须以 `\n---\n` 结束（修原 bug）
    content = f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True)}---\n\n{body}"
    safe_write(page.path, content)
```

---

## 6. 验证脚本（V4）

待重写：`scripts/validate_novel_wiki_frontmatter.py`（V4 schema）

```python
REQUIRED_FIELDS = {"id", "title", "type", "relations", "tags", "sources",
                   "created_at", "updated_at"}
ALLOWED_FIELDS = REQUIRED_FIELDS  # V4 严格白名单——8 字段以外一律 fail
ALLOWED_TYPES = {"source", "entity", "concept", "synthesis"}
```

**预期**：迁移后 `P0=0, P1=0`（8 字段全白名单）

---

## 7. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| [wiki-fields-template-2026-08-31.deprecated.md](./wiki-fields-template-2026-08-31.deprecated.md) | V3 原模板（已弃用）|
| [wiki-fields-ideal-state-2026-08-31.md](./wiki-fields-ideal-state-2026-08-31.md) | 理想态实施指引（WT-1~WT-6）——任务清单需按本模板重新对齐 |
| [ADR-002](./ADR-002-wiki-fields-long-term-evolution.md) | accepted（终态决策；V4=8 键终态）|

---

## 8. 精简前后对比

| 维度 | v2.2 (19) | V3 (16) | V3-slim (14) | **V4 (8)** |
|---|---|---|---|---|
| 必填 | 6 | 8 | 6 | **8** |
| 可选 | 11 | 5 | 6 | **0** |
| 派生 | 2 | 2 | 2 | **0** |
| 逃逸舱 | _ko_extra | _ko_extra | 删除 | **删除** |
| type 数 | 5 | 4 | 5 | **4** |
| 关系类型 | 21 | 21 | 21 | **21** |
| 死字段 | 5 | 5 | 5 | **0（全删）** |
| V3 提议字段 | 0 | 5 | 0 | **0（根本不写）** |

### 关键收益

- **写入负担**：8 字段全部有业务价值，无死字段
- **写入器复杂度**：8 字段 vs 19 字段，写盘脚本代码量 -60%
- **CI 验证**：8 字段白名单严格模式，写错即 fail
- **数据 bug 修复**：写入路径同步修 frontmatter 闭合符

### 关键代价

- **全量重建**：4892 页全部要迁移
- **KO 写入路径改造**：所有 `src/pipeline/*` 涉及 WikiPage 写入的地方要改
- **业务查询变更**：`category: 玄幻` → `relations: [taxonomy_of]`，调用方需更新
- **类型系统变更**：`type=claim` 全部迁移到 `source`，调用方需更新

---

**字段生效**：`NOVEL_WIKI_FIELD_SCHEMA_VERSION = "5.0.0"` (V5：时间戳改为 ISO 8601 datetime)
**通用 WikiPage 模型字段冻结**：见 `docs/guides/wiki-spec.md`（与本模板解耦）