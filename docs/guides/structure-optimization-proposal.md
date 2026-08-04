# ruflo-kb 项目结构优化方案

> **依据**：2026-08-03 由 4 个 Explore agent 实际深读 `src/` 全部 33 包 / 276 个 `.py` 后综合。所有结论附 `文件:行号` 证据，未改动任何代码。
> **目标**：消除"架构先进但接线未完成"的现状，把散落的真源、重复实现、死代码与越界依赖收敛为单一、可维护的结构。

---

## 一、执行摘要（最该先做的 5 件事）

1. **让 stage 机制真正接管摄取** — `PipelineService`（`pipeline/service.py:107`）只跑 `[:1]`（仅 Collector）后手工调旧 `run_ingest`；`PipelineRunner.run_stages`（`runner.py:28`）**生产零调用**，整个 `stages/` 抽象是摆设。
2. **页面类型收敛为单一真源** — `PageType` 在 7 处矛盾定义（8 类 vs 4 类 vs 4 类缩水），导致 `claim/decision/procedure/event` **永远无法被 LLM 生成**且无人校验。
3. **清理约 3000+ 行死代码** — `orchestrator/`（零引用）、`agent/collector.py` + `agent/researcher.py`（仅测试）、`knowledge/{storage,evolution,memory,provenance}`（生产零引用）、`sync/`（死模块）、`page_model.py`（冗余桥）。
4. **合并 `utils/lib/shared` 三袋为 `foundation/`** — 三者无边界，且上层重复造轮子（同义 slugify / cosine 散落 4 处）。
5. **治理件套收编为 `PipelineStage`** — 五个质量件分散在 `pipeline/quality_gate.py` 与 `wiki/features/{dedup,lint,heat,ndg_gate}.py`，未实现 `ports.py:44` 协议；`ndg_gate` 生产链路零调用。

---

## 二、现状问题清单（按严重度）

### 🔴 P0 — 接线断裂 / 功能缺陷

| # | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| P0-1 | stage 机制被绕过 | `service.py:107` 仅 `[:1]`；`runner.py:28` 零生产调用；`stages/analyzer.py:20` 需 `ctx.provider` 但 `service.py:103` 构造 `PipelineContext` 只传 4 字段 | `stages/`、`register_stages` 整套抽象失效 |
| P0-2 | 页面类型定义矛盾 | `types.py:10-18`(8) / `generator.py:64` & `ingest.py:310`(`_DEPTH_BY_TYPE` 4, 逐字重复) / `generator.py` LLM enum(4) / `features/schema_routing.py:8`(4 缩水) | `claim/decision/procedure/event` 永不被生成、不被 `validate_schema_routing` 校验 |
| P0-3 | KOS 组件未接线 | `knowledge/storage/`(1003 行)、`evolution/`(390)、`memory/`(634)、`provenance/` 生产零引用；`mcp_server/main.py:127` `memory_retrieval` 留 `None` | 近 3000 行代码无运行时价值 |
| P0-4 | 质量治理未接入主链路 | `ndg_gate.py` 仅被 `scripts/`+测试调用；`dedup/lint/heat` 由 `services/wiki_analysis.py:249-270` 旁路；均不实现 `ports.py:44` | 摄取产出未经完整治理 |

### 🟡 P1 — 重复实现 / 冗余

| # | 问题 | 证据 |
| --- | --- | --- |
| P1-1 | 三套杂物袋无边界 | `lib/__init__.py`(0 行无导出)、`lib/project.py:16-32`(两行包装)、`shared/test_helpers.py` src 内零引用 |
| P1-2 | 同功能散落 | `utils/similarity.py:4`(零引用) vs `wiki/features/dedup.py:29`；`utils/slugify.py:105` vs `knowledge/memory/decision.py:72`；`utils/text.py:8` vs `pipeline/_pipeline_common.py:34` |
| P1-3 | 双份 stage 实现 | `pipeline/{collector,analyzer,generator}.py`(真逻辑) 与 `stages/*.py`(薄包装) 并存，靠 `__init__.py:113-209` `_PipelineCompatShim` 注入 |
| P1-4 | 模型重复 | `KnowledgeType`(`knowledge/core/object.py:6`) 与 `PageType` 1:1 平行，靠 `adapter.py` 两张映射表硬缝；`LifecycleState` 塞进 `WikiPage._ko_extra` 影子字段 |
| P1-5 | CLI 转发层冗余 | `services/quality.py`(14 行纯转发)、`services/wiki_analysis.py:248-291`(8 函数全转发)、`services/ingest.py:281-285`(3 行转发) |
| P1-6 | 兼容桥冗余 | `wiki/core/page_model.py`(10 行，仅 `wiki/__init__.py:18` 引用) |
| P1-7 | 生成物版本策略反向 | `.gitignore:26` 忽略基线 `.wiki-spec-md5` 却**未忽略**生成物 `pipeline/wiki_rules_prompt.py` → 新克隆误判 spec 已变更 |

### 🟢 P2 — 边界 / 文档异味

| # | 问题 | 证据 |
| --- | --- | --- |
| P2-1 | 基础层反向依赖领域层 | `lib/project.py:13` 与 `maintenance/cache_cleanup.py:15` 均 `import wiki.core.paths` |
| P2-2 | templates 命名冲突 | `src/templates/`(脚手架) 与 `src/wiki/templates/`(页面模板) 同名，`wiki/features/lint.py:32` 相对导入易误读 |
| P2-3 | provider 工厂硬编码 | `llm/provider_factory.py:35-44` if/elif 分支；`minimax` 仅靠 `resolve_embedding_provider_type:57` 名字特判 |
| P2-4 | 维护检查谎报 | `maintenance/checks/__init__.py:1` 写 "H1-H5" 而 H3 缺失；注册硬编码于 `cli_ext/health_cmd.py:28-31` 无自动发现 |
| P2-5 | 全局单例泛滥 | `llm/embedding_runtime.py:46` 与 `searcher/qa.py:91-102` 各维护一份 provider 单例 |
| P2-6 | `features/__init__.py` 漏登记 | 遗漏 `batch_reconcile/ndg_gate/relation_index/slug_aliases/version_history` 共 5 模块 |

---

## 三、目标结构

```
src/
├── cli/                  # 合并 cli.py + cli_ext，统一 add_*_parser 自注册（消除内联/自注册双风格）
├── api/                  # 现 server/（HTTP 12 路由）
├── mcp/                  # 现 mcp_server/（修 [deprecated] 客户端或明确弃用）
├── foundation/           # 合并 utils + lib + shared → {text, path, io, llm, idempotency}
├── llm/                  # provider 注册表（minimax 一等公民），embedding
├── vision/  research/    # 能力 provider（接入 pipeline 或标 experimental/）
├── vector/  searcher/    # 保边界：vector=索引存储，searcher=查询编排
├── pipeline/             # 仅 stage 驱动：service + runner + 调度（删除内联 run_ingest）
│   └── stages/           # 全部 stage：Collector/Analyzer/Generator/Reviewer/
│                         #   CandidatePromoter/Indexer/ClaimExtractor + KOS 接入
├── governance/           # 合并现 quality/ + wiki/features/{dedup,lint,heat,ndg_gate}
│                         #   全部实现 ports.PipelineStage
├── wiki/                 # core(WikiPage + PageType 单一真源) / features(tags,relations)
│                         #   / storage / templates(页面模板)
├── knowledge/            # KOS：保留已接线(core,lifecycle)；未接线移 experimental/
├── schemas/              # 保持（ForwardCompatModel + 迁移，职责干净）
├── sync/                 # 接管 wiki-spec 同步（scripts/sync_wiki_spec.py 并入，产物正确 .gitignore）
├── services/             # 仅保留真实编排（ingest 入队、tags、graph/lint），删纯转发
├── project/  metrics/  maintenance/   # 保持；maintenance 补 H3 + 注册表发现
├── agent/                # 保留 AgentRuntime；CollectorAgent/ResearcherAgent 移 experimental 或删
└── (删除) orchestrator/  # 死代码（零引用 + 状态机已迁 queue/state.py）
```

---

## 四、分阶段迁移建议

### 阶段 0 — 零风险清理（不动行为，立即可做）
- 删除 `orchestrator/`（零引用）；删除 `wiki/core/page_model.py` 并改 `wiki/__init__.py:18` 直连 `core.types`。
- 消灭重复实现：让 `wiki/features/dedup.py`、`knowledge/memory/decision.py` 复用 `utils/similarity.py` / `utils/slugify.py`；删除 `shared/test_helpers.py`（移 `tests/`）。
- 删纯转发服务：`services/quality.py`、`services/wiki_analysis.py` 转发段、`services/ingest.py:281-285`；CLI 直调领域模块。
- 修 `.gitignore`：忽略生成物 `pipeline/wiki_rules_prompt.py`（与 `.wiki-spec-md5` 同进同退）。
- 修 `maintenance/checks/__init__.py` 谎报 + 改 `health_cmd.py:28-31` 为注册表自动发现。
- 补 `features/__init__.py` 漏登记的 5 模块。

### 阶段 1 — 接线修正（核心，需保护现有行为）
- **统一摄取入口**：`service.py` 改为 `await self.runner.run_stages(self._stages, ctx)`；补齐 `PipelineContext`（paths/provider，`service.py:124-125` 已有解析可复用）；把 `run_ingest` 写盘逻辑下沉为 `CommitStage`。**注意**：`run_ingest` 现有"更新既有页面跳过 `validate_tag_compliance`"的微妙行为必须原样保留进 CommitStage。
- **页面类型单一真源**：以 `types.py:PageType` 派生 `_DEPTH_BY_TYPE`、`_TYPE_TO_DIR`、LLM enum、`validate_schema_routing`；删除 `ingest.py:310` / `generator.py:64` 孪生副本与 `schema_routing.py:8` 缩水版；决断 8 类 vs 4 类（建议放开 8 类或显式降级）。
- **provider 工厂→注册表**：以 `TYPE_REGISTRY` 取代 `provider_factory.py:35-44` 的 if/elif，`minimax` 提为一等类型。

### 阶段 2 — 结构收敛（中风险）
- 建 `foundation/`，迁 `utils+lib+shared`，按 `{text,path,io,llm}` 分包；消除基础层对 `wiki.core` 的反向依赖（路径常量上提 `foundation/path`）。
- `src/templates/` → `src/scaffold/`，消除与 `wiki/templates/` 同名冲突。
- 治理件套并入 `governance/`，全部实现 `ports.PipelineStage`；`ndg_gate` 接回主链路。

### 阶段 3 — KOS 收尾（需产品决策）
- 逐个裁定 `knowledge/{storage,evolution,memory,provenance,graph,claims,conflicts}`：接线（注入 lifecycle/evolution loop、修 `mcp_server:127` 空 memory 后端、注册 `ClaimExtractor`/`Indexer` stage）或移 `knowledge/experimental/` 明确标记。
- 删除 `stages/__init__.py:7-14` 对 `Reviewer/ClaimExtractor` 的漏登记与对 `CandidatePromoter/Indexer` 的遗漏。
- 收敛 `KnowledgeType`↔`PageType` 双模型：要么以一方为唯一真源，要么明确 KOS 仅作派生视图。

---

## 五、风险与注意

1. **Markdown 真相源不可破**：所有改动不得改变「磁盘 Markdown 为唯一真相源」原则；`wiki_rules_prompt.py` 仍由 sync 生成、禁手改。
2. **保护微妙行为**：`run_ingest` 的"更新页面跳过标签校验""LLM 失败回退 source-only stub"等逻辑，迁入 stage 时必须逐条对照保留。
3. **测试耦合死模块**：`agent/collector.py` / `researcher.py` 仅被测试引用（如 `test_agent/test_collector.py:10`），删除前需改测试或同步移除。
4. **KOS 是产品方向非技术债**：`evolution/memory/provenance` 属 KOS 演进路线，阶段 3 应"接线或显式实验标记"，不宜直接删，除非产品确认放弃。
5. **分阶段交付**：建议每阶段独立 PR + 跑 `873 tests`（README 徽标计数），阶段 0/1 优先于结构性大改。

---

## 六、与现有文档关系

- 本方案是 `../superpowers/plans/2026-08-02-ingest-pipeline-completion.md`（KOS 接线）的**结构性上位方案**：后者聚焦摄取接线，本方案补齐页面类型、死代码、分层、治理件等全局问题。
- 问题证据可与 `../evaluations/`（tag-namespace、wiki-spec-consistency 等）交叉印证。
- 实施时以 `module-map.md`（接线状态图例）为进度跟踪底图。
