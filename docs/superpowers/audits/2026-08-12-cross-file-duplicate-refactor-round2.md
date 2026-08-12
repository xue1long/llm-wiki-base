# Plan Audit Round 2 — Failure and Pressure Simulation

**Scope:** the same implementation plan after Round 1 controls.

**Result:** PASS. The plan remains compatibility-first under the simulated failure cases below.

## Simulated cases

1. **Missing project / invalid ID / CJK path:** the CLI resolver continues to delegate to the existing canonical functions and keeps the command-level error conversion; tests cover both valid and missing inputs.
2. **Hash boundary and large file:** binary reads with the existing 64 KiB default preserve digest results across empty, exact-boundary, and multi-chunk files. No eager whole-file read is introduced.
3. **Missing or permission-denied file:** the helper does not invent a new exception policy; callers receive the same open/read failure as before.
4. **Cosine empty or mismatched vectors:** the wrapper preserves the private function's observed empty behavior while the canonical function retains its mismatch and zero-norm behavior. A failed edge test blocks migration.
5. **Encrypted PDF with warning or unknown exception:** PDF-specific warning handling remains in `pdf.py`; the classifier only handles the shared signal.
6. **Malformed Office package:** `PackageNotFoundError` and `BadZipFile` handling remains in `office.py`, so malformed files are not mislabeled as encrypted.
7. **Report directory absent / Unicode message:** the logging tests lock current behavior before extraction. The plan does not silently add directory creation or change report paths.
8. **Direct script execution:** the helper import is smoke-tested using the existing script invocation mode; failure blocks replacing local `_log`.
9. **Test monkeypatch and collection order:** focused tests run with the repository's importlib mode and conftest conventions. A collection failure is treated as a regression, not ignored as an environment issue.
10. **Partial migration rollback:** each task is one commit with focused tests. If a task fails, revert only that task's commit or restore its local wrapper; do not continue to deletion.
11. **Graph false negative:** static `rg` and module export inspection are mandatory secondary evidence. A graph zero alone never authorizes deletion.
12. **Server import regression:** because top-level project/extractor imports can affect runtime, run the documented import/smoke check when those paths change; no server behavior is otherwise modified.

## Residual risk

- **Medium:** codebase-memory may under-report dynamic imports or monkeypatches. Mitigation: retain wrappers for one migration cycle and require both graph and source search evidence.
- **Low:** script packaging differs between direct and imported execution. Mitigation: direct smoke checks and explicit `scripts/_common.py` import design.

## Gate decision

No simulated case requires a new architectural abstraction or broadening scope. Proceed with TDD implementation. High-risk deletion remains prohibited; only compatibility-preserving delegation is authorized until final graph verification.
