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
