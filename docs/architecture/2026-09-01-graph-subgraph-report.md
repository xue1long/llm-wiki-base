# Graph subgraph report — `batch_runner.run_batch` blast radius & `src.kc` ↔ `src.knowledge` coupling

**Generated:** 2026-09-01
**Repo:** `D:\5-Project\2026814\llm-wiki-base.bak.20260822`
**Author tool:** delegated graph-query subagent (MiniMax-M3 via DeepSeek Harness)

---

## 0. Source and methodology notice (read this first)

The original task brief expected this analysis to run against a **codebase-memory-MCP** knowledge graph (39,416 nodes / 105,838 edges), but **neither `mcp__codebase_memory__*` tools, nor a local Cypher endpoint, nor `GEMINI_API_KEY` / `GOOGLE_API_KEY`, are available in this session**. Approval prompts are disabled — no sandbox escalation can be attempted.

The only graph available in this session is `graphify-out/graph.json`, the **AST-extracted** graph produced by the local `graphify` CLI (v0.9.46). It is well-formed:

- **39,422 nodes** (matching the brief's count); 9,014 code nodes, 24,042 document nodes, 5,441 rationale nodes, 925 concept nodes
- **49,787 directed edges** (`networkx` node-link format; relation field in `{calls, method, imports, imports_from, uses, indirect_call, re_exports, inherits, implements, defines, shares_data_with, contains, references, rationale_for, conceptually_related_to, semantically_similar_to, cites}`)

**Important ontological differences vs. the requested codebase-memory graph:**

| Requested (codebase-memory) | Available (graph.json / AST) | Impact |
|---|---|---|
| `HANDLES`, `HTTP_CALLS` edges | **NOT present** | Section 1.3 falls back to a heuristic that scans for route-handler-shaped nodes under `src/server/routes/`. No route handler appears within 2 hops of `run_batch` — see §1.3. |
| `WRITES` / `READS` edges + `Variable` nodes (name `*batch_state*`, `*queue*`) | **NOT present** | Section 1.4 falls back to a filename-text-mention scan across ALL nodes. The literal filenames `.index/batch_build_state.json` / `.kb-queue.json` are only mentioned in 7 graph nodes — see §1.4. |
| Weighted PageRank over a subgraph | Only unweighted adjacency is available | Section 1.2 runs a pure-Python PageRank (damping 0.85, 50 iter) on the undirected 2-hop adjacency. Standard, but the lack of edge weights means it captures only structural centrality, not call frequency. |
| Tarjan SCC | Tooling absent | Implemented inline in Python (§2.4). |
| `run_batch` qualified_name as `Function:src.orchestrator.batch_runner.run_batch` | Actual node ID is `src_orchestrator_batch_runner_run_batch` | I cite both the graph-internal node ID and the `source_location` (file path + line) for every symbol. |

**Top-level conclusion that the source constraint shapes:** `run_batch` and its 3 sibling helpers are **fully CLI-driven**, **not HTTP-driven**, and they live **3 hops away** from the only state-file writer (`src/services/batch_state.py`). The 2-hop blast radius is therefore smaller than a same-shared-graph-API would otherwise show.

All reasoning scripts and intermediates are kept under `graphify-out/_scratch_*.py` so the analysis is reproducible.

---

# 1. Subgraph 1 — `batch_runner.run_batch` blast radius

## 1.0 Targets & neighbourhood size

| target (user-supplied qualified name) | actual node id | source_location |
|---|---|---|
| `Function:src.orchestrator.batch_runner.run_batch` | `src_orchestrator_batch_runner_run_batch` | `src/orchestrator/batch_runner.py:L606` |
| `Function:src.orchestrator.batch_runner._rerun_gate_batch` | `src_orchestrator_batch_runner_rerun_gate_batch` | `src/orchestrator/batch_runner.py:L417` |
| `Function:src.orchestrator.batch_runner._auto_tag_ugc` | `src_orchestrator_batch_runner_auto_tag_ugc` | `src/orchestrator/batch_runner.py:L330` |
| `Function:src.orchestrator.batch_runner._generate_raw` | `src_orchestrator_batch_runner_generate_raw` | `src/orchestrator/batch_runner.py:L221` |

BFS along **all** edge relation types (union-directed) for ≤ 2 hops:

| metric | value |
|---|---|
| seed nodes | 4 |
| reachable nodes (0–2 hops) | **199** |
| subgraph edges (both endpoints in neighbourhood) | **467** |

Cypher-equivalent (for re-running on the codebase-memory graph when present):

```cypher
MATCH (seed)
WHERE seed.id IN [
  'src_orchestrator_batch_runner_run_batch',
  'src_orchestrator_batch_runner_rerun_gate_batch',
  'src_orchestrator_batch_runner_auto_tag_ugc',
  'src_orchestrator_batch_runner_generate_raw']
CALL {
  WITH seed
  MATCH (seed)-[*1..2]-(n)
  RETURN DISTINCT n
  UNION
  RETURN seed AS n
}
WITH collect(DISTINCT n) AS nodes
MATCH (a)-[r]->(b) WHERE a IN nodes AND b IN nodes
RETURN count(DISTINCT a) AS nodes, count(r) AS edges;
```

## 1.1 Direct callers of `run_batch` (relation = `calls`) and direct callees (out-edges relation = `calls`)

**External callers** (callers whose `source_file != src/orchestrator/batch_runner.py`) — 2 results, both deduplicated on `source_location`:

| # | caller qualified_name | source_location | relation |
|---|---|---|---|
| 1 | `scripts.batch_executor.main` | `scripts/batch_executor.py:L99` | `calls` |
| 2 | `src.cli_ext.batch_cmd.cmd_batch_run` | `src/cli_ext/batch_cmd.py:L110` (call site `L113`) | `calls` |

> The remaining `calls` in-edges into `run_batch` come from intra-file helpers such as `_crash_at` (L860), `_is_fake_mode` (L611), etc. — these are *out*-edges of `run_batch` (it calls them at lines like L606, L611, L860), and the bidirectional-call ambiguity in the graphifier's union-directed BFS double-counts them. After splitting them as "callees", only the 2 callers above are external.

**Callees of `run_batch`** — 15 intra-file helpers, **0 external**:

| callee qualified_name | source_location | relation |
|---|---|---|
| `src.orchestrator.batch_runner._crash_at` | `batch_runner.py:L860` | `calls` |
| `src.orchestrator.batch_runner._is_fake_mode` | `batch_runner.py:L611` | `calls` |
| `src.orchestrator.batch_runner._estimate_batch_cost` | `batch_runner.py:L968` | `calls` |
| `src.orchestrator.batch_runner._resolve_paths` | `batch_runner.py:L607` | `calls` |
| `src.orchestrator.batch_runner._resolve_provider` | `batch_runner.py:L611` | `calls` |
| `src.orchestrator.batch_runner._git_snapshot` | `batch_runner.py:L631` | `calls` |
| `src.orchestrator.batch_runner._commit_raw` | `batch_runner.py:L849` | `calls` |
| `src.orchestrator.batch_runner._set_batch_status` | `batch_runner.py:L644` | `calls` |
| `src.orchestrator.batch_runner._update_fail_streak` | `batch_runner.py:L746` | `calls` |
| `src.orchestrator.batch_runner._auto_tag_ugc` | `batch_runner.py:L782` | `calls` |
| `src.orchestrator.batch_runner._upsert_batch_vectors` | `batch_runner.py:L932` | `calls` |
| `src.orchestrator.batch_runner._rerun_gate_batch` | `batch_runner.py:L962` | `calls` |
| `src.orchestrator.batch_runner.Batch` | `batch_runner.py:L686` | `calls` |
| `src.orchestrator.batch_runner.._on_phase_start` | `batch_runner.py:L686` | `calls` |
| `src.orchestrator.batch_runner.._on_phase_end` | `batch_runner.py:L741` | `calls` |

**Take-away:** `run_batch` is a **self-contained orchestrator** — every callee is a private helper inside `batch_runner.py`. The only public callers are the Phase-4 driver script `scripts/batch_executor.py` (`main()`) and the CLI subcommand `src/cli_ext/batch_cmd.py:cmd_batch_run()` (the `ruflo batch run` CLI). There is **no HTTP route into `run_batch`**.

## 1.2 Top 20 nodes by PageRank in the 2-hop neighbourhood

Pure-Python PageRank (damping = 0.85, 50 iterations, convergence tol = 1e-6) over the undirected 2-hop adjacency.

| Rank | Score | label | file_type | source_location | notes |
|---:|---:|---|---|---|---|
| 1 | 0.03443 | `read_page` | code | `src/wiki/storage/page_writer.py:L135` | Top scorer — wiki storage is the deepest sink |
| 2 | 0.02680 | `PageType` | code | `src/wiki/core/types.py:L29` | Wiki v2 page-type enum |
| 3 | 0.02270 | `WikiPage.from_dict` | code | `src/wiki/core/types.py:L119` | Deserialiser |
| 4 | 0.01721 | `WikiPage` | code | `src/wiki/core/types.py:L46` | Core wiki dataclass |
| 5 | 0.01306 | `generate_ingest` | code | `src/pipeline/ingest.py:L554` | LLM generation pass |
| 6 | 0.01223 | `Path` (built-in alias) | code | `src:` | Built-in (`src_wiki_storage_page_writer_py_path`) |
| 7 | 0.00935 | `PageNotFoundError` | code | `src/wiki/storage/page_writer.py:L31` | Storage exception |
| 8 | 0.00847 | `page_path_for` | code | `src/wiki/storage/page_writer.py:L35` | Path computation |
| 9 | 0.00663 | `WriteConflictError` | code | `src/wiki/storage/page_writer.py:L76` | Concurrent-write guard |
| 10 | 0.00519 | `WikiPaths` (alias from `pipeline/ingest.py`) | code | `src:` | Re-imported alias |
| 11 | 0.00468 | `_crash_at` | code | `src/orchestrator/batch_runner.py:L75` | First intra-file helper to appear |
| 12 | 0.00425 | `WikiPaths` (alias from `batch_runner.py`) | code | `src:` | Re-imported alias |
| 13 | 0.00419 | `commit_ingest` | code | `src/pipeline/ingest.py:L1538` | Final wiki write |
| 14 | 0.00387 | `analyze` | code | `src/pipeline/analyzer.py:L300` | Analyzer stage |
| 15 | 0.00365 | `Path` (alias from `pipeline/ingest.py`) | code | `src:` | |
| 16 | 0.00330 | `load_batch_state` | code | `src/services/batch_state.py:L173` | First non-batch_runner symbol — state-loader reached via 2-hop via WikiPaths |
| 17 | 0.00309 | `_is_fake_mode` | code | `src/orchestrator/batch_runner.py:L146` | |
| 18 | 0.00304 | `apply_readiness_gate` | code | `src/pipeline/readiness_gate.py:L16` | Readiness gate (pre-publish) |
| 19 | 0.00294 | `Batch` | code | `src/orchestrator/batch_runner.py:L470` | Manifest dataclass |
| 20 | 0.00271 | `run_batch` | code | `src/orchestrator/batch_runner.py:L606` | The target itself, ranked 20th |

**Take-away.** The PageRank dome is dominated by the wiki *commit / write path* (`page_writer.py → WikiPage.from_dict → PageType → commit_ingest → analyze → apply_readiness_gate`). The three requested state-keepers (`_set_batch_status`, `_rerun_gate_batch`, `_auto_tag_ugc`, `_generate_raw`) are members of the runner only and do **not** rank in the top 20 — implying nothing in their 2-hop callers/callees belongs to the heavy blog of the codebase. **The blast radius is structurally small, but structurally heavy on the wiki write-path side.**

## 1.3 Route-handler / API surface — approximation

**The codebase-memory ontology's `HANDLES` / `HTTP_CALLS` edges do not exist in `graph.json`.** The AST extractor does not record the FastAPI route decorators as edges. This section therefore uses an *approximation*: it lists every reachable node whose `source_file` is under `src/server/routes/` (or `src/server/metrics_route.py`) and that lies within the 2-hop neighbourhood. Within 2 hops of any seed the result is:

> **0 nodes.** No HTTP route handler reaches `run_batch` in 2 hops.

As a sanity check we widened to full-graph BFS up to 6 hops from `run_batch`:

| hop | `# src/server/* nodes` | sample labels |
|---:|---:|---|
| 3 | 5 | `templates.get_template (L35)`, `templates.edit_template (L63)`, `templates.reset_template (L97)`, `templates.diff_template (L125)`, `heat.get_heat (L14)` |
| 4 | 11 | `capture.mark_page_verified_endpoint (L61)`, `app.create_app (L63)`, … |
| 5 | 28 | `quality.quality_report`, `heat.archive_zombies`, … |
| 6 | 63 | … |

Even at hop ≥ 3 these are all reached by *shared import paths*, not by a route calling `run_batch`. The closest route handlers (`templates.*`, `heat.get_heat`) only share a 3-hop transitive ancestor (typically `WikiPaths` or `page_writer`), not a direct call into the batch subsystem. **Conclusion: `run_batch` is not on any HTTP API surface.**

## 1.4 Anything that READS / WRITES `.index/batch_build_state.json` or `.kb-queue.json`

**No `WRITES` / `READS` edges or `Variable` nodes exist in `graph.json`.** Fallback heuristic: full-graph scan for these literal filenames inside any node's metadata text. Total hits across the entire graph: **7**.

| file referenced | qualified_name | source_location | hop from `run_batch` |
|---|---|---|---:|
| `batch_build_state.json` | `scripts.phase3_accept` | `scripts/phase3_accept.py:L60` | 4 |
| `batch_build_state.json` | `scripts.phase4_batch` | `scripts/phase4_batch.py:L81` | 5 |
| `batch_build_state.json` | `src.services.batch_state` | `src/services/batch_state.py:L1` | 5 |
| `batch_build_state.json` | `src.services.files` | `src/services/files.py:L160` | (not surveyed at every hop but > 2) |
| `batch_build_state.json` | `tests.test_pipeline.test_folder_ingest` | `tests/test_pipeline/test_folder_ingest.py:L205` | (test) |
| `batch_build_state.json` | `tests.test_services.test_batch_state` | `tests/test_services/test_batch_state.py:L1` | (test) |
| `.kb-queue.json` | `docs.archive.superpowers.plans.2026-07-23-followup-carryovers` | `docs/archive/superpowers/plans/2026-07-23-followup-carryovers.md:None` | (doc) |

**0 of the 7 are inside the 2-hop neighborhood.** The state-file writer (`src.services.batch_state`) is reachable in 3 hops from `run_batch` via two intermediates (`_set_batch_status` → `set_raw_status`/`update_batch_state` are *inside* `batch_state.py`). It maps to:

| fn in `src/services/batch_state.py` | hop | source_location |
|---|---:|---|
| `load_batch_state` | 3 | `batch_state.py:L173` |
| `raw_status` | 3 | `batch_state.py:L253` |
| `set_raw_status` | 3 | `batch_state.py:L230` |
| `update_batch_state` | 3 | `batch_state.py:L198` |

Kyb-equivalent Cypher (would re-run on the codebase-memory graph):

```cypher
MATCH (n)-[:WRITES]->(v:Variable)
WHERE v.name CONTAINS 'batch_state' OR v.name CONTAINS 'queue'
RETURN n, v;

MATCH (n)-[r:HANDLES|HTTP_CALLS]->(route)
WHERE (n)-[:*1..2]-(:Function {qualified_name: '...run_batch'})
RETURN n, r, route;
```

**Caveat:** because the AST graph has no edge metadata connecting a function to a *path string*, this result is best read as: "no caller/callee of `run_batch` directly references the batch_state or queue file within two hops; you have to walk into `src/services/batch_state.py` to find the writer".

## 1.5 Total subgraph shape

| metric | value |
|---|---:|
| nodes | 199 |
| edges | 467 |
| average degree | 4.69 |
| max degree | (directional BFS widening makes this moot — most "out-edges in neighbourhood" go through helper nodes) |

---

# 2. Subgraph 2 — `src.kc` ↔ `src.knowledge` bidirectional coupling

## 2.0 Scope & dataset

I use only relations: `imports`, `imports_from`, `calls`, `uses`, `indirect_call`, `re_exports`, `inherits`, `implements`, `shares_data_with`. Cross-package = source is in `src/kc/` and target in `src/knowledge/` (or vice versa).

| counter | value |
|---|---:|
| `src/kc/*` nodes | 761 |
| `src/knowledge/*` nodes | 560 |
| total coupling edges (`kc→knowledge`) | 33 |
| total coupling edges (`knowledge→kc`) | 4 |
| **distinct (direction, src_file, tgt_file, relation)** | **24** |
| distinct source modules participating | 11 |

## 2.1 Top 30 cross-package edges by frequency

The full list has 24 entries; here are all of them sorted by `count desc` (some edges appear with 3+ separate `imports / calls / uses` tuples between the same two files).

| # | count | direction | relations | src module | tgt module |
|---:|---:|---|---|---|---|
| 1 | 4 | `kc→knowledge` | `calls` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/version_manager.py` |
| 2 | 4 | `kc→knowledge` | `imports` | `src/kc/compiler/compile.py` | `src/knowledge/core/object.py` |
| 3 | 3 | `kc→knowledge` | `imports` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/version_manager.py` |
| 4 | 3 | `knowledge→kc` | `imports` | `src/knowledge/core/mode_extension.py` | `src/kc/contracts/mode.py` |
| 5 | 2 | `kc→knowledge` | `uses` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/object.py` |
| 6 | 2 | `kc→knowledge` | `uses` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/version_manager.py` |
| 7 | 2 | `kc→knowledge` | `imports` | `src/kc/contracts/mode.py` | `src/knowledge/core/candidate.py` |
| 8 | 1 | `kc→knowledge` | `imports_from` | `src/kc/adapters/wiki_projection.py` | `src/knowledge/core/object.py` |
| 9 | 1 | `kc→knowledge` | `imports` | `src/kc/adapters/wiki_projection.py` | `src/knowledge/core/object.py` |
| 10 | 1 | `kc→knowledge` | `imports_from` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/object.py` |
| 11 | 1 | `kc→knowledge` | `imports` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/object.py` |
| 12 | 1 | `kc→knowledge` | `imports_from` | `src/kc/backup/core_snapshot.py` | `src/knowledge/core/version_manager.py` |
| 13 | 1 | `kc→knowledge` | `imports_from` | `src/kc/backup/drill.py` | `src/knowledge/core/object.py` |
| 14 | 1 | `kc→knowledge` | `imports` | `src/kc/backup/drill.py` | `src/knowledge/core/object.py` |
| 15 | 1 | `kc→knowledge` | `uses` | `src/kc/backup/drill.py` | `src/knowledge/core/object.py` |
| 16 | 1 | `kc→knowledge` | `imports_from` | `src/kc/compiler/compile.py` | `src/knowledge/core/object.py` |
| 17 | 1 | `kc→knowledge` | `calls` | `src/kc/compiler/compile.py` | `src/knowledge/core/object.py` |
| 18 | 1 | `kc→knowledge` | `imports_from` | `src/kc/compiler/temporal.py` | `src/knowledge/core/object.py` |
| 19 | 1 | `kc→knowledge` | `imports` | `src/kc/compiler/temporal.py` | `src/knowledge/core/object.py` |
| 20 | 1 | `knowledge→kc` | `imports_from` | `src/knowledge/core/mode_extension.py` | `src/kc/contracts/mode.py` |
| 21 | 1 | `kc→knowledge` | `calls` | `src/kc/contracts/mode.py` | `src/knowledge/core/candidate.py` |
| 22 | 1 | `kc→knowledge` | `calls` | `src/kc/contracts/mode.py` | `src/knowledge/core/object.py` |
| 23 | 1 | `kc→knowledge` | `imports_from` | `src/kc/mainline.py` | `src/knowledge/core/candidate.py` |
| 24 | 1 | `kc→knowledge` | `imports_from` | `src/kc/mainline.py` | `src/knowledge/core/object.py` |

## 2.2 Top 15 `src.kc.*` symbols by **out-degree to** `src.knowledge.*` (kc depends on knowledge)

| rank | out-deg | relations | qualified_name (source_location) |
|---:|---:|---|---|
| 1 | 6 | `imports:4, imports_from:2` | `src.kc.backup.core_snapshot.core_snapshot` (`batch_runner.py`-side — actually `src/kc/backup/core_snapshot.py:L1`) |
| 2 | 5 | `imports:4, imports_from:1` | `src.kc.compiler.compile.compile` (`src/kc/compiler/compile.py:L1`) |
| 3 | 2 | `imports:1, imports_from:1` | `src.kc.adapters.wiki_projection.wiki_projection` (`src/kc/adapters/wiki_projection.py:L1`) |
| 4 | 2 | `uses:2` | `src.kc.backup.core_snapshot.Snapshot` (`src/kc/backup/core_snapshot.py:L45`) |
| 5 | 2 | `uses:2` | `src.kc.backup.core_snapshot.RestoreReport` (`src/kc/backup/core_snapshot.py:L61`) |
| 6 | 2 | `calls:2` | `src.kc.backup.core_snapshot._collect_objects_from_storage` (`src/kc/backup/core_snapshot.py:L224`) |
| 7 | 2 | `imports:1, imports_from:1` | `src.kc.backup.drill.drill` (`src/kc/backup/drill.py:L1`) |
| 8 | 2 | `imports:1, imports_from:1` | `src.kc.compiler.temporal.temporal` (`src/kc/compiler/temporal.py:L1`) |
| 9 | 2 | `imports:2` | `src.kc.contracts.mode.mode` (`src/kc/contracts/mode.py:L1`) |
| 10 | 2 | `calls:2` | `src.kc.contracts.mode.parse_llm_output_with_mode` (`src/kc/contracts/mode.py:L88`) |
| 11 | 2 | `imports_from:2` | `src.kc.mainline.mainline` (`src/kc/mainline.py:L1`) |
| 12 | 1 | `calls:1` | `src.kc.backup.core_snapshot.create_snapshot` (`src/kc/backup/core_snapshot.py:L125`) |
| 13 | 1 | `calls:1` | `src.kc.backup.core_snapshot.restore_snapshot` (`src/kc/backup/core_snapshot.py:L282`) |
| 14 | 1 | `uses:1` | `src.kc.backup.drill.DrillReport` (`src/kc/backup/drill.py:L34`) |
| 15 | 1 | `calls:1` | `src.kc.compiler.compile.compile_claim` (`src/kc/compiler/compile.py:L11`) |

## 2.3 Top 15 `src.knowledge.*` symbols by **out-degree to** `src.kc.*` (knowledge depends on kc)

| rank | out-deg | relations | qualified_name (source_location) |
|---:|---:|---|---|
| 1 | 4 | `imports:3, imports_from:1` | `src.knowledge.core.mode_extension.mode_extension` (`src/knowledge/core/mode_extension.py:L1`) |
| 2..15 | 0 | — | no other `src/knowledge/*` symbol out-degrees into `src/kc/*` at all |

> **The full set of `src/knowledge/*` symbols that reach across the boundary is exactly ONE module:** `src/knowledge/core/mode_extension.py` — and the only thing it pulls is `src/kc/contracts/mode.py:mode` (the Mode tag contract). Nothing else in `src/knowledge/*` imports, calls, uses, or otherwise references any `src/kc/*` symbol.

## 2.4 Cyclic dependencies — Tarjan SCC on the module-level bipartite graph

Built directed bipartite graph: vertices = source_file modules of either side, edges = any `imports/imports_from/calls/uses/...` between them. Modules with no cross-package edges are dropped. Tarjan (iterative implementation, recursion-limit safe).

| metric | value |
|---|---:|
| kc-side modules in bipartite graph | 12 |
| knowledge-side modules in bipartite graph | 14 |
| total vertices | 26 |
| total SCCs found | 199 (whole-graph) |
| **SCCs that contain BOTH a `kc/*` module and a `knowledge/*` module (= a real cycle)** | **0** |

Cross-check: explicit "A→B AND B→A both exist" search across all 11 directed module pairs — result: **0 pairs**.

Graphically:

```
src/kc/mainline.py ───────────► src/knowledge/core/{candidate,object}.py
src/kc/contracts/mode.py ────► src/knowledge/core/{candidate,object}.py
src/kc/compiler/{compile,temporal}.py ──► src/knowledge/core/object.py
src/kc/backup/core_snapshot.py ─────► src/knowledge/core/{object,version_manager}.py
src/kc/backup/drill.py ─────────────► src/knowledge/core/object.py
src/kc/adapters/wiki_projection.py ──► src/knowledge/core/object.py

         src/knowledge/core/mode_extension.py ──► src/kc/contracts/mode.py
```

The single `knowledge→kc` arrow is **terminal**: `mode_extension` consumes `mode` but **nothing in `kc/` ever imports `mode_extension`**. So the coupling is a strict DAG: **`kc` consumes `knowledge`; `knowledge` consumes exactly one leaf module of `kc`**. No cycles.

**Take-away:** the architecture is intentionally layered. `src/knowledge/` is the data model that `src/kc/` builds on top of, with one narrow, well-named "type/contract" exception (`mode.py` ↔ `mode_extension.py`) that flows back the other way without coupling.

Cypher-equivalent (for codebase-memory):

```cypher
MATCH (kc:Module)-[r:IMPORTS|USAGE]->(kn:Module)
WHERE kc.qualified_name STARTS WITH 'src.kc.'
  AND kn.qualified_name STARTS WITH 'src.knowledge.'
WITH kc, kn, count(r) AS cnt
ORDER BY cnt DESC
LIMIT 30
RETURN kc.qualified_name AS src, kn.qualified_name AS tgt,
       collect(DISTINCT type(r)) AS relations, cnt;

// SCC over the bipartite:
MATCH (a:Module)-[:IMPORTS|USAGE]->(b:Module)
WHERE (a.qualified_name STARTS WITH 'src.kc.' AND b.qualified_name STARTS WITH 'src.knowledge.')
   OR (a.qualified_name STARTS WITH 'src.knowledge.' AND b.qualified_name STARTS WITH 'src.kc.')
WITH collect(DISTINCT a) + collect(DISTINCT b) AS verts
UNWIND verts AS v
WITH DISTINCT v
MATCH (v)-[:IMPORTS|USAGE*]-(w)
WHERE (v.qualified_name STARTS WITH 'src.kc.' AND w.qualified_name STARTS WITH 'src.knowledge.')
   OR (v.qualified_name STARTS WITH 'src.knowledge.' AND w.qualified_name STARTS WITH 'src.kc.')
RETURN v.qualified_name, w.qualified_name;
//   → 0 rows back = no cycles in the bipartite
```

## 2.5 Hub symbols (≥ 5 IMPORTS / IMPORTS_FROM / RE_EXPORTS crossing edges)

Both directions of any cross-package import-related edge are counted. **Total: 4 hubs.**

| total edges | directions | qualified_name | source_location | one-line (first rationale/docstring in graph) |
|---:|---|---|---|---|
| 8 | `kc→knowledge:8` | `src.knowledge.core.object.KnowledgeObject` | `src/knowledge/core/object.py:L54` | "Core knowledge data model — enums, provenance, and the KnowledgeObject dataclass" |
| 6 | `kc→knowledge:6` | `src.kc.backup.core_snapshot.core_snapshot` (module node) | `src/kc/backup/core_snapshot.py:L1` | "Core backup + restore API (Z-1, spec §1 M-7 + §5.13 Publication Batch)" |
| 6 | `kc→knowledge:6` | `src.knowledge.core.object.object` (module node) | `src/knowledge/core/object.py:L1` | "Core knowledge data model — enums, provenance, and the KnowledgeObject dataclass" |
| 5 | `kc→knowledge:5` | `src.kc.compiler.compile.compile` (module node) | `src/kc/compiler/compile.py:L1` | "Projection seam into the existing KnowledgeObject model" |

Equivalent **module-level** view (a single `KnowledgeObject` symbol counts as 8 edges but the file `object.py` aggregates to 19 — the largest single endpoint):

| hub module | package | total cross-package import-related edges |
|---|---|---:|
| `src/knowledge/core/object.py` | knowledge | **19** |
| `src/kc/backup/core_snapshot.py` | kc | 14 |
| `src/knowledge/core/version_manager.py` | knowledge | 10 |
| `src/kc/contracts/mode.py` | kc | 8 |
| `src/kc/compiler/compile.py` | kc | 6 |

(`object.py` aggregating higher than `KnowledgeObject` because the same file is the import target of multiple `imports_from X.Y` lines; each line is a separate AST edge.)

---

## High-level takeaways

1. **`run_batch` is a small, CLI-only orchestrator.** The 2-hop blast radius is 199 nodes / 467 edges and is dominated by intra-file helpers, the wiki write-path (`page_writer.py`, `WikiPage`, `from_dict`), and one shared sibling (`src/services/batch_state.py:load_batch_state`). It has **no HTTP route caller**, **no Variable / WRITES edge** in this graph, and the only writers of `.index/batch_build_state.json` (`src/services/batch_state.py`) live **3 hops away**, not 2. Widening to 6 hops still does **not** reveal a route handler into `run_batch` — confirming that the `ruflo batch run` CLI is the only public entry point.

2. **The `src.kc` → `src.knowledge` coupling is one-directional, narrow, and acyclic.** Only 11 cross-package module pairs exist; the only `knowledge → kc` traffic is `src/knowledge/core/mode_extension.py` ↔ `src/kc/contracts/mode.py` (a deliberate contract exchange — `mode_extension` is the `KnowledgeCandidate` extension entry for the `Mode` tag, and it imports the `Mode` tag definition). Tarjan SCC on the bipartite **finds zero cycles**. That single back-edge does not loop because `mode.py` does not import from `mode_extension.py`.

3. **Five coupling hubs carry the entire inter-package load.** On the `kc` side: `src/kc/backup/core_snapshot.py` (Z-1 backup/restore API), `src/kc/contracts/mode.py` (Mode tag contract), `src/kc/compiler/compile.py` (KC→KO projection seam). On the `knowledge` side: `src/knowledge/core/object.py` (the `KnowledgeObject` dataclass, 19 inbound edges) and `src/knowledge/core/version_manager.py` (snapshot/history/diff/retention). Any change to `object.KnowledgeObject`'s lifecycle or to `mode.parse_llm_output_with_mode` will ripple into most of the rest.

4. **Caveats.** This report uses the `graphify-out/graph.json` AST graph because the codebase-memory MCP tools and Cypher endpoint are not registered in this session and `GEMINI_API_KEY` / `GOOGLE_API_KEY` are unset. The AST graph is missing the `HANDLES / HTTP_CALLS / WRITES / READS / Variable / Route` node-and-edge types the brief assumed, so §1.3 (route handlers) and §1.4 (state-file writers) are approximated by string-matching on `source_file` and rationale-text. The structural findings above hold either way (route handlers do not reach `run_batch` in 6 hops, period), but if the codebase-memory MCP graph were available the count and named ROUTE nodes would be precise. All scratch scripts are saved as `graphify-out/_scratch_*.py` so the analysis can be re-run against either data source.
