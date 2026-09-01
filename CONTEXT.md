# CONTEXT.md — ruflo-kb Glossary

> Project-wide glossary for the ruflo-kb knowledge-base platform.
> Terms below are pinned to a single meaning; if a term is overloaded, the **canonical** meaning is the one in this file.
> Domain enums and values listed here are authoritative.

## Core domain types (owned by `src.knowledge`)

| Term | Canonical meaning | Owner |
|---|---|---|
| `KnowledgeObject` | A persisted knowledge unit with full lifecycle, version history, and provenance. Subclassed by `KnowledgeCandidate` (transient) and `KnowledgeUnit` (KC's projection). | `src.knowledge.core.object` |
| `KnowledgeCandidate` | A transient LLM-extracted claim/evidence pair awaiting review and promotion to `KnowledgeObject`. Carries `knowledge_mode`, `failure_reason`, `status`. | `src.knowledge.core.candidate` |
| `KnowledgeMode` | Literal tag indicating whether a knowledge unit is **observed** (carries raw quotes), **synthesized** (derived), or **unknown** (fail-closed default). **Always accepts all 3 values** — `"unknown"` is never rejected. | `src.knowledge.core.candidate` |
| `CandidateStatus` | Lifecycle: `PENDING` → (review) → `VALIDATED` / `REJECTED` / `NEEDS_HUMAN_REVIEW`. | `src.knowledge.core.candidate` |
| `LifecycleState` | The state machine of a promoted `KnowledgeObject`: `PROCESSING` / `ACCEPTED` / `REJECTED` / `QUARANTINED`. | `src.knowledge.core.object` |
| `KnowledgeKernel` | Unified facade for `permissions × events × lifecycle × versions`. Stateless wrapper; agents go through this rather than touching subsystems. | `src.knowledge.kernel` |

## Pipeline concepts

| Term | Canonical meaning | Owner |
|---|---|---|
| `Collector` | Reads raw sources (PDF/DOCX/XLSX/HTML/MD/TXT/URL). | `src.collector` |
| `Analyzer` | LLM-extracts `KnowledgeCandidate` (JSON mode) or markdown (legacy mode). | `src.pipeline.analyzer` |
| `ReviewerStage` | 4 rule checks (schema, evidence, references, confidence). Routes to REJECTED/NEEDS_HUMAN_REVIEW/VALIDATED. | `src.pipeline.reviewer` |
| `CandidatePromoter` | Promotes `KnowledgeCandidate` → `KnowledgeObject` (lifecycle=PROCESSING). | `src.pipeline.promoter` |
| `Generator` | LLM-renders body slots from a `KnowledgeObject`; frontmatter is sourced from KO. | `src.pipeline.generator` |
| `Writer` | Atomic: write_page + append_index + log_event. | `src.wiki.storage.writer` |

## Wiki concepts

| Term | Canonical meaning | Owner |
|---|---|---|
| `WikiPage` | Core dataclass — frontmatter (YAML) + body (Markdown with `[[wikilinks]]`). | `src.wiki.core.types` |
| `WikiPaths` | Resolves the wiki tree (sources/entities/concepts/synthesis/_stubs). | `src.wiki.core.paths` |
| `PageType` | Enum: `source` / `entity` / `concept` / `synthesis`. | `src.wiki.core.types` |
| `Batch` | A unit of ingest work, persisted in `.index/batch_build_state.json` under FileLock. | `src.orchestrator.batch_runner` |

## Knowledge Compiler (KC) — adapter / compiler layer

| Term | Canonical meaning | Owner |
|---|---|---|
| `CandidateReviewer` | Compiles + validates a candidate via `kc_api.compile_source`; returns `ReviewResult`. | `src/kc/mainline.py` |
| `CandidatePromoter` | Promotes a validated candidate to `KnowledgeObject`. | `src/kc/mainline.py` |
| `IntegrityGate` | Pipeline of 11 Gate checks (spec §11.3). | `src/kc/integrity/orchestrator.py` |
| `check_default_closure` | 8-condition AND validation (spec §11.3). | `src/kc/integrity/closure.py` |

## Acronyms

| Acronym | Meaning |
|---|---|
| KC | Knowledge Compiler (`src/kc/`) |
| KO | Knowledge Object |
| KU | Knowledge Unit (KC's projection of KO) |
| NDG | (referenced in batch_runner) — Non-Deterministic Gate, batch-level predicate |
| TLD | (referenced in audit reports) — Transitive Loop Depth |
| SCC | Strongly Connected Component |

## Cross-references

- Architecture overview: `AGENTS.md` §Architecture
- Wiki spec: `docs/guides/wiki-spec.md`
- Audit reports: `docs/codebase-graph-stats-2026-09-01.md`, `docs/codebase-dup-analysis-2026-09-01.md`
- Refactor plans: `docs/superpowers/plans/2026-09-01-batch-runner-decompose.md`, `docs/superpowers/plans/2026-09-01-kc-knowledge-boundary.md`
- Graph subgraph report: `docs/architecture/2026-09-01-graph-subgraph-report.md`
- ADRs: `docs/adr/0007-knowledge-candidate-ownership.md`