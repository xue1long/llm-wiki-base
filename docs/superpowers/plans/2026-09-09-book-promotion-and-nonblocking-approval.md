# Book Preview Promotion and Non-Blocking Human Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote an already validated Book preview without a second LLM generation, while making human readability approval advisory rather than a publication blocker.

**Architecture:** Add one deep compiler seam, `promote_preview_release(...)`, that validates a staged preview and delegates the existing atomic publisher without touching an LLM provider. Keep CLI parsing thin. Separate external-LLM governance (`approver`, budget, authorization) from human readability review: the former remains mandatory evidence for generated content, while the latter is recorded as optional audit evidence and never blocks `CURRENT.json`.

**Tech Stack:** Python 3.11+, asyncio, dataclasses, JSON manifests, pytest, existing CLI and Book release publisher.

**Spec:** User request in the current task, plus [`2026-09-09-book-llm-republish-hardening.md`](2026-09-09-book-llm-republish-hardening.md).

## Global Constraints

- `--apply-from RELEASE_ID` must make zero provider calls.
- `--apply-from` may promote only a release staged under the resolved output directory; release IDs are opaque hex IDs, never filesystem paths.
- `CURRENT.json` advances only after release-file hashes, manifest digest, snapshot freshness, and automated acceptance pass.
- Human readability and human acceptance are non-blocking; they must not be conflated with external-LLM authorization or the `approver` recorded in `llm_metadata`.
- Existing manifests remain readable; the `llm_metadata.call_sites.pending` field is accepted during transition while new manifests emit `requested`.
- A Book build does not update LanceDB. Any vector reconciliation remains a separate command and separate operational result.
- Do not silently increase `max_llm_calls`, add dependencies, or send real project content during tests.
- Preserve unrelated dirty work in the repository.

## Release protocol invariants

The implementation must treat a Preview result as an immutable candidate release,
not as a mutable directory that happens to have a UUID. These are hard protocol
invariants, not best-effort checks:

1. **One generation, one content identity.** `release_id` locates a candidate;
   the immutable content identity is the SHA-256 of canonical manifest bytes.
   The manifest is a closed proof over every byte that `CURRENT` can expose,
   plus the source snapshot, editorial inputs, rules, compiler/validator,
   generation contract, provider/model, and policy identity.
2. **Apply-from is a pure promotion.** It performs only
   `load_candidate -> validate_candidate -> publish_validated_candidate`.
   It must not construct a provider, call outline/body/polish code, rewrite the
   candidate, or update LanceDB. Its provider-call upper bound is exactly zero,
   including failure paths.
3. **Generation-time authorization is irreversible evidence.** The Preview
   manifest records the pre-call authorization decision, approver, policy hash,
   source classification, provider/model, call timestamps, and budget outcome.
   Apply-time policy checks may reject publication, but can never retroactively
   authorize an earlier external call.
4. **Validate and switch are one publication transaction.** Freshness is
   rechecked while holding the publication lock; CURRENT is replaced only after
   a compare-and-swap against the expected current pointer/source revision.
   Any race, crash, write failure, or validation failure leaves the old CURRENT
   unchanged and the candidate non-publishable until explicitly reissued.
5. **Immutable content and mutable evidence are separate.** Content identity,
   manifest digest, and release files are immutable. Human review, publication
   events, lifecycle state, and operational diagnostics are sidecars bound to
   that identity and must not rewrite the content manifest.
6. **No implicit rollback.** Repeating the active release is idempotent.
   Promoting an older, superseded, expired, or cross-project release is rejected
   by normal `--apply-from`; rollback, if later needed, is a separate explicit
   operation with its own audit record.

The existing implementation currently reports human gates as `pending`, but
`publish_book()` does not use those fields as a hard publication condition.
This change therefore corrects the state semantics and operator contract; it
must not be described as bypassing an existing Book publish gate unless a
caller is found that actually enforces it.

## Proposed user-facing behavior

Preview and promote the same artifact:

```powershell
python -m src.cli book build-from-wiki `
  --project D:\5-Project\20260903\llm-wiki-base\knowledge\novel-wiki `
  --preview --max-attempts 1 --max-llm-calls 4 --budget-cap 4 --approver owner --json

python -m src.cli book build-from-wiki `
  --project D:\5-Project\20260903\llm-wiki-base\knowledge\novel-wiki `
  --apply --apply-from PREVIEW_RELEASE_ID --json
```

The second command validates and promotes the preview release; it does not
call MiniMax again. The generated immutable manifest remains the source of
truth for the original provider, model, call count, budget, authorization, and
source gates. The promotion result reports `llm_calls_used: 0` for the
promotion operation and `source_release_id: PREVIEW_RELEASE_ID` without
rewriting the candidate manifest or release files.

Human review evidence is separate:

```json
{
  "schema_version": "human-approval-v1",
  "release_id": "RELEASE_ID",
  "manifest_sha256": "MANIFEST_SHA256",
  "human_readability_review": "approved",
  "human_content_review": "approved",
  "required_for_publish": false,
  "reviewer": "reviewer-name",
  "note": "optional review note"
}
```

No such file is required for promotion. If it is absent, the automated
acceptance report records `automated_acceptance: "passed"` separately from
`human_readability_review: "not_requested"`; an optional audit file may later
record a human decision without changing the release manifest or content
hashes. This file is informational evidence, not external-LLM authorization
or publication authority.

## File map

- Modify `src/cli.py`: add `--apply-from` to the `build-from-wiki` parser and
  enforce that it is used only with `--apply`.
- Modify `src/cli_ext/book_cmd.py`: pass the promotion ID through and avoid
  provider/preflight paths that imply a new generation.
- Modify `src/kc/views/book/wiki/compiler.py`: add the promotion seam, shared
  candidate lifecycle, shared release validation, no-provider promotion path,
  lock/CAS publication protocol, and full call-site budget preflight for fresh
  outlines.
- Modify `src/kc/views/book/wiki/acceptance.py`: make human gates advisory,
  separate machine validation from human review, load/validate the optional
  `human-approval.json`, and preserve old reports.
- Modify `src/kc/views/book/wiki/outline_llm.py`: expose the same deterministic
  eligible-call calculation used by `plan_outline`, so budget preflight does
  not duplicate prompt-size logic.
- Modify `src/kc/views/book/wiki/polish_llm.py` only if a shared typed failure
  or call-accounting interface is needed; otherwise leave the already fixed
  retry contract unchanged.
- Modify `tests/test_cli_ext/test_book_build_from_wiki_modes.py`: parser and
  mode constraints for `--apply-from`.
- Create `tests/test_kc/test_book_promotion.py`: promotion, integrity,
  snapshot, path-safety, idempotency, and zero-provider-call tests.
- Modify `tests/test_kc/test_book_acceptance_report.py`: advisory human gates,
  optional approval sidecar, and backward compatibility.
- Modify `tests/test_kc/test_book_chapter_body.py` and/or
  `tests/test_kc/test_book_wiki_compiler.py`: fresh-outline budget preflight
  and `requested` call-site metadata.
- Modify `docs/environment/SETUP.md`: operator runbook for preview → promote,
  policy configuration, human review semantics, and separate vector status.
- Modify `.memory/MEMORY.md` and add a dated feedback entry after rollout.

## Interface decisions

### Promotion seam

```python
def promote_preview_release(
    project_root: Path,
    *,
    output_dir: Path,
    release_id: str,
    apply: bool = True,
) -> dict[str, Any]:
    """Validate and optionally atomically promote an existing preview release."""
```

The compiler must also expose one shared internal protocol used by both normal
Apply and Apply-from:

```python
def validate_candidate_release(
    project_root: Path,
    *,
    output_dir: Path,
    release_id: str,
    expected_current: str | None = None,
) -> ValidatedCandidate:
    """Load an immutable candidate and return only validated publish inputs."""

def publish_validated_candidate(
    candidate: ValidatedCandidate,
    *,
    output_dir: Path,
    lock: Any,
) -> PublishReport:
    """Copy verified bytes and atomically switch CURRENT exactly once."""
```

`ValidatedCandidate` is an internal typed value, not a path string. It carries
the canonical manifest digest, source snapshot/revision, project/book identity,
release lifecycle state, and the verified file set. The publisher must not
accept an unvalidated `Path`.

Invariants:

- `release_id` must match `^[0-9a-f]{32}$`.
- The source is exactly `project_root / ".index" / "book-wiki" /
  "versions" / release_id`; `output_dir` is only the publication target and
  must not influence candidate path resolution. The candidate path must not be
  resolved from a user-supplied path.
- The candidate manifest digest, closed file set, `release_status ==
  "complete"`, source snapshot/revision, automated acceptance, project/book
  identity, lifecycle status, and generation-time LLM authorization evidence
  must pass.
- Validation and the final snapshot/CURRENT compare-and-swap happen under the
  same publication lock. If Wiki ingestion or another publisher does not
  participate in that lock, the source revision check must detect the race and
  fail closed.
- Normal Apply and Apply-from both call `publish_validated_candidate`. The
  existing `publish_book` may be refactored into that primitive; it must not be
  called as a shortcut that bypasses candidate validation.
- It must be idempotent: promoting the active release returns success without
  generating another release or changing content.
- A failed validation or publication leaves the previous `CURRENT.json`
  byte-for-byte unchanged and marks the candidate rejected/expired in a
  separate lifecycle sidecar so it cannot be retried as if it were valid.

### Human approval

`acceptance.py` must distinguish:

- `llm_metadata.approver`: external data-export governance; still required for
  a fresh LLM generation.
- `acceptance.automated_acceptance`: machine validation result; this is the
  only acceptance result used by the publication protocol.
- `acceptance.human_readability_review`: advisory status, defaulting to
  `not_requested` when the project does not require human review.
- `acceptance.human_content_review`: advisory status, defaulting to
  `not_requested`; neither human field blocks publication in this Book mode.
- `human-approval.json`: optional human evidence, bound to release ID and
  manifest hash.

The optional sidecar is not included in the immutable content `files` hash map,
avoiding a circular manifest update. Its loader rejects mismatched release IDs,
manifest hashes, project/book identities, or unsupported status values and
treats a missing sidecar as `not_requested`. It is audit evidence only and
cannot satisfy or replace external-LLM authorization.

## Task 0: Freeze the candidate-release publication protocol

**Files:**
- Modify: `src/kc/views/book/wiki/compiler.py`
- Modify: `src/kc/views/book/wiki/acceptance.py` only for shared validation types
- Create: `tests/test_kc/test_book_release_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

  Cover manifest closed-world hashing, canonical manifest identity, project/book
  isolation, candidate lifecycle transitions, source revision binding, and the
  rule that mutable audit/lifecycle sidecars never change content identity.

- [ ] **Step 2: Implement typed validation and lifecycle state**

  Add `ValidatedCandidate`, `validate_candidate_release`, and a lifecycle
  sidecar with explicit `candidate`, `validated`, `published`, `superseded`,
  `expired`, and `rejected` states. A rejected or expired candidate cannot be
  promoted by ordinary `--apply-from`.

- [ ] **Step 3: Verify protocol tests**

  ```text
  uv run --offline pytest tests/test_kc/test_book_release_protocol.py -q
  ```

- [ ] **Step 4: Commit**

  ```text
  git add src/kc/views/book/wiki/compiler.py src/kc/views/book/wiki/acceptance.py tests/test_kc/test_book_release_protocol.py
  git commit -m "feat(book): define immutable candidate release protocol"
  ```

## Task 1: Define non-blocking human approval evidence

**Files:**
- Modify: `src/kc/views/book/wiki/acceptance.py`
- Test: `tests/test_kc/test_book_acceptance_report.py`
- Test: create `tests/test_kc/test_human_approval.py` only if the existing
  acceptance test file becomes difficult to keep focused

**Interfaces:**
- `build_release_acceptance_report(...)` emits `automated_acceptance` as the
  machine result and both human review fields as `not_requested` by default.
- `load_human_approval(release_dir: Path, manifest: Mapping[str, Any]) -> dict[str, Any] | None`
  validates the optional sidecar and returns `None` when absent.
- `write_human_approval(release_dir: Path, payload: Mapping[str, Any]) -> Path`
  validates release ID, manifest hash, and allowed status values before writing.

- [ ] **Step 1: Write failing tests**

  Add tests that assert a committed LLM release remains
  `automated_acceptance: "pass"` when no human review file exists, that human
  review says `not_requested`, and that a sidecar with the wrong manifest hash
  or project/book identity is rejected without changing the release manifest.

- [ ] **Step 2: Run the focused tests and verify failure**

  ```text
  uv run --offline pytest tests/test_kc/test_book_acceptance_report.py -q
  ```

  Expected failure: the current report hard-codes `pending` and has no
  sidecar interface.

- [ ] **Step 3: Implement the smallest advisory approval module**

  Keep automated checks unchanged. Replace only the human-review output and
  add sidecar validation. Do not add an approval requirement to
  `publish_book`, `build_from_wiki`, or `validate_candidate_release`.

- [ ] **Step 4: Run the focused tests**

  ```text
  uv run --offline pytest tests/test_kc/test_book_acceptance_report.py tests/test_kc/test_human_approval.py -q
  ```

- [ ] **Step 5: Commit**

  ```text
  git add src/kc/views/book/wiki/acceptance.py tests/test_kc/test_book_acceptance_report.py tests/test_kc/test_human_approval.py
  git commit -m "feat(book): make human approval advisory"
  ```

## Task 2: Promote a validated preview without another LLM call

**Files:**
- Modify: `src/cli.py`
- Modify: `src/cli_ext/book_cmd.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Test: `tests/test_cli_ext/test_book_build_from_wiki_modes.py`
- Test: `tests/test_kc/test_book_promotion.py`

**Interfaces:**
- CLI accepts `--apply-from RELEASE_ID` only when `--apply` is selected.
- `promote_preview_release(...)` returns `status`, `source_release_id`,
  `run_id`, `manifest_sha256`, `llm_calls_used: 0`, and `acceptance`.

- [ ] **Step 1: Write failing tests**

  Create a complete deterministic preview fixture with two Markdown chapters
  and a manifest. Add assertions that:

  ```python
  result = promote_preview_release(root, output_dir=book, release_id=run_id)
  assert result["status"] == "committed"
  assert result["source_release_id"] == run_id
  assert result["llm_calls_used"] == 0
  assert json.loads((book / "CURRENT.json").read_text())["version"] == run_id
  ```

  Add a fake provider that raises if called and assert `--apply-from` never
  reaches it. Add failure tests for a traversal-shaped ID, missing manifest,
  bad manifest digest, stale snapshot, incomplete release, and a failed
  promotion preserving the prior CURRENT pointer.

- [ ] **Step 2: Run tests and verify failure**

  ```text
  uv run --offline pytest tests/test_kc/test_book_promotion.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
  ```

  Expected failure: the CLI flag and promotion seam do not exist.

- [ ] **Step 3: Implement promotion behind the compiler seam**

  Refactor the existing path into `validate_candidate_release` plus
  `publish_validated_candidate`. Resolve only the canonical staging path and
  reject traversal-shaped IDs before filesystem access. Validate the canonical
  manifest digest, closed file set, acceptance evidence, project/book identity,
  source snapshot/revision, lifecycle state, and generation-time authorization.
  Acquire the publication lock, re-read the source revision and expected
  CURRENT, then copy only verified bytes and perform a compare-and-swap pointer
  replacement. Never call provider construction, `plan_outline`,
  `generate_chapter_body`, or embedding code. Do not rewrite the candidate
  manifest, acceptance evidence, or chapter files during promotion.

- [ ] **Step 4: Wire the thin CLI adapter**

  Reject `--apply-from` without `--apply` with a deterministic parser error.
  For promotion, pass the absolute project root and output directory to the
  compiler; do not infer the project by short name when an absolute path was
  supplied.

- [ ] **Step 5: Run focused and regression tests**

  ```text
  uv run --offline pytest tests/test_kc/test_book_promotion.py tests/test_cli_ext/test_book_build_from_wiki_modes.py tests/test_kc/test_book_wiki_staged_failure.py -q
  ```

  The focused suite must include provider-unavailable and provider-call-raising
  fixtures, concurrent source/CURRENT mutation, process-failure simulation at
  both sides of pointer replacement, repeat promotion, old-release replay,
  cross-project IDs, lifecycle rejection, and byte-for-byte preservation of
  the prior CURRENT on every failure.

- [ ] **Step 6: Commit**

  ```text
  git add src/cli.py src/cli_ext/book_cmd.py src/kc/views/book/wiki/compiler.py tests/test_cli_ext/test_book_build_from_wiki_modes.py tests/test_kc/test_book_promotion.py tests/test_kc/test_book_wiki_staged_failure.py
  git commit -m "feat(book): promote validated previews without regeneration"
  ```

## Task 3: Make fresh-outline budget preflight exact

**Files:**
- Modify: `src/kc/views/book/wiki/outline_llm.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Test: `tests/test_kc/test_book_chapter_body.py`
- Test: `tests/test_cli_ext/test_book_build_from_wiki_modes.py`

**Interfaces:**
- `estimate_outline_call_sites(snapshot, chapter_chunks, *, token_budget) -> int`
  uses the same page payload and token estimate as `plan_outline`.
- New manifest metadata emits `call_sites.<name>.requested`; old `pending` is
  accepted while reading existing manifests.
- `minimum_llm_calls` and `configured_max_llm_calls` are calculated from the
  actual eligible outline chunks, theme batches, optional index, and chapter
  retry policy.

- [ ] **Step 1: Write failing tests**

  Cover:

  - fresh outline with two eligible chunks and cap below outline-plus-body
    minimum blocks before the first provider call;
  - a low token budget that makes one chunk rule-fallback does not count that
    skipped chunk as a mandatory provider call;
  - persisted outline reports zero outline calls;
  - metadata uses `requested`, not `pending`, for new releases;
  - observed fake-provider calls equal the sum of `actual_calls`.

- [ ] **Step 2: Run tests and verify failure**

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
  ```

- [ ] **Step 3: Refactor the estimator into the outline module**

  Extract the existing prompt construction/estimate decision once. Have both
  `plan_outline` and the compiler call the same estimator so future prompt
  changes cannot silently invalidate the budget formula. Keep the global
  `_BudgetedProvider` as the runtime guard.

- [ ] **Step 4: Add preflight for every provider call site**

  Calculate the minimum before outline, theme mapping, encyclopedic index, or
  chapter calls. If the approved cap is below the minimum, return
  `E_LLM_BUDGET_INSUFFICIENT` with no provider call. Do not reject a cap that
  covers all first attempts but not every retry; expose the reserve shortfall.

- [ ] **Step 5: Run focused tests and commit**

  ```text
  uv run --offline pytest tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
  git add src/kc/views/book/wiki/outline_llm.py src/kc/views/book/wiki/compiler.py tests/test_kc/test_book_chapter_body.py tests/test_cli_ext/test_book_build_from_wiki_modes.py
  git commit -m "fix(book): preflight all LLM call sites"
  ```

## Task 4: Persist project governance and separate vector status

**Files:**
- Modify: `knowledge/novel-wiki/.llm-wiki/policy.json` only if the operator
  approves committing project policy changes
- Modify: `src/cli_ext/book_cmd.py` and/or result assembly in
  `src/kc/views/book/wiki/compiler.py`
- Modify: `docs/environment/SETUP.md`
- Test: `tests/test_cli_ext/test_book_build_from_wiki_modes.py`

**Interfaces:**
- Fresh generation reads `approver`, `budget_cap`, and optional
  `allowed_paths` from policy; command-line values may override only when the
  existing policy rules permit it.
- Book result includes `vector_index: "not_updated"` and a stable hint to use
  `vector status` / `vector reconcile`; it does not mutate LanceDB.

- [ ] **Step 1: Write failing tests**

  Assert that a Book result clearly reports vectors were not updated, and that
  policy fields are loaded without exposing secret values. Assert that
  `vector reconcile` remains a separate operation.

- [ ] **Step 2: Implement policy/documentation changes**

  Add only non-secret governance fields to the project policy. Never copy API
  keys into policy. Document that Book publication consumes Wiki content but
  does not re-embed it.

- [ ] **Step 3: Run focused tests and commit**

  ```text
  uv run --offline pytest tests/test_cli_ext/test_book_build_from_wiki_modes.py tests/test_cli_ext/test_vector_cmd.py -q
  git add src/cli_ext/book_cmd.py src/kc/views/book/wiki/compiler.py docs/environment/SETUP.md tests/test_cli_ext/test_book_build_from_wiki_modes.py tests/test_cli_ext/test_vector_cmd.py
  git commit -m "docs(book): clarify governance and vector separation"
  ```

## Task 5: End-to-end rollout and operator verification

**Files:**
- Modify: `.memory/MEMORY.md`
- Create: `.memory/feedback-book-preview-promotion-2026-09-09.md`
- Test/verification: full Book and CLI suites; no real provider call in CI

- [ ] **Step 1: Run the complete deterministic regression**

  ```text
  uv run --offline pytest tests/test_kc/ tests/test_cli_ext/test_book_build_from_wiki.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q
  ```

- [ ] **Step 2: Run a no-provider promotion drill**

  Use a staged fixture and a provider that raises on every invocation. Verify
  the promoted release is byte-identical to the preview chapter files,
  `CURRENT.json` points to the same release ID, and the provider call count is
  zero.

- [ ] **Step 3: Run one authorized real preview only**

  Use the absolute `knowledge/novel-wiki` path, inspect the manifest call-site
  budget, and record the release ID. Do not apply by regenerating.

- [ ] **Step 4: Promote that exact preview**

  Run `--apply --apply-from PREVIEW_RELEASE_ID`, verify the current pointer,
  manifest hash, chapter hashes, and `vector_index: not_updated`. Optionally
  write `human-approval.json`; its absence must not block publication.

- [ ] **Step 5: Record the rollout and commit**

  ```text
  git add .memory/MEMORY.md .memory/feedback-book-preview-promotion-2026-09-09.md
  git commit -m "docs(book): record preview promotion rollout"
  ```

## Acceptance criteria

- A preview can be promoted with `--apply-from` without any LLM or embedding
  provider invocation.
- `apply-from` executes only `load_candidate -> validate_candidate ->
  publish_validated_candidate`; its provider-call upper bound is zero on both
  success and failure paths.
- The promoted release ID and content hashes are exactly those from preview.
- The immutable manifest is a closed proof over all published bytes and binds
  source snapshot/revision, editorial inputs, rules, compiler/validator,
  generation contract, provider/model, and policy identity.
- Invalid, stale, incomplete, or tampered previews never update CURRENT.
- Validation and CURRENT replacement use the publication lock plus a source
  revision/CURRENT compare-and-swap; expected crash and write failures leave
  the previous CURRENT byte-for-byte unchanged.
- Failed or expired candidates cannot be replayed through ordinary
  `--apply-from`; old-release downgrade requires a separate explicit rollback
  operation.
- Human readability/content review is optional evidence, represented as
  `not_requested` when absent, and never blocks a release whose
  `automated_acceptance` passes.
- External LLM authorization, approver, budget, and source/sensitivity gates
  remain enforced before every fresh provider call; Apply-from cannot repair a
  missing historical authorization and may still reject publication under a
  stricter current publication policy.
- Fresh-outline budget insufficiency is detected before the first provider
  call; retry reserve shortfall is observable and never silently increased.
- New manifests use `requested`; old `pending` metadata remains readable.
- Book publishing explicitly reports that LanceDB was not updated, and tests
  prove Preview, normal Apply, and Apply-from perform no vector write.
- Existing Book tests plus all new tests pass.

## Plan audit — Round 1: comprehensive vulnerability audit

### Critical

1. **Promotion trusts a preview directory.** If `--apply-from` copies files
   without validating the manifest digest and every listed file hash, a user
   could publish a modified chapter under an approved release ID. Mitigation:
   validate the release before any pointer write and reuse the existing
   integrity checker.
2. **Release ID path traversal.** Accepting `../` or an absolute path could
   promote an unrelated directory. Mitigation: strict 32-hex ID validation and
   canonical staging-root containment tests.

### Major

3. **Stale preview.** Wiki content can change after preview, making the
   promoted book stale. Mitigation: compare manifest snapshot ID to a fresh
   Wiki snapshot and fail closed.
4. **Approval conflation.** Removing the human gate could accidentally remove
   the external-LLM approver or authorization gate. Mitigation: keep
   `llm_metadata.approver`, `budget_cap`, authorization, and sensitivity checks
   independent from `human-approval.json`.
5. **Acceptance report invalidation.** Rewriting the manifest after adding
   human evidence can invalidate its digest. Mitigation: keep the human
   sidecar outside the manifest file hash map and bind it to the immutable
   manifest hash.
6. **Double publication race.** Two promotions could race on CURRENT. Mitigation:
   reuse the existing book run lock and make same-release promotion idempotent.
7. **Policy drift.** A policy may be stricter after preview. Mitigation: verify
   current external authorization and source/sensitivity policy before
   promotion, while preserving the original manifest evidence.
8. **Backward compatibility.** Consumers may still read `pending`. Mitigation:
   accept both fields during transition and add fixture tests for old manifests.

### Optimization gaps

9. **Estimator drift.** Duplicating outline prompt sizing in compiler and
   outline planner will eventually produce wrong minimum budgets. Mitigation:
   one estimator in `outline_llm.py`, used by both.
10. **Vector assumption.** Operators may think Book publication refreshed
    search vectors. Mitigation: explicit `vector_index: not_updated` result and
    runbook command.

## Plan audit — Round 2: pressure-test scenarios

| Scenario | Expected result | Protection |
|---|---|---|
| Valid preview, provider unavailable | Promotion succeeds with zero provider calls | Preview promotion is provider-free |
| Preview chapter edited after generation | Promotion blocked by file hash mismatch | Manifest integrity |
| Preview ID is `../../other-release` | CLI rejects before filesystem access | ID validation and containment |
| Wiki changed after preview | Promotion blocked, prior CURRENT unchanged | Snapshot freshness |
| Manifest has `release_status=partial` | Promotion blocked | Complete-release gate |
| Human approval file missing | Promotion succeeds; gates remain advisory | Non-blocking approval policy |
| Human approval file has wrong manifest hash | Sidecar ignored/rejected; release content remains unchanged | Sidecar binding |
| External authorization is revoked after preview | Promotion blocked or requires explicit policy revalidation | Governance gate |
| Cap below fresh-outline minimum | No provider call; deterministic budget block | Shared estimator |
| Cap covers first attempts but not retries | First attempts run; reserve shortfall is recorded; no silent cap increase | Runtime counter |
| Two concurrent promotions | One lock owner publishes; other returns idempotent/current result | Run lock |
| Book apply after Wiki ingest but before vector indexing | Book publishes and reports vector status separately | Pipeline separation |

## Audit disposition and implementation gate

The plan does not remove external-LLM governance, does not trust mutable
preview files, and does not make LanceDB a hidden side effect of Book release.
The only intended behavior change is that human readability approval becomes
optional evidence, while preview promotion reuses the exact validated artifact.
Implementation may start after the user confirms this plan, with Task 0, Task 1,
and Task 2 reviewed before Task 3 budget refactoring.

## Plan audit — Round 3 after remediation

The previous audit found four P0 gaps. This revision closes them at the plan
level as follows:

| P0 gap | Revised control | Required proof before implementation is considered complete |
|---|---|---|
| Release ID was weaker than content identity | Canonical manifest digest, closed-world file set, typed `ValidatedCandidate` | Tamper, missing-file, cross-project, and identity-binding tests |
| Apply-from could accidentally re-enter generation | Dedicated `load -> validate -> publish` protocol and zero-call invariant | Provider-absent and provider-raises tests with call count zero |
| Apply could be mistaken for retroactive authorization | Preview-time pre-call evidence plus separate current publication-policy check | Unauthorized Preview fails before first provider call; Apply cannot repair it |
| Freshness check had a TOCTOU window | Lock-scoped recheck plus source revision/CURRENT CAS | Concurrent mutation and crash-window tests preserve old CURRENT |

The second audit also identified and this revision addresses:

- immutable content versus mutable human/lifecycle evidence;
- policy/compiler/acceptance version drift;
- failed/expired candidate sealing;
- replay, downgrade, and explicit rollback boundaries;
- candidate retention and reader visibility requirements;
- vector no-side-effect behavior rather than metadata-only claims.

The plan is now implementation-ready only if Task 0 and Task 2 are completed
before the budget and documentation work. A passing happy-path test alone is
not sufficient for release: the failure matrix and zero-provider-call proof
are mandatory gates.
