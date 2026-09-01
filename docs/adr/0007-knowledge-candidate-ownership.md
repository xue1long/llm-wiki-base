# ADR-0007: KnowledgeCandidate domain types own by `src.knowledge`

- **Status**: Proposed (2026-09-01)
- **Supersedes**: (none — this is the first ADR on knowledge/kc boundary)
- **Related**: `docs/superpowers/plans/2026-09-01-kc-knowledge-boundary.md`

## Context

`src/kc` (Knowledge Compiler) and `src/knowledge` (Knowledge OS) co-evolved during the 2026-08 novel-wiki migration. Domain types (`KnowledgeObject`, `KnowledgeCandidate`, `KnowledgeMode`) appear in both packages:

| Type | In `src/kc` | In `src/knowledge` |
|---|---|---|
| `KnowledgeObject` | consumed via import | defined in `core/object.py` |
| `KnowledgeCandidate` | consumed via import | defined in `core/candidate.py` |
| `KnowledgeMode` | re-defined 3 places | defined 1 place |

`KnowledgeMode` has **two domain-level definitions (both 3-value, consistent) plus one alias shadow**:

1. `src/kc/contracts/mode.py:22` — 3 values (`observed`/`synthesized`/`unknown`) — domain layer definition (duplicated)
2. `src/knowledge/core/candidate.py:76` — 3 values (`observed`/`synthesized`/`unknown`) — **canonical** domain definition
3. `src/kc/views/book/contract.py:302` — `KnowledgeMode = _ALLOWED_KNOWLEDGE_MODES` (type-ignored reassignment) — **alias shadow** that turns `KnowledgeMode` into a 2-value frozenset at the `book_view` import path

The alias on line 302 is a **bug**: any code that does `from src.kc.views.book.contract import KnowledgeMode` gets the 2-value frozenset instead of the canonical 3-value Literal — polluting the global `KnowledgeMode` namespace.

The 2-value business rule itself (`book_view` rejects `"unknown"`) is intentional: `"unknown"` is the fail-closed default for `KnowledgeCandidate` and should not propagate to a rendered book — that data should be handled by KC's state machine, not by book view.

Cross-package dependency matrix shows **one** file importing back (`src/knowledge/core/mode_extension.py:22` re-exports `src/kc.contracts.mode`) — this is a vestigial C-4 transition shim, not a real coupling.

## Decision

1. **`KnowledgeCandidate` and its enum types** (`KnowledgeMode`, `CandidateStatus`, `KnowledgeType`) **are owned by `src.knowledge.core.candidate`** as the single source of truth.

2. **`KnowledgeMode` value space is fixed at 3 values** (`observed`/`synthesized`/`unknown`) in the domain layer. **Book view keeps its 2-value validation** (`_ALLOWED_KNOWLEDGE_MODES`) as a business rule, but does **not** redefine `KnowledgeMode` as that 2-value frozenset (the alias on line 302 is the bug).

3. **Delete `src/knowledge/core/mode_extension.py`** (40-line re-export shim; the C-4 transition it served is done).

4. **`src/knowledge/__init__.py` exposes a public API whitelist**, mirroring `src/kc/__init__.py` style.

5. **`src/kc/contracts/mode.py` imports `KnowledgeMode` from `src.knowledge.core.candidate`** instead of redefining it.

## Consequences

### Positive

- Cross-package coupling: `knowledge → kc` goes from **1 file** to **0 files**.
- `KnowledgeMode` value space: from **2 definitions (1 domain + 1 alias shadow)** to **1 canonical definition**.
- The `KnowledgeMode` symbol is no longer aliased by `book_view` — global namespace is consistent.
- `src/knowledge` becomes a self-contained domain layer; tests for it no longer need `src/kc`.

### Negative

- Legacy import path `from src.knowledge.core.mode_extension import KnowledgeMode` is removed (verified with grep: 0 external imports).
- Book view keeps rejecting `"unknown"` (intentional, unchanged) — no test fixtures change.

### Risks (mitigated in plan §4)

- **R1**: `parse_llm_output_with_mode` crosses package boundary on import — must add regression test for 5 LLM truncation scenarios.
- **R2**: `src/knowledge/__init__.py` whitelist could introduce cycle if `src/kc` does `from src.knowledge import ...` at module load — kc must keep using `from src.knowledge.core.candidate import ...` at entry points.

## Alternatives Considered

### A. Keep `KnowledgeMode` in `src/kc/contracts/mode.py` (single source of truth there)

**Rejected.** `src/kc` is the compiler/adapter layer, not the domain layer. Domain enums do not belong in `kc/contracts/` (which holds pure data contracts like `Evidence`).

### B. Merge `knowledge` into `kc` (reverse absorption)

**Rejected.** `src/knowledge` is more stable (kernel.py is a single facade with no stateful business logic); 100+ files depend on it. Absorbing `knowledge` into `kc` would be a breaking change with no upside.

### C. Keep status quo, document the inconsistency

**Rejected.** Production data can be silently rejected (book view rejects `"unknown"`). Documentation does not fix the bug.

### D. Move `KnowledgeMode` to a new `src/domain_types/` package

**Rejected.** Adds a third package without removing any dependency. Adds ceremony without solving the problem. YAGNI.

## References

- `docs/codebase-graph-stats-2026-09-01.md` §5.5 — coupling matrix shows `kc ↔ knowledge` I=0.53/0.47 (highest bidirectional)
- `docs/codebase-dup-analysis-2026-09-01.md` — pattern for "extract shared utility" methodology applied here
- `src/kc/contracts/mode.py:88-158` — `parse_llm_output_with_mode` algorithm (unchanged by this ADR)
- `src/knowledge/core/candidate.py:76` — canonical `KnowledgeMode` definition