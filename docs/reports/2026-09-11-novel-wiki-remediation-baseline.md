# novel-wiki 写作知识库整改基线

- Snapshot time: 2026-09-11（Task 0 修正后）
- Project root: `knowledge/novel-wiki`
- Git HEAD at scan: `a51d5c07`（后续修正提交不会改变本次基线的计数口径）
- Worktree: dirty; unrelated existing changes preserved
- Scan commands: `scripts/validate_novel_wiki_frontmatter.py --strict` and read-only PowerShell counts

## Task 0 contract result

当前运行时合同是 V6：`WikiPage.to_frontmatter_dict()` 写入基础 8 个字段和 10 个迁移字段，共 18 个字段。现有 novel-wiki 存量页主要仍是 V4/V5 的基础 8 键格式；读取侧为缺失的 V6 字段补默认值，校验器同时接受两种格式。未知顶层字段仍然属于 P0。

本次只修正合同说明、写入层注释和兼容校验器，没有迁移存量页、修改 raw 或扩展字段集合。V6 的架构 ADR 仍标记为 proposed，这是后续治理审批事项，不在本轮自动改变。

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
| V4/V5/V6 validator P0 | 0 | strict read-only validator, 1,747 pages scanned |
| Runtime write schema | V6 / 18 keys | legacy V4/V5 8-key pages remain readable |
| Embedding model | unavailable in current contract | pending ledger has no canonical model identity |
| Vector content hash | unavailable in current contract | pending ledger stores page body hash only |

## Input hashes

| Input | SHA-256 |
|---|---|
| `knowledge/novel-wiki/purpose.md` | `0C1E842494B0754FE9E67363AD8748009FFDD6C4687A8268488664633ABA7F98` |
| `knowledge/novel-wiki/schema.md` | `F88394C8F921F16BCE2E7ADFFB8DEC393B8D4171B08E7295668295C7E35468C8` |
| `docs/guides/wiki-spec.md` | `2442098284AFB35F745581FEAFCE06A191FED5E58E921E1AAA257CDB8239C3E9` |
| `docs/architecture/novel-wiki-fields-template-2026-08-31.md` | `5757F004899F1DF919733BA5FE54FE7716330A785C1D7121C9EB9FAF2A839401` |

## Verification

- Current writer regression: V6 emits the 18-key set; legacy 8-key and V6 pages both pass the validator regression.
- Python compile for changed implementation and test: PASS.
- `scripts/validate_novel_wiki_frontmatter.py --strict`: PASS, `P0=0`.
- The core count scan was repeated on the same corpus and remained stable; rerun it before the canary.
- Raw files were read only; no raw deletion or full ingestion was performed.

## Task 0 decision

**PASS with an explicit governance limitation:** the runtime, writer comments, guide, historical template status, validator and regression test now describe the same V6 write / V4-V5 read-compatible contract. The V6 ADR remains proposed, and vector model identity plus vector-side content hash remain Task 3 work.
