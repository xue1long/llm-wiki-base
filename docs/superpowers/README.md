# ruflo-kb Design Documentation

> **Mission**: 把任意来源（文件 / URL / 网页 / PDF 图片）转化为可被人类与 AI agent 协作维护、可自演化（heat decay + LLM judge + dedup + cascade）、可被多接口查询（CLI / HTTP / MCP / SSE chat agent）的本地优先语义知识图谱。

## 📂 目录结构

```
docs/superpowers/
├── specs/                              # 设计规范（每个 spec 一份）
│   ├── _input_contracts.md             # ⭐ 跨 spec 依赖图（SSOT）
│   ├── _apply_optimization.py           # batch 优化脚本
│   ├── 2026-07-21-wiki-semantic-structure-design.md
│   ├── 2026-07-21-project-multi-instancing-design.md
│   ├── ... (共 18 份 spec)
│
└── plans/                              # 实施计划（每个 spec 一份 plan）
    ├── 2026-07-21-nkb-to-ruflo-migration.md  (历史，从 NKB 迁移)
    ├── 2026-07-22-project-multi-instancing.md
    ├── 2026-07-22-schemas-v3.md
    ├── ... (共 18 份 plan)
```

## 🗺️ 如何读这套文档

| 读者 | 路径 | 目的 |
|---|---|---|
| 新人 / 总览 | 本 README + [`specs/_input_contracts.md`](specs/_input_contracts.md) | 5 分钟理解整体设计 |
| 设计师 | 任何 `specs/2026-07-21-*.md` | 看 Goal / Non-goals / Architecture / Data structures |
| 实施者 | 任何 `plans/2026-07-22-*.md` | 看 Task 列表（5 步 / task）+ 完整代码 |
| 协调多 spec | [`specs/_input_contracts.md`](specs/_input_contracts.md) | 看 Phase 排序 + 跨 spec 依赖 |

## 🏗️ 4 Phase 实施顺序

```
Phase 0: src/shared/  (新基础设施层)
  ↓
Phase 1: Foundations (4 specs, parallel)            ~9.5 hours
  ├── Project multi-instancing        (UUID + registry + mutex)
  ├── Schemas v3                       (Migration + forward-compat)
  ├── AtomicContext + BudgetedLLM      (atomic commits + chunked LLM)
  └── Health Check                      (H1 + H2 + H4 MVP)
  ↓
Phase 2: Core (3 specs, chain)                       ~13-16 hours
  ├── Wiki v2.0                         (4 page types + 2-step CoT + A1-A7)
  ├── Multi-Provider LLM                (Ollama + registry)
  └── HTTP API + MCP                    (8 endpoints + 8 MCP tools + daemon)
  ↓
Phase 3: Quality + Wiki Polish (6 specs, partial parallel)  ~10-15 hours
  ├── Quality Gate v2.0                 (6-dim LLM judge + 1 retry)
  ├── Wiki Fields v2.2                  (UUID v7 IDs + tag namespace)
  ├── Wiki Relations                    (typed graph + INVERSE table)
  ├── Wiki Heat 5-Pool                  (heat decay + zombie detection)
  ├── Wiki v2.1 polish                  (stubs auto + dedup --auto + lint cache)
  └── Vision / Image Input              (PDF extraction + captioning)
  ↓
Phase 4: Advanced (5 specs, partial parallel)        ~8-10 hours
  ├── Chat Agent                        (5 tools + agent loop)
  ├── Web Search + Deep Research       (Tavily + synthesis)
  ├── Quality Gate v2.1 Ensemble       (multi-judge voting)
  ├── Metrics endpoint                  (Prometheus + 24h rolling)
  └── CLI/UX polish                    (argcomplete + 1 template)
```

**总规模**：~50-60 小时实施，~420 KB 文档（18 plans）

## 📋 18 个 Spec + Plan 一览

### Phase 1 - Foundations

| # | Spec | Plan | 任务 | 估计 | MVP 范围 |
|---|---|---|---|---|---|
| 1 | [wiki-semantic-structure](../specs/2026-07-21-wiki-semantic-structure-design.md) | [wiki-v2](../plans/2026-07-22-wiki-v2.md) | 16 | 8-10h | 4 page types + 2-step CoT + A1-A7 |
| 2 | [project-multi-instancing](../specs/2026-07-21-project-multi-instancing-design.md) | [project-multi-instancing](../plans/2026-07-22-project-multi-instancing.md) | 11 | 3h | UUID + 4-step resolve + mutex + auto-discovery + 6 CLI |
| 3 | (uses Schemas v3 + AtomicContext + Health Check) | [schemas-v3](../plans/2026-07-22-schemas-v3.md) | 6 | 3h | Migration base + 5 CLI |
| 4 | | [atomic-ctx-budgeted-llm](../plans/2026-07-22-atomic-ctx-budgeted-llm.md) | 5 | 2h | AtomicContext + BudgetedLLM + 3 CLI |
| 5 | | [health-check](../plans/2026-07-22-health-check.md) | 5 | 1.5h | H1 + H2 + H4 of 5 |

### Phase 2 - Core

| # | Spec | Plan | 任务 | 估计 | MVP 范围 |
|---|---|---|---|---|---|
| 6 | [multi-provider-llm](../specs/2026-07-21-multi-provider-llm-design.md) | [multi-provider-llm](../plans/2026-07-22-multi-provider-llm.md) | 6 | 2h | Ollama only + global registry + 6 CLI |
| 7 | [http-api-mcp](../specs/2026-07-21-http-api-mcp-design.md) | [http-api-mcp](../plans/2026-07-22-http-api-mcp.md) | 4 | 3-4h | 8 endpoints + 8 MCP tools + daemon (no SSE) |

### Phase 3 - Quality + Wiki Polish

| # | Spec | Plan | 任务 | 估计 | MVP 范围 |
|---|---|---|---|---|---|
| 8 | [quality-gate-v2](../specs/2026-07-21-quality-gate-v2-design.md) | [quality-gate-v2](../plans/2026-07-22-quality-gate-v2.md) | 4 | 2-3h | 6 dim + 2-tier verdict + 1 retry + basic quarantine |
| 9 | [wiki-fields](../specs/2026-07-21-wiki-fields-design.md) | [wiki-fields-v22](../plans/2026-07-22-wiki-fields-v22.md) | 4 | 1.5-2h | 4 fields + tag namespace + migration |
| 10 | [wiki-relations](../specs/2026-07-21-wiki-relations-design.md) | [wiki-relations](../plans/2026-07-22-wiki-relations.md) | 3 | 2-3h | 16 relation types + bidirectional sync + 6 CLI |
| 11 | [wiki-heat-5pool](../specs/2026-07-21-wiki-heat-5pool-design.md) | [wiki-heat-5pool](../plans/2026-07-22-wiki-heat-5pool.md) | 2 | 1.5-2h | heat decay + zombie detection + 7 CLI (Pool routing deferred) |
| 12 | [wiki-v21-polish](../specs/2026-07-21-wiki-v21-polish-design.md) | [wiki-v21-polish](../plans/2026-07-22-wiki-v21-polish.md) | 3 | 1.5-2h | stubs auto + dedup --auto + lint cache |
| 13 | [vision-image-input](../specs/2026-07-21-vision-image-input-design.md) | [vision](../plans/2026-07-22-vision.md) | 3 | 2-3h | PDF extract + GPT-4o-mini/Claude vision |

### Phase 4 - Advanced

| # | Spec | Plan | 任务 | 估计 | MVP 范围 |
|---|---|---|---|---|---|
| 14 | [chat-agent](../specs/2026-07-21-chat-agent-design.md) | [chat-agent](../plans/2026-07-22-chat-agent.md) | 3 | 2-3h | 5 tools + agent loop (no SSE/REPL) |
| 15 | [web-search-deep-research](../specs/2026-07-21-web-search-deep-research-design.md) | [web-search-deep-research](../plans/2026-07-22-web-search-deep-research.md) | 1 | 2h | Tavily + 3 queries + synthesis |
| 16 | [quality-gate-v21-ensemble](../specs/2026-07-21-quality-gate-v21-ensemble-design.md) | [quality-gate-v21-ensemble](../plans/2026-07-22-quality-gate-v21-ensemble.md) | 2 | 1.5-2h | 2 judges + mean + veto on factuality |
| 17 | [metrics-endpoint](../specs/2026-07-21-metrics-endpoint-design.md) | [metrics-endpoint](../plans/2026-07-22-metrics-endpoint.md) | 2 | 1.5h | 5 core metrics + Prometheus + 24h rolling |
| 18 | [cli-ux-polish](../specs/2026-07-21-cli-ux-polish-design.md) | [cli-ux-polish](../plans/2026-07-22-cli-ux-polish.md) | 2 | 1-1.5h | bash/zsh completion + 1 template (research) |

## 🔄 MVP Cutoff Summary

按 spec 的 MVP/Polish/Deferred 分层：

| Tier | 包含 spec 数量 | 估计工时 | 实施顺序 |
|---|---|---|---|
| **MVP (Week 6)** | 11 spec | ~30h | Phase 1+2 + Phase 3 部分 |
| **Polish (Week 12)** | 7 spec（v2.0.1 增量）| ~15h | Phase 3 余 + Phase 4 部分 |
| **v2.1 (Week 20)** | 剩余 | ~15h | Phase 3+4 余下 |
| **v3.0+ 实验** | 暂未排 | 待定 | Auth + Metrics + 等等 |

### MVP 11 spec (Week 6 交付)

1. Project multi-instancing
2. Schemas v3
3. AtomicContext + BudgetedLLM
4. Health Check (H1 + H2 + H4)
5. Wiki v2.0 (4 page types + 2-step CoT + A1-A7 lifecycle)
6. Multi-Provider LLM (Ollama)
7. HTTP API + MCP (8 endpoints + 8 MCP tools)
8. Quality Gate v2.0 (6-dim judge + 1 retry)
9. Wiki Fields v2.2 (4 fields)
10. Chat Agent (5 tools)
11. Web Search + Deep Research (Tavily)

## 🏷️ 文件命名规范

```
specs/YYYY-MM-DD-<feature>-design.md
plans/YYYY-MM-DD-<feature>.md
```

- **specs** 描述**做什么**（Goal / Architecture / Data structures / Error handling）
- **plans** 描述**怎么做**（Task 列表 + 每步完整代码 + Commit 节奏）
- **日期相同** 表示 spec 和 plan 一一对应

## 📚 引用规范

每个 spec 顶部都包含：

```markdown
## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs): ...
**This spec requires from other specs**: ...
**Phase**: Phase N — Tier
**Priority**: P0 / P1 / P2
```

## 🛠️ 工具脚本

- [`specs/_apply_optimization.py`](specs/_apply_optimization.py) — batch 给 18 个 spec 加 Input Contract + MVP/Polish/Deferred 章节
- [`specs/_input_contracts.md`](specs/_input_contracts.md) — 跨 spec 依赖图（SSOT）

## 📈 文档统计

| 类型 | 数量 | 总行数 |
|---|---|---|
| Spec 文档 | 18 | ~10000 |
| Plan 文档 | 18 | ~12000 |
| Contract map | 1 | 500 |
| Optimization 脚本 | 1 | 600 |
| **总计** | **38 文件** | **~23000 行** |

## 🎯 设计来源

| 来源 | 借鉴的特性 |
|---|---|
| [llm_wiki-main](https://github.com/nashsu/llm_wiki) | Wiki 2-step CoT, typed relations, 14 chat-agent tools, HTTP API + MCP, Web Search + Deep Research |
| [Novel-Knowledge-Base v3.0](https://github.com/example/NKB) | 5-Pool + Heat, Card ID + L0-L3 fields, schema versioning + up()/down(), Health Check H1-H11, AtomicContext, Chrome SSOT |
| 自有设计 | Project 多实例化、Quality Gate v2.0 LLM judge、rufflo-kb-specific 简化决策 |

## 🗓️ 实施时间线（推荐）

| Week | 完成 Phase | 交付 |
|---|---|---|
| 1-2 | Phase 0 (src/shared/) | 共享基础设施层 |
| 3-4 | Phase 1 (4 plans) | Foundations 并行 |
| 5-8 | Phase 2 (3 plans) | Core chain |
| 9-12 | Phase 3 (6 plans) | Quality + Polish 并行 |
| 13-16 | Phase 4 (5 plans) | Advanced chain |
| 17-20 | v2.0.1 polish | 增量改进 |
| 21+ | v2.1 / v3.0 | 实验性特性 |

## ⚠️ 重要约束

1. **每个 step 必须含完整代码**（writing-plans skill 要求）— 不写 `...` 或 TODO 占位
2. **TDD per task 节奏** — 写失败测试 → 跑确认失败 → 实现 → 跑确认通过 → commit
3. **每 task 一 commit**（conventional commits）
4. **MVP scope 优先** — Polish/Deferred 部分留到后续 plan / v2.0.1
5. **测试用 mock LLM** — `MockLLMProvider` 提供 scripted_responses，避免实际 LLM 调用
6. **No new deps unless required** — atomic_ctx / budgeted_llm 用 stdlib；HTTP 用 fastapi/uvicorn/mcp

## 🔗 相关

- [Project README](../../README.md) — 用户视角的项目说明
- [Project CLAUDE.md](../../CLAUDE.md) — AI 助手的项目入口
- [NKB migration plan](2026-07-21-nkb-to-ruflo-migration.md) — 从 Novel-Knowledge-Base 迁移的早期计划

---

**最后更新**: 2026-07-22
**总 commit 数**: 26+ commits
**总 spec / plan 文档**: 19 文件 / ~23000 行
**下一步**: 实施 Phase 0（src/shared/）或继续优化现有 plan