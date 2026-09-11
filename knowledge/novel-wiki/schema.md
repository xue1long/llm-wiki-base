# Wiki Schema

## Page Types

| type | directory |
|------|-----------|
| source | wiki/sources |
| entity | wiki/entities |
| concept | wiki/concepts |
| synthesis | wiki/synthesis |

## Conventions

- 页面使用 YAML frontmatter 和 `[[wikilink]]` 交叉引用。
- 分类轴：category/taxonomy_sub 必须落入 taxonomy.md 受控枚举（见项目 taxonomy.md）。
- 可信度：UGC 来源页面必须打 `素材/ugc` + `可信度/ugc` 双 tag。
- 用途：只允许受控标签 `用途/可执行`；授予前必须存在 `.index/reviews_resolved.json` 中的人工审核记录（page_id、reviewer、decision、decided_at）。
- 生成器和分析器不得直接授予 `用途/可执行`；迁移脚本默认 dry-run，只有人工审核记录允许 apply。
