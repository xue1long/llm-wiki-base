# Final Minor Carryovers Cleanup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Address the 3 remaining minor carryovers from Plan 20's final review. Small, focused, single branch.

**Architecture:** Three sequential tasks on `fix/2026-07-23-cleanup-final-minors` from `master` HEAD. Each task = one commit.

**Tech Stack:** Python 3.11+, pytest.

**Global Constraints:**

- Python 3.11+; test command: `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy PYTHONPATH=. python -m pytest --import-mode=importlib`
- All file writes through `src.lib.write_hooks.safe_write` — never raw `Path.write_text` / `os.unlink`
- Each task = one commit
- 702 existing tests must still pass
- After each task, dispatch a code-review subagent; fix Critical/Important findings before the next task

---

## Task C1: Remove redundant `self.client = client` in `OpenAIEmbeddingProvider.__init__:224`

**Files:**
- Modify: `src/llm/openai_provider.py:224` (verify line number) — remove redundant `self.client = client`
- Test: `tests/test_llm/test_openai_embedding_provider_init.py` (or extend existing)

**Approach:**

1. Open `src/llm/openai_provider.py`, locate `OpenAIEmbeddingProvider.__init__` (around line 224)
2. Verify `self.client = client` is redundant — the embedding provider should use `self._sdk` (or whatever the actual storage is) instead of `self.client`
3. Grep the file for `self.client` references OUTSIDE the assignment line; if any exist, they need to be updated to `self._sdk` (or canonical name) first
4. Delete the `self.client = client` line
5. Verify the embedding provider still works (existing tests should cover it)

**Tests:**

- `test_openai_embedding_provider_no_redundant_client_attribute`: instantiate `OpenAIEmbeddingProvider`, assert `hasattr(self, "_sdk")` is True AND `hasattr(self, "client")` is False (or whatever the canonical pattern is)
- Verify existing embedding tests still pass

- [ ] **Step 1: Write failing test** — confirm `self.client` is gone after removal

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Remove `self.client = client` line**

- [ ] **Step 4: Run, verify PASS** — 702 + 1 new = 703

- [ ] **Step 5: Commit**

```bash
git add src/llm/openai_provider.py tests/test_llm/test_openai_embedding_provider_init.py
git commit -m "fix(llm): remove redundant self.client in OpenAIEmbeddingProvider.__init__"
```

---

## Task C2: Document / fix `Registry.remove("openai")` silent env-default drop

**Files:**
- Modify: `src/llm/registry.py:remove()` — add docstring + decide behavior
- Test: `tests/test_llm/test_registry_remove_env_default.py`

**Approach:**

The current behavior: `Registry.remove("openai")` removes the entry from `_providers` dict. But on next `save()`, `_default_providers()` may re-add it from env. This is a subtle behavior.

Two options:

**Option A (document-only):** Add a clear docstring explaining:
- `remove()` removes from the registry state
- If the provider is env-sourced (`sourced_from_env=True`), the env var continues to take effect at runtime via the factory's env-var fallback
- On next `save()`, `_default_providers()` may re-add the entry from env (which is intended — env defaults are re-derived each time)

**Option B (hard disable):** Track a "disabled" set; `remove()` on an env-sourced provider marks it disabled; the factory's env-var fallback is skipped for disabled providers.

**Option C (rename):** Add a separate `disable()` method for env-sourced providers; `remove()` only affects user-added providers.

Pick **Option A** as the simplest — it documents the existing behavior and adds a regression test that verifies the behavior is what we want. If the user wants stronger semantics, that can be a separate plan.

**Tests:**

- `test_remove_env_sourced_provider_does_not_break_runtime`: env set, load registry, remove the env-sourced entry, verify a fresh `load()` still finds the entry (env-derived) AND runtime provider resolution still works
- `test_remove_user_added_provider_persists_absence`: env NOT set, add user provider, save, remove, save again, reload, assert provider is gone

- [ ] **Step 1: Write failing tests** — verify both behaviors

- [ ] **Step 2: Run, verify FAIL** (likely the docstring only, tests should pass; the new docstring doesn't affect runtime)

- [ ] **Step 3: Add docstring + implement any test-only fixes**

- [ ] **Step 4: Run, verify PASS** — 703 + 2 new = 705

- [ ] **Step 5: Commit**

```bash
git add src/llm/registry.py tests/test_llm/test_registry_remove_env_default.py
git commit -m "docs(llm): document Registry.remove() behavior for env-sourced providers"
```

---

## Task C3: Add explanatory comment to `_isolated_registry` test helper

**Files:**
- Modify: `tests/test_llm/test_registry_env_persistence.py` — add comment explaining what `_isolated_registry` does and why it doesn't need `config_dir()` stubbing

**Approach:**

Inline edit (trivial). Add a docstring or comment block at the top of the `_isolated_registry` function explaining:
- It creates an isolated registry per test
- It monkeypatches the registry's `_config_dir` (or equivalent) so the test doesn't pollute `~/.config/ruflo-kb/`
- It doesn't need `config_dir()` stubbing because the function itself sets up the isolated dir

- [ ] **Step 1: Apply inline comment edit**

- [ ] **Step 2: Commit**

```bash
git add tests/test_llm/test_registry_env_persistence.py
git commit -m "test(llm): add explanatory comment to _isolated_registry helper"
```

---

## Self-Review Checklist

1. **Spec coverage:** All 3 carryovers have a task. ✓
2. **No placeholders:** Each step has concrete guidance. ✓
3. **Type consistency:** N/A (no cross-task symbol changes). ✓
4. **Branch isolation:** All work on `fix/2026-07-23-cleanup-final-minors`; merge to master via PR after all 3 tasks. ✓

---

## Execution Order

1 → 2 → 3 (sequential; no cross-task dependencies; all small tasks)

Estimated total time: <1 hour of subagent work.

After all 3 tasks land and tests are green, dispatch one final review over the 3 new commits and offer merge to master.
