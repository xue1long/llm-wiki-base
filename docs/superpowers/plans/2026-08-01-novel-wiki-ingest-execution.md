# 执行方案 — novel-wiki 摄入规范 v2 落地（2026-08-01）

> 依据：`docs/guides/novel-wiki-ingest-spec.md`（规范 v2）。本文件是把规范"翻译成可执行任务"的实施计划：每阶段拆任务，标注 Files / Tests / Implementation guidance / 验收 / commit。遵守 CLAUDE.md 的 TDD-per-task + 一次一 commit + 每任务 reviewer 工作流。
>
> **已完成的阶段**：Phase 0（基线审计，数字见规范 §十）、Phase 2（concept 项目模板 + F2 验证）。**本方案执行 Phase 0.5 / 1 / 3 / 4 / 5。**

## 执行顺序（依赖是硬约束）

```
Phase 0.5 Generator 对账层 ──(必须先行，否则 Phase 1/4 白做)──┐
   ├─► Phase 1 数据清理（占位页 + 旧前缀 tag）                 │
Phase 3 Lint 增强 + 提示词（可与 1/4 并行，UGC 检查依赖 Phase 4 数据）
Phase 4 分批再摄取 ──(依赖 0.5 已生效)────────────────────────┘
Phase 5 合规（随时可做，建议最后）
```

**验收总目标**（规范 §十）：tap rate ≥80%｜占位页 0｜grade C <10%｜sources 非空率 100%｜孤立页 <10%｜LINT-DUPLICATE 0｜`tags validate` 全绿｜每批 ≤20 文件。

---

## Phase 0.5 — Generator 对账层（F3 修复，前置）

### 0.5.1 引用-产出对账（修 stub 根因）
- **Files**：`src/pipeline/ingest.py`（stub 逻辑区 ≈686–837 行，`missing = referenced − produced − existing` 的自动建 stub 分支）
- **Tests**：扩展 `tests/test_pipeline/test_ingest_crossref_p0.py`
- **Implementation guidance**：
  1. 生成页后、建 stub 前，对每个 `missing` slug 分级处置而非一律建 stub：
     - **source 页错误 slug 变体**（**判据：slug 的 `-[0-9a-f]{8}` 尾 == 某个真实 source 页确定性 slug 的 `md5(path)[:8]`**，禁止用"去连字符比 stem"的宽松匹配，以免误伤合法实体）→ 打 WARN 日志，**不建 stub**。该错误引用**不靠 Phase 4 自动修复**——已有 stub 与引用由 Phase 1 重指，新引用随真实 source 页建成后再处理。
     - **tag 名 / 路径状 / 类型前缀 / `-entity` 后缀** → 打 WARN，不建 stub。
     - **clean 真实实体引用** → 仍建 stub，但受硬上限约束（见 0.5.3）。
  2. 未解析引用一律记入 `unresolved_references`，并**必须有下游动作**：进人工队列（Phase 1 清理时重指/摘除）或下一批摄取自动重试——否则 cap 掉 stub 只是把"占位污染"换成"断链污染"。
- **验收**：合成一个 Generator 引用幽灵 slug 的摄取 → stub 数 0（或等于硬上限）；`test_ingest_crossref_p0.py` 新增用例通过。

### 0.5.2 生成页 id 校验（修坏 id）
- **Files**：`src/pipeline/generator.py`（`slug = _slugify(title)`：unified_generate ≈522 行、generate ≈776 行）
- **Tests**：`tests/test_pipeline/test_generator.py`
- **Implementation guidance**：`slug` 计算后加白名单校验，命中任一即 WARN + 修复或跳过：
  - tag 前缀：`^(题材|功能|角色|事件|情绪|实体|场景阶段|状态|素材|可信度)-`
  - 类型前缀：`^(source|concept|synthesis|entity)-`；后缀 `-entity$`
  - 路径状：含 `raw` / `--` / `-md-`
  - 修复策略：可剥词缀类（tag 前缀/类型前缀/`-entity`）剥掉后若仍干净则用之；**路径状 id 无法修复 → 整页丢弃 + 记日志**（不要"跳过→触发 stub"）；正则只对 `slug` 生效，命中后仍需人工/日志确认确是坏 id，避免误伤合法标题（如"题材-和-读者"）。
  - **与 0.5.1 的交互**：被丢弃页的引用一律进 `unresolved_references`，**不走"clean 实体被引用→建 stub"兜底**，避免跳过页制造新 stub。
- **验收**：`title="func-教程"` → 该页被修复或跳过；`test_generator.py` 用例通过。

### 0.5.3 stub 兜底与硬上限
- **Files**：`src/pipeline/ingest.py` `_get_max_stubs_per_ingest`（≈781 行）
- **Implementation guidance**：把默认上限收紧（如 ≤3），超限一律不建并告警到 `log.md`；上限写入 `.index/quality_settings.json` 便于配置。
- **验收**：同一 raw 连跑两次摄取，stub 计数稳定不增。
- **Commit**：`fix(pipeline): 引用-产出对账 + 生成页 id 校验，遏制 stub 自动生成`

---

## Phase 1 — 数据清理

### 1.1 占位页清理（引用修复 → 归档/删除）
- **Files**：`scripts/cleanup_stub_pages.py`（新建，复用 `scripts/audit_placeholder_classify.py`）
- **Steps**：
  1. **dry-run**：按形态分类 538 个 stub（audit_placeholder_classify），输出每类清单。
  2. **source_like（139）**：按**确定性 slug 判据**（hex 尾 == 真实 source 页 `md5(path)[:8]`）匹配真实 source 页 → 存在则把引用重指到真实 slug；不存在则删 stub + 双向清理引用（Phase 4 重取会重建真实源页，**stub 本身必须在此删除**）。
  3. **clean（382）**：同名真实页已存在 → 重指；否则删 stub + 双向清理引用。
  4. **坏形态（16）**：删 stub + 双向清理引用。
  5. **双向清理定义**（每个被删 stub 都要做）——① 引用方 `relations[].target` / `[[wikilink]]` 指向 stub 的：重指或移除；② **stub 自身 relations 指出去的关系、以及别的页 `target == stub` 的反向边**（`_compute_reverse_relations` 产物）一并清理，避免删后残留死链。
  6. 删除用 `git rm`（天然可回滚），归档副本放 `.llm-wiki/dedup_history/`（**不放 `wiki/_archive/`**——`quality_check_wiki.py` 会 `rglob("*.md")` 扫到它）。
- **验收**：`python scripts/quality_check_wiki.py <root>` 的 broken-wikilink 数显著下降；entity 页数 ≈ 1110−538；`lint` 不新增问题。
- **Commit**：`chore(novel-wiki): 清理 538 个 stub entity 页 + 修复引用`

### 1.2 旧英文前缀 tag 迁移
- **Files**：`scripts/migrate_legacy_tags.py`（新建）
- **Implementation guidance**：扫描 `wiki/{sources,entities,concepts,synthesis}/*.md`，解析 frontmatter `tags`，按映射 `genre→题材, func→功能, char→角色, event→事件, mood→情绪, entity→实体, scene_phase→场景阶段, status→状态` 改写（保留 tag 名，如 `genre/玄幻→题材/玄幻`）。**先 dry-run** 输出将改写的文件数；正式跑前 `git add` 全部 wiki 页以便一键回滚。
- **验收**：`python -m src.cli tags validate --all --project 8dd46257-...` 全绿。
- **Commit**：`chore(novel-wiki): 迁移旧英文前缀 tags 到中文前缀`

---

## Phase 3 — Lint 增强 + 提示词

### 3.1 新增 3 项 lint 检查
- **Files**：`src/wiki/features/lint.py`（现 6 项确定性检查），`tests/test_wiki/test_lint.py`
- **Implementation guidance**：新增检查（全部确定性、无 LLM）：
  - `LINT-RAW-PASTE`：body 存在 >300 字、未用 blockquote/list 包裹、**且页面 type ≠ source 且非"正文内容"章节**的长段 → 未加工原文。**必须豁免 source 页**——其 `main_content` 槽本就是完整正文（>300 字长段是设计行为）。注意：lint 读的是**渲染后 body**（无 slot 标记），判定只依赖渲染结构，不写"slot 标记内"这类运行时概念。
  - `LINT-MISSING-SOURCES`：`sources` 字段为空 **且** 无 `derived_from/supported_by` 关系。**豁免**：聚合多 raw 的 synthesis 页只要 `sources` 列出全部来源即合法；完全无来源才违规。
  - `LINT-UGC-CRED`：带 `素材/ugc` 但缺 `可信度/ugc`。
- **验收**：三个新 code 的单元测试通过；在 novel-wiki 上跑出合理违规量级（**LINT-UGC-CRED 在 Phase 3.2 打标规则 + Phase 4 数据落地前预期为 0，属正常，不代表方案未生效**）。
- **Commit**：`feat(lint): 新增未加工原文/溯源缺失/UGC可信度检查`

### 3.2 提示词 UGC 打标显式规则
- **Files**：`src/pipeline/generator.py`（GENERATOR_PROMPT + UNIFIED_PROMPT）、`src/pipeline/analyzer.py`
- **Implementation guidance**：加一条显式指令——"来源为公众号/论坛/自媒体/UGC 的页，tags 必须含 `素材/ugc` + `可信度/ugc`；专业书籍含 `素材/book` + `可信度/book`"。这是 §十"可信度/ugc 100%" 与 Lint 项 9 的**前提**（规范 BUG-E）。
- **验收**：重摄取一份 UGC 样例，页 tags 含 `素材/ugc` + `可信度/ugc`。
- **Commit**：`feat(pipeline): 提示词显式要求 UGC 素材打 素材/ugc + 可信度/ugc`

---

## Phase 4 — 分批再摄取

### 4.1 摄取欠账清单
- **Files**：`scripts/build_reingest_backlog.py`（新建）
- **Implementation guidance**：列出 1361 raw 中未被任一 wiki 页 `sources` 引用的文件（≈1051），按主题/目录分组，产出 ≤20 文件/批的分批清单；标记每批主题与优先级。
- **验收**：清单可预览、分组合理。

### 4.2 分批再摄取（含反斜杠路径）
- **Files**：批次脚本（API 循环或 `run_ingest` 程序化入口）
- **Implementation guidance**：
  - 每批 ≤20 文件，批间停顿，超预算即停。
  - 只重取清单内的未引用 raw——**不重复触达已引用文件**（幂等对旧文件无效，靠清单兜底，见规范 §六）。
  - 源页 slug 由 `{NFC stem}-{md5(path)[:8]}` 决定：路径不变则 slug 不变 → 覆盖而非重复。
  - **反斜杠路径规范化拆成独立子步骤**：先跑 `scripts/normalize_sources_paths.py` 处理存量页并**单独 commit**，再开始批次摄取——避免一次失败分不清是路径问题还是 Generator 问题。
  - 每批后跑门禁：`lint` + `tags validate` + `fields validate`；stub 计数若回升即回退排查（说明 0.5 未生效）。
- **验收**：tap rate 逐批上升，目标 ≥80%；stub 不新增；`sources` 全正斜杠。
- **Commit**：`feat(novel-wiki): 分批再摄取未触达 raw（每批≤20 + 门禁）`

---

## Phase 5 — 合规

### 5.1 现状盘点 + 敏感内容处置
- **Steps**：列出 `raw/sources/` 中已入库的第三方全文/隐私内容清单 → 决定保留 / `git rm --cached` + `.gitignore` 排除同步；为未来的 `conversations/ journal/ transcripts/ assets/` 提前写 `.gitignore` 条目。
- **验收**：`git ls-files` 确认敏感目录未跟踪；`.gitignore` 条目存在。
- **Commit**：`chore(compliance): 现状盘点 + .gitignore 排除敏感/大文件`

### 5.2 synthesis 人工门流程
- **Steps**：固化流程文档（stubs → 候选清单 → 人工确认 → 创建 synthesis），明确复核人与频率。
- **验收**：流程文档落盘，一次"候选→发布"演练通过。
- **Commit**：`docs: synthesis 人工门流程`

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| Phase 1 删 stub 造成断链 | 先做引用修复（1.1 步骤 2-4）再用 `git rm`；全程 git 可回滚 |
| Phase 4 重取制造新 stub | 0.5 必须先行；批后门禁查 stub 计数，回升即停 |
| 旧前缀 tag 迁移破坏 frontmatter | 迁移前**先让用户提交/stash 现有 novel-wiki 改动**（当前工作树很脏，"`git add` 全部 wiki 页"会把用户无关改动卷进迁移 commit）；dry-run 先行；**只正则改写 `- <legacy>/` 打头的 tag 行、不整体 YAML dump**（避免全库格式噪音）；回滚用独立 commit + `git revert` |
| Lint 新检查误报 | 全部确定性规则 + 单元测试；先在 novel-wiki 上校准阈值再全量 |
| 成本失控 | 每批 ≤20 + 预算硬停；只取清单内未引用文件 |

## 依赖的现有工具
- `python -m src.cli lint --project <id>`、`tags validate --all`、`fields validate`、`heat zombies`（宿主既有）
- `scripts/audit_wiki_baseline.py`、`scripts/audit_placeholder_classify.py`（Phase 0/F3 已建）
- `python scripts/quality_check_wiki.py <root>`（存量质检，含 broken-wikilink 统计）
