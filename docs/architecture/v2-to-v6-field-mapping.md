# v2 → V6 字段与文件映射

本文件是迁移器唯一字段映射入口。实现、测试、验收不得各自重新定义字段归属。

## 1. 页面字段映射

| v2 字段/来源 | V6 目标 | 规则 |
|---|---|---|
| 文件名 stem | `id` | 保留原 stem；目标文件名冲突时默认 fail |
| `title` | `title` | 原值保留 |
| concepts | `type: concept` | 落 `wiki/concepts/` |
| entities | `type: entity` | 落 `wiki/entities/` |
| `url` | `sources` | 单值转单元素列表；同时保留 `_ko_extra.v2_url` 以便精确回溯 |
| `created` / `updated` | `created_at` / `updated_at` | 统一转换为 Unix ms；原始字符串保留在 `_ko_extra.v2_created` / `_ko_extra.v2_updated` |
| `tags` | `tags` + `_ko_extra._v2_tags_original` | 可识别 tag 进入规范化 tags；原列表必须完整保留 |
| `processing_depth` | `processing_depth` | 顶层唯一 canonical home |
| `source_grade` | `source_grade` | 顶层唯一 canonical home |
| `platform` | `platform` | 顶层唯一 canonical home，不再重复写 `_ko_extra.platform` |
| `category` | `category` | 顶层唯一 canonical home |
| `taxonomy_sub` | `taxonomy_sub` | 顶层唯一 canonical home |
| `use_context` | `use_context` | 顶层唯一 canonical home |
| `workflow_state` | `workflow_state` | 顶层唯一 canonical home |
| 视频来源/平台 | `capture_type` | 视频转录=`video-transcript`；文章=`article`；碎片/seed=`inspiration` |
| 迁移来源 | `v2_origin: true` | 所有进入 Wiki 的 v2 卡必须为 true |
| `version` / `author` / `maturity` / `summary` | `_ko_extra` | 原值保留 |
| `aliases` | `_ko_extra.aliases` + alias registry | entity 才写入 `.llm-wiki/slug_aliases.json` |
| `instance_of` | `custom_type` + `_ko_extra.instance_of` | `custom_type` 用于 schema routing，原值仍保留 |
| `bv` / `video_id` / `note_id` | `_ko_extra` | 原值保留；不得仅依靠推导 URL |
| 未识别字段 | `_ko_extra._v2_unknown_fields` | 不得静默丢弃 |

`_ko_extra` 只承载没有 V6 canonical home 的字段，除 `v2_url`、原始 tags、原始日期等审计副本外，不允许同一语义字段出现两个可变来源。

## 2. 文件 disposition

每个来源文件必须在 `migration-manifest.json` 中记录：`source_path`、`sha256`、`size`、`kind`、`disposition`、`target_path`、`reason`。

允许的 disposition：

```text
migrated / archived / skipped / quarantined / support-artifact /
metadata-only / collision / failed
```

`failed` 只能出现在 dry-run 或失败报告中，不能出现在最终成功 manifest。

## 3. Wikilink 规则

- canonical slug 优先使用目标页面 `id`；
- alias 通过 `.llm-wiki/slug_aliases.json` 解析；
- 已存在目标页面的链接写入 relations；
- 不存在目标页面的链接写入 knowledge-gap，并保留原始文本；
- self-reference 不写 relation，但必须计入审计报告；
- 迁移前后必须输出链接总数、resolved、gap、self-reference 和 parse-error。
