# novel-wiki-v2 Task 2 — fail-closed candidate slots

- Candidate ingest now performs slot-level validation at the formal
  generator→writer boundary: `FILLED` and `DECLARATIVE_ABSENCE` pass; `EMPTY`
  and `PLACEHOLDER` concepts are withheld with `NEEDS_HUMAN_REVIEW`, while the
  deterministic source page remains available.
- Rejected/empty candidates, source-ID mismatches, invalid evidence, reviewer
  rejections, and promotion failures now quarantine instead of taking the
  source-only path.
- The Task 1 heading-only regression calls `quality_gate.check_pages()`
  directly, so its `missing_required_content` rejection necessarily lives in
  that gate rather than generator/ingest alone.
- Verification: Task 2 focused suite `119 passed` (11 existing legacy-path
  deprecation warnings); candidate boundary compatibility suite `18 passed`.
