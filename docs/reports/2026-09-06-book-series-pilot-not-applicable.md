# Pilot Not Applicable — book-series publish gate blocks all candidates

**Date:** 2026-09-06
**Branch:** `codex/book-series-target`
**Project:** `knowledge/novel-wiki` (`id=f3f51582-06d8-48ed-8d2a-759e514fa539`, schema_version=v2.0)
**Snapshot:** `61eb65b94d75d079d146c43cdcfc9a2891d39130c4c6cea289ed20e89d6ed610`
**Snapshot fingerprint:** `3ffe4234058a5507170dd04b36066e97a4c6cabdfb752da624b2cbbf5ab0b5df`

## 1. Conclusion

The Task 8 multi-book pilot **is not applicable** in this baseline. The
rule-only series gate downgrades every candidate (`book-a`, `book-b`,
`book-c`) to `cancel` and assigns zero pages to a primary book. No
candidate proceeds; the series is `blocked`. Per the 2026-09-06
remediation contract, when the baseline cannot retain three books we
must auto-merge/downgrade/cancel and **must not call an LLM to fill
the gap**. Therefore no narrative, encyclopedic, or pilot chapters
are produced.

## 3. Evidence — rule-only baseline (`docs/reports/2026-09-06-book-series-baseline-live.json` + `knowledge/novel-wiki/.index/book-series/baseline.json`)

```
series_status        = blocked
generation_mode      = rule_only
block_reasons        = ['external_authorized', 'budget_cap',
                        'approver', 'no_retained_candidate']
total_pages          = 1255
page_type_counts     = [['concept', 924], ['entity', 316], ['synthesis', 15]]
source_coverage      = 1.000
duplicate_pages      = 0
relation_count       = 8632
relation_parse_rate  = 0.623
relation_unresolved  = 3254
estimated_chars      = 891958
candidates           = book-a/b/c all `cancel`
assignment_metrics   = assigned_pages=0, ledger_pages=1255,
                       conflict_pages=580, isolated_relations=6766
ledger_reasons       = cross_book_conflict=580, isolated_relation=675
```

## 4. CLI dry-run proof (`knowledge/novel-wiki/.index/book-series/cli-dryrun.json`)

Command (no `--apply`, no `--use-llm`, no `--narrative`, no `--polish`):

```text
$ python -m src.cli book build-from-wiki \
    --project knowledge/novel-wiki \
    --output-dir book-wiki \
    --quality-gate rule
Wiki book: blocked
  output_dir=D:\5-Project\20260903\llm-wiki-base\knowledge\novel-wiki\book-wiki
  dry-run: nothing was published
```

Result:

- `rc = 1` (the `--book build-from-wiki` handler maps `blocked` to exit 1, expected).
- `status = blocked`
- `pointer_unchanged = true` — `book-wiki/CURRENT.json` sha `93a1b3516eba4402...` before and after.
- `releases_unchanged = true` — `.releases/` directory listing unchanged.
- `CURRENT.json` mtime remained at `2026-09-05 23:35:00`, contents
  `{"version":"4e1229dae60241e3a5aeb323b14a123a","manifest_sha256":"762a86..."}`.

## 5. Why no reader-task review either

The reader-task rubric exists only after a book has been built.
Per the contract:

* reader_promise, exit_artifact, entry_requirements, content_roles
  live on the **chapter** record;
* chapters are emitted by `compile_book` only after the series gate
  allows the build to proceed.

Because the gate rejects every candidate at the gate check (no
retained candidate), no chapter is compiled, no rubric is bound,
and no reader task can be evaluated. Reporting "n/a" is the
correct outcome — the remediation plan explicitly forbids faking
review by calling an LLM to manufacture reader artefacts when the
gate already failed closed.

## 6. Required next actions before re-attempting the pilot

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Decide whether the three-book series model fits the novel-wiki corpus. The current page distribution puts everything under the **Chinese taxonomy labels** (写作技法/小说结构/平台规则/etc.); mapping these onto `writing-foundations/story-craft/revision-release/writing-reference` is required. | design owner | not started |
| 2 | Resolve the 580 `cross_book_conflict` pages (pages whose declared taxonomy disagrees with their relations target's taxonomy). | editor | not started |
| 3 | Resolve the 675 `isolated_relation` pages (relations pointing at page IDs that no longer exist). | editor | not started |
| 4 | Re-run `evaluate_series_gate` after (1)-(3) and confirm at least one candidate returns `proceed`. | gate owner | not started |
| 5 | Set governance fields (`external_authorized`, `budget_cap`, `approver`) and freeze them in `docs/reports/2026-09-06-book-series-governance.md`. | approver | not started |
| 6 | Re-run the rule-only baseline; only then may the pilot be scheduled. | gate owner | not started |

Until all six actions land, the pilot stays not applicable and the
release stays at `blocked` + `rule_only`. No LLM call may be issued.