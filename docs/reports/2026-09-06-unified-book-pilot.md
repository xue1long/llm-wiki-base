# Unified Book Rule-only Pilot

**Date:** 2026-09-06  
**Project:** `knowledge/novel-wiki`  
**Book:** `novel-wiki-book`  
**Snapshot:** `61eb65b94d75d079d146c43cdcfc9a2891d39130c4c6cea289ed20e89d6ed610`

## Scope

This is a real-data rule-only pilot, not the cancelled three-book series
pilot. It uses 12 existing Wiki pages and produces two readable chapters:

- `chapter-structure`: 7 pages from the existing `大纲与结构` taxonomy.
- `chapter-technique`: 5 pages from the existing `写作技巧` taxonomy.

The page IDs, review hashes, source paths, and reasons are persisted in
`knowledge/novel-wiki/book-wiki/editorial/curation.json`; the stable chapter
assignment is in `editorial/outline.json`.

## Findings

- All 12 selected pages matched the current Wiki snapshot content hash.
- The rule-only build produced both chapters and passed the quality gate.
- Chapter bodies remain existing Wiki blocks; no semantic deduplication or
  LLM rewriting is claimed.
- No duplicate or conflict disposition was required in this selected set;
  the absence is recorded rather than fabricated.
- Tutorial paths remain empty in this pilot. The path file is present and
  contains no body text.

## Source boundary

Sources are existing project-local ingested files under `raw/sources/`.
This pilot performs no external provider call and does not publish source
material outside the local release. Original copyright/licence permissions
were not re-audited here; any external distribution remains blocked until
that review is completed.

## Verification

The real project dry-run returned `status=planned`, generated two chapters,
and passed the deterministic quality gate. The existing `CURRENT.json` was
not changed by the dry-run.
