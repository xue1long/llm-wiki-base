# Code-review Fix Plan — Duplicate Refactor

**Baseline:** `main...HEAD`

**Findings addressed:** the review found missing seam tests, a CLI resolver contract risk, Python 3.12 overconstraint, and unrelated CI/environment/test-isolation scope.

## Task 1: Remove unrelated scope

Revert only the three commits that are unrelated to duplicate-logic refactoring:

- `da1c14a chore(dev): 固定开发环境检查基线`
- `2594dd9 test(project): 隔离测试项目与真实知识库`
- `11f0219 chore(dev): 增加任务范围变更检查`

Do not touch the refactor commits or user-owned uncommitted files. Verify the resulting diff contains no CI/environment/test-isolation/SOP changes.

## Task 2: Restore explicit CLI resolver compatibility

Add `src/cli_ext/project_resolve.py::resolve_cli_project(project_arg, *, with_paths=True, by_id_only=True)` so CLI error handling stays in the adapter layer. Keep `src/lib/project.py` pure. Pass the explicit resolution mode through to `resolve_project` and `resolve_ctx_only`; test both return shapes, both resolution modes, and `SystemExit(2)` with stderr output. Existing command wrappers remain thin adapters.

Add direct tests under `tests/test_lib/` and a focused CLI wrapper regression test. Do not alter command output or aliases.

## Task 3: Add direct seam tests

Add focused tests for:

- `src/utils/hashing.py` including empty, multi-chunk, `Path`, and read error behavior;
- `src/utils/extract/errors.py` plus PDF/Office format-specific adapters;
- `scripts/_common.py` formatting, flush, append, and Unicode behavior;
- dedup delegation and all cosine edge cases.

Reuse existing fixtures and stubs; no new dependency or broad fixture framework.

## Task 4: Final verification

Run focused tests, compile checks, `git diff --check`, re-index with codebase-memory-MCP, and the full suite. Record environment-only collection failures separately if they remain. Perform a final two-axis review against the original spec.
