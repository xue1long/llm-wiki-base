# LLM-Wiki 双项目全量对比报告
> 生成时间：2026-08-10
> 对比对象：
> - **A（当前工作区）** = `D:\5-Project\LLM-Wiki`
> - **B（7-31 快照）** = `D:\5-Project\LLM-Wiki-7-31\LLM-Wiki`

## 0. 一句话结论

这两个目录**不是同一个项目的两个版本，而是从共同祖先分叉出的两条不同演进路线**：

- **A（当前）** = **生产管线方向**：保留了 `orchestrator / server / searcher / schemas`，以 `novel-wiki` 实例的「采集→生成→语义索引」完整体验为目标，知识库已基本跑通（2596 篇 wiki + 955 个 LanceDB 数据文件）。
- **B（7-31）** = **Knowledge-OS 研究方向**：用一个庞大的 `knowledge/` 包（graph / evolution / provenance / memory / conflicts / claims / storage / lifecycle）做「知识操作系统」实验，配套大量研究与评测文档、脚本与测试。其 `novel-wiki` 实例基本停留在采集阶段（2009 个 raw，仅 4 篇 wiki，索引为空）。

> ⚠️ B 的 git 仓库**从未提交过任何 commit**（所有文件 `git add` 暂存但未 commit）。若 B 对你有价值，先把它 commit 下来，否则极易丢失。

---

## 1. 仓库与 Git 状态

| 维度 | A（当前工作区） | B（7-31 快照） |
|---|---|---|
| 分支 | `main` + `feat/continue-implementation` + worktree | 仅 `main`（含 worktree 引用） |
| 提交历史 | **有**，最近 15+ 提交（最新：`feat(pipeline): add rule-based wiki page quality gate`） | **无 commit**（全部文件处于 `A` 暂存态，未提交） |
| 工作区改动 | 大量未提交修改（knowledge 概念页 M/D） | 全部 `git add` 暂存，无基线 |
| remote | `origin/main` | `origin/main`、`origin/feat/combined-llm-generation`、`origin/feat/ndg-remediation`、`origin/master` |

A 的近期提交主题（管线成熟度信号）：quality gate、SourceSanitizer、MiniMax embedding 修复、concurrent archive、wiki 去重修复、slug 规范化等——纯生产管线打磨。
B 的暂存文件包含 `.superpowers/sdd/*`、`docs/ARCHITECTURE.md`、`KNOWLEDGE_OS_EVOLUTION_FEASIBILITY_REPORT.md`、`.github/workflows/wiki-spec-sync.yml`——纯研究/治理方向。

---

## 2. 规模总览（排除缓存/venv/.git/node_modules）

| 目录 | A 文件数 | B 文件数 | 仅 A | 仅 B | 内容变更 |
|---|---:|---:|---:|---:|---:|
| `src/` | 227 | 319 | 7 | 99 | 126 |
| `tests/` | 244 | 361 | 6 | 123 | 155 |
| `docs/` | 70 | 120 | 2 | 52 | 3 |
| `scripts/` | 16 | 37 | 0 | 21 | 2 |
| `web/`（不含 node_modules） | 13 | 13 | 0 | 0 | 5 |
| `knowledge/`（novel-wiki） | ~3957 | 2020 | — | — | — |

整体文件数（含缓存）：A ≈ 15946，B ≈ 16492。差异主要来自 `src/`、`tests/`、`docs/`、`scripts/` 与 `knowledge/` 内容，而非缓存垃圾。

---

## 3. 源码架构分叉（最关键差异）

### 3.1 仅在 A（当前）存在的源码（7 个）
生产管线新增：
- `orchestrator/`（整套：`__init__`、`audit_hard`、`orchestrator`、`router`、`state_machine`）
- `pipeline/auto_archive_config.py`
- `sync/file_watcher.py`

### 3.2 仅在 B（7-31）存在的源码（99 个）—— 按包归类
- **`knowledge/` 整包（约 50 个文件）**：`claims/`、`conflicts/`、`core/`（adapter/candidate/concurrency/lifecycle/object/version_manager）、`evolution/`（loop/scheduler）、`graph/builder`、`kernel`、`lifecycle/decay`、`memory/`（decision/retrieval/types）、`provenance/tracker`、`storage/`（event_store/facade/metadata/object_store/wiki_adapter）。→ 这就是 Knowledge-OS 内核。
- **`agent/` 拆分**（6）：`collector / curator / historian / researcher / skills`（A 中这些被合并进 `agent/runtime.py`、`agent/tools.py`）。
- **`cli_ext/` 研究命令**（3）：`decision_cmd`、`evolution_cmd`、`project_templates_cmd`。
- **`llm/` 增强**（3）：`provider_profiles`、`rate_limiter`、`token_metrics`。
- **`pipeline/` 子阶段拆分**（约 15）：`chunker`、`checkpoint`、`context_budget`、`c_grade_handler`、`generator_constraint`、`ingest_report`、`config`、`_prompt_common` 等（A 已将这些逻辑收敛进 `pipeline/{collector,analyzer,generator,librarian,service,sanitizer,quality_gate}.py`）。
- **`_deprecated/orchestrator/`**（5）：A 的 `orchestrator/` 在 B 中被整体废弃并移入 `_deprecated/`。
- 其余：`mcp_server/memory_tools.py`、`lib/validators.py` 等。

### 3.3 两边都有但内容不同（126 个）
覆盖共享核心：pipeline（analyzer/collector/generator/librarian/service/sanitizer/quality_gate/schemas）、llm（minimax_embed/openai_provider/provider_factory/types）、project、quality、queue、permissions、cli、cli_ext 全套命令、server/routes、maintenance/checks 等。说明**共享内核也在两边各自演进**，不是单向移植。

**解读**：A 把 B 的 `knowledge/` 内核整体替换为 `orchestrator + server + searcher + schemas` 的轻量生产架构，并把 `agent/*`、`pipeline/*` 的多文件拆分收敛为合并实现；B 则走向「知识图谱 + 演化 + 溯源 + 记忆」的重型内核。二者是**架构级反向分叉**。

---

## 4. 测试分叉

- A 独有 6 个：`test_file_watcher.py`、`test_orchestrator/*`（router/state_machine/audit 等）。
- B 独有 123 个：主要是 `test_knowledge/*`（约 40 个，对应 knowledge 内核）、`test_agent/test_{collector,curator,historian,researcher,skills}.py`、`test_pipeline/test_{chunker,checkpoint,context_budget,c_grade_handler,...}.py`、`conftest.py`、`fixtures/prompt_golden/*`、`test_deprecated/*`、`test_e2e/test_batch_status_completion.py` 等。
- 共有 155 个测试文件内容不同——测试套件同样分叉严重。

---

## 5. 文档分叉

- A 独有 2 个：`guides/ingest-optimization-plan.md`、`reference/ingest-prompts.md`（生产 ingest 向）。
- B 独有 52 个：大量研究与治理文档——
  - `KNOWLEDGE_OS_EVOLUTION_FEASIBILITY_REPORT.md`、`ARCHITECTURE.md`、`CONSTRAINTS.md`、`INDEX.md`、`TECH_DEBT_CHECKLIST.md`、`project-brief.md`
  - `evaluations/*`（约 13 篇：nash 吸收、语义分类、标签命名空间、wiki-spec 一致性审计…）
  - `guides/structure-optimization-proposal-v{1..5}*`、各种 ingest 规范
  - `superpowers/plans/*`（约 18 篇 2026-08 计划与审计）
  - `plans/*`（性能优化、压测、模板演化）
- 共有仅 3 个文档不同：`environment/SETUP.md`、`environment/requirements-cp314.txt`、`guides/wiki-spec.md`。

---

## 6. 知识库（novel-wiki 实例）差异 —— 最实用的差别

| 子目录 | A（当前） | B（7-31） |
|---|---:|---:|
| `raw/`（源材料） | 1361 | **2009** |
| `wiki/`（生成页） | **2596** | 4 |
| `.index/lancedb` 数据文件 | **955**（索引已填充） | 1（基本为空） |
| `.llm-wiki` 配置 | 有 | 有 |
| 另有 `perf-test/` | 无 | 6 |

**解读**：
- A 已把 novel-wiki **完整跑通生成+语义索引**（2596 篇 wiki + 955 个向量文件）——这是可直接检索/问答的生产态知识库。
- B 的 novel-wiki 停留在**采集阶段**：raw 比 A 还多（2009 vs 1361），但几乎没生成 wiki（4 篇）、索引为空。**注意**：两边的 raw 来源集合未必相同，不能简单理解为「B 是 A 的前身」。
- 结论：若你要用的是**已建好的小说知识库**，A 才是成品；B 的 novel-wiki 等于没建完。

---

## 7. 根配置与入口文件差异

| 文件 | A | B | 状态 |
|---|---:|---:|---|
| `pyproject.toml` | 730 B | 2513 B | **DIFFER** |
| `README.md` | 9949 B | 9940 B | DIFFER |
| `CLAUDE.md` | 27457 B | 27810 B | DIFFER |
| `.gitignore` | 1194 B | 1526 B | DIFFER |
| `env.example` | 4009 B | 4009 B | same |
| `registry.json` | **718394 B** | 39 B | DIFFER |
| `start.bat` | 1241 B | 1241 B | same |
| `start-full.bat` | 1858 B | 1858 B | DIFFER |

要点：
- **`registry.json`**：A 含真实项目注册数据（718 KB）；B 是空的 `{"version":1,"projects":{}}`。A 是已初始化的项目注册态，B 是未注册/重置态。
- **`pyproject.toml`**：B 版本号 `2.0.0` 且带完整 `ruff`/`mypy` 配置；A 是 `0.1.0` 精简版（仅依赖 + pytest）。**反向**：B 在打包治理上更「正式」，A 更务实精简。
- `README`/`CLAUDE`/`.gitignore`/`start-full.bat` 均有差异，需按用途逐一核对。
- `env.example` 与 `start.bat` 完全一致——基础运行配置一致。

---

## 8. Web 前端

两边 `web/` 源码文件数相同（13，不含 `node_modules`）。差异仅在 5 个文件内容：
`js/views/{ingest,search,settings,status}.js`、`style.css`。
注意：B 的 `web/` 含 `node_modules/`（2730 个文件，未在对比计入），A 不含——A 的前端依赖未安装/未提交。

---

## 9. 综合判断与建议

1. **它们不是「新旧版本」，而是两条分叉路线**：A=生产管线（orchestrator/server/searcher/schemas + 已建好的 novel-wiki），B=Knowledge-OS 研究内核（knowledge/ 图演化溯源 + 大量研究文档/测试）。
2. **如果你要的是能用的知识库系统**：保留 **A**。它 git 历史清晰、novel-wiki 已生成+索引，且修复了 MiniMax/权限/去重等已知坑（见项目 MEMORY）。
3. **如果你要的是 Knowledge-OS 研究方向**：代码在 **B**，但 B 的 git **零提交**（全部暂存未 commit），且 novel-wiki 没建完。**立即对 B 做一次 commit 或备份**，否则一 `git reset/checkout` 就可能丢数据。
4. **不要直接互相覆盖**：两棵树的同名文件有 126(src)+155(tests)+… 处内容不同，且目录结构已不兼容（orchestrator vs knowledge）。任何合并都应按「取 A 的生产管线 + 选择性移植 B 的研究模块」手工进行，而非目录拷贝。
5. **可安全共享的部分**：`env.example`、`start.bat` 完全一致，可直接复用；`uv.lock` 两边字节相同（249474 B），依赖锁定一致。

---

## 附：对比方法（可复现）
脚本：`/tmp/compare_projects.py`（Python 标准库，按相对路径做集合差 + MD5 内容比对，已排除 `.git/.venv/__pycache__/node_modules/.superpowers/.claude/.obsidian` 等）。如需把完整文件级 delta 落盘为 CSV/JSON，可再跑一次并导出。
