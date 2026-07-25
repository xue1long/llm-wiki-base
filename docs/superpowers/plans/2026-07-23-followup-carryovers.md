# Followup Carryovers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Address the 8 deferred carryovers + 1 pre-existing test isolation quirk from the 2026-07-23 full-audit-fix merge (`e0b934e`).

**Architecture:** Six small focused tasks on a single feature branch `fix/2026-07-23-followup-carryovers` from `master` HEAD. Each task = one commit. Sequential execution (small tasks; no parallel conflicts).

**Tech Stack:** Python 3.11+, pytest, dataclass, asyncio.

**Global Constraints (apply to every task):**

- Python 3.11+; test command: `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy PYTHONPATH=. python -m pytest --import-mode=importlib`
- All file writes through `src.lib.write_hooks.safe_write` — never raw `Path.write_text` / `os.unlink`
- Wiki path access via `WikiPaths(ctx.path)` — never `ctx.paths`
- Each task = one commit; commit prefix follows repo convention
- After each task, dispatch a code-review subagent; fix Critical/Important findings before the next task
- The merge of `fix/2026-07-23-full-audit` (`e0b934e`) is the base — no regression to its 676 passing tests

**Out of scope (deferred to separate plan):**
- `__pycache__/*.pyc` tracked files — project convention; bulk cleanup is unrelated to carryovers

---

## File Structure

```
src/
├── agent/runtime.py                  (F1: remove dead isinstance shim)
├── llm/
│   ├── openai_provider.py            (F1: remove redundant self.client)
│   ├── ollama_provider.py            (F1: consolidate embedding alias)
│   ├── types.py                      (F4: docstring fix)
│   └── registry.py                   (F5: env-var persistence fix)
├── searcher/hybrid_search.py         (F2: exception classification)
├── vector/store.py                   (F3: init_vector_store(db_path) cleanup)
tests/
└── test_queue/test_queue_retry_liveness.py   (F6: setup/teardown to clear kb-queue.json)
```

Each task's deliverable is one commit on `fix/2026-07-23-followup-carryovers`. Tests must pass at the end of each task: `PYTHONPATH=. pytest tests/<new-or-modified-file> -v`.

---

## Task F1: T3 dead code + redundant assignment cleanup

**Files:**
- Modify: `src/agent/runtime.py:477-484` (remove dead `isinstance(response, dict)` compatibility shim)
- Modify: `src/llm/openai_provider.py:49-50` (remove redundant `self.client = client` assignment)
- Modify: `src/llm/ollama_provider.py:128-135` (consolidate `embedding()` alias — rename to `embed` or remove the alias)
- Test: `tests/test_llm/test_dead_code_cleanup.py` (verify callers compile after removal)

**Interfaces:**
- Consumes: existing callers — search for `isinstance(..., dict)` in `agent/runtime.py`; `self.client` references in `openai_provider.py`; `embedding(` references in `ollama_provider.py`
- Produces: clean code; LLMResponse dataclass is the only return type; `embed` is the canonical method name

- [ ] **Step 1: Write failing tests** — verify each removal site: no callers remain; `LLMResponse` is the canonical return; `embed()` (not `embedding()`) is the canonical method

- [ ] **Step 2: Run tests, verify FAIL**

- [ ] **Step 3: Implement removals**

```python
# src/agent/runtime.py — delete the isinstance(response, dict) shim block
# (lines 477-484 — preserve the LLMResponse branch)

# src/llm/openai_provider.py — remove line `self.client = client`
# (the OpenAI client is set elsewhere; verify self._client or self._sdk is used)

# src/llm/ollama_provider.py — if embedding() is just an alias for embed(),
# remove the alias. Otherwise rename the more-used name to the canonical one.
```

- [ ] **Step 4: Run tests, verify PASS** — 676 existing tests still pass + new tests pass

- [ ] **Step 5: Commit**

```bash
git add src/agent/runtime.py src/llm/openai_provider.py src/llm/ollama_provider.py \
        tests/test_llm/test_dead_code_cleanup.py
git commit -m "fix(llm+agent): remove T3 dead isinstance shim, redundant self.client, embedding alias"
```

---

## Task F2: hybrid_search exception classification (no more silent swallow)

**Files:**
- Modify: `src/searcher/hybrid_search.py:100-123`
- Test: `tests/test_searcher/test_exception_classification.py` (verify exception class is logged, not swallowed)

**Interfaces:**
- The exception handler should classify the failure (e.g. `EmbedProviderError`, `TimeoutError`, `RuntimeError`) and log the class name + a brief reason. Keyword-only fallback remains as the final safety net, but operators see the failure mode.

- [ ] **Step 1: Write failing tests** — `caplog` capture; assert log record contains the exception class name; assert keyword fallback still works

- [ ] **Step 2: Run tests, verify FAIL**

- [ ] **Step 3: Implement** — add `log.warning("hybrid_search: semantic retrieval failed (%s: %s); falling back to keyword-only", type(e).__name__, str(e)[:200])` in the `except` block

- [ ] **Step 4: Run tests, verify PASS**

- [ ] **Step 5: Commit**

```bash
git add src/searcher/hybrid_search.py tests/test_searcher/test_exception_classification.py
git commit -m "fix(search): classify hybrid_search exception (log class+reason) instead of silent swallow"
```

---

## Task F3: vector store `init_vector_store(db_path)` cleanup

**Files:**
- Modify: `src/vector/store.py:77-99` (replace parent-walking heuristic with explicit `WikiPaths` parameter; remove `init_vector_store(db_path)` parent-walking)
- Update callers (per audit context: search for `init_vector_store(` and migrate to `init_vector_store_for_paths`)
- Test: `tests/test_vector/test_store_init.py` (already covers `init_vector_store_for_paths`; add coverage for legacy deprecation path)

**Interfaces:**
- Drop `init_vector_store(db_path: str)` in favor of explicit `init_vector_store_for_paths(paths: WikiPaths)`
- If callers exist that still use the legacy form, migrate them or raise `NotImplementedError` with a migration message

- [ ] **Step 1: Write tests** — confirm `init_vector_store_for_paths(WikiPaths(...))` is the only public init; legacy form either removed or raises

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — search for all `init_vector_store(` callers; migrate or update

- [ ] **Step 4: Run, verify PASS** — 676 + new tests pass

- [ ] **Step 5: Commit**

```bash
git add src/vector/store.py tests/test_vector/test_store_init.py
git commit -m "fix(vector): drop legacy init_vector_store(db_path) parent-walking; require WikiPaths"
```

---

## Task F4: T10 docstring drift fix

**Files:**
- Modify: `src/llm/types.py:44-48`

**Interfaces:**
- Docstring says "shorter than 4" but code uses `< 5` (correct). Fix the docstring.

- [ ] **Step 1: No test needed** — trivial docstring fix

- [ ] **Step 2: Apply edit**

```python
# src/llm/types.py:44-48
# Before:
#     """Mask api_key for redacted serialization.
#     Keys shorter than 4 chars are masked as "***".
#     """
# After:
    """Mask api_key for redacted serialization.
    Keys of length < 5 are masked as "***" to avoid leaking
    the entire key when it's only 4 chars (last-4 = full key).
    """
```

- [ ] **Step 3: Commit**

```bash
git add src/llm/types.py
git commit -m "fix(llm): docstring drift in to_dict redact (shorter than 4 → < 5)"
```

---

## Task F5: T10 env-var key persistence fix

**Files:**
- Modify: `src/llm/registry.py:212-228` (`_default_providers` materializes env-var keys; first upsert persists them unredacted)
- Test: `tests/test_llm/test_registry_env_persistence.py` (verify env-var keys are NOT persisted to disk on first upsert)

**Interfaces:**
- When `_default_providers` reads `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` from env, the resulting `ProviderConfig` must NOT be persisted to disk (env-sourced keys are not "owned" by the registry)
- Either:
  - Add `sourced_from_env: bool = False` field to `ProviderConfig`; `Registry.save()` skips env-sourced entries
  - Or use `keyring`/`SecretService` for persistence and only persist refs
  - Or strip api_key from the saved JSON when env-sourced

- [ ] **Step 1: Write failing tests** — set `OPENAI_API_KEY` in env, trigger first upsert, assert the registry JSON file does NOT contain the literal key value

- [ ] **Step 2: Run tests, verify FAIL**

- [ ] **Step 3: Implement** — pick the cleanest of the three options; document the choice in the commit message

- [ ] **Step 4: Run, verify PASS** — 676 + new tests pass

- [ ] **Step 5: Commit**

```bash
git add src/llm/registry.py tests/test_llm/test_registry_env_persistence.py
git commit -m "fix(llm): registry does not persist env-sourced API keys (security)"
```

---

## Task F6: test_queue_retry_liveness flake fix

**Files:**
- Modify: `tests/test_queue/test_queue_retry_liveness.py` (add setup_function / teardown_function that clears `.kb-queue.json` and resets module state)
- Test: `tests/test_queue/test_retry_liveness_isolation.py` (verify running test_queue_retry_liveness.py twice in a row produces no contamination)

**Interfaces:**
- The test file's `setup_function` should call `__reset_for_testing()` (if available) AND `Path(".kb-queue.json").unlink(missing_ok=True)` before each test

- [ ] **Step 1: Write the isolation test** — run test_queue_retry_liveness.py twice consecutively; assert second run also passes

- [ ] **Step 2: Run, verify FAIL** (without the setup/teardown fix)

- [ ] **Step 3: Implement** — add `setup_function(_): __reset_for_testing(); Path(".kb-queue.json").unlink(missing_ok=True)` at the top of test_queue_retry_liveness.py

- [ ] **Step 4: Run, verify PASS** — and run the full suite twice to confirm no contamination

- [ ] **Step 5: Commit**

```bash
git add tests/test_queue/test_queue_retry_liveness.py tests/test_queue/test_retry_liveness_isolation.py
git commit -m "test(queue): setup/teardown clears .kb-queue.json to fix retry_liveness flake"
```

---

## Self-Review Checklist

1. **Spec coverage:** Each deferred carryover and the pre-existing quirk has a task. ✓
2. **No placeholders:** All code blocks are concrete; TDD per task. ✓
3. **Type consistency:** No cross-task symbol changes. ✓
4. **Dependencies:** F4 trivially precedes F5 (both touch `src/llm/`); sequential execution is fine. ✓
5. **Branch isolation:** All work on `fix/2026-07-23-followup-carryovers`; merge to master via PR after all 6 tasks. ✓

---

## Execution Order

1 → 2 → 3 → 4 → 5 → 6 (sequential; no cross-task dependencies; small tasks)

Estimated total time: 1-2 hours of subagent work.

After all 6 tasks land and tests are green, dispatch one final review over the 6 new commits and offer merge to master.
