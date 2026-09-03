# Instance Template Compatible Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every project instance use a pinned scenario template that drives Analyzer, Reviewer, Generator, and final Wiki validation without breaking existing projects or the current Writer/index/vector path.

**Architecture:** Keep the existing scenario-template loader and project-materialized files. Add a small immutable `TemplateSnapshot`/`TemplateContract` seam: resolve and compile the effective project template once at task creation, pass only stage-specific prompt/rule projections downstream, and keep `commit_ingest()` as the only final writer. Old projects use `general@compat` until explicitly upgraded.

**Tech Stack:** Python 3.11+, dataclasses, JSON/YAML already used by the repository, existing Markdown template parser, pytest, existing queue and idempotency helpers.

**Spec:** `docs/design-doc-driven-pipeline.md`, `docs/superpowers/plans/2026-08-28-kc-mainline-three-levels.md`, and this plan's compatibility rules.

## Global Constraints

- Do not add a template marketplace, YAML workflow engine, or new Writer/vector protocol. Optional remote template distribution is covered only by Task 10 and must remain hash-verified and offline-safe.
- Do not let source content or the LLM select `template_id`, `template_version`, Wiki type, slot, or route.
- `schema.md` owns types/routes; `.wiki-templates/<type>.md` owns slots; `purpose.md` and prompt files own natural-language instructions.
- All HTTP, CLI, queue, MCP, batch, and synchronous ingestion paths must create or receive the same `IngestSnapshot`.
- Retry must use the original snapshot; a changed template must never silently affect an existing task.
- Existing projects without binding use `general@compat`; historical Wiki pages are not rewritten automatically.
- `commit_ingest()` remains the only final Wiki/index/vector commit path.
- Every task ends with targeted tests and one logical commit; do not push.

## Fixed Audit Remediations (scope lock)

- Persist the complete compiled contract under `.llm-wiki/template-snapshots/<contract_hash>.json`; retries use that snapshot or fail closed.
- `schema.md` is the only source of Wiki types/routes; `.wiki-templates/<type>.md` is the only source of slots. The compiler must prove their complete closure.
- HTTP, CLI, queue, MCP, batch, and direct ingestion share one snapshot-producing task boundary; downstream code never resolves “latest”.
- `contract_hash` participates in task identity. Within one project, the same canonical source and Wiki type update the existing page even when the contract changes.
- Acceptance must prove different final scenario pages with fixed fixtures, not merely different Prompt text.
- Findings not listed in the original six remediation categories remain post-MVP and are intentionally unchanged.

## Delivery Contracts (must be implemented exactly)

- `TemplateContract` is written by `persist_template_snapshot()` using canonical JSON (`sort_keys=True`, UTF-8, newline-terminated) through `safe_write`; the contract hash is the SHA-256 of that canonical JSON. The writer creates the parent directory first and replaces the file atomically.
- The task-creation sequence is fixed: (1) read materialized files, (2) validate and compile, (3) persist the contract and verify the file hash, (4) persist the project binding if missing, (5) construct `IngestSnapshot`, (6) calculate the task hash, (7) enqueue. Any failure before step 7 enqueues nothing.
- `load_template_snapshot()` reads only the requested `<contract_hash>.json`, recomputes the canonical hash, and raises `template_unavailable` on missing file, malformed JSON, or hash mismatch. It never reads current template files.
- `IngestSnapshot` is declared once in `src/types.py`; `KnowledgeTask.ingest_snapshot` stores its JSON representation. The five duplicated template fields on `KnowledgeTask` are retained only as compatibility projections and must equal the embedded snapshot. `KnowledgeTask.from_dict()` rejects disagreement rather than choosing one value.
- `src/services/ingest.py:create_ingest_snapshot()` is the sole new snapshot-producing seam. HTTP, CLI, MCP, batch, and direct synchronous calls delegate to it; queue retry and dead-letter recovery consume its serialized result. Execution/retry paths never call a template resolver.
- Canonical page identity is `(project_id, canonical_source_identity, wiki_type)`. The existing page lookup/update path must be named in the task and used before slug generation; `contract_hash` affects task identity only, never page identity.
- Publication uses the existing KC `PublicationState`, `PublicationBatch`/`PublicationGate`, `AtomicContext`, and `vector.pending` mechanisms. `PublicationIntent` is one extension of that existing durable state, not a second publication state machine or writer.
- Remote distribution in Task 10 means an optional read-only center index plus verified bundle source; it does not implement publishing, revocation, or marketplace governance. The acceptance criterion is “a center descriptor resolves to a verified local bundle”.

## Domain Terms

- **Scenario template:** the instance-level package that describes purpose, allowed Wiki types, page templates, and stage instructions.
- **Template snapshot:** the immutable identity captured for one ingest task: template id, version, file hash, and compiled contract hash.
- **Template contract:** the validated runtime projection consumed by pipeline stages; it is data, not a second template source.
- **Page template:** the existing Markdown slot template for one Wiki type.

## File Map

- Create `src/templates/contract.py`: frozen `TemplateSnapshot`, `TemplateContract`, and stage projections.
- Create `src/templates/compiler.py`: compile the current project-materialized template and reject inconsistent type/slot/route definitions.
- Modify `src/templates/loader.py`: expose metadata version and canonical content hashing while preserving flat legacy templates.
- Modify `src/templates/__init__.py`: expose only the public template seam.
- Modify `src/project/identity.py` and `src/cli_ext/project_cmd.py`: persist and initialize the template binding.
- Modify `src/types.py`: persist `IngestSnapshot` fields on `KnowledgeTask` with backward-compatible defaults.
- Modify `src/services/ingest.py`: resolve the snapshot before enqueueing and include it in task identity.
- Modify: `src/queue/service.py`, `src/queue/queue.py`, and `src/services/ingest.py` for task serialization, reload, retry, and idempotency propagation.
- Modify `src/pipeline/ingest.py`, `src/pipeline/analyzer.py`, and `src/pipeline/generator.py`: consume the snapshot/contract and remove duplicated template-driven type/slot rules.
- Modify: `src/pipeline/readiness_gate.py` and `src/kc/integrity/gates.py`; these are the existing structural/readiness gate seams. Do not create a `ReviewerStage` module.
- Add tests beside the touched modules under `tests/test_templates/`, `tests/test_project/`, `tests/test_services/`, and `tests/test_pipeline/`.

---

### Task 1: Add the immutable template contract and canonical compiler

**Files:**
- Create: `src/templates/contract.py`
- Create: `src/templates/compiler.py`
- Create: `src/templates/snapshot.py`
- Modify: `src/templates/loader.py`
- Modify: `src/templates/__init__.py`
- Test: `tests/test_templates/test_contract.py`
- Test: `tests/test_templates/test_compiler.py`

**Interfaces:**
- `TemplateSnapshot(template_id: str, template_version: str, template_hash: str, contract_hash: str, snapshot_path: str)`
- `TemplateContract` is frozen and contains `allowed_types`, `slot_rules`, `routes`, `purpose`, `analyzer_instructions`, and `generator_instructions`.
- `compile_project_template(project_root: Path, *, template_id: str, template_version: str, expected_hash: str | None = None) -> tuple[TemplateSnapshot, TemplateContract]`
- `TemplateContract.analyzer_context() -> dict`
- `TemplateContract.generator_context(wiki_type: str) -> dict`
- `persist_template_snapshot(project_root: Path, contract: TemplateContract) -> TemplateSnapshot`
- `load_template_snapshot(project_root: Path, contract_hash: str) -> TemplateContract`

- [ ] Write tests for a valid project template, deterministic hashes, missing prompt files, invalid page-template headers, unknown types, and schema/page-template mismatch.
- [ ] Run `PYTHONPATH=. pytest tests/test_templates/test_contract.py tests/test_templates/test_compiler.py -v`; confirm the new tests fail before implementation.
- [ ] Extend the existing `Template` metadata with `version`, defaulting legacy templates to `compat`, and add canonical hashing over sorted relative paths plus UTF-8 file bytes.
- [ ] Compile existing `schema.md`, `purpose.md`, and `.wiki-templates/*.md`; read optional `analyzer.prompt.md` and `generator.prompt.md`. If absent, store an empty instruction string and use the existing code prompt as the sole fallback.
- [ ] Derive type and route data only from the existing schema registry and slot data only from the existing page-template parser; do not add a second type or route registry.
- [ ] Verify every allowed type has exactly one route and page-template slot definition, and every route/page-template type is declared by the schema.
- [ ] Persist the complete compiled contract JSON under `.llm-wiki/template-snapshots/<contract_hash>.json`; the file contains all text needed for retry, not only the hash.
- [ ] Reject a missing or mismatched expected hash with a specific validation error.
- [ ] Run the targeted tests and commit `feat(templates): add immutable template contract`.

### Task 2: Bind templates to projects and create compatibility snapshots

**Files:**
- Modify: `src/project/identity.py`
- Modify: `src/cli_ext/project_cmd.py`
- Modify: `src/templates/loader.py`
- Modify: `src/types.py`
- Test: `tests/test_cli_ext/test_cmd_project.py`
- Test: `tests/test_templates/test_project_binding.py`

**Interfaces:**
- `resolve_project_template(project_root: Path) -> tuple[TemplateSnapshot, TemplateContract]`
- `IngestSnapshot` contains `instance_id`, `source_identity`, `source_version`, `template_snapshot`, and `pipeline_contract_version`.
- `KnowledgeTask` gains optional persisted fields `snapshot_path`, `template_id`, `template_version`, `template_hash`, and `contract_hash`.

- [ ] Write tests proving a new project records the selected template, an old project resolves to `general@compat`, and malformed binding fails without rewriting project data.
- [ ] Run the targeted tests and confirm failure.
- [ ] On project initialization, apply the existing scenario template, compile the effective project files, and persist the binding in `.llm-wiki/project.json`.
- [ ] Define `general@compat` as a loader alias for the current project-materialized legacy files, not as a new bundled directory. Compile and persist its contract on first project touch, then record the binding; do not rewrite Wiki pages.
- [ ] Use backward-compatible defaults when loading `KnowledgeTask` without template fields.
- [ ] Run `PYTHONPATH=. pytest tests/test_cli_ext/test_cmd_project.py tests/test_templates/test_project_binding.py -v` and commit `feat(project): pin scenario template compatibility binding`.

### Task 3: Thread one snapshot through every ingestion entry point and idempotency key

**Files:**
- Modify: `src/services/ingest.py`
- Modify: `src/types.py`
- Modify: `src/queue/queue.py`
- Modify: `src/utils/idempotency.py`
- Modify: `src/pipeline/ingest.py`
- Modify: `src/server/routes/ingest.py`, `src/mcp_server/main.py`, `src/cli_ext/batch_cmd.py`, and `scripts/batch_executor.py` only at their existing task-construction call sites.
- Test: `tests/test_services/test_ingest_template_snapshot.py`
- Test: `tests/test_utils/test_idempotency.py`
- Test: `tests/test_pipeline/test_ingest_template_snapshot.py`

**Interfaces:**
- `create_ingest_snapshot(project_id: str, source: str, *, round_key: str = "") -> IngestSnapshot`
- `IngestSnapshot` is serialized as task data and is not reconstructed from current project files during execution.
- Internal execution entry points receive `IngestSnapshot`; they do not resolve the current template again.
- `generate_task_hash(..., contract_hash: str = "") -> str` keeps the old hash when the new argument is empty.
- `create_ingest_snapshot(...)` persists the contract before enqueue and returns a task carrying `snapshot_path` and `contract_hash`.

- [ ] Write tests for the shared service seam plus HTTP (`src/server/routes/ingest.py`), MCP (`src/mcp_server/main.py`), batch (`src/cli_ext/batch_cmd.py`, `scripts/batch_executor.py`), direct (`src/pipeline/ingest.py`), queue reload, and dead-letter paths using the same snapshot; test that different contract hashes produce different task hashes.
- [ ] Run the targeted tests and confirm failure.
- [ ] Resolve and compile the template in `enqueue_source()` before calling `enqueue_task()`.
- [ ] Persist `snapshot_path`, `template_id`, `template_version`, `template_hash`, and `contract_hash` on the queue task and restore them from JSON with old-task defaults.
- [ ] Add `contract_hash` to the idempotency input after the existing project/source fields; preserve old behavior when absent.
- [ ] Audit and test the complete call chain: HTTP/MCP/batch/direct entry points delegate to `src/services/ingest.py`; `src/queue/queue.py`, `src/queue/service.py`, `src/pipeline/service.py`, `src/pipeline/dispatcher.py`, and `src/queue/scheduler.py` only forward or deserialize the snapshot. Retry and dead-letter recovery load the stored snapshot instead of calling the resolver.
- [ ] Reject a missing historical snapshot or changed hash as `template_unavailable`; never fall back to the latest version during retry.
- [ ] Define and test the collision policy at `src/wiki/storage/page_writer.py`: resolve `(project_id, canonical_source_identity, wiki_type)` before slug generation, update that page when present, and create a page only when absent. A changed contract changes task identity but not page identity.
- [ ] Run service, queue, idempotency, and pipeline tests and commit `feat(ingest): carry pinned template snapshots through tasks`.

### Task 4: Inject stage-specific PromptContext and remove duplicated template rules

**Files:**
- Modify: `src/pipeline/analyzer.py`
- Modify: `src/pipeline/generator.py`
- Modify: `src/pipeline/ingest.py`
- Modify: `src/pipeline/analyzer.py` for `ANALYZER_PROMPT` and analyzer prompt construction; modify `src/pipeline/generator.py` for `GENERATOR_PROMPT`, `_DEPTH_BY_TYPE`, and all `required_slots_by_type` call sites. Remove only scenario-template duplicates; retain framework defaults.
- Test: `tests/test_pipeline/test_template_prompt_context.py`

**Interfaces:**
- `build_analyzer_prompt(source_text: str, context: dict) -> str`
- `build_generator_prompt(candidate, context: dict) -> str`
- Prompt context is built only from the task's `TemplateContract`.

- [ ] Write tests proving two contracts produce different stage prompts, source text cannot alter contract fields, and no prompt is built without a snapshot.
- [ ] Run the targeted tests and confirm failure.
- [ ] Add explicit delimiters for system/template rules and untrusted source content.
- [ ] Pass only analyzer fields to Analyzer and only per-type generator fields to Generator.
- [ ] Remove or replace hardcoded template-driven type lists, slot lists, and route decisions; retain only framework-level built-in behavior that is not scenario-specific.
- [ ] Preserve the existing fake-provider and retry behavior.
- [ ] Run `PYTHONPATH=. pytest tests/test_pipeline/test_template_prompt_context.py tests/test_pipeline/test_ingest_kc_mainline.py -v` and commit `feat(pipeline): inject instance template context into llm stages`.

### Task 5: Enforce the contract at Reviewer and final Wiki boundaries

**Files:**
- Modify: `src/pipeline/readiness_gate.py` for the pre-generator structural gate
- Modify: `src/kc/integrity/gates.py` for candidate/evidence structural validation
- Modify: `src/pipeline/ingest.py`
- Modify: `src/wiki/core/types.py` for template provenance round-trip
- Modify: `src/wiki/storage/page_writer.py` for the narrow pre-commit contract check and canonical page lookup/update
- Test: `tests/test_pipeline/test_template_gates.py`
- Test: `tests/test_wiki/test_template_provenance.py`

**Interfaces:**
- `validate_candidate(contract: TemplateContract, candidate) -> None`
- `validate_page(contract: TemplateContract, page: WikiPage) -> None`

- [ ] Write tests for illegal type, missing required slot, unknown slot, missing route, invalid evidence, and source prompt injection.
- [ ] Run the targeted tests and confirm failure.
- [ ] Gate Analyzer output before Generator and Generator output before `commit_ingest()`.
- [ ] Reject invalid output before any Wiki/index/vector write.
- [ ] Validate the final page's resolved route and page type against the contract before `commit_ingest()`; preserve existing `custom_type`/schema behavior.
- [ ] Store `template_id`, `template_version`, and `contract_hash` in the existing page provenance or `_ko_extra` round-trip path; do not add a parallel writer.
- [ ] Verify normal pages still use exactly one `commit_ingest()` and existing vector pending behavior.
- [ ] Run targeted pipeline/wiki tests and commit `feat(pipeline): enforce compiled template contract before commit`.

### Task 6: Add compatibility rollout, diagnostics, and migration controls

**Files:**
- Modify: `src/templates/loader.py`
- Modify: `src/cli_ext/project_cmd.py`
- Modify: `src/cli_ext/project_cmd.py` for dry-run and explicit project-template upgrade commands; do not create or select another template CLI module.
- Modify: `src/services/ingest.py`
- Test: `tests/test_cli_ext/test_scenario_templates.py`
- Test: `tests/test_services/test_ingest_template_migration.py`
- Docs: `docs/wiki-template-field-guide.md`, `docs/design-doc-driven-pipeline.md`

**Interfaces:**
- `template status` reports binding, version, current hash, and validation errors without changing files.
- `template upgrade <version>` changes the project binding only after compilation succeeds.
- `template rebuild --template-version <version>` is explicit and never runs as part of ordinary ingest.

- [ ] Write tests for `general@compat`, invalid legacy templates, dry-run upgrade, explicit upgrade, and old-page preservation.
- [ ] Run the targeted tests and confirm failure.
- [ ] Add a compatibility mode that records diagnostics but does not block legacy projects until their template is compiled successfully.
- [ ] Make strict contract validation the default for newly created or explicitly upgraded projects.
- [ ] Keep legacy pages unchanged; record the selected template only for new writes or explicit rebuilds.
- [ ] Log `template_id`, `template_version`, `contract_hash`, and validation outcome for every ingest task.
- [ ] Add one fixed novel fixture and one fixed research fixture with expected final Wiki type, route, and required slots; assert the final pages differ by scenario, not only their Prompts.
- [ ] Document that page provenance is construction lineage, not claim-level attribution.
- [ ] Run the full touched-area suite and commit `docs(templates): document compatible template migration`.

## Rollout and Stop Conditions

1. Deploy Task 1–2 with no pipeline behavior change; only compile and record diagnostics.
2. Enable snapshot persistence and contract-aware idempotency in Task 3.
3. Enable PromptContext in shadow/diagnostic mode; compare old and new prompts before strict rejection.
4. Enable strict gates for new projects and explicitly upgraded projects.
5. Expand strict mode to legacy projects only after their compile diagnostics are clean.

Stop the rollout if any of these occur:

- An existing project silently switches template version.
- A retry resolves the latest template instead of its stored snapshot.
- A template change creates duplicate pages for the same project/source/type.
- A rejected candidate writes Wiki, index, vector, or audit state that claims success.
- HTTP, CLI, queue, MCP, batch, and direct ingestion produce different template identities.
- Existing page read/write loses template provenance or unrelated frontmatter.

## Final Acceptance

```text
project A + novel template  → novel Wiki structure
project B + research template → research Wiki structure
same project + same source + same contract → one idempotent task
same source + different contract → distinct task identity
template upgrade → new ingests only; old pages unchanged
retry after template file change → uses original snapshot or fails closed
invalid type/slot/route → no Wiki/index/vector commit
all ingestion entry points → same resolver and snapshot contract
same project + same source + same Wiki type + changed contract → update existing page, no duplicate page
fixed novel/research fixtures → different final types/routes/slots, not only different Prompts
```

After implementation, run:

```powershell
$env:PYTHONPATH = "."
python -m pytest tests/test_templates/ tests/test_cli_ext/test_scenario_templates.py tests/test_services/test_ingest_template_snapshot.py tests/test_pipeline/test_template_prompt_context.py tests/test_pipeline/test_template_gates.py tests/test_wiki/test_template_provenance.py --import-mode=importlib -v
python -m pytest tests/test_pipeline/ tests/test_services/ tests/test_queue/ tests/test_wiki/ --import-mode=importlib
```

Then run the project server smoke test required by `AGENTS.md` if any change touched `src/cli.py`, `src/server/`, or top-level wiki imports. Run `graphify update .` after code changes.

---

## Authorized Scope Extension: Governance and End-State Reliability

The following six areas were previously post-MVP. They are now explicitly in scope. They do not replace or widen the scenario-template goal; they harden its security, cost, semantic quality, remote distribution, evidence lifecycle, and cross-store publication behavior.

### Task 7: Template permission and security governance

**Files:**
- Modify: `src/permissions.py`
- Modify: `src/templates/loader.py`
- Modify: `src/templates/compiler.py`
- Modify: `src/cli_ext/project_cmd.py` only for the existing project-template update command
- Test: `tests/test_templates/test_security.py`
- Test: `tests/test_permissions/test_template_permissions.py`

**Interfaces:**
- `validate_template_source(root: Path, *, owner_project: Path | None = None) -> None`
- `can_edit_template(agent_type, project_id) -> bool`

- [ ] Write failing tests for path traversal, symlink escape, unsupported files, oversized prompt text, unauthorized edit, and cross-project template mutation.
- [ ] Reject template files outside the allowed template root, symlink escapes, executable files, and unapproved binary content.
- [ ] Restrict template edits in the existing `project_cmd.py` path to `AgentType.ORCHESTRATOR`/the existing project-admin permission; all other agents can only read/compile. No new HTTP mutation route is added.
- [ ] Treat remote or user-authored template text as configuration, not as authority to change permissions, tools, or pipeline routing.
- [ ] Validate Prompt size and allowed placeholders before compilation; never scan source documents as if they were template configuration.
- [ ] Run targeted security tests and commit `fix(templates): enforce template permissions and source boundaries`.

### Task 8: Prompt budget, cache, and cost controls

**Files:**
- Modify: `src/templates/compiler.py`
- Modify: `src/pipeline/analyzer.py`
- Modify: `src/pipeline/generator.py`
- Modify: `src/config.py`
- Modify: `src/services/ingest.py`
- Test: `tests/test_templates/test_template_cache.py`
- Test: `tests/test_pipeline/test_prompt_budget.py`

**Interfaces:**
- `compile_project_template(...)` returns a cached immutable contract keyed by effective content hash.
- `estimate_prompt_tokens(context: dict) -> int`
- `enforce_ingest_budget(project_id: str, estimated_tokens: int) -> None`

- [ ] Write failing tests for cache reuse, hash invalidation, oversized Prompt rejection, and per-project budget exhaustion.
- [ ] Cache only compiled contracts; never cache a mutable project file or a provider response.
- [ ] Apply a fixed Prompt token ceiling before the LLM call and fail closed with a diagnostic when exceeded.
- [ ] Reuse existing budget/cost configuration and logging; do not add a second billing system.
- [ ] Preserve existing retry limits and ensure rejected Prompt size does not trigger unbounded LLM retries.
- [ ] Run targeted tests and commit `feat(templates): add prompt budget and contract cache controls`.

### Task 9: Semantic quality scoring without weakening structural Gates

**Files:**
- Modify: `src/pipeline/readiness_gate.py`
- Modify: `src/services/quality.py`
- Modify: `src/kc/integrity/gates.py`
- Modify: `src/pipeline/ingest_report.py`
- Test: `tests/test_pipeline/test_semantic_quality.py`
- Test: `tests/test_services/test_quality.py`

**Interfaces:**
- `score_template_fit(contract: TemplateContract, page: WikiPage) -> QualityResult`
- `QualityResult(score: float, dimensions: dict[str, float], status: str)`

- [ ] Write failing tests for missing scenario concepts, slot-content mismatch, unsupported claims, and a structurally valid but semantically weak page.
- [ ] Keep semantic scoring separate from type/slot/evidence validity; a low semantic score must never make an invalid page valid.
- [ ] Store the fixed rubric in `TemplateContract.semantic_rubric`; each dimension is a named required slot/concept with a weight, and the default threshold is `0.70` only when `quality.enforce_template_fit` is explicitly enabled. Return `not_evaluable` when no rubric dimension is declared.
- [ ] Record score, rubric version, and evaluation status in the existing ingest report; do not claim semantic truth from the score.
- [ ] Make rollout diagnostic-only first; enforcement is enabled only by the existing project quality setting `quality.enforce_template_fit` and applies only to new/upgraded template bindings. A missing setting remains diagnostic-only.
- [ ] Run targeted tests and commit `feat(quality): score template fit without bypassing structural gates`.

### Task 10: Optional remote template distribution

**Files:**
- Create: `src/templates/remote.py`
- Modify: `src/templates/loader.py`
- Modify: `src/templates/contract.py`
- Modify: `src/config.py`
- Test: `tests/test_templates/test_remote_templates.py`

**Interfaces:**
- `resolve_template_ref(ref: str, *, index_url: str | None = None, offline: bool = True) -> RemoteTemplateDescriptor`
- `fetch_template_bundle(ref: str, *, destination: Path) -> Path`
- `verify_template_bundle(path: Path, expected_hash: str, signature: str | None = None) -> None`
- `load_template(ref: str, *, offline: bool = True) -> Template`

- [ ] Write failing tests for offline default, invalid ref, hash mismatch, unavailable remote, and verified bundle reuse.
- [ ] Define the minimal read-only center index contract as JSON `{ref, version, bundle_url, content_hash, signature}`; `resolve_template_ref()` accepts only that contract and rejects missing fields or a descriptor whose `ref` does not match the request.
- [ ] Keep remote loading disabled by default; an instance must opt in through an explicit template reference.
- [ ] Download only into a staging directory, validate the bundle, then atomically promote it into the local template cache.
- [ ] Require the expected content hash; if signature verification is configured, reject an absent or invalid signature.
- [ ] Persist the verified local bundle before creating an `IngestSnapshot`; retries never fetch “latest”.
- [ ] Ensure remote failure falls back only to an already verified local copy, never to an unverified or newer template.
- [ ] Treat the remote reference as a read-only center index lookup plus content-addressed bundle URL/path. This task does not implement publishing, revocation, or marketplace behavior. The local verified bundle is then passed through the same `load_template()` and compiler path as built-in templates.
- [ ] Run targeted tests and commit `feat(templates): support verified optional remote bundles`.

### Task 11: Evidence and L3 publication lifecycle

**Files:**
- Modify: `src/kc/contracts/evidence.py`
- Modify: `src/kc/compiler/evidence.py`
- Modify: `src/kc/compiler/verify.py`
- Modify: `src/kc/evidence/storage.py`
- Modify: `src/kc/integrity/identity_key.py`
- Modify: `src/pipeline/ingest.py`
- Test: `tests/test_kc/test_evidence_lifecycle.py`
- Test: `tests/test_pipeline/test_evidence_publication.py`

**Interfaces:**
- Evidence states are `anchored → structurally_verified → entailed | unsupported | needs_human_review`.
- `EvidenceIdentity(source_id, source_version, block_id, quote_hash)`
- Extend the existing KC publication record with `PublicationIntent(task_id, page_id, contract_hash, evidence_version, state)`; do not add a parallel publication enum or gate.

- [ ] Write failing tests for source update invalidation, stale evidence, unsupported claims, human review, and retrying the same publication intent.
- [ ] Keep L1 structural verification distinct from semantic `entailed`; no L1 change may claim truth.
- [ ] Store evidence identity using source version and quote hash; source mutation makes the old evidence stale instead of silently valid.
- [ ] Create one intent record per Wiki commit attempt in the existing `PublicationBatch`/`PublicationGate` durable state, keyed by `task_id + page_id`; retries reopen the same record.
- [ ] Reconcile incomplete intents through the existing KC recovery path and prevent a stale intent from publishing a newer evidence version.
- [ ] Preserve the existing page-level provenance limitation; do not infer claim-to-page attribution without an explicit mapping.
- [ ] Run targeted tests and commit `feat(kc): add evidence lifecycle and publication intent`.

### Task 12: Writer/index/vector publication consistency

**Files:**
- Modify: `src/wiki/storage/page_writer.py`
- Modify: `src/pipeline/stages/indexer.py`
- Modify: `src/vector/pending.py`
- Modify: `src/pipeline/ingest.py`
- Modify: `src/wiki/core/paths.py`
- Test: `tests/test_wiki/test_publication_recovery.py`
- Test: `tests/test_vector/test_publication_intent.py`

**Interfaces:**
- `commit_ingest()` remains the only public final commit entry point.
- Extend the existing KC publication-record API with `record_publication_intent(...) -> PublicationIntent` and `reconcile_publication_intent(...) -> ReconcileResult`; do not create a second writer or publication state machine.

- [ ] Write failing tests for wiki success/index failure, index success/vector failure, crash before commit, crash after commit, duplicate retry, and stale vector removal.
- [ ] Use this fixed order: create/update the durable intent as `pending`; atomically write Wiki page; mark `wiki_written`; append/reconcile index; mark `index_written`; upsert/reconcile vector; mark `published`. Any exception records `failed` with the completed-step list. The intent is written before the first side effect.
- [ ] Record the durable intent through the existing `PublicationBatch`/`PublicationGate` storage before the first side effect; update the same record after Wiki, index, and vector steps.
- [ ] Make reconciliation idempotent: it may complete missing index/vector work or mark the intent failed, but must not duplicate pages or index rows.
- [ ] Reuse existing `AtomicContext`, `safe_write`, `DELETE_SENTINEL`, `PublicationBatch`/`PublicationGate`, and vector pending mechanisms; do not introduce a second writer or state machine.
- [ ] Preserve existing vector dimension/provider behavior and page hash conflict checks.
- [ ] Run targeted tests, then the required server `/health` smoke test, and commit `feat(publish): reconcile wiki-index-vector publication intents`.

## Extended Acceptance

The complete scope passes only when all of the following are true:

- An unauthorized actor cannot mutate an instance template or escape its template root.
- Identical compiled contracts are cached; oversized Prompt contexts are rejected before LLM calls.
- Semantic quality is measurable but cannot bypass structural evidence or schema Gates.
- Remote templates are opt-in, hash-verified, locally persisted, and offline-safe.
- Evidence becomes stale when its source version changes; `entailed` is never inferred from structural verification.
- A crashed Wiki/index/vector publication can be reconciled idempotently without duplicate pages, index rows, or vector records.
- The original instance-template objective still holds across two different project templates and all ingestion entry points.

Execution order and dependencies are fixed: Tasks 7 and 8 depend on Task 1; Task 9 depends on Tasks 1 and 5; Task 10 depends on Tasks 1 and 7; Task 11 depends on the existing KC publication records and Tasks 3 and 5; Task 12 depends on Task 11. Implement in that order after Tasks 1–6. If any task fails, stop that task and do not silently weaken the existing L1/L2 contract to make it pass.
