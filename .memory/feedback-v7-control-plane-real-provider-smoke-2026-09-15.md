# V7 control-plane — 真实 MiniMax-M3 Provider smoke（2026-09-15）

## Outcome

Ran two `extract_full.py --apply` invocations against a single smoke raw
under a temporary root (`E:\tmp-v8-smoke\`) using a real external Provider
(`MiniMax-M3` via openai-compatible endpoint). Both runs exited 0 and the
five-way V7 control-plane contract held end-to-end: raw MD5 unchanged,
checkpoint v2 written, writer wrote the concept page, second run skipped
the source by md5, queue did not grow, summary fields (`written/blocked/
failed/incomplete/skipped/generated_pages`) matched the actual on-disk
state.

## Durable rules (added)

- `extract_full.py --provider minimax` works without `~/.config/ruflo-kb/
  llm-providers.json` because `src/llm/registry.py:396` derives the
  `minimax` provider from `$MINIMAX_API_KEY` env. Same pattern covers
  OpenAI / Anthropic / Ollama.
- DSH `pwsh` calls are stateless (no env inheritance between invocations).
  Use a dotenv wrapper subprocess script with `env=os.environ.copy()` to
  feed `.env` into the child reliably; `scripts/ingest_novel_wiki_d.py:
  37-48` is the established pattern.
- The `--provider` flag and `--apply` flag on `extract_full.py` were wired
  in commit `34976b6a` (runtime source-control-plane-hardening) per its
  `--help`. `--apply` requires `$V7_ALLOW_APPLY=1` (fail-closed at
  Writer first line).
- Stage-internal LLM retry is logged as `LLM call failed (attempt 1/3):
  LLM response was truncated by max_tokens` and does NOT count toward
  source-level `attempts` (which remains `1` in the checkpoint). This
  matches the durable rule recorded after Wave 4.

## Verification

- raw md5 src vs dst: `25ab715bee91014f4f6564e1397999cc` == same.
- apply1 summary: `selected=1, processed=1, written=1, blocked=0,
  failed=0, incomplete=0, skipped=0, generated_pages=1, errors=0,
  pages=1` (37.69s elapsed).
- apply2 summary: `selected=1, processed=0, written=0, blocked=0,
  failed=0, incomplete=0, skipped=1, generated_pages=0, errors=0,
  pages=1` (1.03s elapsed — no LLM call, md5 skip).
- checkpoint: `version=2, schema_version=2, sources=1`,
  source row `status=written, legacy_status=ok, md5=25ab715b...,
  attempts=1, dry_run=false, written_page_ids=[chuangku-women-
  romance-lecture]`.
- wiki page: `E:\tmp-v8-smoke\wiki\concepts\chuangku-women-romance-
  lecture.md` (3130 bytes, content present: definition / characteristics
  / examples sections populated by the LLM).
- reviews_queue.json: not created (written source has no blocked/failed
  outcomes to enqueue — V7 control-plane contract).

## Out of scope (still)

- 4918 / 1362 source full apply not executed.
- `_legacy.py` placeholder untouched (Wave 0 decision still binding).
- Production raw under `knowledge/novel-wiki/` not touched (md5 is the
  physical proof).
- No push performed; awaiting explicit user confirmation.
- `~/.config/ruflo-kb/llm-providers.json` not written (env-derived
  provider suffices).

## Artifacts

Archived in
`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/
wave5/v8-pilot/`:
- `apply1.json`, `apply1.md`
- `apply2.json`, `apply2.md`
- `v7_full_checkpoint.json`
- `chuangku-women-romance-lecture.md`
- `runner.py`, `runner.log`

Progress ledger updated with a `Wave 5 — 真实 Provider (MiniMax-M3) 单源
smoke` section.