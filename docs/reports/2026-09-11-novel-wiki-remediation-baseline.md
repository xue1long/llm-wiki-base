# novel-wiki 写作知识库整改基线

- Snapshot time: 2026-09-11T17:06:50+08:00
- Project root: `knowledge/novel-wiki`
- Git HEAD: `09884d271e6bf5333266950dd4e1a78977ac9e1d`
- Worktree: dirty; unrelated existing changes preserved
- Scan commands: `scripts/validate_novel_wiki_frontmatter.py --strict` and read-only PowerShell counts

## Task 0 contract result

文档和实现原先存在冲突：V4/V5 文档及校验脚本要求磁盘 frontmatter 只有 8 个键，但 `WikiPage.to_frontmatter_dict()` 实际返回了额外的运行时字段。已在 `src/wiki/core/types.py` 删除额外输出，保留以下 8 个键：

`id`, `title`, `type`, `relations`, `tags`, `sources`, `created_at`, `updated_at`

读侧仍保留 legacy 字段兼容；本次没有修改 raw，也没有扩展 schema。

## Baseline counts

| Metric | Value | Method / limitation |
|---|---:|---|
| Wiki pages | 1,747 | `wiki/**/*.md`, excluding `index.md` and `log.md` |
| Raw files | 1,364 | `raw/**/*` files |
| Actionable tag occurrences | 0 | exact text scan for `用途/可执行`; migration not started |
| Vector pending | 1,221 | `.index/vector_pending.json` entries |
| Pending state | 1,221 pending | ledger publication state |
| Knowledge gaps | 230 | `.index/knowledge_gaps.json` |
| Open gaps | 230 | current status field |
| V4 validator P0 | 0 | strict read-only validator, 1,747 pages scanned |
| Wiki schema | V5.0.0 | current guide/template declaration |
| Embedding model | unavailable in current contract | pending ledger has no canonical model identity |
| Vector content hash | unavailable in current contract | pending ledger stores page body hash only |

## Input hashes

| Input | SHA-256 |
|---|---|
| `knowledge/novel-wiki/purpose.md` | `0C1E842494B0754FE9E67363AD8748009FFDD6C4687A8268488664633ABA7F98` |
| `knowledge/novel-wiki/schema.md` | `F88394C8F921F16BCE2E7ADFFB8DEC393B8D4171B08E7295668295C7E35468C8` |
| `docs/guides/wiki-spec.md` | `C5F099D0BF2A7A26A929E3350338A535A007548B56BEA41695FB5980CC673` |
| `docs/architecture/novel-wiki-fields-template-2026-08-31.md` | `954D29BCEE2EDB1B736E06748DB5059917AA1946929656061885926A3E6DA45E` |

## Verification

- Frontmatter contract regression: PASS.
- Python compile for changed implementation and test: PASS.
- `scripts/validate_novel_wiki_frontmatter.py --strict`: PASS, `P0=0`.
- Same-corpus repeated metrics: not automated; counts above are the frozen first read and must be rerun before final canary.

## Task 0 decision

**PASS with a recorded limitation:** schema/write contract is unified; vector model identity and vector-side content hash are not yet available and remain Task 3 work. No full ingestion or cleanup was performed.
