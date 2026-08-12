# Code-review Fix Plan Audit — Round 2

1. If a revert encounters a dependency conflict, stop and preserve the unrelated commit rather than resolving unrelated code in this task.
2. If `by_id_only=False` resolves by path/name while `True` rejects it, assert each behavior instead of normalizing them.
3. If `ProjectNotFoundError` is raised, assert exactly stderr prefix and exit code 2; do not swallow the original cause.
4. If a test passes before implementation, it is not a regression test; run the new seam test in RED before changing production code.
5. If extractor tests use a real optional dependency, prefer existing monkeypatch stubs so collection remains deterministic.
6. If script tests import `_common` through two paths, verify both package and direct-script import modes.
7. Re-index after cleanup; zero graph callers alone is insufficient without `rg` symbol search.
8. Full-suite failures caused by missing optional packages or host registry permissions remain blockers to merge, not reasons to weaken production behavior.

**Gate:** implementation may proceed with compatibility-first changes only; no high-risk deletion is authorized.
