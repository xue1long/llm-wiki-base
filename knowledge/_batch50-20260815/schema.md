# Wiki Schema Routing

## Page Types

| type | directory |
|------|-----------|
| source | wiki/sources |
| entity | wiki/entities |
| concept | wiki/concepts |
| synthesis | wiki/synthesis |
| claim | wiki/claims |
| decision | wiki/decisions |

## Conventions
- Every wiki page MUST have frontmatter `id`, `title`, `type`, `sources`, `created_at`, `updated_at`.
- `sources[]` holds relative paths into `raw/sources/`.
- `grade: A | B | C` (default B); `processing_depth: concept | memory` (default concept).
- Body uses `[[wikilink]]` syntax.
