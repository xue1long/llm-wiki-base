# CLI Dry-run Result — Blocked (no retained candidate)

**Date:** 2026-09-06
**Branch:** `codex/book-series-target`
**Project:** `knowledge/novel-wiki`
**Snapshot:** `61eb65b94d75d079d146c43cdcfc9a2891d39130c4c6cea289ed20e89d6ed610`
**Snapshot fingerprint:** `3ffe4234058a5507170dd04b36066e97a4c6cabdfb752da624b2cbbf5ab0b5df`

## 1. Inputs

Baseline file (already present at run time):

- `knowledge/novel-wiki/.index/book-series/baseline.json` — **exists**,
  parseable; `series_status=blocked`, `generation_mode=rule_only`,
  `block_reasons=['external_authorized','budget_cap','approver','no_retained_candidate']`,
  `retained_proceed=0`.

CLI invocation (rule-only, no `--apply`, no `--use-llm`, no
`--narrative`, no `--polish`):

```text
python -m src.cli book build-from-wiki \
    --project knowledge/novel-wiki \
    --output-dir book-wiki \
    --quality-gate rule
```

## 2. CLI stdout

```text
Wiki book: blocked
  output_dir=D:\5-Project\20260903\llm-wiki-base\knowledge\novel-wiki\book-wiki
  dry-run: nothing was published
```

## 3. CURRENT.json integrity (before vs after)

| Field | Before | After |
|---|---|---|
| `pointer_sha256` | `93a1b3516eba440274e7a5af8dd74153280b6ad27fb9f3e2ffce58f8c5185804` | identical |
| `pointer_content` | `{"version":"4e1229dae60241e3a5aeb323b14a123a","manifest_sha256":"762a865c..."}` | identical |
| `release_dirs` | `["4e1229dae60241e3a5aeb323b14a123a", "79780de66b0f47988ffa5cedecdee951"]` | identical |
| `mtime` | `2026-09-05 23:35:00` | unchanged |
| `pointer_unchanged` | — | **true** |
| `releases_unchanged` | — | **true** |

JSON report:

- `knowledge/novel-wiki/.index/book-series/cli-dryrun.json`

## 4. Why the build is blocked (no `proceed` candidate)

`build_from_wiki()` runs the rule-only series gate with
`external_authorized=True, budget_cap=1, approver='rule-only-dry-run'`
solely so the test can observe the gate result without depending on
external authorisation. The gate still returns `status=blocked`
because the real corpus has zero pages tagged with the default
`book-a / book-b / book-c` taxonomies (every real taxonomy is in
Chinese, e.g. `写作技法`, `小说结构`, `平台规则`).

| Decision count | value |
|---|---|
| `proceed` | **0** |
| `merge` | majority |
| `reference` | a few thin categories |
| `cancel` | the three default book keys |

Result:

```json
{
  "status": "blocked",
  "reason_codes": ["E_SERIES_GATE_NO_RETAINED_CANDIDATE"],
  "series_status": "blocked",
  "generation_mode": "rule_only",
  "block_reasons": ["external_authorized","budget_cap","approver","no_retained_candidate"]
}
```

## 5. What this means for the rest of Task 8

1. **Pilot is not applicable.** No `proceed` candidate exists, so
   `book build-from-wiki` cannot produce any chapter body — and the
   2026-09-06 plan explicitly forbids using an LLM to manufacture a
   chapter when the gate already failed closed.
   See `docs/reports/2026-09-06-book-series-pilot-not-applicable.md`.
2. **Human reader-task review is not applicable.** A rubric-driven
   reader task only exists once a chapter is compiled; no chapter
   exists today.
   See `docs/reports/2026-09-06-book-series-reader-task-not-applicable.md`.
3. **No LLM provider was invoked.** The series gate short-circuits
   the build before any `create_llm_provider(...)` call.
4. **No release directory or pointer was touched.** `CURRENT.json`
   and `.releases/` are byte-identical before and after the command.

## 6. Path forward (gating the next attempt)

| # | Required before re-attempting pilot | Owner |
|---|---|---|
| 1 | Map the real Chinese taxonomy labels to `writing-foundations` / `story-craft` / `revision-release` / `writing-reference` and re-run the baseline until at least one candidate returns `proceed`. | design owner |
| 2 | Resolve the 580 `cross_book_conflict` pages (taxonomy vs. relation target taxonomy). | editor |
| 3 | Resolve the 675 `isolated_relation` pages (relations pointing at page IDs that no longer exist). | editor |
| 4 | Freeze governance values (`external_authorized`, `budget_cap`, `approver`) in `docs/reports/2026-09-06-book-series-governance.md`. | approver |
| 5 | Re-run `book build-from-wiki --dry-run` and confirm `status=planned`. | gate owner |
| 6 | Schedule the first 3–5 chapter pilot only after steps 1-5 succeed. | reviewer |

Until steps 1-5 succeed the pilot and reader-task review stay
formally **not applicable**, the build remains at `blocked` +
`rule_only`, and **no full apply is permitted**.