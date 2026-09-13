# Task 5 — Project bootstrap and durable docs

Implement the project rule template and documentation only.

Write set: `src/cli_ext/project_cmd.py`, `docs/adr/2026-09-08-unified-book-llm-pipeline.md`, `docs/adr/INDEX.md`, focused project-init/docs tests if needed.

Requirements:
- New project initialization creates a neutral `book.rules.md` template with no guessed project style and no authorization.
- Do not auto-authorize `.llm-wiki/policy.json`.
- Document that existing projects need explicit migration and that this plan only covers `book build-from-wiki`, not legacy `book build`.
- Preserve unrelated dirty changes. Follow TDD where code changes, and report exact checks.
