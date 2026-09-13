# Task 2 report — CLI mode contract

## Changed files

- `src/cli.py`
  - Added mutually exclusive `--plan`, `--preview`, and `--apply` modes.
  - Defaults to `--plan` during the existing validation hook.
  - `--preview` and `--apply` normalize legacy flags to `use_llm=True` and `polish=True`.
  - Legacy `--use-llm` / `--polish` remain parseable only as compatibility inputs; a lone legacy LLM flag is rejected, while the legacy pair maps to preview.
  - Narrative mode now requires preview or apply.
- `src/cli_ext/book_cmd.py`
  - Converts the public mode to the existing compiler arguments.
  - Plan passes `use_llm=False`, `polish=False`, `apply=False`.
  - Preview passes `use_llm=True`, `polish=True`, `apply=False`.
  - Apply passes `use_llm=True`, `polish=True`, `apply=True`.
  - Keeps direct callers without `build_mode` compatible.
- `tests/test_cli_ext/test_book_build_from_wiki_modes.py`
  - Added focused parser and forwarding tests.

## Tests

Attempted:

```text
$env:PYTHONPATH='.'; python -m pytest --import-mode=importlib tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
```

Blocked: `python` is not available on PATH.

Attempted with the repository's documented uv path:

```text
$env:UV_CACHE_DIR='...\\.uv-cache-task2'; $env:PYTHONPATH='.'; uv run --offline python -m pytest --import-mode=importlib tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
```

Blocked: uv failed to query the Python interpreter with Windows `拒绝访问。 (os error 5)`.

`git diff --check` was also run; it reported pre-existing trailing whitespace in `src/ruflo_kb.egg-info/PKG-INFO`, not in the task files.

## Concerns

- Runtime pytest verification remains outstanding because no usable Python interpreter is accessible in this environment.
- Existing unrelated dirty changes in `src/cli.py` and `src/cli_ext/book_cmd.py` were preserved.
- No compiler or preflight files were changed.
