---
rules:
  id:
    pattern: "^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-一-鿿]+|[a-z0-9-一-鿿]+)$"
    max_length: 64
    reserved: [index, log]
  frontmatter:
    required: [id, title, type]
    optional: [sources, relations, grade, processing_depth, is_immutable, heat, last_used_at, zombie_since, tags]
  body:
    min_length: 1
    max_length: 50000  # 单个 body 最大字符数
    wikilink_syntax: "[[slug]]"
    allowed_markdown:
      - bold
      - italic
      - headings
      - lists
      - wikilinks
---

# Wiki 规范

## ID 命名规则

ID 有两种可用格式：

- kebab-case slug（**含 CJK 支持**, 2026-07-26 cut-over）：如 `shuang-dian`、`ceo-romance`、`网络文学`、`仙侠小说`
- UUID v7 (`card_<13hex>_<8hex>_<slug>`)：如 `card_018f3a8e2b1c4_a3f9d12c_lin-feng`，v2.2+ 默认生成

### 字符集

ID 字符（与 ``slugify()`` 一致）：

- ASCII `a-z`、`0-9`、连字符 `-`
- CJK 基本区 `U+4E00–U+9FFF`（保留原字）

**禁止**：

- 大写 ASCII（kebab-case 是小写）
- 下划线 `_`（kebab-case 用 `-`）
- Latin Extended（`é`、`ñ` 等）—— 不在当前 slugify 范围内，需要时手动加 alias
- 文件路径分隔符、控制字符、`[` / `]`

### 中文 slug

`slugify()` 在切到 CJK 后（commit 9d92eab）：

- 保留 CJK 原字（不再走 pinyin 转写）
- NFC 标准化输入（处理 macOS HFS+ NFD）
- `混Test合` → `混-test-合`（运行边界用连字符）
- `café` → `café`（拉丁扩展字符作为变音符融合不分割）

LLM 提示词（commit 8025eaa）已更新为：

> Slugs (id、relations[].target) 可直接使用中文 (CJK),也可使用 ASCII kebab-case — 保留概念的自然字面,**无需拼音转写**;专有名词/英文术语在 ASCII 段仍保持原始写法。

### 历史迁移

如果旧 wiki 还存在 pinyin slug（切到 CJK 之前的产物），可运行：

```bash
python scripts/migrate_pinyin_to_cjk_aliases.py --apply
```

脚本读取每个页面的标题，用新的 CJK-aware `slugify()` 算出"应为"的 CJK slug，并把 `cjk_slug → existing_pinyin_id` 写入 `.llm-wiki/slug_aliases.json`。**不会**重命名文件（破坏性操作）。

审计工具（H4）同意两种格式；不得使用 `index`、`log` 等保留 ID。

## Frontmatter 字段

### 必须字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | 与文件名一致，不含 `.md` |
| `title` | str | 显示标题 |
| `type` | PageType | `source` \| `entity` \| `concept` \| `synthesis` |

### 可选字段

`sources`、`relations`、`grade`、`processing_depth`、`is_immutable`、`heat`、`last_used_at`、`zombie_since`、`tags`

### Tags 规则

Tags 使用受控命名空间前缀，格式为 `prefix/name`。可用前缀：

| 前缀 | 说明 |
|---|---|
| `genre/` | 题材类型 |
| `func/` | 功能类型 |
| `char/` | 角色类型 |
| `event/` | 事件类型 |
| `mood/` | 情绪氛围 |
| `entity/` | 是什么 (What) |
| `scene_phase/` | 何时用 (When) |
| `status/` | 生命周期 |

## Body 规则

- 不得为空（空 body → LINT-EMPTY-BODY INFO 告警）
- 支持 Markdown：`**bold**`、`*italic*`、`## 标题`、`### 子标题`、`- 列表`
- 跨页引用使用 `[[slug]]` 语法，如 `[[shuang-dian]]`

## PageType 语义（4 种 page type 的判定标准）

正确分类是知识库图谱可用的前提。每条 `suggested_pages` 必须落到下面 4 类之一：

| type | 判定标准 | 典型例子 |
|---|---|---|
| `source` | 原始摄入的文档/URL。每个摄取任务自动产生一条,保存原文摘要 + 元数据,不依赖 LLM 决定 | 摄取的 PDF/MD/URL 本身 |
| `entity` | 具象实体:**有名字、可数、可唯一标识的对象**。人物、组织、具体作品、地点、特定流派名 | `李白`、`佛本是道`、`阅文集团`、`起点中文网`、`洪荒封神流`(具体流派) |
| `concept` | 抽象概念:**可跨页复用、不依附具体作品**的主题/技巧/原则/题材大类 | `仙侠小说`(题材大类)、`画面感`(写作技巧)、`长生`(主题)、`伏笔`(叙事技巧) |
| `synthesis` | 跨页综合分析:对多个 concept/entity 的对比、综述、汇总 | "仙侠 vs 玄幻对比"、"仙侠流派综述" |

**判定启发式**:
- 问"它是某个人/某本书/某个具体东西吗?" → entity
- 问"它是一个抽象的方法/原则/类别吗?" → concept
- 问"它是把多个东西综合起来的对比/汇总吗?" → synthesis
- 问"它是原始摄取的文档吗?" → source

**反例(常见误判)**:
- `佛本是道`(具体作品) ❌ concept → ✅ entity
- `李白`(历史人物) ❌ concept → ✅ entity
- `网络文学`(题材大类) ❌ entity → ✅ concept
- `画面感`(抽象技巧) ✓ concept

## Wiki Page Templates (Plan 25)

每种 `PageType` 都有一个**章节模板**,Generator 提示 LLM 按模板填充 slot,保证知识库结构一致。

**模板格式** — 普通 Markdown,用 HTML 注释做标记:

```markdown
<!-- wiki-template-version: 1.0.0 -->
<!-- wiki-template-type: concept -->

## 定义

<!-- slot:definition -->

## 例子

<!-- slot:examples -->

## 别名

<!-- if:has_aliases -->

<!-- slot:aliases -->

<!-- /if:has_aliases -->
```

**标记种类**:

| 标记 | 含义 |
|---|---|
| `<!-- wiki-template-version: X.Y.Z -->` | 模板版本(必需) |
| `<!-- wiki-template-type: TYPE -->` | PageType(必需,parser 验证) |
| `<!-- slot:NAME -->` | LLM 应填充的位置 |
| `<!-- slot:NAME? -->` | 可选 slot,空则省略整个章节 |
| `<!-- if:LABEL -->...<!-- /if:LABEL -->` | 同 `?`,LABEL 只是标签 |
| `<!-- include:_base.md -->` | 引用片段(深度 ≤ 3 防循环) |

**优先级(三级)**:
1. `<project>/.wiki-templates/<type>.md` (项目级覆盖)
2. `~/.config/ruflo-kb/wiki-templates/<type>.md` (用户全局)
3. `src/wiki/templates/bundled/<type>.md` (bundled 默认)

**默认模板**:每个 PageType 在 bundled/ 都有 4-5 个章节骨架。详见 `src/wiki/templates/bundled/`。

**CLI 管理**:
```bash
python -m src.cli wiki-templates list         # 列出所有 PageType
python -m src.cli wiki-templates show concept # 查看模板内容
python -m src.cli wiki-templates edit concept # 复制 bundled → user/,打开编辑器
python -m src.cli wiki-templates edit concept --project novel-wiki  # 复制到项目
python -m src.cli wiki-templates reset concept # 删除 user/ 覆盖,回落到 bundled
```

## v2.3 Schema (Plan 27, 2026-07-26) — 模板驱动的 body 生成

自 v2.3 起,wiki 页面的 body **不再**是 LLM 自由发挥的字符串,而是由 Generator 强制按模板 slot 填充后渲染的产物。bundled 模板版本号从 `1.0.0` 升到 `2.0.0`,以此把"v1 自由发挥"和"v2 结构化"区分开。

### 新的 LLM 响应结构

Generator 的 JSON schema 把 `body_markdown: string` 替换成 `slots: object`。LLM 必须为每个 PageType 的所有 required slot 提供非空内容;可选 slot (`<!-- slot:NAME? -->` 或 `<!-- if:X -->` 包裹) 允许省略或返回空列表,被省略时其整个 heading 也被丢弃。

```jsonc
{
  "pages": [
    {
      "id": "<slug>",
      "type": "concept",
      "title": "<title>",
      "slots": {
        "definition": "...",
        "characteristics": ["特性 1", "特性 2"],
        "examples": ["例 1"],
        "related_concepts": ["[[other-slug]]"],
        "references": ["来源"]
      }
    }
  ]
}
```

### 三道防线(防回归)

1. **Schema 防护**:Provider 用 JSON schema 拒绝 `slots` 缺失或每个 slot 值为空字符串的情况。
2. **代码校验 + 一次 retry**:Generator 在 retry 一次仍未填补所有 required slot 时,以 server-side 占位字符 (`（系统占位：此项由系统补齐，请人工补充）`) 填充,并 `WARN` 到 `log.md`。
3. **Lint 兜底**:`cli lint` 新增 `LINT-MISSING-SECTION` WARNING。**仅**对版本 `>= 2.0.0` 的页面触发,旧版页面不受影响。

### v2.3 升级路径

- **新摄入的内容**自动按 v2.3 schema 渲染。每个 wiki 文件首行的 `<!-- wiki-template-version: 2.0.0 -->` 注释让 lint 能识别并校验。
- **已有的 v1 wiki 页面** (`wiki-template-version: 1.0.0`) 保持原样,不被 lint 强制重写。如要让旧页面也通过结构性检查,简单做法是重新摄取对应的源文件。
- **升级占位字符到有意义内容**:对带 `(见下游概念页)` / `(待补充)` 等占位的页面,运行对应 raw 文件的 `POST /api/v1/projects/<id>/ingest` 让 Generator 重新生成;占位会被真实抽取内容替换。

### 不变的部分

- `WikiPage` 数据模型的 `body: str` 字段保持不变 — 仍是单一 markdown 字符串落地。
- `page_writer.write_page` / `read_page` 不动 — 行为完全向后兼容。
- features (relations / heat / indexer / review / dedup / 等) 不动 — 它们对 body 内容不敏感。
- 任意项目级 / 用户级模板 (`<project>/.wiki-templates/`, `~/.config/ruflo-kb/wiki-templates/`) 都可以独立 bump 到 2.0.0 享受新校验。
