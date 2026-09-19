# V7 Stage 1 交接给远端机器执行

## 交接原因

源机（本机）从 2026-09-19 11:44 起被 MiniMax API 持续 429 限流，
`classify_doc` 的 3 次重试 × 4 次内部尝试全部耗尽，无法完成真实摄取。
换机器可换出口 IP / 配额，是本次交接的直接动机。
限流是外部依赖问题，不是 V7 代码问题。

## 交接范围

远端 agent 执行三件事：

1. **工作项 A** — 复现 V7 桥接冒烟，确认链路在干净机器上可用
2. **工作项 B** — Stage 1 灰度观察（3 天，用户已定）
3. **工作项 C** — 质量门修复计划 Task 6（隔离实例真实 smoke）

**不在交接范围**：Stage 2（改默认值）、Stage 3（删除 candidate/chunked/unified 旧路径）
——源机保留这两步的决策权。

## 为用户决策所做的准备

用户拍定两个选项：

- **同步范围 = A（可复现种子）**：只同步 `schema.md` / `purpose.md` / `taxonomy*.md` /
  `book.rules.md` / `.wiki-templates/` / `raw/`（133 文件 3.84 MB）+ `.llm-wiki/project.json`。
  **不含**已生成的 `wiki/` 页面与 `.index/`（属运行态产物，两边不混）。
- **provider 凭据 = 文档手动步骤**：密钥不入库，runbook 给命令模板，用户用安全渠道传递。

## 本次为交接新增/修改的产物

| 产物 | 说明 |
|---|---|
| `docs/ops/handoff-v7-stage1-remote.md` | 交接 runbook（10 节：目标 / 环境 / provider / 种子 / 三个工作项 / 回写约定 / 已知坑 / 文档索引） |
| `scripts/smoke_v7_bridge.py` | 由临时脚本 `.tmp-smoke-70kb.py` 提升为正式可移植脚本（argparse、仓库根自动注入、`sys.executable` 调 CLI、可配置预算） |
| `.gitignore` | 加白名单放行 `knowledge/*/.llm-wiki/project.json` |
| `knowledge/novel-wiki-v2/` | 首次入库项目种子 |

## 关键发现（交接前审查暴露）

### 发现 1（严重）：V7 路径上 Stage 6 关系抽取完全空转

三处叠加，导致 V7 产出的 concept 页 `relations: []`：

1. `bridge.py:488` 调 `extract_relations(concept_pages, llm=llm, project_root=...)`
   **没传 `index`**；而 `relation_extractor.py:43` 的 `index: Any = None` 默认值
   意味着落到文档里明确标注的「legacy / tests 路径」，而非生产本应走的
   `_extract_with_ontology`（有界候选检索 + 谓词白名单）。
2. legacy 分支 `relation_extractor.py:76` → `_extract_with_llm`，
   其 `asyncio.run(response)`（line 252）在已运行的事件循环内抛 `RuntimeError`，
   被 line 227 的 `except (... RuntimeError ...)` 吞掉 → 返回空。
   **这正是长期看到的 `RuntimeWarning: coroutine 'ProviderAdapter.complete'
   was never awaited` 的根因**，此前被当作存量噪音。
3. 即便返回了结果也没用：`bridge.py:488` 是 `_ = extract_relations(...)`，
   返回值被丢弃；`adapt_concept_page` 也从不给 `WikiPage` 传 `relations`
   （只有 `build_source_stub_page` 建 `references` 边）。

**实测证据**：`knowledge/novel-wiki-v2/wiki/concepts/d237368f-raw-sources-*.md`
frontmatter 为 `relations: []`；对比 candidate 路径的
`wiki/concepts/小说大纲写作技巧.md`，有 `taxonomy_of` + `references` 边。

**影响**：① Stage 6 每次仍花 1 次 LLM 调用但结果无用；② V7 concept 页没有
`refines` / `supported_by` / `taxonomy_of` 边，backlinks / relations 导航看不到它们；
③ **H2「unresolved 引用」因没有边而平凡通过**——Stage 1 验收不能把 H2=0
当作引用质量合格的证据。

**状态**：未修。属架构决策（是给 `extract_relations` 传 `index` 走 ontology 路径
并接住返回值，还是其它落关系方式），需用户先定方向。

### 发现 2（构建期）：`.gitignore` 里 `.llm-wiki/*` 会漏掉嵌套项目

含 `/` 的 gitignore 模式默认锚定到 `.gitignore` 所在目录，因此
`.llm-wiki/*` 只匹配仓库根的 `.llm-wiki`，**嵌套项目的 `.llm-wiki`
（如 `knowledge/*/.llm-wiki/server.lock`）会失去忽略**。
必须写成 `**/.llm-wiki/*`。已修正。

### 发现 3（脚本）：`RUFLO_V7_STAGE_TIMEOUT_SEC` 必须是整数

`BridgeBudget.from_env()` 用 `int()` 解析该环境变量，传 `"180.0"` 直接
`ValueError`。新脚本的 argparse 已改为 `type=int`。

## 交接后待办

1. 远端跑通工作项 A（若同样 429，则需换 provider 或降 `max_retries`）
2. Stage 1 观察期 3 天，逐日记录任务状态 / H1–H5 / wiki-quality
3. 观察期结束后由用户决定：延长观察 / 进 Stage 2 / 排查
4. 质量门修复计划 Task 6 完成后回写 `progress.md` 台账
5. **发现 1 需用户先定方向再动代码**

## 相关提交

交接产物在 `codex/book-series-target` 分支；`0e1e4f87` / `eaa8ca12` 是
plan 文档与 SDD 台账归档，交接提交在其之后。
