# Unified Knowledge Book Specification

## Purpose

For one knowledge domain, compile a canonical Book that a person can read by
directory and chapter. Wiki remains the factual/search layer. TutorialPath is
only a reference-based navigation overlay and never owns chapter body text.

## Authoritative inputs

The formal Book inputs live under `book-wiki/`:

```text
book.json
editorial/curation.json
editorial/outline.json
editorial/paths.json
```

`curation.json` records page disposition (`include`, `duplicate`, `conflict`,
`exclude`, `unresolved`), one primary chapter owner, optional secondary
references, a reason, and the content hash reviewed. `outline.json` owns
stable volume/chapter IDs. `paths.json` owns only chapter/section references,
tasks, checkpoints, and path status.

The first Book uses `domain_id=novel-wiki` and `book_id=novel-wiki-book`.
Legacy `series_id` is compatibility metadata only and cannot assign pages.

## Invariants

- A release is bound to one Wiki snapshot and one editorial revision.
- Pages outside the Book subset are allowed; declared pages must be known to
  the snapshot and every outline page must have a valid disposition.
- An included or conflict page has exactly one primary chapter.
- Duplicate/excluded/unresolved pages do not produce Book body blocks.
- Review hashes must match the current Wiki snapshot before compilation.
- Conflict content is visibly marked as disputed in rule-only output.
- `generated_only` is the first body policy; no manual body override exists.
- Failed or partial builds never update `CURRENT.json`.

## Release modes

`rule_only` is the safe baseline. LLM generation, partial-output budgets,
TutorialPath UI and full-corpus expansion are subsequent stages gated on a
successful human pilot. The first pilot uses 12 real Wiki pages in two
chapters and records source-permission limits in
`docs/reports/2026-09-06-unified-book-pilot.md`.

## Explicit non-goals

No claim graph, claim-level entailment, automatic conflict adjudication,
second search index, multi-Book registry, chapter lineage service, or copied
tutorial正文 is introduced by this specification.
