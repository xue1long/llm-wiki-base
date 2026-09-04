# 2026-09-04 risk-remediation Task 0 inventory

Status: passed — baseline ready for implementation

## Baseline

| kind | path:line | current behavior | proposed action | compatibility risk | test gate |
|---|---|---|---|---|---|
| git | repository HEAD | `361273eee03e95b96ae523bf3bcf14b6f7566324` (`361273ee fix(batch): V5 datetime 序列化回归`) | Preserve as implementation base | None | Record again before first code task |
| dirty state | repository root | `.memory/MEMORY.md`, `src/pipeline/wiki_rules_prompt.py`, two architecture artifacts, and two risk-remediation plan files are dirty/untracked | Preserve all unrelated changes | Accidental staging/rollback | `git status --short` before every task |
| test baseline | repository root | Bundled Python 3.12.14 exists at `C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; project dev dependencies are installed. Tests require workspace-local `TEMP/TMP` and isolated `USERPROFILE/HOME/APPDATA/LOCALAPPDATA` because the host user directories deny access. | Reuse this explicit runtime and isolated test environment for subsequent gates | Running with inherited host paths produces permission-only noise | `3716 passed, 45 warnings` with `--import-mode=importlib` |
| time | 5 production definitions | `src/maintenance/cache_cleanup.py`, `src/project/context.py`, `src/project/identity.py`, `src/server/ingest_tracker.py`, `src/wiki/features/cascade_delete.py` define `_now_ms` | Extract only after caller inventory is reviewed | Timestamp unit/serialization regression | Dedicated time tests plus full suite |
| hash | 32 source/script files contain hashlib calls | Calls include full digests and different truncation lengths and purposes | Keep separate unless algorithm, input, normalization, length and error behavior are identical | Persisted ID/cache/integrity compatibility break | Post-change caller inventory diff |
| retry | `src/pipeline/retry.py` already owns async LLM retry; queue and worker loops use bounded `for range` loops | Do not migrate queue advance or slot-filling loops; only extract proven sync exception retry | Changed throughput or exception semantics | Existing retry tests plus caller-specific tests |
| test stubs | 19 `tests/**/conftest.py` files write `sys.modules` | Start with `tests/test_lib/conftest.py`, then fixed A–D batches from the plan | Import-cache leakage and collection-order failures | Snapshot/restore and subprocess tests |
| server globals | `src/server/app.py` lifespan reads discovery paths, provider registry, embedding state and CWD/home-derived paths | Isolate project root, CWD, HOME/config/cache, registry, singleton and network probes | User config mutation or network calls during tests | Lifespan test asserts zero network calls and state restoration |
| hook | `.git/hooks/pre-commit` is absent; `AGENTS.md` and `CLAUDE.md` bodies currently differ | Fix sync rule and test installer against explicit temporary target; install locally only | Immediate commit blocking or unrelated file changes | Temporary-directory installer tests |
| CI | `.github/workflows/quality.yml` runs Python 3.12 only; `pyproject.toml` lacks `pytest-cov` | Add clean-install coverage and required 3.11–3.13 matrix after baseline | False green/false red CI | Clean install, concrete baseline-derived threshold |

## Commands and results

```text
git rev-parse HEAD
361273eee03e95b96ae523bf3bcf14b6f7566324

rg -n "^def _now_ms" src
5 definitions

hashlib files in src/scripts
32 files

conftests containing sys.modules writes
19 files

C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install --no-build-isolation -e ".[dev]"
PASS: project dev dependencies installed (including pytest, pytest-asyncio, pytest-cov, ruff, mypy).

C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest --import-mode=importlib --collect-only -q
PASS: 3716 tests collected.

C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest --import-mode=importlib -q
PASS: 3716 passed, 45 warnings in 444.07s (7:24), using workspace-local temp and isolated user/config directories.

The inherited-host-path run is not a code baseline: it produced 1950 passed,
1762 permission errors, and 8 failed tests because pytest and project code could
not access the host temp/config directories. The same affected tests passed in
the isolated rerun; no unexplained project failure remains.
```

## Decision

Task 0 passes. The available Python 3.12.14 runtime has the project dev
dependencies, collection is stable at 3716 tests, and the isolated full baseline
is green. The 45 warnings are existing dependency/deprecation warnings and are
not introduced by this remediation. No unrelated dirty file was modified.
