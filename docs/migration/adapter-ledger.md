# Knowledge Compiler adapter ledger

| Adapter | Current caller | Replacement target | Exit condition |
|---|---|---|---|
| `LegacyCollector` | `src/kc/api.py` C-phase entry | Native CanonicalDocument collector | Markdown/TXT/URL native collector passes two acceptance runs |
| `LegacyAnalyzer` | Candidate JSON seam | Native structured extractor | Analyzer emits locally verifiable Evidence for all supported inputs |
| `wiki_projection` | C-phase read-only projection | Existing Writer-backed projection | Writer can atomically persist reverse references and rollback |

The C acceptance script is read-only (`write_count=0`); it does not migrate or overwrite existing Wiki pages.
