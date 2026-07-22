# Wiki Schema Routing

## Page Types

| type | directory |
|------|-----------|
| source | wiki/sources |
| entity | wiki/entities |
| concept | wiki/concepts |
| synthesis | wiki/synthesis |

## Conventions
- All wiki pages MUST have frontmatter `id`, `title`, `type`, `sources`, `created_at`, `updated_at`.
- `id` is UUID v7 format (auto-generated if not provided)
- `sources[]` is relative paths to `raw/sources/<task_id>.<ext>`
- `grade: A | B | C` indicates source quality
- `processing_depth: concept | memory` controls depth
