# 规范性检查报告 · ruflo-kb（llm-wiki-base.bak.20260822）

- **日期**：2026-09-01
- **工具**：codebase-memory-MCP（moderate 索引，34,893 节点 / 92,008 边，过滤 venv/tests）
- **基线规则来源**：`CLAUDE.md`、`README.md`、`pyproject.toml`
- **检查维度**：架构统一性 · 接口/入口统一性 · 配置开关源统一性 · 规则遵循 · 层级/服务边界

---

## 一、总体结论

> **架构与规则在"细节层面"统一度较高，但在"编排范式"与"配置开关源"两个维度存在明显缺口。**

落实良好的部分：`src/wiki/` 分层导入、向量库初始化、项目解析单入口、清晰的分层（api → services → core）。
**未统一的核心问题**：存在两套并行管线编排（单体 `run_ingest` vs stage `PipelineRunner`），但只有单体路径是活的，stage 调度器是孤儿代码；且管线行为开关 `RUFLO_PIPELINE_MODE` 绕过已建立的集中式 `config.settings()` 被原始 `os.environ` 直读。

---

## 二、发现清单（按严重度）

### F1 ·【高】双管线编排未统一，stage 调度器是孤儿代码

| 项 | 证据 |
|---|---|
| stage 调度器定义 | `src/pipeline/runner.py:30` `run_stages`；`src/pipeline/ports.py` `PipelineStage`；`src/pipeline/service.py:54` 注册 `CollectorStage, AnalyzerStage, GeneratorStage` |
| 生产调用方全部走单体路径 | `src/server/routes/ingest.py:27` → `services/ingest.py:281`（`asyncio.run(run_ingest(...))`）→ `pipeline/ingest.run_ingest`；`orchestrator/batch_runner.py:229` 调 `generate_ingest`；`pipeline/service.py:136` 也委托 `run_ingest` |
| `run_stages` 无生产调用点 | 全局 grep `run_stages|PipelineRunner(` 仅命中其自身定义与 `events.py`/`ports.py`/`service.py` 的注册/注释，**无任何驱动调用** |
| `CommitterStage` 缺失 | `service.py:54` 仅注册 Collector/Analyzer/Generator，stage 路径无落盘提交步骤 |
| 切换变量不存在 | grep `RUFLO_USE_STAGE_SCHEDULER` 全文 **零命中** —— 用户记忆中"用该变量切换双管线"在本快照未落地 |

**影响**：两套编排范式并存，维护者无法判定哪条是"主路径"；目标漂移（目标漂移审计）风险高；stage 调度器属应清理的死代码或待接线的半成品。

---

### F2 ·【高】管线行为开关散落读取，绕过集中式 `config`

- `src/config.py:73-74` 已定义 `pipeline_mode` / `shadow_mode` 的集中只读视图（pydantic `Settings`），文档明确"all env-var-driven configuration coalesces here / 单一开关源"。
- 但行为开关的实际读取**未走** `settings()`：
  - `src/pipeline/ingest.py:723`：`_candidate_mode = os.environ.get("RUFLO_PIPELINE_MODE", "candidate") == "candidate"` —— 原始 `os.environ` 直读。
  - `src/pipeline/shadow.py:34/36/52/54`：直接 `os.environ.get/pop/["RUFLO_PIPELINE_MODE"]` 读写。
- 违反既定原则"**单一开关源 / CI 防散落 env 读取**"。集中 `Settings` 形同虚设（仅 `collector.py:54`、`generator.py:66`、`prefilter.py:73`、`_pipeline_common.py:497` 用 `settings()` 读 `max_source_chars` 等非行为类参数）。

**影响**：修改管线模式时，必须在 `config.py` 与 `ingest.py`/`shadow.py` 两处同步，易遗漏；CI 无法单点审计 env 契约。

---

### F3 ·【中】Generator/Analyzer 入口 proliferation，无单一生成调度器

`src/pipeline/generator.py` 暴露多个并列入口，契约各不相同：
- `unified_generate`（`generator.py:558`，legacy 统一生成）
- `generate_from_candidate`（`generator.py:936`，candidate 路径）
- `generate_from_knowledge_object`（`generator.py:1162`，KC 对象 → body）
- `generate`（`generator.py:1391`，legacy two-step）
- 外加 `analyzer.analyze`（`analyzer.py:300`）与 `pipeline.analyze`/`pipeline.generate` 兼容 shim。

`ingest.py` 内部用一长串 `if/elif`（candidate → chunked → unified → two-step fallback）**手工派发**这些入口，而非统一调度器。不同调用方（candidate 路径、shadow、batch_runner）各自选择不同入口。

**影响**：违反"**单一生成调度器**"原则；入口契约不一致，回归面大。

---

### F4 ·【中】部分 Route 绕过 service 层直连 domain

| 位置 | 直连内容 |
|---|---|
| `src/server/routes/kc.py:41` | `from src.kc.compiler.normalize import normalize_text` |
| `src/server/routes/kc.py:108` | `from src.kc.api import compile_source` |
| `src/server/app.py:217` | `from src.kc.mainline import recover_staged_bundles`（lifespan 直连） |

对照 `src/server/routes/analysis.py:8` `from ...services import wiki_analysis`（正确用法）—— 同仓内不一致，违反"**Routes are thin adapters; services are unit-testable**"规则。

---

### F5 ·【低】`_resolve_ctx` 薄包装冗余且错误处理不一致

4 个 CLI 命令文件各自定义 `_resolve_ctx`，**均委托** `resolve_project`（单入口已落实，非重实现，✓）：
- `cli_ext/cache_cmd.py:11`、`cli_ext/heat_cmd.py:13`、`cli_ext/wiki_polish_cmd.py:11`：捕获 `ProjectNotFoundError` → stderr + `exit(2)`。
- `cli_ext/fields_cmd.py:14`：**未捕获** `ProjectNotFoundError` → 会向 CLI 抛出原始异常，与其他 3 处行为不一致。
- 4 处重复同一小包装，可收敛为 `cli_ext` 共享 helper。

低危，但属 DRY / 行为一致性瑕疵。

---

## 三、已统一（保持良好，不应破坏）

- ✅ **wiki 导入分层**：无 `src.wiki.ensure` 平面导入残留；全部走 `src.wiki.core.*` / `src.wiki.storage.*` / `src.wiki.features.*`。`ensure_knowledge_base`（wiki/storage/ensure）fan_in=275 为正确分层用法。
- ✅ **向量库初始化**：legacy `init_vector_store(db_path)` 无存活调用（仅 `vector/store.py:19` docstring 提及），统一使用 `init_vector_store_for_paths(WikiPaths)`。
- ✅ **`ctx.paths` 违规**：全文仅 `quality/quarantine.py:28` 一处 **docstring** 误写 `ctx.paths.root`，无代码违规（`ProjectContext.path` 是 `Path`，非 `paths`）。
- ✅ **层级清晰**：api → services → core（wiki / knowledge / pipeline / vector / searcher / …）；架构边界显示测试均指向正确层（test_server→services、test_wiki→wiki）。
- ✅ **三段式职责**：`run_ingest` / `generate_ingest`（零磁盘）/ `commit_ingest`（落盘）切分清晰；KC（Knowledge Compiler）作为 enrich 层接入 candidate 路径，仍以 `WikiPage` 为主数据模型。
- ✅ **raw `os.environ` 读取**：14 个文件中有原始 env 访问，但多数属合理（serve HOST/PORT、registry provider 路径等），仅**行为开关类**未走集中 config（见 F2）。

---

## 四、修复优先级建议

| 优先级 | 项 | 动作 |
|---|---|---|
| **P0** | F1 | 决定 stage 调度器命运：要么接线（在 `run_ingest` 内按 `RUFLO_USE_STAGE_SCHEDULER` 切换，并补 `CommitterStage` 落盘步骤），要么删除孤儿 `PipelineRunner`/`stages/` 以消除歧义。**先与用户确认架构方向（目标漂移审计）** |
| **P0** | F2 | 将 `RUFLO_PIPELINE_MODE` / `RUFLO_SHADOW_MODE` 读取统一收口到 `config.settings()`，消除 `ingest.py:723` 与 `shadow.py` 的 raw `os.environ` 直读 |
| **P1** | F3 | 引入单一 Generator 调度器，统一 `unified_generate` / `generate_from_candidate` / `generate_from_knowledge_object` 的契约与选择逻辑，消除 `ingest.py` 内手工 `if/elif` 派发 |
| **P1** | F4 | 将 `routes/kc.py`、`app.py` 的直连 domain 改为经 `services/kc`（或明确豁免并文档化） |
| **P2** | F5 | 收敛 4 处 `_resolve_ctx` 为共享 helper，统一 `ProjectNotFoundError` 处理 |

---

## 五、方法论附录

1. 重新索引仓库（moderate 模式，过滤 venv/tests/docs）→ 34,893 节点 / 92,008 边。
2. 读取项目"应然"基线：`CLAUDE.md` / `README.md` / `pyproject.toml`，提取统一规则（单入口 `src/lib/project.py`、集中 config、`ctx.path` 非 `paths`、wiki 分层导入、向量库 `init_vector_store_for_paths`、Routes 薄适配）。
3. 图分析：`get_architecture`（overview/structure/boundaries/clusters/layers）、`search_graph`（_resolve_ctx、AnalyzerStage）、`search_code`（env 读取散点）。
4. 交叉核验：Grep 反模式（`_resolve_ctx`、`ctx.paths`、`src.wiki.ensure`、`init_vector_store(`、`RUFLO_*` 开关、stage 调度器调用方、route 直连 domain）。
5. 逐条以 `file:line` 证据定性与定级。
