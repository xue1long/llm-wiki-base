# Plan: V7 生产路径已证实严重缺陷修复（关系生成功能推迟）

status: planned
branch: codex/book-series-target（当前 worktree）
date: 2026-09-19

## Goal

**用户可见结果**：修掉 V7 生产路径上四条**已在本机实测复现**的严重缺陷——
静默丢页、预算丢弃已算完页面、`refines` 被 lint 拒绝、全链无超时——
并让 Stage 6 从"静默降级成子串启发式"变成**显式空转且可观测**。

**明确的非目标（non-goals）**：

- **不实现关系生成功能**。`docs/superpowers/plans/2026-09-19-v7-stage6-relations-landing-fix.md`
  经两轮 plan-audit 判定**不得进入编码**（F1 召回层对 CJK 结构性失效、M5 提示词信息不足），
  关系生成需独立的召回层 + 提示词设计，另开方案。
- 不改 candidate / chunked / unified 路径；不改 `RUFLO_PIPELINE_MODE` 默认值。
- **不上调** `RUFLO_V7_MAX_CALLS` 默认值（避免掩盖 T2 的语义修正）。
- 不合并 4 份重复的 slugify 实现（只记录为 finding）。
- 不接入 `vector_neighbors`。

## 背景：证据

### 现场事实

`knowledge/novel-wiki-v2`：`wiki/log.md` 记 `kb-20260919105159-24b4a79f — generated 3 pages`
（= 1 stub + 2 concept），但 `wiki/concepts/` 只有 **1 个** V7 concept 落盘，
且 stub 有 **2 条完全相同**的 `references` 边。

### 实测复现（本机）

**D7 — page_id 塌缩（静默丢页）**

```
rel = 'raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md'
t1 = derive_topic_id(source_id=rel, candidate_ids=['item-a','item-b'])
t2 = derive_topic_id(source_id=rel, candidate_ids=['item-c','item-d','item-e'])
t1 != t2                                  # topic 身份区分得开
_slugify(t1) == _slugify(t2)              # 但 slug 相同
   = 'raw-sources-视频音频转录教程-音频教程-大纲写作技巧'    # 恰好 32 字符
_stable_page_id(rel, t1) == _stable_page_id(rel, t2)
   = 'd237368f-raw-sources-视频音频转录教程-音频教程-大纲写作技巧'
```

根因：`_page_id._MAX_SLUG_LEN = 32` + `_slugify` 取 `lowered[:32]`。
`topic_id` = `<source_id>-topic-<16hex>`，CJK 源路径替换 `/`→`-` 后前缀已吃满 32 字符，
**判别符 `-topic-<16hex>` 被整段截断**；`md5(rel)[:8]` 只区分源、不区分 topic。
P1-3 去重按 `topic.id` 计数，而两个 `topic.id` 确实不同 → 两者 `n_occurrence` 都是 0
→ 同一个 `page_id` → 第二个覆盖第一个。

**`_slugify` 调用点排查（全仓 147 处匹配）**

| 实现 | 位置 | 截断 | 受影响 |
|---|---|---|---|
| `slugify`（规范版，CJK-first） | `src/utils/slugify.py:105` | **无** | 否 |
| `_slugify`（私有重实现） | `src/pipeline/v7_extract/_page_id.py:23` | **32** | ✅ **D7 根因** |
| `_slugify` | `src/knowledge/memory/decision.py:79` | 40 | 否（独立用途） |
| `_slugify` | `scripts/aggregate_synthesis.py:302` | 无 | 否 |
| `_MAX_SLUG_LEN` | `src/kc/views/book/id_policy.py:25` | 40 | 否（独立用途） |

**爆炸半径仅一处**。副产物：v7 `_slugify` 与规范版**规则也不同**（规范版在 CJK↔ASCII
边界插连字符、空串返回 `""`；v7 版不插、空串返回 `"untitled"`），是发散的重复实现
——记为 finding，本次不合并。另 `tests/test_pipeline/test_v7_extract_page_id.py:122
test_slugify_caps_at_32_chars` **把 bug 写成了断言**，必须一并更新。

**F2 — `refines` 被 lint 拒绝，且 `wiki-quality --strict` 是假绿**

```
lint._BUILTIN_RELATIONS : 21 项，无 refines / refined_by
relations.RelationType  : 19 项，有 refines / refined_by
lint 判定式             : if rtype not in _BUILTIN_RELATIONS and not rtype.startswith("x-")
```

`tests` 实测：带 `relations=[refines]` 的页 → `LINT-ILLEGAL-RELATION`（ERROR）。
且 `wiki-quality --strict` **不调用 lint**，所以给出"0 error"的假绿。

**M1 — `_bounded_complete` 是死代码 → 全链无超时**

`grep _bounded_complete src/pipeline/v7_extract/*.py` 只命中定义处 `bridge.py:162`，
**无任何调用点**。因此 `RUFLO_V7_STAGE_TIMEOUT_SEC` 对 V7 全链形同虚设，
`bridge.py:536` 的 `except asyncio.TimeoutError → failure_stage="timeout"` **永不触发**。

**F3 — 预算 raise 丢弃已算完的页面**

`_check_budget`（`bridge.py:206-218`）在 `calls_count >= max_calls` 时 **raise**
`BridgeBudgetExceeded` → 顶层捕获 → `failure_stage="budget"` → `ingest.py` 抛
`RetryableDependencyError` → **`commit_ingest` 从未执行，已算完并付费的页面整批丢弃**。
队列重试 3 次（每次新建 adapter、`calls_count` 归零、必然同样撞墙）→ dead_letter。
`budget` 属确定性失败，被归入 `_transient_stages` 是错误的。

**P11 — `health` 没有 H3**

`src/cli_ext/health_cmd.py:14 CHECKS_AVAILABLE = {"H1","H2","H4","H5"}`。
原方案与交接 runbook 里的 "H1–H5" 是错的（runbook 已修正）。

## Tasks

TDD：先写测试（红）→ 实现（绿）→ 提交。每个 Task 一个逻辑切片。

### T1: 修 D7 —— page_id 塌缩导致静默丢页

- Files: `src/pipeline/v7_extract/_page_id.py`、
  `tests/test_pipeline/test_v7_extract_page_id.py`
- Test（先红）：
  1. 同一源、两个不同 `topic_id` → `_stable_page_id` 返回**不同**值（现为相同）。
  2. **纯 ASCII 32 字符路径**（如 `raw/sources/novel/character-growth.md`）同样不碰撞
     ——证明修复不依赖 CJK。
  3. **打乱 topic 顺序** → 每个 topic 的 page_id 不变（跨运行稳定；`-{n}` 方案会挂在这条）。
  4. 短路径对照（`raw/sources/a.md`）仍正常。
  5. 更新 `test_slugify_caps_at_32_chars`：`_slugify` 自身保留 32 上限不变，
     但**唯一性不再依赖 slug 长度**。
- Implementation（用户已定方案）：把稳定判别符放进不受截断影响的位置——

  ```python
  def _stable_page_id(relative: str, topic_id: str) -> str:
      rel = relative.replace("\\", "/")
      digest = hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
      stem_slug = _slugify(Path(rel).stem)          # 可读性，可安全截断
      topic_hash = hashlib.md5(topic_id.encode("utf-8")).hexdigest()[:8]  # 唯一性
      return f"{digest}-{stem_slug}-{topic_hash}"
  ```

  形如 `d237368f-大纲写作技巧-1bee59b7`。`topic_hash` 在截断预算之外，**唯一性有保证**；
  `stem_slug` 只承担可读性。
- **本机已实测验证（4 项全过，先于编码）**：

  ```
  1. 现场两个同名不同目录的源 → 区分
     raw/sources/视频音频转录教程/02进阶视频教程/大纲写作技巧.md -> 8471759c-大纲写作技巧-c5adeeba
     raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md       -> d237368f-大纲写作技巧-c5adeeba
  2. 同一源不同 topic（原 bug 场景）→ 区分
     d237368f-大纲写作技巧-13a839e2  /  d237368f-大纲写作技巧-0467410b
  3. 纯 ASCII 32 字符路径 → 区分
     raw/sources/retrieval-augmentation-notes.md -> 7b571644-retrieval-augmentation-notes-6f95eab1
                                                 / 7b571644-retrieval-augmentation-notes-019c3499
  4. validate_page_id 接受全部新 id
  ```

  附带确认：`_slugify(stem)` 对病态 stem（`...`/`''`/`'!!!'`/`'--'`）返回 `untitled`，
  但**不影响唯一性**——`md5(rel)[:8]` 区分源、`md5(topic_id)[:8]` 区分 topic，
  两者都在截断预算之外。这是本设计的稳健性要点。

  对照：旧 scheme 的塌缩结果 `d237368f-raw-sources-视频音频转录教程-音频教程-大纲写作技巧`
  对同一源的所有 topic 完全相同。
- **爆炸半径已排查（全仓 grep id 格式解析）**：没有任何代码解析 concept id 的格式。
  - `tests/test_pipeline/test_v7_extract_page_adapter.py:303-316` 断言的
    `{stem}-{8-char-path-hash}` / `len(id.split("-")[-1]) == 8` 针对的是
    **source stub**（`build_source_stub_page`），**T1 不改它**，该断言保持有效。
  - `card_<13hex>_<8hex>_<slug>` 是 candidate 路径的另一套 scheme，不受影响。
  - `page_adapter.py:162` 的文档注释描述的是 stub 约定，不改。
  - 因此 T1 的改动面 = `_page_id.py` + `test_v7_extract_page_id.py`。
- Acceptance: 上述 5 条用例全绿；`validate_page_id` 仍通过；旧 id 页成为孤儿
  （已决定接受，验证阶段手工清理）。
- Status: pending

### T2: 修 F3 —— Stage 6 预算 raise 不得丢弃已算完的页面

- Files: `src/pipeline/v7_extract/bridge.py`、`src/pipeline/ingest.py`、
  `tests/test_pipeline/test_v7_extract_bridge.py`
- Test（先红）：
  1. `calls_count >= max_calls` 进入 Stage 6 → **页面照常返回**、`failure_stage is None`、
     `meta["stage6_skipped"] == "budget"`、有 warning。
  2. 预算充足 → 正常执行、`meta` 无 `stage6_skipped`。
  3. `budget` 不再是可重试分类：`ingest.py` 对 `failure_stage == "budget"` 抛
     **非** `RetryableDependencyError`（确定性失败不该烧 3 次重试 × 20 calls）。
  4. `stage1`（429 等瞬时依赖）**保持** `RetryableDependencyError` 与现有重试行为不变。
- Implementation:
  - Stage 6 的预算判定改为 **look-ahead + skip**，且必须位于
    `_check_budget(llm, budget, "stage6")` **之前**（原方案的 look-ahead 放在其之后，
    在"已超上限"支上不可达——这是原方案的致命错）：
    `if llm.calls_count + needed > budget.max_calls: skip`
  - Stage 6 是文档化的 best-effort 阶段，**不得成为终止整轮的唯一原因**。
  - `ingest.py` 的失败分类：`budget` 从 `_transient_stages` 移出。
- Acceptance: v3 路径（23 calls）场景下页面照常落盘；`stage1` 重试行为不变。
- Status: pending

### T3: 修 F2 —— `refines` 被 lint 拒绝（词表分叉）

- Files: `src/wiki/features/lint.py`、`tests/test_wiki/test_lint.py`（或同目录既有文件）
- Test（先红）：
  1. 带 `relations=[Relation(target_id=…, type="refines")]` 的页 → lint **0 ERROR**。
  2. **漂移守卫**：`{t.value for t in RelationType} ⊆ _BUILTIN_RELATIONS`。
     该断言在当前代码下**失败**（差 `refines`、`refined_by`），修复后通过，
     且今后任一侧新增成员而另一侧没跟上都会失败。
- Implementation: 把 `refines` / `refined_by` 补进 `lint._BUILTIN_RELATIONS`。
- Acceptance: 守卫测试在人为移除一个成员时确实变红（人工验证一次）。
- 说明：`_BUILTIN_RELATIONS` 另有 4 个 `RelationType` 没有的领域类型
  （`belongs_to_audience`/`has_credibility`/`hosted_on_platform`/`taxonomy_of`），
  所以断言方向是 `RelationType ⊆ _BUILTIN_RELATIONS`（不是相等）。
- Status: pending

### T4: 修 M1 —— 让超时真正生效 + Stage 6 显式空转

- Files: `src/pipeline/v7_extract/bridge.py`、`tests/test_pipeline/test_v7_extract_bridge.py`
- Test（先红）：
  1. provider 永不返回 → LLM 调用在 `stage_timeout_sec` 内被放弃、
     `failure_stage == "timeout"`、**无页面**、写 `v7_failure.md`。
     （当前该分支不可达，测试会挂。）
  2. Stage 6 不再创建未 await 的协程：bridge 冒烟输出里
     `RuntimeWarning: coroutine ... was never awaited` 计数为 **0**。
  3. `meta["stage6_status"] == "disabled"`（显式），且**不再回退到 `_heuristic_relations`**。
- Implementation:
  - 把一个 `_BoundedLLM` 包装器套在 `ProviderAdapter` 外层（bridge 入口一处改动），
    使 Stage 1/3/4/5 的**每一次** `complete()` 都经过
    `asyncio.wait_for(..., budget.stage_timeout_sec)` 与调用计数。
    需代理 `provider_name` / `calls_count`（`bridge.py:459` 等处依赖）。
  - Stage 6 改为显式空转：**删除** `extract_relations` 调用（它只创建协程、从不执行、
    再回退到子串启发式、结果又被丢弃），写 `meta["stage6_status"]="disabled"` +
    一条说明性 warning，并留下指向关系生成独立方案的注释。
- Acceptance: 既有 bridge 用例全绿；`meta["stage6_status"]` 可观测。
- 风险：`_BoundedLLM` 包装可能影响既有脚本 provider 测试的调用计数断言，需同步核对。
- Status: pending

### T5: 文档事实修正

- Files: `docs/ops/handoff-v7-stage1-remote.md`、本文档、
  `.superpowers/sdd/progress.md`
- 内容：
  1. `H1–H5` → `H1/H2/H4/H5`（`health` 无 H3）——runbook 已改。
  2. 新增运维事实：**`wiki-quality --strict` 不调用 lint**，涉及关系词表的验收必须
     显式跑 `python -m src.cli lint`。
  3. 新增 D7 的旧 id 孤儿页说明与清理动作。
  4. pytest 命令写法修正为 `PYTHONPATH=. python -m pytest --import-mode=importlib …`
     （`PYTHONPATH=.` 写在 pytest 之后会被当作测试路径参数）。
  5. 把原 `2026-09-19-v7-stage6-relations-landing-fix.md` 标为 **deferred / 未通过审查**，
     并链接本文档。
- Status: pending

## 预埋审查标准（9 维度）

| 维度 | 落点 |
|---|---|
| 目标对齐 | 只修 4 条已实测复现的严重缺陷 + 文档事实；关系生成明确推迟 |
| 前提假设 | ① `_stable_page_id` 的调用方都能接受 id 格式变化；② `_BoundedLLM` 包装不影响既有属性访问；③ `budget` 移出 transient 不破坏其它路径；④ `RelationType ⊆ _BUILTIN_RELATIONS` 是本仓应有不变量 |
| 边界场景 | 0 topic / 1 topic / N topic；topic 顺序变化；纯 ASCII 长路径；`calls_count` 恰好等于上限；provider 挂起；provider 立即抛 `CircuitBreakerOpen`；`stage1` 429 重试 |
| 依赖项 | `_page_id`、`topic_id`、`lint`、`bridge`、`ingest`、`utils/slugify`；缺失兜底 = 每个 Task 的 except/warning + meta |
| 风险与副作用 | page id 变化产生孤儿页（已接受）；`_BoundedLLM` 影响调用计数；T2 改变 v3 预算中止行为；T3 放宽 lint 可能让存量非法类型变得合法 |
| 可执行性 | 每个 Task 有 Files/Test/Acceptance |
| 验收标准 | 见下 |
| 盲区清单 | 真实 provider 仍 429；`_BoundedLLM` 与 provider 内部重试的交互未验证 |
| 回滚预案 | 逐个 revert T1–T5；**代码 revert 不回滚磁盘副作用**（孤儿页、已写关系），回滚后需重跑 health + lint + wiki-quality |

## 验收标准（可量化）

1. `tests/test_pipeline/test_v7_extract_*` + `tests/test_wiki/` 相关用例全绿。
2. **D7**：同源不同 topic → 不同 page_id；打乱 topic 顺序 → page_id 不变；
   纯 ASCII 32 字符路径不碰撞。（不再出现"generated N pages 但落盘 <N"。）
3. **F3**：`calls_count >= max_calls` 时页面**照常落盘**；`budget` 不再重试放大。
4. **F2**：带 `refines` 的页 lint 0 ERROR；漂移守卫测试存在且在人为破坏时变红。
5. **M1**：provider 挂起时在 `stage_timeout_sec` 内放弃并标记 `timeout`。
6. **Stage 6**：`RuntimeWarning ... never awaited` 计数为 0；`meta["stage6_status"]=="disabled"`。
7. **回归**：candidate 路径不受影响；`stage1` 的 retryable 分类与重试行为不变。
8. 文档修正全部落地，原关系方案标记为 deferred。

## Audit

- Round 1: **不通过**（4 条致命 F-1…F-4）
- Round 2: **不通过**（P1…P15；阻塞项为 P1/P2/P3/P5+P6/P9/P10/P7+P8/P12）
- Human review: pending
- **结论：原方案的 T2/T4 不得进入编码。已按用户决定把方案拆为 S1a（可实施）/ S1b（需重新设计）。**

### 用户决定（2026-09-19）

| 决定 | 内容 |
|---|---|
| 范围 | **开工 S1a**：T1(D7) + T3(词表单真源) + F-2 不变量 + T5(文档)。T2/T4 移出，另开 S1b。 |
| batch_gate | **拆开**：让 `batch_gate` 读写入侧真源（`generator.RELATION_TYPES`），而不是共用 lint 的私有 frozenset。 |

### 本机独立复核的审计断言

未复核的不作为既定事实。

| 断言 | 复核 |
|---|---|
| R1-F-1 超时异常被阶段层吞掉 → `failure_stage="timeout"` 不可达 | ✅ 实测：`doc_classifier.py:233`、`completeness_checker.py:214`、`topic_clusterer.py:253`、`bridge.py:444` 均为宽 `except Exception` |
| R1-F-2 Stage 5 全 topic 失败 → 静默成功（**既有活 bug**） | ✅ 实测：`bridge.py:444` 吞异常 → `concept_page=None` → `failed_topics` 非空但 `concept_pages=[]` → `empty_extraction` 不置位、`failure_stage` 仍 None |
| R1-M-1 新 id 打红既有 shape 断言 | ✅ 实测：`^[0-9a-f]{8}-[a-z0-9-]+$` 对 `16a635b3-source_a-bf2850b7` 与 CJK id 均 False |
| R1-M-2 路径拼写未归一 → 同一文件多个 id | ✅ 实测：5 种拼写 → 4 个 id（`./` 前缀 / 绝对路径 / 大写各变一个） |
| R1-M-7 存在第三份词表，守卫方向反了 | ✅ 实测：`RELATION_TYPES(23) - _BUILTIN_RELATIONS(21) = {refines, refined_by}`；`LBR - RT = {}`；`RT == RelationType ∪ {4 命名空间}` |
| R2-E9 `delete_by_source` 列语义错位 → 恒删 0 行 | ✅ 实测：`store.py:235` docstring 称按 raw 路径匹配；写入侧 `vector_cmd.py:91` 存 `normalize_source_path(page.id)` = 页面 id |
| R2-P3 T1 会失效 `expected_ids.json` 与 `test_extract_pilot` | ✅ 实测：该 fixture 的 `_comment` 明确写旧格式 `md5(relative)[:8] + slug(topic_title)[:32]` |
| R2-P9 `max_usd` 是死字段 | 采信（审计 grep 全仓仅定义 + 读 env，无比较点） |
| R2-P10 `stage_timeout_sec` == `provider.timeout_seconds` == 120 → 外层恒先触发 | 采信（数值与默认值一致，机制成立） |
| R2-P7 `budget` 进 `task_queue` 熔断 → 连续 10 个即停摆 65s | 采信 |
| R2-P5 孤儿页对 lint/H2 不可见且被 server 启动 reconcile 主动索引 | 采信 |

### S1a 与 S1b 的划分

**S1a（可实施，本方案执行）**

| Task | 内容 | 相对原稿的变化 |
|---|---|---|
| T1 | 修 D7 丢页 | **Files 补齐**：`test_v7_extract_page_id.py`（shape 正则 + 32 上限用例）、`tests/fixtures/v7_control_plane/expected_ids.json`、`tests/test_scripts/test_extract_pilot.py`、`docs/guides/v7-ingestion-pipeline.md`、`docs/adr/0011-*.md`。**新增不变量**：`_MAX_SLUG_LEN=32` 保留且显式 `[:32]`（P4，防 id 过长击穿文件系统）；路径先归一（M-2）；运行内 page_id 唯一性断言（P15）；**措辞**从"唯一性有保证"改为"32 位哈希 + 运行内断言"（M-3）。**孤儿清理不作验收项**（依赖 P6 的向量工具，见 gap） |
| T3 | 词表单真源 | 改为让 `batch_gate` 读 `generator.RELATION_TYPES`（用户决定）；守卫补 `INVERSE_RELATIONS` 方向（P12）；`RelationType` 断言方向改为 `RELATION_TYPES ⊆ _BUILTIN_RELATIONS`（M-7）；同步修 lint 里"17 built-in"的误导文案。**`.kc/relation_registry.yaml` 缺 `refines`** 记为 gap（P12-c） |
| T6（新） | F-2 不变量：`concept_pages` 为空且 `failed_topics` 非空 → 必须置 `failure_stage`，不得算成功 | 新增（R1-F-2 的既有活 bug） |
| T5 | 文档修正 | 补 runbook 坑 1 分类表、坑 7 的事实错误（"Stage 6 每次仍花 1 次调用"是错的，实际 0 次） |

**S1b（另开方案，需重新设计）**：超时语义与异常传播（P1/P10）、预算语义与熔断（P2/P7/P9）、`stage6_status` 可观测消费者（P8）、Stage 6 显式空转（T4 原稿）。

**记录在案但不属本次范围的 gap（不得静默丢失）**

- **G1**：`delete_by_source` 列语义错位 → 孤儿向量永久不可删（R2-P6）。需要 `delete_vectors_for_page_ids` + lineage 反查 + 集成用例。
- **G2**：孤儿页盘点工具（`wiki gc --dry-run` 三类报告）缺失（R2-P5）。
- **G3**：`max_usd` 是死字段（R2-P9）；`stage_timeout_sec`/`provider.timeout_seconds` 数值关系未定（R2-P10）。
- **G4**：`enqueue_failure` 读-改-写无锁 + 固定 tmp 名 → 并发丢失败记录（R2-P11）。
- **G5**：`.wiki-templates` 解析失败使 lint 与 batch_gate 双双 fail-open 静默降级（R2-P14）。
- **G6**：`.kc/relation_registry.yaml` 无 `refines` → 注入 registry 时 100% block（R2-P12-c）。
- **G7**：`v7_meta` / `v7_calls_count` 全仓零消费者（R1-F-4 / R2-P8）。
- **G8**：`slugify(page_id) != page_id`（含 `_` 时）→ 走 `Relation.from_dict` 的路径静默对不上（R2-P13）。属既有问题，T1 顺带补断言但不在本次修 `slugify`。
- **G9（T6 实施中发现）**：**v3（`fill_slots_v2`）路径没有 happy-path 端到端测试**。
  `tests/test_pipeline/test_v7_extract_bridge.py::test_bridge_runs_v3_path_short_source`
  的脚本桩无法让 `fill_slots_v2` 达到 `FILLED`——其 claims 全被降级为
  `INSUFFICIENT_EVIDENCE`，`page_synthesizer` 因此返回 `FillStatus.INSUFFICIENT`
  （`page_synthesizer.py:428-431`），不产出 concept 页。
  **该测试此前断言「v3 分支被调用」而忽略了这个结果，等于靠 F-2 的静默成功才绿**——
  T6 落地后它如实暴露为 `stage5_all_failed`，已改为断言真实语义。
  要让 v3 happy path 有覆盖，需要一个 claim `span_ids` 能匹配 Stage 2 真实 span 注册表的
  fixture（`fill_slots_v2` 走 inline `spans_per_slot`，格式 `span-{item_id}-{slot[:4]}-i{j}`）。
- **G11（T3 实施中发现）**：`tests/test_wiki/test_lint_workflow_state.py` **既有的收集错误**——
  它 `from src.wiki.features.lint import VALID_PROCESSING_DEPTHS`，但该符号在 `lint.py`
  的 HEAD 版本里也不存在（已用 `git stash` 验证：暂存 T3 改动后同样
  `ImportError`）。跑 `tests/test_wiki` 会因此 `Interrupted: 1 error during collection`，
  需 `--ignore` 才能跑完（本次回归 575 passed）。属既有破损测试，未在本方案修。
- **G12**：「17 built-in relation types」这一过时计数散落在 **53 处**，包括
  **LLM 提示词正文**（`generator.py:478/655/1069`、`docs/reference/ingest-prompts.md`）与
  `kc` 契约层、ADR、架构文档。T3 只修了实际判定逻辑与紧邻的两处代码文案；
  提示词与其余文档未动——改提示词是行为变更，需单独评估（且有
  `tests/test_pipeline/test_generator.py:552` 断言该文案）。
- **G10**：跑 `tests/test_pipeline tests/test_scripts` 全量会**改写仓库源文件**
  `src/pipeline/wiki_rules_prompt.py`（`--ignore-cr-at-eol` 下仍 7+/23-）与
  `docs/guides/wiki-spec.md`（纯行尾差异）。疑为测试内触发的 wiki-spec 同步。
  已还原、未提交。这会让"跑完测试后 `git status`"变得不可信，建议查清并让测试不再写源文件。
- Open risks:
  - **R1**：T1 改变 page id 格式 → 磁盘上既有 V7 页成为孤儿（已决定接受，验证时清理）。
    需确认孤儿页不会被向量库/索引持续命中而污染检索。
  - **R2**：`_BoundedLLM` 与 provider 内部 `RetryLLMProvider`（自带 2/10/30s 退避）
    的交互——`wait_for` 包在**外层**会把内部重试一起计入超时，可能使原本会成功的重试被掐断。
    需实测确认 `stage_timeout_sec` 的语义应是"单次调用"还是"含重试的整次"。
  - **R3**：T2 把 `budget` 移出 transient 改变既有分类；须确认没有别的路径依赖
    `budget` 可重试。
  - **R4**：T3 放宽 lint 词表后，存量页面中新变得合法的类型
    （`refines`/`refined_by`）是否会被其它门禁（`batch_gate` 共用同一常量）接受——
    共用常量意味着两处同时放宽，需确认是期望行为。
  - **R5**：真实 provider 仍 429 → T4 的 429 相关路径只能靠合成 provider 验证。
- Rollback: 逐个 revert T1–T5 的提交；`page_adapter` 未改动（关系生成已推迟），
  回滚面比原方案小。回滚后必跑：`python -m src.cli health`、
  `python -m src.cli lint`、`python -m src.cli wiki-quality --strict`。

## Completion evidence

- Final commit:
- Tests:
- Static checks: 无 linter/formatter/type checker（仓库未配置）
- Documentation updated:
- Progress ledger updated: no
