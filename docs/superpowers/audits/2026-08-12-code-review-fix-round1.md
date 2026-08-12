# Code-review Fix Plan Audit — Round 1

1. **Important — revert scope:** reverting the three named unrelated commits could conflict with later user work. Use `git show` first, revert only those exact commits, and preserve current uncommitted files.
2. **Important — CLI mode:** a hidden default change could affect path/CWD/last-project resolution. Make `by_id_only` explicit and test both values.
3. **Important — error contract:** moving or removing `SystemExit(2)` would break commands. Test stderr and exit status directly.
4. **Important — wrapper coverage:** existing tests may monkeypatch local wrappers and bypass the new seam. Add direct tests against the seam.
5. **Important — cosine semantics:** delegation must retain empty, mismatched, zero-norm, and normal vector results.
6. **Important — extraction branches:** shared classification must not absorb `BadZipFile`, `PackageNotFoundError`, or PDF warning mapping.
7. **Important — logging side effects:** test flush, exact timestamp shape, newline, report append, and Unicode.
8. **Important — Python support:** removing the 3.12-only guard must not weaken the documented 3.11+ requirement.
9. **Optimization — scope check:** do not add new environment tooling while repairing the refactor.

**Gate:** proceed to pressure simulation; all high-risk paths have concrete tests or rollback controls.
