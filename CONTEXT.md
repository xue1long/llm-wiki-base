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

## Book domain concepts

| Term | Canonical meaning | Owner |
|---|---|---|
| `BookEditorialState` | 持久化的 Book 编辑输入：页面裁决、章节归属、canonical outline 和稳定章节 ID；不是一次构建的临时产物。 | `src/kc/views/book/wiki` |
| `Canonical Book` | 一个知识域面向人阅读的正文权威容器；包含卷、章、节和章节来源范围。 | `src/kc/views/book/wiki` |
| `BookRelease` | 绑定 Wiki snapshot 和 BookEditorialState revision 的不可变阅读版本。 | `src/kc/views/book/wiki` |
| `TutorialPath` | Book 之上的引用式阅读路径；保存章节/小节顺序、任务和检查点，不拥有章节正文。 | `src/kc/views/book/wiki` |
| `PageDisposition` | 页面进入 Book 的裁决：`include`、`duplicate`、`conflict`、`exclude` 或 `unresolved`。 | `src/kc/views/book/wiki` |
| `BookFreshness` | Book 相对于最新 Wiki snapshot 的状态：`fresh`、`stale`、`building` 或 `failed`；不等同于 release 状态。 | `src/kc/views/book/wiki` |
| `SectionStatus` | 章节小节状态：`normal`、`disputed`、`blocked` 或 `editorial`。 | `src/kc/views/book/wiki` |

## LLM provider concepts

| Term | Canonical meaning | Owner |
|---|---|---|
| `Provider` | 一个可被知识库流水线调用的模型服务配置，包含服务身份、协议类型、连接地址、凭据和默认模型。 | `src.llm` |
| `Provider type` | Provider 使用的连接/兼容协议分类；它不是供应商名称，多个供应商可以共享同一类型。 | `src.llm.types.ProviderConfig` |
| `Provider preset` | 设置页用于快速填充 Provider 类型、地址和模型默认值的品牌/场景快捷方式；它不是 Provider 身份，也不落入 Provider 配置。 | `web/js/views/settings.js` |
| `Default Provider` | 当前用户级配置中，供未显式指定 Provider 的 LLM 调用解析使用的 Provider；显式选择优先于旧环境兼容值。 | `src.llm.registry.ProviderRegistry` |
| `Default model` | Provider 上保存的默认聊天模型或默认嵌入模型；它不是远端实时模型目录。 | `src.llm.types.ModelInfo` |
| `Connection test` | 针对已保存 Provider 的可达性与最小响应兼容性检查，不等同于一次知识库摄取。 | `src.server.routes.providers` |
| `Model discovery` | 从 Provider 端点读取可用模型目录的独立能力；首期设置页不依赖它。 | `src.server.routes.providers` |

## Skill management concepts

| Term | Canonical meaning | Owner |
|---|---|---|
| `Skill` | A self-contained agent capability package whose entry document is `SKILL.md`, with optional supporting files. | Skill manager domain |
| `Plugin` | Reserved future artifact type. In v1, `plugin.json` is rejected as `UNSUPPORTED_PLUGIN_TYPE`; executable plugins are unsupported. | Skill manager domain |
| `Source` | A mutable locator used to acquire content, such as a local directory or a future pinned public GitHub source. | Skill manager domain |
| `Artifact` | An immutable, validated Skill snapshot identified by normalized content hash and, for remote sources, resolved commit SHA. | Skill manager domain |
| `Skill Library` | The user-owned collection of validated immutable Artifacts before they are assigned to an Agent. | Skill manager domain |
| `Agent` | A local AI coding tool that consumes skills from a configured skills directory, such as Codex or Claude Code. | Skill manager domain |
| `Deployment` | An explicit assignment of one Artifact into one concrete Agent skill directory, with ownership and verification state. | Skill manager domain |
| `Managed Target` | An Agent skill directory whose ownership and installed-file manifest are known to the Skill Library. | Skill manager domain |
| `Operation` | A durable record of an import/deployment attempt; terminal states are `succeeded`, `failed`, `conflict`, or `partial_failure`. | `src.skill_manager.types` |

_Avoid_: executable plugin, installer script, implicit direct copy, marketplace (when referring to the v1 managed deployment flow).

## Acronyms

| Acronym | Meaning |
|---|---|
| KC | Knowledge Compiler (`src/kc/`) |
| KO | Knowledge Object |
| KU | Knowledge Unit (KC's projection of KO) |
| NDG | (referenced in batch_runner) — Non-Deterministic Gate, batch-level predicate |
| TLD | (referenced in audit reports) — Transitive Loop Depth |
| SCC | Strongly Connected Component |
| AGL | Agent Lightning — Microsoft RL training framework (external repo `E:\002-Pr\agent-lightning-main`). Three components: Trainer (verl + vLLM + GRPO) / Gateway (FastAPI proxy + event store) / Controller (local or K8s rollout spawner). |
| V7 | The 7-stage ingestion pipeline (`src/pipeline/v7_extract/`). Default mode is V3 (`V7_USE_V3=true`); V2 is fallback. Stages: `classify_doc` → `extract_structure` → `check_completeness` → `cluster_topics` → `fill_slots` → `extract_relations` → `commit_and_index`. |
| V7 Stage5 | The slot-filling LLM call. V2 path = `slot_filler.fill_slots` (single LLM call, all slots in one JSON). V3 path = `claim_extractor.extract_slot_claims` (per-slot, 8+1 LLM calls). For AGL training, lock to V2 via `V7_USE_V3=false`. |
| V7 Stage7 | The atomic wiki write (`wiki_writer.commit_and_index`). Writes V7 ownership 6 fields (`owner/pipeline/commit_id/pipeline_fingerprint/revision_hash/committed_at`). 4 gates: P4 (`__other__`) / needs_review / has_evidence / content_filter. |
| Rollout | One Agent Lightning execution unit = one (input, is_train, config) tuple. Lifecycle: `QUEUING` → `RUNNING` → `SUCCEEDED` / `FAILED`. Events: `model_request` (auto by Gateway) / `reward` (agent-posted) / custom. |
| Triplet | `(prompt_token_ids, response_token_ids, reward)` derived from one `model_request` event. Per-rollout-mean loss treats all triplets in one rollout as equal contributors; reward broadcasts to every triplet. |

## Cross-references

- Architecture overview: `AGENTS.md` §Architecture
- Wiki spec: `docs/guides/wiki-spec.md`
- Audit reports: `docs/codebase-graph-stats-2026-09-01.md`, `docs/codebase-dup-analysis-2026-09-01.md`
- Refactor plans: `docs/superpowers/plans/2026-09-01-batch-runner-decompose.md`, `docs/superpowers/plans/2026-09-01-kc-knowledge-boundary.md`
- Provider settings portability decision: `docs/adr/2026-09-13-provider-settings-portability.md`
- Skill Library and Agent deployment decision: `docs/adr/0010-skill-library-and-agent-deployment.md`
- Graph subgraph report: `docs/architecture/2026-09-01-graph-subgraph-report.md`
- ADRs: `docs/adr/0007-knowledge-candidate-ownership.md`
- V7 AGL 训练设计档案: `.memory/feedback-v7-agl-design-tree-2026-09-18.md`
