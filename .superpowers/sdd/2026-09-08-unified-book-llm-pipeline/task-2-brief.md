# Task 2 — CLI mode contract

Implement only public mode parsing for `book build-from-wiki`.

Write set: `src/cli.py`, `src/cli_ext/book_cmd.py`, focused CLI tests only.

Requirements:
- Add mutually exclusive `--plan`, `--preview`, `--apply`; default is `--plan`.
- Plan does not request LLM; preview and apply request LLM body polishing.
- Reject conflicting combinations.
- Keep old flags parseable only as compatibility inputs; never allow a formal mode with outline-only LLM.
- Do not implement compiler behavior or edit compiler/preflight files.
- Preserve unrelated dirty changes. Follow TDD and report exact tests.
