# Book LLM Republish Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Book LLM publication failures distinguishable and recoverable without weakening the strict chapter contract or changing the fail-closed publication gate.

**Architecture:** Keep the compiler-owned schema and validation as the source of truth. Add a small failure taxonomy and attempt history at the chapter-generation boundary, feed a bounded validation hint only into retries that can be corrected by the model, and expose the global budget shortfall explicitly at the compiler boundary. Define budget formulas from actual provider call sites rather than assuming a fixed number of stages. Preserve `CURRENT.json` unless the existing complete release and acceptance checks pass.

**Tech Stack:** Python 3.11+, asyncio, dataclasses, pytest, existing CLI and Book compiler.

**Spec:** This plan is based on the incident evidence in `knowledge/novel-wiki/.index/book-wiki/versions/154604afefd44f8487d2d9ea487f54b5/manifest.json` and `knowledge/novel-wiki/.index/book-wiki/versions/7ac56ed87eac4d5dbb8a3c0d9f70e251/manifest.json`.

## Global Constraints

- Keep `apply` fail-closed; invalid, incomplete, or budget-exhausted LLM output must never advance `CURRENT.json`.
- Keep the strict top-level chapter object and source-page validation; do not accept a list of titles or strings as chapter content.
- Do not send additional real project content to an external provider in tests.
- Do not silently increase `max_llm_calls`; the CLI must continue to require an explicit approved budget.
- Preserve the existing `E_LLM_REQUIRED_FOR_APPLY` code for compatibility, while adding a more specific diagnostic code.
- Use the absolute project path for real publication because the short project name collides with the stale backup project.

## Local Evidence

- The older failed run recorded `ValueError: response_not_structured_chapter:type=list:items=str,str,str`; the provider returned JSON, but not the required object shape.
- The latest failed run recorded `_LLMBudgetExceeded: max_llm_calls exhausted`, with `llm_calls_used=3`, `max_llm_calls=3`, `max_retries=1`, and two chapters.
- `src/kc/views/book/wiki/compiler.py` uses one publication-scoped call counter and collapses all non-passed apply states to `E_LLM_REQUIRED_FOR_APPLY`.
- `src/kc/views/book/wiki/polish_llm.py` currently retries after parse, truncation, provider, or validation failures; the retry currently receives no structured correction hint and should be narrowed to model-correctable contract failures.
- Existing targeted Book tests pass after the retry-default change; the new behavior must be covered with deterministic fake providers only.

## Task 1: Preserve typed chapter failure diagnostics

**Files:**
- Modify: `src/kc/views/book/wiki/polish_llm.py` around `GeneratedChapter` and `generate_chapter_body`
- Modify: `src/kc/views/book/wiki/compiler.py` around `llm_metadata` assembly and the `apply` gate
- Test: `tests/test_kc/test_book_chapter_body.py`
- Test: `tests/test_cli_ext/test_book_build_from_wiki.py`

**Interfaces:**
- `GeneratedChapter.failure_code: str` is optional and defaults to the empty string for backward compatibility.
- `llm_metadata.failure_codes` is a sorted list of stable codes; existing `failure_reasons` remains available for human diagnosis.
- Apply results retain `E_LLM_REQUIRED_FOR_APPLY` and add one specific code such as `E_LLM_BUDGET_EXHAUSTED`, `E_LLM_RESPONSE_INVALID`, `E_LLM_PROVIDER_FAILED`, or `E_LLM_RETRY_EXHAUSTED`.

- [x] **Step 1: Write failing tests for failure preservation**

  Add deterministic tests that assert:

  ```python
  result = asyncio.run(generate_chapter_body(
      _draft(), provider_that_returns_a_list_then_hits_budget,
      section_plan=({"section_id": "s1", "title": "Overview"},),
      retries=1,
  ))
  assert result.failure_code == "E_LLM_BUDGET_EXHAUSTED"
  assert "response_not_structured_chapter" in result.failure_reason
  assert "max_llm_calls exhausted" in result.failure_reason
  ```

  Add a compiler-level assertion that the result contains both the legacy generic code and the specific code, and that `CURRENT.json` is unchanged after the failed apply.

- [x] **Step 2: Run the focused tests and verify they fail**

  Run:

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki.py -q
  ```

  Expected failure: `GeneratedChapter` has no typed failure code and the previous attempt reason is not retained.

- [x] **Step 3: Implement the smallest failure taxonomy**

  In `generate_chapter_body`, classify failures without changing acceptance rules:

  - JSON shape, truncation, and chapter validation failures → `E_LLM_RESPONSE_INVALID`.
  - Provider exceptions other than the budget sentinel → `E_LLM_PROVIDER_FAILED`.
  - `_LLMBudgetExceeded` → `E_LLM_BUDGET_EXHAUSTED`.
  - If retries finish after an invalid/provider failure, retain the final code and append the bounded prior attempt reasons to `failure_reason`.
  - Keep an attempt-history list in memory so a terminal budget exception cannot erase an earlier invalid-response reason.

  In the compiler, aggregate unique `failure_codes` and map them to the result's `reason_codes` while retaining `E_LLM_REQUIRED_FOR_APPLY`.

- [x] **Step 4: Run the focused tests and verify they pass**

  Run the same command from Step 2. Expected: all existing tests plus the new failure-preservation tests pass.

- [x] **Step 5: Commit**

  ```text
  git add src/kc/views/book/wiki/polish_llm.py src/kc/views/book/wiki/compiler.py tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki.py
  git commit -m "fix(book): preserve LLM failure diagnostics"
  ```

## Task 2: Make retries provider-aware without weakening validation

**Files:**
- Modify: `src/kc/views/book/wiki/polish_llm.py` in the retry loop
- Test: `tests/test_kc/test_book_chapter_body.py`

**Interfaces:**
- Only deterministic model-correctable contract failures are retryable: malformed JSON shape, truncation/empty output, and chapter validation failures.
- Provider transport/authentication failures and budget/runtime exhaustion are terminal for that chapter and do not trigger another provider call.
- Each retry sends the same chapter payload and compiler-owned section list, plus a fixed, bounded correction hint derived only from the local failure category.
- The provider still receives `response_format={"type": "json_object"}` and the same strict validator.

- [x] **Step 1: Write a failing retry-feedback test**

  Use a fake provider that returns `json.dumps(["标题一", "标题二"])` on the first call and a valid chapter object on the second call. Assert that the second request contains a correction such as `previous response failed the top-level object contract` and that the final result is complete. Add a separate fake provider that raises `TimeoutError` and assert it is called once even when `retries=1`.

- [x] **Step 2: Run the test and verify it fails**

  Run:

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py::test_retry_includes_structured_contract_feedback -q
  ```

  Expected failure: both attempts currently send the same task text.

- [x] **Step 3: Add a bounded correction hint**

  Keep a local `last_failure_category` variable. Retry only for the retryable categories above. On retry, append one fixed instruction selected from the category; do not include raw model output or unbounded exception text in the next prompt. For example, a shape failure adds: `The previous response violated the top-level object contract. Return exactly one JSON object with a sections array; never return an array.`

- [x] **Step 4: Run the focused test and the existing contract tests**

  Run:

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py -q
  ```

  Expected: the retry succeeds for the deterministic invalid-then-valid provider, while the existing list/invalid-reference tests still fail closed.

- [x] **Step 5: Commit**

  ```text
  git add src/kc/views/book/wiki/polish_llm.py tests/test_kc/test_book_chapter_body.py
  git commit -m "fix(book): give LLM retries contract feedback"
  ```

## Task 3: Make the publication budget boundary explicit

**Files:**
- Modify: `src/kc/views/book/wiki/compiler.py` near budget metadata and before provider calls
- Modify: `src/cli.py` only if the help text needs to expose the budget calculation
- Modify: `src/cli_ext/book_cmd.py` only if its compatibility parser needs the same default/help text
- Test: `tests/test_kc/test_book_chapter_body.py`
- Test: `tests/test_cli_ext/test_book_build_from_wiki_modes.py`

**Interfaces:**
- Manifest `llm_metadata` gains `call_sites`, `minimum_llm_calls`, `configured_max_llm_calls`, and `retry_reserve_shortfall`.
- `call_sites` is derived from the actual code paths that invoke the publication-scoped provider. It must state whether an outline call is pending, how many chapter calls are required, and whether any other LLM operation consumes the same counter.
- `minimum_llm_calls` counts the actual mandatory calls for the current artifact. A persisted outline contributes zero pending outline calls only when the implementation proves no provider call occurs for it.
- `configured_max_llm_calls` is the maximum call count under the configured retry policy, derived from the same call-site model; it must not be a hard-coded four.
- The compiler blocks before provider calls only when `max_llm_calls < minimum_llm_calls`; it does not reject a budget that can complete on first attempts but cannot cover every retry.
- If a retry is attempted after the global counter is exhausted, the specific budget code from Task 1 is returned.

- [x] **Step 1: Write failing budget-boundary tests**

  Add tests for:

  - two chapters with a persisted outline and `max_llm_calls=1` → blocked before provider call with `E_LLM_BUDGET_INSUFFICIENT`;
  - two chapters with `max_llm_calls=3` and no invalid response → allowed, preserving current behavior;
  - two chapters with `max_llm_calls=3`, one invalid response, and one retry → no pointer advance and a specific budget diagnostic;
  - metadata reports the actual call sites, mandatory call count, configured maximum, and retry-reserve shortfall for the latter configuration;
  - a persisted outline contributes zero outline calls, while a fresh outline contributes exactly the number of provider calls observed at that call site;
  - the fake provider invocation count equals the manifest accounting in every case.

- [x] **Step 2: Run the tests and verify the new assertions fail**

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
  ```

- [x] **Step 3: Implement budget preflight and metadata**

  First enumerate the actual provider call sites in the current path and add a deterministic test for each one. Compute the counts from those call sites, the actual pending outline state, and generated chapter drafts. Persist the counts in the staged manifest before any provider call. Return a deterministic blocked result for an impossible minimum budget. Preserve the current runtime counter and do not auto-increase the caller's approved cap.

- [x] **Step 4: Run focused and regression tests**

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki_modes.py tests/test_cli_ext/test_book_build_from_wiki.py -q
  ```

  Expected: the existing 31 targeted tests plus the new budget tests pass.

- [x] **Step 5: Commit**

  ```text
  git add src/kc/views/book/wiki/compiler.py src/cli.py src/cli_ext/book_cmd.py tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki_modes.py
  git commit -m "fix(book): report insufficient LLM budget"
  ```

## Task 4: Document and verify the real republish procedure

**Files:**
- Modify: `docs/environment/SETUP.md` or the existing Book operations document that owns publication commands
- Modify: `.memory/MEMORY.md` with the final incident rule
- Test/verification: no new production code

- [x] **Step 1: Document the operator rule**

  Record that a two-chapter LLM publication with one retry allowance needs approval for the call count reported by the plan's actual call-site accounting. In the current persisted-outline path this is expected to be four calls only if there are exactly two chapter calls and one retry per chapter; documentation must state that condition instead of treating four as an intrinsic constant.

- [x] **Step 2: Run the full relevant verification**

  ```text
  uv run --offline pytest tests/test_kc/ tests/test_cli_ext/test_book_build_from_wiki.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
  graphify update .
  ```

  If `graphify update .` hits the known uv trampoline permission error, record it as an environment limitation; it must not be mistaken for a Book failure.

- [x] **Step 3: Verify an authorized real publish**

  First run a plan with the absolute target path and inspect `minimum_llm_calls`, `worst_case_llm_calls`, and `retry_reserve_shortfall`. Only after explicit approval of the displayed cap, run `--apply`. Verify release acceptance, manifest hash, chapter files, and `CURRENT.json`.

- [x] **Step 4: Commit**

  ```text
  git add docs/environment/SETUP.md .memory/MEMORY.md
  git commit -m "docs(book): document LLM republish budget"
  ```

## Two-round plan audit

### Round 1: Comprehensive vulnerability audit

1. **Major — worst-case budget can be over-restrictive.** If the implementation blocks on the configured maximum, a clean first-attempt run with a valid smaller cap would be rejected. Mitigation: hard-block only below `minimum_llm_calls`; expose the retry reserve shortfall without silently spending more.
2. **Major — diagnostic fields can break old consumers.** Adding a required dataclass field or replacing the legacy reason code can break tests and CLI clients. Mitigation: default the new field to empty and retain `E_LLM_REQUIRED_FOR_APPLY`.
3. **Major — retry feedback can leak provider output.** Raw exception/model text could contain source content or prompt-injection text. Mitigation: use fixed category messages and keep verbose details only in local manifest metadata.
4. **Major — accepting arrays would create false positives.** The historical failure was a string array. Mitigation: keep the strict object validator and test arrays as permanent rejection cases.
5. **Major — persisted and fresh outlines have different budgets.** Counting an already persisted outline as a new call would reject valid runs. Mitigation: calculate pending outline calls from the actual outline mode.
6. **Important — a provider can return HTTP 200 with malformed JSON.** Transport success is not semantic success. Mitigation: classify parse/shape/validation failures separately from provider transport failures.
7. **Important — all chapters may not share the same retry behavior.** One chapter can succeed while another consumes the remaining budget. Mitigation: aggregate per-chapter failure codes and keep the staged release non-publishable until every chapter is complete.
8. **Important — partial files may look publishable.** A staged directory can contain complete-looking Markdown while its manifest is partial. Mitigation: keep `CURRENT.json` as the only active pointer and require release acceptance plus manifest integrity.
9. **Optimization — test fixtures may hide provider quirks.** Existing fake providers return ideal JSON. Mitigation: add deterministic invalid-then-valid and budget-exhausted fixtures, without calling a real provider.
10. **Major — call-count formulas can be confidently wrong.** A persisted outline, fresh outline, or hidden shared provider call changes the required budget. Mitigation: derive accounting from actual call sites and assert fake-provider invocation counts against the manifest.

### Round 2: Pressure-test scenarios and hardening

| Scenario | Expected result | Hardening covered |
|---|---|---|
| First response is a string array, retry is valid | Publish may pass within budget; manifest records first shape failure only as attempt history | Typed diagnostics + retry feedback |
| Both attempts are malformed | No publish; specific response/retry code; `CURRENT.json` unchanged | Strict validator + fail-closed gate |
| Provider returns HTTP 200 with invalid JSON | No publish; `E_LLM_RESPONSE_INVALID`, not a transport-success false pass | Parse classification |
| Provider times out | No publish; `E_LLM_PROVIDER_FAILED`; no retry prompt containing raw exception text | Safe feedback |
| Cap is below the two-chapter minimum | Block before provider call; no budget is consumed | Budget preflight |
| Cap is 3 and one retry is needed | Run stops at the cap; specific budget diagnostic and retry shortfall visible | Global counter + metadata |
| Outline is persisted | Minimum budget counts only chapter calls | Pending-call accounting |
| Outline is fresh | Manifest includes the actual outline provider call count | Call-site accounting |
| A partial staging directory exists after failure | Active pointer remains the previous complete release | Atomic publication invariant |

### Audit disposition

The plan is approved for implementation after the mitigations above. The design deliberately does not weaken the chapter schema, silently increase budget, retry terminal provider failures, or auto-publish partial output. The next implementation step is Task 1, using deterministic tests before touching compiler behavior.
