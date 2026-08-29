# ruflo-kb 模块 / 路线 / 双摄取路径分析报告

> 生成日期：2026-08-27
> 数据来源：codebase-memory-MCP full 索引（83,845 节点 / 135,728 边）+ `src/` 实际 import 链路取证 + `README.md` / `AGENTS.md` / `ADR-001` / kc spec 路线图
> 目的：梳理项目模块分层、执行路线、各路线目标，并对比两条主摄取路径（`pipeline/` vs `kc/`），给出"现在该用哪条"的判断。

---

## 一、项目总体目标

**ruflo-kb** —— Python 3.11+ 的**多 Agent 知识库平台 / Knowledge OS / auto-Wiki 生成器**。

| 维度 | 目标 |
|---|---|
| 输入 | 摄取 URL 及文件（PDF / DOCX / XLSX / HTML / MD / TXT） |
| 处理 | 经 `Collector → Analyzer → Generator` 流水线，把原始资料转为结构化 Wiki 页面 + 1536 维 LanceDB 向量 |
| 输出 | 结构化 Markdown 笔记（Wiki 页面：source / entity / concept / synthesis） |
| 服务 | 提供 **hybrid 搜索**（semantic 语义 + keyword 关键词，RRF 融合排序） |
| 演进 | 正从旧 `Novel-Knowledge-Base` 增量迁移；核心摄取正从旧 `pipeline/` 迁移到新 `kc/`（ADR-001 已 accepted） |

一句话落地：**让多个 AI 安全地共建一份可信知识（knowledge 真相层），并把它编译成人类能读懂、能查、能长期养好的 Wiki（wiki 呈现层）。**

### 双核心数据层（与"代码"无关的产品定位）

- **`knowledge/` = 机器侧真相层**：事件溯源（EventStore）+ 溯源（Provenance）+ 冲突检测，保证多 Agent 并发读写不丢信息、每条知识可溯源、重复摄取幂等合并。解决"对不对、从哪来"。
- **`wiki/` = 人侧呈现层**：把真相层编译成带 frontmatter（grade / processing_depth / heat / relations / tags）的 Markdown 页面，配合 Obsidian + Dataview 做动态查询、关系图导航。解决"好不好读、好不好查、好不好养"。

两者通过 Generator 单向编译衔接：改呈现不必动真相层，真相层合并冲突也不破坏可读页面。

---

## 二、模块分层（src/ 共 343 个 .py 文件）

| 层 | 模块 | 职责 |
|---|---|---|
| **入口层** | `cli.py` + `cli_ext/`(60) | CLI 子命令（project / llm-providers / serve / health / schema / quality …） |
| | `server/`(20 routes) + `services/`(15) | FastAPI HTTP API 与业务服务层 |
| | `mcp_server/` | stdio MCP（13 tools），供外部 Agent 驱动 |
| **双核心数据层** | `knowledge/` | 真相层：KnowledgeObject + Provenance + EventStore + 冲突检测 |
| | `wiki/`(core / storage / features / templates) | 呈现层：source / entity / concept / synthesis 页面 + 模板 + frontmatter |
| **摄取层** | `pipeline/`(legacy) + `kc/`(new) | 两条 ingest 主路线（见下） |
| | `collector/` + `queue/`(9) + `utils/extract/` | 采集、异步队列、文件抽取 |
| **智能层** | `llm/` | provider 注册（OpenAI / Anthropic / Ollama / MiniMax / Kimi / DeepSeek / GLM 等兼容端） |
| | `agent/` + `orchestrator/` + `research/` + `vision/` + `quality/` | 多 Agent 运行时、编排、深研、视觉、质量评审 |
| **检索层** | `vector/` + `searcher/` | LanceDB 向量 + hybrid(RRF) 检索 + 带引用问答 |
| **治理 / 运维层** | `schemas/` `maintenance/` `metrics/` `project/` | frontmatter 迁移、H1/H2/H4 健康、指标、多项目 |
| **支撑层** | `events/` `sync/` `web/` `templates/` `kc/contracts·adapters` | 事件总线、快照、前端、业务模板、契约 |

**前端**：`web/`（index.html + js：app / router / api + views：browse / search / chat / ingest / graph / heat / collect / settings / templates / status）。

---

## 三、有几条"路线"（端到端产出知识库的流程）

从「把输入变成知识库内容」的视角，有 **2 条主路线 + 6 条旁挂能力路线 + 一批治理路线**。

### 主路线（产出知识，过渡并存）

| # | 路线 | 入口 | 数据流 | 目标 |
|---|---|---|---|---|
| ① | **旧流水线 (legacy pipeline)** | HTTP `/api/v1/.../ingest` → `queue` | Collector → Analyzer(LLM) → Generator(LLM) → `write_page` + index + log | 确定性骨架 + LLM 生成正文，事后靠 quality 门禁修 |
| ② | **新知识编译器 (kc)** | HTTP `/api/v1/kc/compile` | Collector → parse → `validate_evidence` → `verify_claim` → compile → `project_wiki` | 以证据为锚、写入前验证、fail-closed；ADR-001 指定为未来主路径 |

### 旁挂能力路线（独立子命令 / 路由，不在主 ingest 关键路径）

| # | 路线 | 入口 | 目标 |
|---|---|---|---|
| ③ | 批量多 Agent 演进 | `batch` → `orchestrator/agent` | 对已有 KB 批量补写 / 演进 |
| ④ | 联网深研 | `research` → `research/`(Tavily) | 联网调研产出研究笔记（偏离"我的文件" source-of-truth） |
| ⑤ | 视觉理解 | `vision` → `vision/` | PDF 图片抽取 + 图说（低频高成本） |
| ⑥ | 网页采集 | `capture` / `collect` | 抓网页转笔记 |
| ⑦ | 对话问答 | `chat` route + `searcher/qa` | 基于已有 KB 的带引用问答（不新增知识） |
| ⑧ | MCP 驱动 | `mcp` stdio | 暴露 13 tools 供外部 Agent 调用 |

### 运维 / 治理路线（不产生新知识，维护已有库）

`health` `quality` `lint` `dedup` `stubs` `heat` `relations` `tags` `fields` `schema` `vector reconcile` `cache` `metrics` `templates` `project`

> **结论**：若只算"端到端把资料变成知识"的路线 = **2 条**（legacy + kc，过渡并存）；加上旁挂能力 = **8 条**。两者并存是 ADR-001 的迁移过渡态，不是废代码。

---

## 四、8 条路线 × 是否在关键路径 对照矩阵

> 判定标准：「关键路径」= 端到端把原始资料变成可被人类消费的知识库内容、且默认开启的主链路。

| 路线 | 是否关键路径 | 成熟度 | 对"核心目标"的贡献 | 风险 / 备注 |
|---|---|---|---|---|
| ① legacy pipeline | ✅ 是（当前生产路径） | 已接全链路 | 直接产出 4 类可读 Wiki 页 | 非确定（LLM 写散文），靠页级门禁 + 可选评审兜底 |
| ② kc 编译器 | ⚠️ 未来主路径（迁移中） | 最小闭环跑通，公共路由未落盘 | 以证据为锚、防幻觉、可重建 | 见第五节 3 个阻断点 |
| ③ batch 多 Agent 演进 | ❌ 旁挂 | 子命令可达 | 演进已有 KB | 范围蔓延风险，价值取决于真实使用者 |
| ④ research 联网深研 | ❌ 旁挂 / 跑题 | 子命令可达 | 产出研究笔记 | 与"我的文件" source-of-truth 目标相悖 |
| ⑤ vision 视觉理解 | ❌ 旁挂 | 子命令可达 | PDF 图说 | 低频高成本，ROI 低 |
| ⑥ 网页采集 | ❌ 旁挂 | 子命令可达 | 抓网页转笔记 | 合理但非核心生产 |
| ⑦ chat 问答 | ❌ 旁挂（交互） | 路由可达 | 不新增知识，只消费 | 合理，取决于是否有使用者 |
| ⑧ MCP 驱动 | ❌ 旁挂（驱动） | stdio 可达 | 暴露 13 tools 供外部 Agent | 仅当真从外部驱动才有价值，否则闲置基建 |

---

## 五、`kc/compile` 与 `pipeline/ingest.py` 实际输出差异

### 5.1 数据流对比（代码实证）

```
pipeline/ingest.py:
  源文本 → Collector(抽取) → Analyzer(LLM 抽 AnalysisResult)
        → Generator(LLM 渲染 WikiPage 列表，遵循模板)
        → write_page + append_to_index + log_event
  产物：source / entity / concept / synthesis 四类页（叙事型）

kc/api.py:compile_source:
  源文本 + candidate_json(LLM 抽取的 claims+evidence，自备)
        → LegacyCollector.collect() 归一为 CanonicalDocument（块级切分）
        → parse_candidate_json() 严格校验 claims 结构（缺 id/text/evidence 即报错）
        → validate_evidence()  Evidence 必须命中文档真实 block + quote_hash 校验
        → verify_claim()         Claim 必须有 verified 状态 evidence 才放行
        → compile_claim()      → KnowledgeObject（接现有 knowledge 模型）
        → project_wiki()       → WikiPage（带 evidence_refs 溯源，_ko_extra 引用级证据）
  产物：CLAIM 页（每 claim 一页，带引用级证据）
```

### 5.2 关键差异对照表

| 维度 | ① legacy pipeline | ② kc |
|---|---|---|
| 证据强度 | 页级 `sources:[路径]`，无引用级证据 | 引用级 quote 命中真实 block + sha256 校验 |
| 防幻觉时机 | 事后（quality 门禁 / 可选 LLM 评审修） | 事前（verify_claim 无 verified evidence 即 fail-closed 拒写） |
| 是否调 LLM | 是（Analyzer + Generator 都调） | **否**（candidate_json 需自备，抽取在 kc 之外） |
| 产出页型 | source / entity / concept / synthesis（叙事型，人读友好） | CLAIM 页（每 claim 一页，机器友好 / 审计友好） |
| 自动落盘 | 是（write_page + index + log + vector pending 全接） | **否**（路由 `/kc/compile` 只返回 `{"document_id","projections"}`，未调 `write_projection` 写盘） |
| 溯源 / 重建 | 元信息级 | Wiki 仅为 WikiProjection，可从 Core 重建（ADR 不变量） |
| 失败模式 | 软（低质页进 quarantine 或降级） | 硬（fail-closed，证据不达标整条拒写） |

### 5.3 现在该用哪条：明确判断

**首选 ① legacy pipeline（`pipeline/ingest.py`）** —— 因为它现在就是"能直接产出 wiki"的那条：
- 端到端已接：`HTTP /ingest` → `queue` → `write_page` → `index.md` 追加 → `log.md` → vector pending；
- 产出 4 类页 + 完整 frontmatter（grade / processing_depth / relations / tags），人能读、能 Dataview 查、能维护；
- 非确定但工程上已兜住：规则门禁（ghost / empty / dup）+ 可选 LLM 评审（默认关）+ 反向关系 / 缺失引用对账。

**② kc 是未来方向，但今天有 3 个阻断点，不能直接当生产力用：**
1. **公共路由未落盘** —— `src/server/routes/kc.py` 的 `/kc/compile` 只调用 `compile_source` 返回字典，**未调 `write_projection` 写盘**（落盘 adapter 存在但没接进路由）；
2. **kc 不调 LLM** —— `candidate_json` 要自备，抽取那步在 kc 之外；
3. **产物形态不同** —— kc 产出 `CLAIM` 页（无叙事型 4 类页，不自动挂 index / log / vector），对"人读知识库"体验弱。

**但 kc 的信任内核正是 pipeline 缺的**：pipeline 只有页级 `sources:[路径]`，无引用级证据；kc 用 `validate_evidence` + `verify_claim` 把"防幻觉"做在写入之前，而非事后评审补。

### 5.4 务实迁移建议

| 目标 | 用哪条 | 理由 |
|---|---|---|
| 现在就要可读、可查的 wiki | **① pipeline** | 全链路已接，直接出 4 类页 |
| 要可信、可审计、可重建 | kc 内核 | 需自接 `write_projection` + 自备 candidate 抽取 + 补 index / vector 接线 |
| **两全（推荐）** | pipeline 为主 + 挂 kc 校验插件 | 把 `verify_claim / validate_evidence` 作为"证据校验"嵌进 pipeline 的 generate 阶段，给每页补 quote 级 evidence——既保住可读 wiki，又拿到 kc 的防幻觉内核，比硬切 kc 更稳 |

---

## 六、对"伪需求"的评估结论（呼应前序分析）

**真实成立的需求（核心边界，别动）**：
- Collector→Analyzer→Generator 流水线（确定性骨架）
- knowledge 真相层（Provenance / EventStore / ConflictDetector）——多源合并刚需
- wiki 呈现层 + 模板 + frontmatter（Dataview 可查、可维护）——核心价值
- hybrid 搜索（vector + RRF）——知识库根本用途
- 异步队列 ingest——工程刚需
- **kc 信任内核**（以证据为锚的编译）——最有价值的设计，是 knowledge/wiki 双核心"可信"目标的正式落地

**偏重 / 可质疑项**：
- `kc` 整体 = 真需求 + 当前主方向；但其 B 段 spec 路线图（11 Gate / 254 项目标 / 13–16 周）对"个人 / 单租户 Obsidian 库"可能过度。
- `vision` / `research` / 深研 Agent = 范围蔓延风险高，ROI 低，偏离核心目标。
- `heat` 衰减 / 僵尸页 / 冷页模型 = 过度设计，Obsidian + Dataview 用"修改时间 + 反链数"即可。
- `schemas/` 四版 frontmatter 迁移（v1→v2→v2.1→v2.2）= 单租户个人库用不上。
- `quality/` 集成评审 + 隔离 = 部分自产自销（修 LLM 生成自己引入的不稳定）；若改确定性抽取 + 模板可大幅删减。

---

## 七、图谱索引规模（codebase-memory-MCP full 模式）

| 指标 | 数值 |
|---|---|
| 总节点 | 83,845 |
| 总边 | 135,728 |
| 跳过文件 | 0 |
| 高内聚簇（Leiden） | 11 个，核心枢纽均为 `WikiPaths` / `ensure_knowledge_base` / `write_page` / `generate_ingest` / `EventStore.append` 等 ingest / wiki 关键路径 |

> 已正确排除 `.venv` / `uv-cache` / `graphify-out` / `.git` / `__pycache__` 等第三方依赖与生成产物，未污染图谱。
