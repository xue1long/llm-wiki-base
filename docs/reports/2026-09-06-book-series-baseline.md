# Book Series Baseline

Task 0 uses `scan_wiki_snapshot` output and deterministic taxonomy partitioning to produce `SeriesGateResult` before any outline or Provider call.

The gate records page type counts, duplicate pages/rate by non-empty `content_sha256`, page-level source coverage, structured relation count and parse rate, estimated characters, reader task candidates, and candidate-local `eligible_page_count`, `source_coverage`, `duplicate_rate`, `estimated_chars`, `reader_task_count`, `closure_status`, and `decision`.

Candidate decisions are rule-only. Any candidate below 20 pages, below 0.80 source coverage, or without concept/entity/synthesis (or their structural aliases) is not `proceed`. Missing external authorization, budget cap, or approver sets `status=blocked` and `generation_mode=rule_only`.

The snapshot fingerprint includes the snapshot ID, reader profile, and governance configuration. The baseline contains no absolute paths or credentials.
