# Reader-task Review Not Applicable — series gate blocks all candidates

**Date:** 2026-09-06
**Status:** not-applicable / blocked

## 1. Why this report exists

The 2026-09-06 book-series plan requires a human-reviewed reader-task
report for the first batch of staged chapters. The current
`knowledge/novel-wiki` baseline does not produce any chapter because:

* `evaluate_series_gate` returns `status=blocked`,
  `generation_mode=rule_only`, with `no_retained_candidate`;
* `build_from_wiki()` short-circuits to
  `{"status": "blocked", "reason_codes": ["E_SERIES_GATE_NO_RETAINED_CANDIDATE"]}`
  before any chapter or rubric record is built.

Per the plan, we must never use an LLM to manufacture reader tasks
when the baseline gate is blocked. Therefore this report formally
records the review as **not applicable** rather than producing a
fabricated or partial result.

## 2. Required reader-task fields and why each is unobservable today

| Field | Reason it is unobservable |
|---|---|
| `task_id` | `run_reader_tasks` requires a chapter directory emitted by `compile_book`. No chapter is emitted when the gate blocks. |
| `book_id` / `chapter_id` | Series gate returns no `proceed` candidate; no chapter ID exists. |
| `reader_goal` | `reader_promise` lives on the chapter record. The chapter record is not created. |
| `input_artifact` | `entry_requirements` lives on the chapter record. Not created. |
| `expected_output` | `exit_artifact` lives on the chapter record. Not created. |
| `actual_output` | No chapter body exists, so no actual output can be checked. |
| `next_chapter_consumes` | Without a chapter chain there is nothing to chain. |
| `evidence` | Without a chapter body there are no fact blocks to attach evidence to. |
| `reviewer` / `review_date` | None — no task to review. |
| `status` | recorded as **n/a**. |

## 3. Process for re-running this report

1. Re-run the rule-only baseline after pages 1-6 in
   `docs/reports/2026-09-06-book-series-pilot-not-applicable.md`
   are completed.
2. The series gate must report at least one `proceed` candidate.
3. `build_from_wiki --quality-gate rule --apply=false` must return
   `status=planned` instead of `blocked`.
4. Run the rubric-driven reader-task runner and capture per-chapter
   `ReaderTaskReport` records.
5. A human reviewer signs off each row.
6. Append the populated table to this document under a new dated
   section. Do **not** retroactively change the **not applicable**
   conclusion above.