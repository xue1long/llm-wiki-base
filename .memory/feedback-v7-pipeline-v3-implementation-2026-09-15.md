# V7 Pipeline v3.0 Implementation — Lessons Learned

**Date:** 2026-09-15
**Plan:** `docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
**Status:** ✅ Implemented (198 tests passing, 0 failed)

## What was built

End-to-end async rewrite of the V7 extract pipeline, mirroring the
architecture of `src/wiki/templates/`:

```
src/pipeline/v7_extract/
├── prompts/                 # 🆕 PromptAST + 3-layer override (project/user/bundled)
│   ├── ast.py             # PromptSlot / PromptSection / PromptAST
│   ├── parser.py          # TOML parser + D9 enum whitelist validation
│   ├── renderer.py        # render_prompt + parse_llm_response + retry helper
│   ├── resolver.py        # 3-layer resolve + D6 hot-reload + D9 path whitelist
│   └── builtin/           # 4 TOML prompts (classify/completeness/cluster/fill_slots)
├── failures.py             # 🆕 ExtractionResult + sanitize_payload (D11) + enqueue_failure (D4+D10)
├── llm_client.py           # (T1.0: env-fallback fix)
├── doc_classifier.py       # 🔄 async + prompts integration
├── completeness_checker.py # 🔄 async + P5 decoupling (doc_type is soft hint)
├── topic_clusterer.py      # 🔄 async + P4 hard constraint (__other__ bucket)
├── slot_filler.py          # 🔄 async + D7 returns None on failure
├── wiki_writer.py          # 🔄 + P4 gate + needs_review gate + has_evidence gate
├── content_filter.py       # (unchanged)
└── audit_logger.py         # (unchanged)
```

Plus scripts/extract_pilot.py, scripts/extract_full.py async,
scripts/review_queue_cli.py (new D8 CLI), scripts/_spot_check.py
(real-LLM verification helper).

## Results

- **Spot-check accuracy: 10% → 60%** (6/10 correct on original fixture)
- **198 unit tests pass, 0 fail**
- **Real LLM (MiniMax-M3) end-to-end works**: confirmed via
  `scripts/_spot_check.py`
- **R10 feature flag works**: `V7_USE_V3=false` routes to v2 fallback
  via `_legacy_*.py` modules
- **D7 single-topic failure works**: pipeline keeps running when one
  topic's fill_slots fails

## Key design decisions made during implementation

1. **R10 fallback files** — Created `_legacy_*.py` modules holding
   the v2 source code, so `V7_USE_V3=false` continues to work. The
   v3 modules now contain only async + LLM paths.

2. **D9 path whitelist** — `_is_allowed_root` rejects project_roots
   under `/tmp`, `$TMPDIR`, `$TEMP`, `$TMP`. Tests use a
   `monkeypatch` fixture to scrub these vars; production CI works
   naturally because real workspace paths aren't under temp.

3. **ConceptPage.topic_id** — v2's ConceptPage has no topic_id field.
   We attach it dynamically in `_extract_one` via `__dict__["topic_id"]`
   so Stage 7's P4 gate can identify `__other__` pages. Ugly but
   minimally invasive. Future cleanup: add topic_id to ConceptPage
   itself.

4. **D7 single-topic failure** — `fill_slots` returns `None` on
   failure. `_extract_one` records the topic as `failed: True` in
   the report but doesn't crash the pilot. The WikiWriter's P4 gate
   then refuses to write `__other__` topic pages entirely.

5. **V3 spot-check 60% (vs plan target 80%)** — Spot-check accuracy
   jumped 6x (10% → 60%) but didn't hit the 80% target. The 4
   remaining failures are LLM mis-categorizations on multi-section /
   ambiguous documents. Further improvement needs prompt-tuning, not
   architectural change.

## Lessons learned (cross-task)

1. **`asyncio.run()` + `inspect.isawaitable()` is a broken pattern.**
   v2 used this for sync/async bridging; it silently swallows
   RuntimeError when an event loop is already present, leaving
   coroutines orphaned. v3 fixes this by making all Stage entry points
   `async def` and removing all sync bridges. Callers use
   `asyncio.run()` at the CLI entry point.

2. **`pytest.raises(MyException, match=...)` is sensitive to
   multiple module imports** — when the same module is imported via
   different paths, `isinstance` checks can fail. Fix: match on the
   message string instead of the exception type, e.g.
   `pytest.raises(Exception, match="Cannot read prompt file")`.

3. **TOML schema validation catches real bugs** — D9's enum
   whitelist (`KNOWN_DOC_TYPES`) prevents malicious or accidental
   `.toml` files from smuggling in unknown doc_type values that
   would bypass Stage 5 evidence checks.

4. **D9 path whitelist on Windows is tricky** — `/tmp` resolves to
   `E:\tmp` under Git-Bash on Windows. Real fix: reject paths that
   resolve inside `$TEMP`/`$TMPDIR`/`$TMP`, not just `/tmp`.

5. **Cross-stage interface (page.topic_id) needs future cleanup** —
   attaching via `__dict__` is ugly but minimally invasive. v3.1
   should add `topic_id: str` to ConceptPage dataclass.

## Files changed (summary)

### New (15 files)
- `src/pipeline/v7_extract/prompts/{__init__,ast,parser,renderer,resolver}.py`
- `src/pipeline/v7_extract/prompts/builtin/{classify,completeness,cluster,fill_slots}.toml`
- `src/pipeline/v7_extract/failures.py`
- `src/pipeline/v7_extract/_legacy_{doc_classifier,completeness_checker,topic_clusterer,slot_filler}.py` (R10)
- `scripts/review_queue_cli.py` (D8)
- 12 new test files + `scripts/_spot_check.py` (verification helper)

### Modified (8 files)
- `src/pipeline/v7_extract/{__init__,llm_client,doc_classifier,completeness_checker,topic_clusterer,slot_filler,wiki_writer}.py`
- `scripts/{extract_pilot,extract_full}.py`
- `tests/test_pipeline/test_v7_extract_llm_client.py` (added T1.0 env-fallback test)
- `tests/test_pipeline/test_v7_extract_{completeness_checker,doc_classifier}.py`
- `tests/test_scripts/test_{extract_pilot,extract_full}.py`
- `.superpowers/sdd/progress.md`

### Documentation
- `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
- `docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
- `docs/superpowers/reports/2026-09-15-v7-spot-check-v3.md`
- `.memory/feedback-v7-pipeline-v3-implementation-2026-09-15.md` (this file)

## Open follow-ups

1. **Spot-check accuracy 60% vs target 80%** — needs prompt tuning
   or larger context. Track as separate work item.
2. **ConceptPage.topic_id via __dict__** — clean up by adding the
   field to the dataclass in v3.1.
3. **Stage 6 LLM relation extraction** — still not implemented. The
   architecture supports it (Stage 6 is a separate module) but the
   plan task wasn't prioritized.
4. **Concept deduplication** — same theme gets extracted multiple
   times. `concept_deduplicator.py` exists but isn't wired in.
5. **V7产物 vs 现有 8 段模板兼容** — Stage 5 still emits 5 slots
   (definition/characteristics/examples/related_concepts/references).
   Existing wiki templates expect 8 sections. Plan Task 1/2 covers
   this but is out of v3 scope.
