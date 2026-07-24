# Environment Setup

How to get ruflo-kb's test suite to **722 / 722 passing** from a fresh Python
3.14 install on Windows. The story also covers the host's proxy quirks and
the test-conftest cascade that bites anyone who tries to run the suite on a
Python version newer than the project was last validated against.

> Last verified: 2026-07-23 on `C:\Python314\python.exe` (Python 3.14.3).

## 1. Baseline

| Item | Value |
|---|---|
| Python | **3.14.3** (`C:\Python314\python.exe`) |
| pytest | 9.1.1 |
| Platform | Windows 11 Pro, AMD64 |
| Working dir | `<repo-root>` (this checkout's root) |

The project also runs on Python 3.12 (the alternative interpreter installed at
`C:\Users\hp\AppData\Local\Programs\Python\Python312\python.exe`); the wheels
listed below are cp314-only, so for 3.12 you will need to re-download matching
wheels.

## 2. Install

### Quick path (online)

```powershell
# Important: clear the host's proxy env vars before pip — the local proxy at
# 127.0.0.1:7897 intercepts pip and resets the connection on slow downloads
# (it timed out at 11 kB/s on the 28 MB pyarrow wheel). Bypassing it makes
# pip talk to PyPI directly.
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy `
  C:\Python314\python.exe -m pip install -e ".[dev]"
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy `
  C:\Python314\python.exe -m pip install watchdog tavily-python pypdf
```

### Offline path (use the wheels shipped in this directory)

For the two heavy native packages (pyarrow 28 MB, lancedb 30 MB) pip over the
host's network is unreliable. The wheels live at
`docs/environment/wheels/` and are installable directly:

```powershell
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy `
  C:\Python314\python.exe -m pip install `
    docs/environment/wheels/pyarrow-25.0.0-cp314-cp314-win_amd64.whl `
    docs/environment/wheels/lancedb-0.27.1-cp39-abi3-win_amd64.whl
```

`lancedb` is published as `cp39-abi3-win_amd64` (Stable ABI), not as a
`cp314` wheel — the abi3 tag means it is compatible with Python 3.9+, so it
works on 3.14 too. The `cp314` literal only appears in the pyarrow wheel.

### Pin exact versions

For reproducible installs, use the locked set:

```powershell
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy `
  C:\Python314\python.exe -m pip install -r docs/environment/requirements-cp314.txt
```

## 3. Run the test suite

```powershell
cd "<repo-root>"
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy `
  PYTHONPATH=. C:\Python314\python.exe -m pytest --import-mode=importlib
```

Expected: `722 passed in ~25s`. Two flags matter:

- `--import-mode=importlib` — disambiguates same-named test files across
  directories (`test_paths.py`, `test_types.py`, `test_registry.py` all
  exist in more than one `tests/test_*/` directory; the default
  `prepend` mode collides on the cached `__pycache__`).
- `PYTHONPATH=.` — without it, `from src.xxx import ...` in the test
  files fails with `ModuleNotFoundError`.

## 4. Gotchas baked into this repo

The following test-infrastructure issues were diagnosed on 2026-07-23 and
fixed via new `conftest.py` files under `tests/`. They are documented here
because the underlying pattern is fragile: any new `tests/test_X/conftest.py`
that depends on `platformdirs`, `pyarrow`, `lancedb`, or `mcp` will need
the same "restore real module" treatment as long as the sibling
`tests/test_llm/`, `tests/test_server/`, `tests/test_wiki/` conftests
stub them.

### 4.1 Sibling-conftest pollution

Six test directories (`test_cli_ext`, `test_lib`, `test_llm`,
`test_pipeline`, `test_server`, `test_wiki`) install stubs for the heavy
optional dependencies via `sys.modules.setdefault("platformdirs", _stub)`
at conftest load time. `setdefault` is global to the pytest session, so
**any other test directory that needs the real module inherits the
stub**. Symptoms:

- `user_config_dir("ruflo-kb", "ruflo-kb")` returns `""` instead of a
  real path → `tests/test_project/test_paths.py::test_config_dir_returns_path`
  fails with an empty Path.
- `lancedb.connect()` returns `None` → `src.vector.store` cascades
  into `AttributeError: 'NoneType' object has no attribute 'create_table'`.
- `mcp.server` doesn't exist on the stub → `tests/test_mcp_server/`
  fails to import.

Fix: each affected test directory gets a local `conftest.py` that
re-imports the real module. Where the timing is delicate (an
alphabetically-later conftest re-stubs the module after this one
restores it) the restore must run inside `pytest_configure` rather
than at conftest-load time, e.g. `tests/test_searcher/conftest.py`.

### 4.2 Already-imported modules hold the stub

`src.project.paths` binds `user_config_dir` at import time:

```python
from platformdirs import user_config_dir
```

If the platformdirs stub is the active `platformdirs` module at the
moment `paths.py` is first imported, `paths.user_config_dir` is the
stub forever, even after `sys.modules["platformdirs"]` is fixed. The
test conftest has to re-bind the attribute on the already-imported
module:

```python
_paths.user_config_dir = platformdirs.user_config_dir
```

The same trick applies to `src.vector.store` (re-bind `pa`, `lancedb`)
and `tests/test_vector/conftest.py` does the same for the vector
store.

### 4.3 pytest-asyncio defaults to STRICT

`asyncio_mode = "auto"` is set in `pyproject.toml` so that `async def
test_*` functions run without an explicit `@pytest.mark.asyncio`
marker. The default `STRICT` mode (what `pytest-asyncio>=0.23` ships
with) raises "async def functions are not natively supported" for any
async test that forgot the marker — this bit 4 tests in
`tests/test_project/test_mutex.py` until the project-level config was
added.

### 4.4 src.* modules cached as broken

If `src.searcher.__init__` runs while `lancedb` is stubbed, the
`__init__` import chain fails partway through and `sys.modules["src.searcher"]`
ends up flagged as a partially-initialized package. Re-importing the
real `lancedb` afterwards is not enough — the next test that does
`from src.searcher.qa import generate_answer` still fails with
`ModuleNotFoundError: No module named 'src.searcher.qa'`. The fix
(applied in `tests/test_searcher/conftest.py::pytest_configure`) is
to drop the broken package from `sys.modules` before the real
lancedb is restored, so the test file's import triggers a clean
re-import of the whole chain.

## 5. What lives in this directory

| File | Purpose |
|---|---|
| `SETUP.md` | this document |
| `requirements-cp314.txt` | pinned versions for reproducible install |
| `wheels/pyarrow-25.0.0-cp314-cp314-win_amd64.whl` | pyarrow 25.0.0, cp314, win_amd64 (~28 MB) |
| `wheels/lancedb-0.27.1-cp39-abi3-win_amd64.whl` | lancedb 0.27.1, cp39-abi3, win_amd64 (~30 MB) |

`wheels/` is in `.gitignore` — the wheels are large and platform-specific;
they are kept in-tree as a convenience for this environment, but they
should not be committed. Use the URL list in `requirements-cp314.txt`'s
header comment to fetch fresh wheels for a different platform.
