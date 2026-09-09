# Book LLM republish hardening — 2026-09-09

## Root cause

The incident was both prompt-contract and architecture/observability related:
the provider returned a top-level JSON string array although the chapter
contract required an object with `sections`; the retry sent no correction
feedback; and the compiler collapsed a prior malformed response plus a later
budget exception into generic `E_LLM_REQUIRED_FOR_APPLY`.

## Fix

- `GeneratedChapter.failure_code` now preserves response-invalid, provider,
  and budget-exhausted causes while retaining attempt history.
- Retries are limited to model-correctable shape/truncation/validation
  failures and receive a fixed bounded contract hint. Provider and budget
  failures are terminal for that chapter.
- Publication manifests record actual call-site counts, mandatory calls,
  configured retry maximum, and retry reserve shortfall. Persisted outlines
  with insufficient mandatory budget are blocked before the first provider
  call; `CURRENT.json` remains unchanged.

## Verification

The focused Book suite passes with deterministic fake providers. Real
republishing must use the absolute `knowledge/novel-wiki` path, preview the
manifest budget first, obtain explicit approval for the cap, then run the
same cap with `--apply`.
