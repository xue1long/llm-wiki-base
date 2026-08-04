# ruflo-kb 模块地图（Module Map）

> **维护状态**：2026-08-03 经 `find src -name '*.py'` 实测核对。项目真名 `ruflo-kb` v2.0.0（目录 `LLM-Wiki`）。
> **规模**：`src/` 下 **33 个顶层包、276 个 `.py` 文件**。

## 接线状态图例

| 标记 | 含义 |
| --- | --- |
| ✅ 已接线 | 已进入摄取/查询主链路，运行时生效 |
| 🟡 已写好未接线 | 代码齐全但**未挂入主链路**（多为 KOS 组件与预留 stage） |
| 🔧 基础设施 | 横切支撑，按需被调用 |

---

## 分层结构（mermaid）

```mermaid
graph TD
    subgraph 入口层
        CLI[cli.py + cli_ext/**]
        API[server/routes]
        MCP[mcp_server]
        AGT[agent]
    end
    subgraph 编排流程层
        PIPE[pipeline/** + stages]
        ORCH[orchestrator]
        QUEUE[queue]
        EVT[events]
    end
    subgraph 领域模型层
        WIKI[wiki/**]
        KOS[knowledge/** KOS]
        SCH[schemas/**]
    end
    subgraph 能力支撑层
        LLM[llm]
        VIS[vision]
        RES[research]
]
        SEA[searcher]
        VEC[vector]
        QUAL[quality]
        SYNC[sync]
    end
    subgraph 基础设施
        SVC[services]
        MET[metrics]
        PROJ[project]
        MAINT[maintenance]
        UTL[utils/**]
        LIB[lib]
        TPL[templates]
        SHR[shared]
    end

    CLI --> PIPE
    API --> SVC
    MCP --> SVC
    AGT --> PIPE
    PIPE --> WIKI
    PIPE --> QUAL
    WIKI --> VEC
    WIKI --> SEA
    PIPE --> KOS
    LLM --> PIPE
    VIS --> PIPE
    RES --> PIPE
    SYNC --> WIKI
```

---

## 一、入口层（四种交互面）

| 模块 | 体量 | 状态 | 职责 |
| --- | --- | --- | --- |
| `cli.py` + `cli_ext/` | 1 + 21 py | ✅ | 命令行入口，注册 **28 个顶层子命令**（atomic / budget / cache / completions / dedup / fields / health / heat / lint / lint-cache-clear / llm-providers / mcp / metrics / project / quality / relations / research / schema / serve / serve-status / serve-stop / stubs / tags / templates / vision / wiki-templates / wiki-cleanup-v1-data / wiki-migrate-source-slugs） |
| `server/` (routes) | 4 py + 2 | ✅ | HTTP API，12 条路由 |
| `mcp_server/` | 4 py | ✅ | MCP 服务，8 个工具 |
| `agent/` | 8 py + 1 | 🟡 | 智能体运行时（含 KOS 的 `CollectorAgent` 等，部分未接入主链路） |

## 二、编排 / 流程层

| 模块 | 体量 | 状态 | 职责 |
| --- | --- | --- | --- |
| `pipeline/` (+`stages`) | 25 py + 2 | 🟡 | **摄取管道**：collector / analyzer / generator / runner / service / ingest。默认三件套 stage 仅跑 `[:1]`（仅 Collector），生成走旧 `run_ingest`；`PipelineRunner.run_stages` 预留给 KOS 但未调用 |
| `orchestrator/` | 5 py | ✅ | 采集 / 任务编排 |
| `queue/` | 9 py | ✅ | 异步任务队列 |
| `events/` | 3 py | ✅ | 事件总线（`collector:start` 等） |

## 三、领域模型层

| 模块 | 体量 | 状态 | 职责 |
| --- | --- | --- | --- |
| `wiki/` (core / features / storage / templates) | 1 + 5 + 24 + 4 py | ✅ | **WikiPage 模型** + 标签命名空间(`tag_namespace.py`) + 关系(`relations.py`) + 页面写入(`page_writer.py`，`validate_tag_compliance` 强制校验)。已全量接线 |
| `knowledge/` (KOS) | 2 py + 10 子包 | 🟡 | **知识操作系统层**：`claims` / `conflicts` / `core` / `evolution` / `graph` / `lifecycle` / `memory` / `provenance` / `storage` + `kernel.py`。组件已写好但**未接入摄取主链路**，属已知缺口 |
| `schemas/` (+migrations) | 5 py + 2 | ✅ | 数据 schema 定义与版本迁移 |

## 四、能力 / 支撑层

| 模块 | 体量 | 状态 | 职责 |
| --- | --- | --- | --- |
| `llm/` | 10 py + 1 | ✅ | 多 LLM 后端抽象（anthropic / ollama / openai / minimax…） |
| `vision/` | 4 py | ✅ | 视觉 / 多模态（图片分析） |
| `research/` (+providers) | 2 py + 2 | ✅ | 联网深度研究（web search / deep research 提供商） |
| `searcher/` | 6 py | ✅ | 检索与浏览 |
| `vector/` | 4 py | ✅ | 向量存储（LanceDB 派生索引） |
| `quality/` | 5 py | ✅ | **质量治理五件套**：quality_gate / dedup / lint / heat / ndg_gate |
| `sync/` | 2 py + 1 | ✅ | wiki-spec → `wiki_rules_prompt.py` 自动同步（生成物禁手改） |

## 五、基础设施 / 横切

| 模块 | 体量 | 状态 | 职责 |
| --- | --- | --- | --- |
| `services/` | 11 py | 🔧 | 业务服务层（WikiService 等） |
| `metrics/` | 7 py | 🔧 | Prometheus 指标 |
| `project/` | 7 py | 🔧 | 多实例项目管理 |
| `maintenance/` (+checks) | 3 py + 2 | 🔧 | 维护 / 健康检查 |
| `utils/` (+extract) | 6 py + 2 | 🔧 | 通用工具（含 PDF/DOCX/HTML 文件抽取 `extract/`） |
| `lib/` | 6 py | 🔧 | 基础库 |
| `templates/` | 2 py + 2 | 🔧 | 页面模板 |
| `shared/` | 2 py | 🔧 | 跨模块共享 |

---

## 关键核实结论

1. **真正跑在主链路上的核心** = `pipeline` + `wiki` + `quality` + `llm` + `vector`/`searcher`(索引)，与文档一致、已接线。
2. **`knowledge/`(KOS) 整层**是"架构先进但接线未完成"的典型——`evolution`/`lifecycle`/`claims`/`graph` 等组件代码齐全，却未挂进 `PipelineService._stages`，正是 `../superpowers/plans/2026-08-02-ingest-pipeline-completion.md` 完善方案要补的缺口。
3. `cli_ext` 命令模块(20) ≠ 顶层子命令(28)：部分模块注册多个子命令（如 `wiki_*` 系列），部分子命令由单模块内多 `add_parser` 注册。
4. `wiki/features/` 体量最大（24 py），集中了标签命名空间、关系等核心特征逻辑；`knowledge/` 子包最多（10 个），是未来演进的主要承载区。

## 相关文档

- [INDEX.md](../INDEX.md) — 文档总导航
- [wiki-model-overview.md](wiki-model-overview.md) — WikiPage 数据模型详解
- [ingest-pipeline-overview.md](ingest-pipeline-overview.md) — 摄取流程详解
- [../superpowers/plans/2026-08-02-ingest-pipeline-completion.md](../superpowers/plans/2026-08-02-ingest-pipeline-completion.md) — KOS 组件接线方案
- [../TECH_DEBT_CHECKLIST.md](../TECH_DEBT_CHECKLIST.md) — 17 项技术债务（含 #11 前缀文案重复、页面类型三套矛盾）
