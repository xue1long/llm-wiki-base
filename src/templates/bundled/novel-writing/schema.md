# 小说写作知识库结构

## 页面类型

| type | 用途 | 目录 |
|------|------|------|
| source | 书摘、课程、采访、影视分析、案例原文 | wiki/sources |
| entity | 人物、地点、作品、作者、组织、道具 | wiki/entities |
| concept | 写作技法、主题、叙事概念、类型规则 | wiki/concepts |
| synthesis | 故事方案、章节规划、方法论、改稿总结 | wiki/synthesis |

## 处理深度
- `concept`：沉淀可检索的知识和技法。
- `memory`：沉淀对当前写作项目有直接帮助的记忆。
- `operation`：沉淀可重复执行的写作流程。

## 约定
- 页面使用 YAML frontmatter 和 `[[wikilink]]` 交叉引用。
- `custom_type` 用于区分 `character`、`location`、`work`、`author` 等对象。
- 标签使用固定命名空间，例如 `题材/悬疑`、`技法/视角`、`阶段/大纲`。
- 原始来源、改写内容和个人推断必须尽量区分。
