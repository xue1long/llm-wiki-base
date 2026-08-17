# Wiki 规范同步方案

## 目标

将 Wiki 命名 / Frontmatter / Body 规则固化为规范文档（canonical source of truth），规范变更后 Generator Prompt 自动同步，无需手动改代码。

## 架构

```
docs/guides/wiki-spec.md              # 规范文档（canonical source of truth）
    ↓
scripts/sync_wiki_spec.py             # 同步脚本（读取 YAML frontmatter → 生成 prompt 片段）
    ↓
src/pipeline/wiki_rules_prompt.py    # 生成物（Generator 导入的 prompt 片段）
    ↓
src/pipeline/generator.py             # GENERATOR_PROMPT 引用 wiki_rules_prompt
```

## 规范文档格式

`docs/guides/wiki-spec.md` 使用 YAML frontmatter + Markdown body：

```yaml
---
rules:
  id:
    pattern: "^[a-z0-9-]+$"      # kebab-case slug
    max_length: 64
    reserved: [index, log]       # 保留 ID 列表
  frontmatter:
    required: [id, title, type]
    optional: [sources, relations, grade, processing_depth, is_immutable, heat, last_used_at, zombie_since]
  body:
    min_length: 1                 # 空 body → LINT-EMPTY-BODY (INFO)
    allowed_markdown:
      - bold       # **text**
      - italic    # *text*
      - headings  # ## / ###
      - lists     # - item
      - wikilinks # [[slug]]
    wikilink_syntax: "[[slug]]"  # wikilink 格式
---

# Wiki 规范说明

## ID 命名

ID 必须为小写 kebab-case slug，如 `shuang-dian`、`ceo-romance`。
不得使用 `index`、`log` 等保留 ID。
```

## 同步脚本逻辑

`sync_wiki_spec.py`：

1. 计算 `docs/guides/wiki-spec.md` 的 MD5
2. 与 `.wiki-spec-md5` 中记录的上次 MD5 比较
3. 若相同 → 不做任何事，退出 0
4. 若不同 → 解析 YAML frontmatter，生成 `src/pipeline/wiki_rules_prompt.py`
5. 写新 MD5 到 `.wiki-spec-md5`
6. `git add src/pipeline/wiki_rules_prompt.py`（确保同步产物提交）

```python
# src/pipeline/wiki_rules_prompt.py（生成物示例）
ID_RULES = {
    "pattern": "^[a-z0-9-]+$",
    "max_length": 64,
    "reserved": ["index", "log"],
}
FRONTMATTER_RULES = {
    "required": ["id", "title", "type"],
    "optional": ["sources", "relations", ...],
}
BODY_RULES = {
    "min_length": 1,
    "allowed_markdown": ["bold", "italic", "headings", "lists", "wikilinks"],
    "wikilink_syntax": "[[slug]]",
}

WIKI_RULES_SUMMARY = """
## Wiki Page Rules
- ID: kebab-case, max 64 chars, no reserved IDs
- Frontmatter required: id, title, type
- Body: non-empty, use [[slug]] for cross-references
""".strip()
```

## 触发机制

**Git pre-commit hook**：

```bash
# .git/hooks/pre-commit（安装后）
python scripts/sync_wiki_spec.py || exit 1
```

安装方式：`python scripts/setup_git_hooks.py`（首次运行时安装，后续自动生效）。

若 pre-commit 失败（MD5 不匹配但产物未生成），开发者必须重新 commit 规范变更。

## CLAUDE.md 引用

Wiki 数据模型节新增引用：

```markdown
Wiki 规范（含命名/Frontmatter/Body 规则）：[`docs/guides/wiki-spec.md`](docs/guides/wiki-spec.md)
```

## 实现步骤

1. 创建 `docs/guides/wiki-spec.md`（当前已知的 Wiki 规范）
2. 创建 `scripts/sync_wiki_spec.py`
3. 创建 `src/pipeline/wiki_rules_prompt.py`（首次手动生成）
4. 修改 `src/pipeline/generator.py`，GENERATOR_PROMPT 改为引用 `wiki_rules_prompt.WIKI_RULES_SUMMARY`
5. 创建 `scripts/setup_git_hooks.py` 安装 pre-commit hook
6. 提交所有变更

## 首次同步内容

基于现有代码分析，规范初稿内容：

- ID：纯 slug（`[a-z0-9-]+`），不强制 UUID v7（方案 1：两者并存）
- Frontmatter required：`id`、`title`、`type`
- Body：非空，允许 markdown + `[[wikilinks]]`
