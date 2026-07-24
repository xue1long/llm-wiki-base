---
rules:
  id:
    pattern: "^[a-z0-9-]+$"
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

ID 必须为小写 kebab-case slug，如 `shuang-dian`、`ceo-romance`。
不得使用 `index`、`log` 等保留 ID。

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
