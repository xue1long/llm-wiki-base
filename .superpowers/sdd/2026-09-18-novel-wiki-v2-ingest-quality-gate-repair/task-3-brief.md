# Task 3 brief — semantic constraints and variant disposition

Read the main plan and the completed Task 1/2 reports before coding. Use Luna
for this task's implementation and review. Work in the current shared tree;
preserve unrelated changes and do not reset or push.

## Scope

Allowed production files:

- `src/pipeline/generator.py`
- `src/pipeline/wiki_rules_prompt.py`

Allowed tests:

- `tests/test_pipeline/test_generator_constraint.py`
- `tests/test_pipeline/test_generator.py`
- focused existing generator tests needed for compatibility

## Required behavior

1. Tighten the existing candidate-render prompt and shared wiki rules only; do
   not add a planner or new schema field.
2. For the representative outline source, the semantic variant title must not
   create a second page: exact duplicate ids/titles are deterministically
   deduplicated; an explicitly registered slug alias resolves to its canonical
   page; a merely similar title without proof remains `NEEDS_HUMAN_REVIEW` and
   is not written.
3. A subsection-level claim such as `提纲的重要性` must not become an
   independent concept unless the candidate has independent reusable evidence.
4. References may target only pages defined in the current response, existing
   index pages, or the source page; do not invent slugs. Valid taxonomy targets
   are virtual targets and are handled by Task 4.
5. Preserve Task 2 slot verdicts and fail-closed writer behavior.

## Verification

Run the focused generator/constraint tests and report changed files, test
commands/results, and any deliberate compatibility boundary in
`task-3-report.md`. Do not amend prior commits.
