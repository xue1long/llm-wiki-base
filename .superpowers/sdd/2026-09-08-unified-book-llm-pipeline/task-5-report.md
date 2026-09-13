# Task 5 report — Project bootstrap and durable docs

## Scope

- Added the neutral project-init `book.rules.md` template.
- Added the unified Wiki-to-Book pipeline ADR and ADR index entry.
- Added focused project-init assertions for the template and policy non-authorization.
- Did not edit compiler or CLI mode files.
- Did not spawn subagents or commit.

## Checks

- `git diff --check -- src/cli_ext/project_cmd.py tests/test_cli_ext/test_cmd_project.py docs/adr/2026-09-08-unified-book-llm-pipeline.md docs/adr/INDEX.md .superpowers/sdd/2026-09-08-unified-book-llm-pipeline/task-5-report.md`
- `PYTHONPATH=. python -m pytest --import-mode=importlib tests/test_cli_ext/test_cmd_project.py -q`

## Concerns

- Existing projects still need an explicit, human-reviewed `book.rules.md`; this task does not migrate or infer their editorial intent.
- The generated template is intentionally neutral but non-empty; the LLM rules loader may therefore accept it until the project owner replaces the placeholder.
- The ADR remains `Proposed` until the complete pipeline is integrated and verified.
