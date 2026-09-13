# Task 5 report — deterministic rollout verification

Status: complete.

- Full command: `uv run --offline pytest tests/test_kc/ tests/test_cli_ext/test_book_build_from_wiki.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q`
- Result: `836 passed in 95.61s`.
- Provider-free promotion drill passed: a provider that raises was never
  called; the exact preview release became CURRENT; stale snapshots were
  rejected without creating CURRENT.
- No real MiniMax call was made during implementation.
- `graphify update .` was attempted for the repository rule; the Windows
  graph update did not finish within the bounded wait and was interrupted.
