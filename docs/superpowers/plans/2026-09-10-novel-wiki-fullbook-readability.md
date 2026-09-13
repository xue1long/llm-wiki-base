# Plan: novel-wiki 全量 Book 可读性整改（4 项一揽子）

status: planned
branch: codex/book-series-target
parent plan: docs/superpowers/plans/2026-09-09-novel-wiki-full-book.md
target release: f728939909c44bdf9d7efb6e26760c9d（已发布，但可重命名为新 release_id）

> **第三版变更说明（2026-09-10）**
>
> 第二版方案的核心假设——"`_book_outline_metadata` 返回的 volume_id / volume_title 已经能正确填到 `chapter` 字段"——在收益评估阶段被实证推翻。
>
> 实测（模拟 `book_wiki_manifest` 返回结构）：179 章中**有 0 章**被填上 `volume_id` / `volume_title`，**全部走文件前缀 fallback**。根因不是 `_book_outline_metadata` 没读对（它读对了，179 条映射完整返回），而是：
>
> - **写盘阶段**：`src/kc/views/book/wiki/compiler.py:708` 写出的文件名是 `{_safe(volume_id)}__{_safe(chapter_id)}.md`，其中 `_safe`（line 475-477）会把 `:` 替换为 `_`，所以 `chapter_id="concept-写作技法:5"` 写盘后变成 `concept-写作技法__concept-写作技法_5.md`。
> - **读回阶段**：`src/services/files.py:299-300` 拿到 stem `concept-写作技法__concept-写作技法_5`，按 `split("__", 1)[-1]` 拿到 `concept-写作技法_5`（用 `_`），但 outline.json 里的 `chapter_id` 是 `concept-写作技法:5`（用 `:`）。
> - **结果**：lookup key 不一致，179 章全部 miss；`chapter.volume_id` 和 `chapter.volume_title` 全为 None；WebUI 的 `volumeFor()` 走 `book.js:299-302` 的前缀 fallback，最终只显示 4 个粗桶。
>
> 因此本版新增**Task 0：修复 `book_wiki_manifest` key 推导 bug**作为前置任务，并把 Task 1 重新升格为"修复 + 回归"而非 review-only。
>
> 收益口径同时修订：**Task 0 是收益 A（目录分桶）能否兑现的前置条件**。

## Goal

把当前已发布的全量 Book (`f728939909c44bdf9d7efb6e26760c9d`)从"全量覆盖但人不可读"提升到"可作为教程读本使用"：

1. WebUI 目录按主题分桶，能看到"写作技法 / 人物塑造 / 题材体系 / 平台规则 / 心态与职业 / 读者与市场 / synthesis"等真正命名的卷，而不是 4 个粗糙前缀桶
2. 每章有"第 N 章 · 标题"风格的可读章名，而不是 `concept-写作技法__concept-写作技法_5`
3. 书首有总序 + 主题导读，让读者拿到 5-10 分钟路线图
4. 把 68 个写作技法相关小条重组成 6-8 个有名字的大章（每章覆盖一个写作子方向）

完成后读者能在 WebUI 看到像样的目录，按主题点开章节，每章有清晰标题，正文开头有导读。

## Explicit non-goals

- 不重新跑全部 179 章 LLM 生成（`content_status=complete` 已通过，仅重组 + 改名）
- 不调用外部 LLM 做整章重写（保持原文，仅改编排、起名、加导读）
- 不修改 Wiki 主数据（`wiki/concepts/`、`wiki/entities/` 等只读）
- 不修改 `book.rules.md`（"按已有 Wiki 内容为事实边界"仍是硬规则）
- 不动 `policy.json`、`registry.json`、`llm-providers.json` 等外部配置
- 不批量更新 `glossary_index.json`（沿用既有）
- 不重写 glossary.md / sources-index.md（沿用既有）
- **不写一份 preface.md 走和普通 chapter 相同的存储路径**（必须在 manifest.files 注册豁免并加类型标记，避免被 `book_wiki_manifest` 当成可点章节）
- **不动现有 release 的 .md 文件名**（写盘用 `__`，读回已用 `__` 拆，是有意为之；只在读回侧做 key 归一化，不改 `_safe` 也不改 outline.json 内的命名）

## Design

### 任务依赖图（第三版：Task 0 前置 + Task 1 升格为修复 + 原 2/3/4）

```
Task 0 (前置 bugfix：book_wiki_manifest key 推导)
   ↓ 必须先修，否则收益 A 落空
Task 1 (回归测试 + 复核 outline_metadata 行为)
   ↓ 给出回归基线
Task 2 (WebUI Playwright smoke + 复核 volumeFor 行为)
   ↓ 给出视觉基线
Task 3 (LLM 一次性给每章起人类可读标题 + 总序导读)
   ↓ 用户能读到"第 N 章 · 标题"，首章 preface.md 含 6-8 段导读
Task 4 (重组写作技法 68 块 → 8 大章)
   └─ 独立代码路径，但生成新 release 必须走 apply-from seam
```

> Task 3、4 仍串行（与第二版相同）：两者都改 `compiler.py` 的 chapter/manifest 写入路径，并共享 `acceptance.py` 的 ledger 计算。

### Task 0 修复方向（关键）

两种合理实现，二选一：

**方案 0-A（推荐）：在 `_book_outline_metadata` 内同时索引两种 key**

```python
# src/services/files.py:183-210
chapters[str(chapter["chapter_id"])] = meta            # 原生 "concept-写作技法:5"
chapters[str(chapter["chapter_id"]).replace(":", "_")] = meta  # 兼容 "_safe" 后的 "concept-写作技法_5"
```

优点：最小改动；`book_wiki_manifest` 不动；向后兼容旧 release（因为它的 outline_id 仍是 `concept-写作技法_5`，会命中第二条记录）。

**方案 0-B：在 `book_wiki_manifest` 做 key 归一化**

```python
# src/services/files.py:300 附近
outline_id_raw = chapter_id.split("__", 1)[-1]
outline_id = outline_id_raw.rsplit(":", 1)[0] + ":" + outline_id_raw.rsplit(":", 1)[1]  # 不可逆，舍
```

缺点：`split` 之后无法可靠还原 `:` 在 ID 中的位置；不推荐。

**Task 0 决定采用方案 0-A**。

### 卷结构设计（Task 4 重组方案，修订）

把当前与"写作技法"相关的 68 章（67 个 `concept-写作技法__N` + 1 个 `synthesis-写作技法`；另有 1 个 `concept-写作技法--…` 不计入）按子主题聚合为 8 个有名字的大章。**重组只动这 68 章对应的 page_id 集合；其他 111 个章节（题材体系、读者与市场、fallback、entity 等）保持原 chapter_id 不变**：

| 新章名 | 现有章节数 | 预计合并 N | 内容范围 |
|---|---|---|---|
| 人物塑造与设定 | 68 中约 12 块 | 12→1 | 主角人设、配角、性格、人物关系、反派、女主 |
| 情节与节奏 | 约 12 块 | 12→1 | 主线/支线、冲突、转折、伏笔、节奏控制 |
| 开篇与签约 | 约 8 块 | 8→1 | 书名/简介/开头三章/上架/A 签/VIP |
| 套路与爽点 | 约 12 块 | 12→1 | YY/扮猪吃虎/装B/金手指/打脸/反派碾压 |
| 描写与文笔 | 约 8 块 | 8→1 | 五感/对话/动作/环境/意象/语言 |
| 题材与世界观 | 约 10 块 | 10→1 | 玄幻/仙侠/都市/历史/科幻等 + 世界观设定 |
| 心态与职业 | 约 5 块 | 5→1 | 心态/职业路径/写手坚持/完本 |
| 平台与读者 | 约 5 块 | 5→1 | 平台规则/读者分析/书评/签约 |

重组后 68 块 → 8 大章，其余 111 个 chapter 保持原状。snapshot 总 page_count = 1255 不变。

### 标题生成（Task 3）方案

- 对每个 chapter 输出 `chapter_id, friendly_title` 两列
- **不**改 body 文本，仅在第一行 `## 本章导读` 后插入 `## 章名：<title>`
- 标题生成后必须经过 **后处理裁剪**：剔除 markdown 符号 / 截断到 ≤14 字 / 重名追加 N 后缀
- 对合成页（synthesis-*）和人设页（主角/配角/言情/家斗）友好处理
- 对 fallback 页：用"聚合章：<N> 个写作技巧"等描述性标题

LLM 调用预算（按 `policy.budget_cap=450` **会超**，需先申请提升到 800 或分批）：

- 一次性 prompt：约 179 章标题 + 1 篇总序 = 180 个生成单元
- 单章 prompt 约 1500 tokens 输出，估算 180 × 2 次（含 retries=1）= 360 次
- 加上 Task 4 的 16 次 LLM（8 章 × 2 次 + 1 次总览），**总计 ≈ 377 次**；
- 真实运行含结构性失败重试 + `_failed_body` 兜底路径，实际可能 **400–600 次**。

**Action item（开工前必做）**：`policy.budget_cap` 提升到 **800**，否则中途会撞 `EXIT_BUDGET_EXHAUSTED=6`。

### 总序导读（Task 3）方案

新建 `preface.md`（**非 chapter**，必须在 `manifest.files` 注册并加 `kind=preface` 元数据）：

- 内容：本路线图 6-8 段，每段对应一个新卷
- 体量：约 2500-4000 字
- 风格：教程导读风格，按 `book.rules.md` "概念→原理→方法→示例"结构
- 来源：直接读取 outline.json + 已有 synthesis 页内容（不调 LLM 或只调一次）
- **重要**：必须在 `src/services/files.py:293` 的豁免集中加入 `preface.md`，避免被 `book_wiki_manifest` 当成普通 chapter 出现在目录里

## Tasks

### Task 0：前置 bugfix — 修复 `book_wiki_manifest` key 推导

**性质**：bugfix + 回归测试。**必须在 Task 1 之前完成**。

**根因**：

- `_safe()`（`compiler.py:475-477`）会把 `:` 转 `_`，所以 outline 里的 `chapter_id="concept-写作技法:5"` 写盘后变成 `concept-写作技法__concept-写作技法_5.md`。
- `book_wiki_manifest`（`files.py:298-300`）读回时 `chapter_id.split("__", 1)[-1]` 拿到 `concept-写作技法_5`（下划线），但 `_book_outline_metadata` 的 key 是 `concept-写作技法:5`（冒号）。
- 179 章 lookup 全部 miss。

**Files**：

- `src/services/files.py`（`_book_outline_metadata`，line 183-210）
- `tests/test_kc/test_book_wiki_outline_volume.py`（**新文件**）

**Test first**：

- 用现有 release `f728939909c44bdf9d7efb6e26760c9d` 的 fixture 跑 `book_wiki_manifest`
- 断言：**全部 179 章**都带 `volume_id` 和 `volume_title`（不再为 None）
- 断言：`book.volumes[i].chapter_count > 0` 对所有 53 个真名卷成立
- 断言：`_book_outline_metadata` 返回的 key 同时包含 `concept-写作技法:5` 和 `concept-写作技法_5` 两种形式（如果采用方案 0-A）

**Implementation**：

- `src/services/files.py:204-209` 区域加入：
  ```python
  cid_native = str(chapter["chapter_id"])
  cid_safe = cid_native.replace(":", "_")
  meta = {"title": ..., "volume_id": volume_id, "volume_title": volume_title}
  chapters[cid_native] = meta
  if cid_safe != cid_native:
      chapters[cid_safe] = meta
  ```
- 不动 `_safe()`、不动 `_book_outline_metadata` 的返回签名、不动 outline.json 命名。
- 复用 `_book_outline_metadata` 的现有调用方（`book_wiki_manifest`、`book_wiki_series_manifest` 等）无需改一行。

**Acceptance**：

- 新增 ≥8 个测试，覆盖：原生 `:` key、归一化 `_` key、重复 key 不覆盖原值、空 chapters 跳过、文件名前缀与 outline key 跨多种 page_type 都通
- `book_wiki_manifest` 返回的 `chapters[].volume_id` 填充率从 0/179 提升到 179/179
- `book.volumes[].chapter_count` 全部 > 0
- 现有 `test_book_wiki_compiler.py` 21 个、`test_book_wiki_outline_llm.py` 4 个不退化
- **手工回归**：浏览器打开 Book 视图，左目录显示 ≥9 个真名卷（写作技法 / 题材体系 / 平台规则 / 心态与职业 / 读者与市场 / 4 个 fallback 主题 / synthesis 等），每卷章数 > 0

### Task 1：复核 + 回归测试 `_book_outline_metadata`

**性质**：review-only / 写测试，不改产品代码（前提是 Task 0 已完成）。

**复核结论（已完成）**：

- `src/services/files.py:183-210` 已正确解析顶层 `[OutlineProposal]` 数组与 `volumes[].chapters[]`；
- `src/services/files.py:290, 307-308, 341` 已用映射填充 `chapter.volume_id` / `chapter.volume_title` / `volumes[].chapter_count`；
- 当前 release `f728939909c44bdf9d7efb6e26760c9d` 的 `outline.json` 顶层为 list，长度 1，内含 61 个卷、179 个 chapter。

**Files**：

- `tests/test_kc/test_book_wiki_outline_volume.py`（与 Task 0 共用，补充非 fix 场景的用例）

**Test first**：

- 用 `tests/fixtures/novel-wiki-book-sample/` 构造 6 卷 × 多章的小型 book
- 验证 `_book_outline_metadata` 返回每卷 `chapter_count > 0`
- 验证顶层是 list 时不丢卷
- 验证顶层是 dict 时仍兼容
- 验证同一 release 的多次调用返回结果一致（无副作用）

**Implementation**：仅写测试。**不改** `_book_outline_metadata` 主体逻辑（Task 0 的 fix 已在前面打过补丁）。

**Acceptance**：

- 新增 ≥4 个非 fix 场景用例
- `PYTHONPATH=. pytest tests/test_kc/test_book_wiki_outline_volume.py tests/test_kc/test_book_wiki_compiler.py tests/test_kc/test_book_wiki_outline_llm.py -v` 全绿
- 现有 `test_book_wiki_compiler.py` 21 个、`test_book_wiki_outline_llm.py` 4 个不退化

### Task 2：复核 + WebUI smoke test `volumeFor()` / `volumeLabel()`

**性质**：review-only / 写 smoke test，不改产品代码。

**复核结论（已完成）**：

- `web/js/views/book.js:298` 第一行就 `if (chapter.volume_id) return chapter.volume_id`；
- `web/js/views/book.js:305` 第一行就 `if (chapter?.volume_title) return chapter.volume_title`；
- 4 个粗桶仅在 outline metadata 为空时（fallback 路径）出现。
- **Task 0 修复后，`volume_id` / `volume_title` 不再为 None**，4 桶会被全部替换为真名卷。

**Files**：

- `tests/test_webui/test_book_volume_grouping.py`（**新文件**，Playwright smoke）
- `docs/webui-buttons.md` 补一段"Book 视图左目录分组规则"

**Test first**：

- Playwright 打开 `http://127.0.0.1:19828` → 选 novel-wiki → Book 视图
- 断言：左目录中 `book-volume-heading` 数量 ≥ 9（写作技法 / 题材体系 / 平台规则 / 心态与职业 / 读者与市场 / 4 个 fallback 主题 / synthesis 等）
- 断言：每个 heading 内 `.book-chapter` 数量 > 0
- 断言：`volumeLabel(items[0])` 不等于 `Sources · 来源` / `Concepts · 概念` 等 4 个粗桶（除非 outline metadata 缺失）

**Implementation**：仅写 smoke test。**不改** `web/js/views/book.js`。

**Acceptance**：

- 新增 Playwright smoke 至少 3 个用例
- 浏览器手工回归：4 桶消失/仅 fallback 出现（**前提：Task 0 已完成**）
- 不破坏 `bookSelect` / `versionSelect` / `pathSelect`

### Task 3：LLM 一次性起章名 + 总序导读

**Files**：

- `src/kc/views/book/wiki/polish_llm.py`（新增 `generate_chapter_titles()` 函数，复用现有 `_fallback` 路径）
- `scripts/title_book_chapters.py`（新脚本：编排一次性 LLM 调用）
- `src/cli_ext/book_cmd.py`（新增 `cmd_book_retitle` handler）
- `src/cli.py`（注册 `book retitle` 子解析器）
- `src/services/files.py`（在 `book_wiki_manifest` 的豁免集加入 `preface.md`，并在 chapter 列表里过滤 `kind == "preface"`）
- `src/kc/views/book/wiki/compiler.py`（在 `compile_book` 末尾接受 `preface_path` / `preface_text` 参数，写 manifest 时加 `kind=preface` 元数据）
- `knowledge/novel-wiki/.llm-wiki/policy.json`（**先**把 `budget_cap` 从 450 提到 800）

**Test first**：

- `tests/test_kc/test_book_chapter_titles.py`（新文件）
  - `generate_chapter_titles` 输入 chapter_id 列表 → 输出 title 列表，长度一致
  - 后处理裁剪：标题 ≤14 字，无 markdown 符号（`#*_>\[\]`）
  - 重名追加 N 后缀（`-2`/`-3`）
  - fallback：LLM 返回非 JSON 时使用首词
- `tests/test_kc/test_book_preface.py`（新文件）
  - `book_wiki_manifest` 排除 `preface.md`（不在 chapters 数组里）
  - preface 元数据暴露为单独字段 `preface: { path, kind, word_count }`
  - preface 字数 2500-4000 之间

**Implementation**：

- `generate_chapter_titles(chapters_metadata, provider) -> dict[chapter_id, title]`：
  - 输入：每个 chapter 的 `chapter_id`, `title_segments`, `page_ids`, `source_count`
  - LLM prompt 要求："为以下每个 chapter_id 生成 6-14 字的中文可读标题，不与已有标题重复，标题要概括这一章涵盖的写作主题"
  - 输出：JSON `{"concept-写作技法:5": "人物与节奏"}` 等
  - 后处理：截断到 ≤14 字 → 重名加后缀 → 兜底用 `first_page_title` 或 `f"聚合章{N}"`
- 一次性脚本 `scripts/title_book_chapters.py`：
  - 读取 `book-wiki/.releases/<active>/outline.json` + 所有 chapter 文件的标题段
  - 调用 provider 完成 1 个 prompt（一次性，避免 179 次开销）
  - 写 `chapter-titles.json` 到 release 目录的 `editorial/chapter-titles.json`
- `src/cli.py` 在 `book` 子解析器下新增 `retitle`：
  - `python -m src.cli book retitle --project <id> [--release <rel>] [--apply]`
  - 不带 `--apply` 时 dry-run，只生成 `chapter-titles.json` + `preface.md` 草稿
  - 带 `--apply` 时调 `compile_book` 重写 release，**走 apply-from seam**（见 Task 4）
- `compile_book` 新参数：
  - `preface_path: Path | None = None`：若提供，将文件复制到 release 目录并在 manifest 加 `{"preface.md": {"kind": "preface", "sha256": ...}}` 元数据
  - `chapter_titles_path: Path | None = None`：若提供，发布时在每章首行 `## 本章导读` 后插入 `## 章名：<title>`
- `book_wiki_manifest` 改造：
  - `preface.md` 加入豁免集（与 index/glossary/sources-index 同列）
  - 返回结构新增 `"preface": {"path": "preface.md", "kind": "preface", "word_count": N}` 字段
  - 章节列表过滤 `kind == "preface"`

**Acceptance**：

- 全 179 章每章有唯一标题（中文 ≤14 字）
- 写作技法 68 块每块有标题（重组前临时状态）
- `preface.md` 存在，2500-4000 字，包含 6-8 段主题导读
- `book_wiki_manifest` 返回的 chapters 列表不含 preface，单独字段 `preface` 可用
- 不破坏现有 `test_book_chapter_body.py` 28 个测试
- `budget_cap` 已提前到 800，且实际 LLM 调用 < 700

### Task 4：重组写作技法 68 块 → 8 大章

**Files**：

- `src/kc/views/book/wiki/partition.py`（新增 `partition_writing_technique_merged()` 函数，**不破坏**现有 `partition_pages` 的覆盖不变式）
- `scripts/regroup_writing_technique_chapters.py`（新脚本：编排"读 release → 重组 → 写新 release"）
- `src/kc/views/book/wiki/compiler.py`（在 `compile_book` 接受 `regroup_manifest` 参数，仅在提供时使用新 partition）
- `src/kc/views/book/wiki/acceptance.py`（在 acceptance report 中保留旧 release 的 `chapter_count` / `page_count` / `coverage_ratio` 字段做对比）

**Test first**：

- `tests/test_kc/test_book_writing_technique_regroup.py`（新文件）
  - 输入现有 68 个写作技法相关 chapter 的 page_id 列表
  - 输出 8 个新 chapter_id（每个聚合多个 page_id）
  - **断言**：所有新 chapter 的 page_id 集合 ∪ 其他 111 个原 chapter 的 page_id 集合 = 原 1255 个 page_id，**不增不减**
  - 断言：每个新 chapter 至少有 5 个 page_id（避免单页孤章）
  - 断言：8 个新 chapter 的 page_id 之间互不相交
- `tests/test_kc/test_book_apply_from_seam.py`（新文件）
  - `apply-from` 流程：新 release manifest sha + CURRENT.json 切换后 `resolve_active_version` 返回新 release
  - 旧 release 仍可通过版本选择器读到（`book_wiki_versions` 列出）

**Implementation**：

- `partition_writing_technique_merged(snapshot, *, regroup_rules)`：
  - 接受 full page_ids 集合与关键词正则规则，**仅**把 68 个写作技法 page_id 重新分配到 8 个新 chapter，其余 111 个 chapter 的 page_id 透传
  - 返回 `dict[chapter_id, tuple[page_id, ...]]`，仍满足 `sorted(i for ids in result.values() for i in ids) == sorted(snapshot.pages)` 不变式
  - 基于关键词正则匹配分配：
    - 人物塑造：`人物|主角|配角|性格|女主|反派|身世`
    - 情节与节奏：`情节|主线|支线|冲突|转折|伏笔|节奏`
    - 开篇与签约：`开篇|书名|简介|上架|A签|VIP|签约`
    - 套路与爽点：`套路|YY|扮猪|装B|金手指|打脸|反派|碾压`
    - 描写与文笔：`描写|五感|对话|动作|环境|意象|文笔`
    - 题材与世界观：`题材|世界观|玄幻|仙侠|都市|历史|科幻`
    - 心态与职业：`心态|职业|坚持|完本|全职`
    - 平台与读者：`平台|读者|书评|签约`
  - 未匹配的 page_id 落入"其他"卷，**保留**原 chapter（不丢页）
- `scripts/regroup_writing_technique_chapters.py`：
  - 读取当前 active release 的 manifest + outline.json
  - 抽取 68 个写作技法相关 chapter 的所有 page_id
  - 按 `partition_writing_technique_merged` 重新分配
  - **走 apply-from seam**（不复用旧 release_id）：新生成 release_id，文件名按 `concept-写作技法-人物塑造__0.md` 命名
  - 每个新章节 LLM 生成正文（复用 `polish_llm.generate_chapter_body`，把原 68 块正文做 summarize-like 拼接作为 draft.blocks）
  - 写新文件 + 更新 manifest `files` + **新 manifest 的 sha 走 CURRENT.json 原子切换**（不是简单切换指针，见 Task 4 加固 ②）
  - acceptance.report 同时记录旧 release 的 chapter_count / coverage_ratio 字段（"扁平化基线"），便于事后对比
- LLM 调用预算：8 章 × 2 次 + 1 次总览 = **17 次**；考虑 retries 预留 ≤ 50 次

**Acceptance**：

- 8 个新章节取代 68 个写作技法相关章节
- 每个新章节 `content_status=complete`、`coverage_ratio=1.0`
- 新 release 的 manifest sha 与 CURRENT.json 一致
- `book_wiki_versions` 同时列出旧 release（f728939909c44bdf9d7efb6e26760c9d）和新 release
- 旧 release 的 `.md` 文件**保留**在 `.releases/old_release_id/`（不删），但不再出现在新 release 的 manifest.files 中
- **没有 page_id 丢失或重复**（page_count 仍 = 1255）
- LLM 调用预算 ≤ 50 次

### 任务编排与并行（第三版）

**严格串行**：Task 0 → Task 1 → Task 2 → Task 3 → Task 4（原计划"3+4 并行"在第二版已修正）。

总预算估算：

- Task 0：1 小时，纯 bugfix + 写测试
- Task 1：30 分钟，补测试
- Task 2：30 分钟，Playwright smoke + 手工验证
- Task 3：~2 小时（一次性 LLM 调用 + 改 4 个文件 + CLI 注册 + preface 豁免）
- Task 4：~2 小时（重组 + 8 章重生成 + 走 apply-from seam + acceptance 对比）

总 LLM 调用：Task 3 约 360 次（含 retries），Task 4 约 17 次 = **≈ 377 次**；考虑重试实际 400-600 次。**开工前必须先 `policy.budget_cap: 450 → 800`**。

如果 LLM 调用超过 700 次需分轮：

- 轮 1（preview）：Task 0+1+2 修复 + 回归 + Task 3 标题生成 + Task 4 重组规划（dry-run partition）
- 轮 2（apply）：Task 3 preface 生成 + Task 4 8 章正文生成 + apply-from

## 假设与失败影响（第三版）

| 假设 | 不成立时 |
|---|---|
| `_book_outline_metadata` 行为正确（已代码复核通过） | Task 0 fix 后已覆盖 |
| outline.json 顶层是 `[OutlineProposal]` 列表 | 已验证（`f728939909c44bdf9d7efb6e26760c9d` 实际是 list 长度 1） |
| 68 个写作技法相关 chapter 的 page_id 都在 outline.json 内 | 如果不全，按 `chapter.body` 内 `source_page_ids` 反向重构 |
| LLM 起名任务用 1 次 prompt 可完成 179 章 | 拆为 4-5 个 batch（按主题分桶），单 batch 60-80 章 |
| 重组后 8 个新章可复用现有 `generate_chapter_body` | 调整 `token_budget`（page_ids 数翻倍），并把原 68 块正文做 summarize-like 拼接 |
| `policy.budget_cap=800` 足够 | 提升到 1200；或分批串行跑（每批 200 次） |
| `partition_pages` 覆盖不变式在 `partition_writing_technique_merged` 仍成立 | 严格用 `assert sorted(...) == sorted(snapshot.pages)` 自测 |
| Task 0 fix 后 `chapter.volume_id` 全部填充 | 验证 Task 0 测试若失败，**整轮阻塞**，不进入 Task 1+ |

## Audit — Round 1（第三版）

### ① 致命缺陷（5 条，第三版新增 1 条）

1. **`book_wiki_manifest` key 推导不匹配**（**第三版新增，根因发现**）：`_safe` 把 outline 里的 `:` 转 `_`，写盘后章节文件名用 `_` 而非 `:`；读回时 `split("__", 1)[-1]` 拿到下划线版 ID，与 outline.json 的冒号版 ID 不匹配，**179/179 lookup miss**。→ 整改：Task 0 修复 `_book_outline_metadata` 同时索引两种 key。
2. `preface.md` 命名冲突（沿用第二版）：豁免集未含 preface，会被当 chapter。→ 整改：Task 3 加豁免 + 字段分离。
3. Task 4 重组破坏 partition 覆盖不变式（沿用第二版）：68 块重组需透传 111 章。→ 整改：新增 `partition_writing_technique_merged` 透传 + 严格断言。
4. `book retitle` 子命令未注册（沿用第二版）：CLI 注册步骤需明确。→ 整改：Task 3 加 `src/cli.py` 解析器 + 文档。
5. 新 release 不走 apply-from seam（沿用第二版）：`resolve_active_version` 通过 sha 校验，直接切 CURRENT 会被判 stale。→ 整改：Task 4 强制走 `apply-from`。

### ② 重大隐患（6 条）

6. LLM 预算偏差（沿用第二版）：第一版估算 376 次，实际 400-600。→ `policy.budget_cap: 450 → 800`。
7. 重组后 acceptance 报告缺对比基线（沿用第二版）：保留旧 release 的扁平化字段 + `baseline_release_id`。
8. WebUI smoke test 缺失（沿用第二版）：新增 `tests/test_webui/` 用 `pytest-playwright`，CI 无 playwright 时 skip。
9. preface 链接老化（沿用第二版）：preface 用相对路径或不写链接。
10. 重组时 manifest `files` 哈希一致性（沿用第二版）：新 release 目录**只放**新 8 个 .md，旧 68 块保留在 `.releases/<old_release_id>/`。
11. **Task 0 fix 后旧 release 仍可能有 manifest 哈希校验问题**（**第三版新增**）：`resolve_active_version` 校验 `CURRENT.json` 中 `manifest_sha256` 与磁盘文件 sha 一致；Task 0 只改 lookup key，不动 manifest 与磁盘文件，旧 release 仍可读。→ 整改：Task 0 测试必须对现有 release（不止 fixture）跑回归，确认 `book_wiki_versions` 仍能列出旧 release。

### ③ 优化疏漏（5 条）

12. 章节标题超长（沿用第二版）：后处理截断 ≤14 字。
13. preface 字数 vs 读者耐心（沿用第二版）：目标 2500-4000 字。
14. 重组后 `chapter_count` 字段含义变化（沿用第二版）：acceptance 报告加 `merged_chapter_count` / `merged_page_count`。
15. CLI 注册文档（沿用第二版）：`docs/commands/cli-book.md` 同步更新。
16. manifest `release_manifest_hash` 链断裂（沿用第二版）：`acceptance.py` 的 `derive_acceptance` 步骤统一重算。

## Audit — Round 2：压力测试（第三版）

| 场景 | 连锁反应 | 加固方案 |
|---|---|---|
| Task 0 测试发现 `_book_outline_metadata` 在某些边界有更多 key 派生 bug | 必须改产品代码 | 仍在 Task 0 范围内修复，不延后 |
| Task 3 preface 生成被 LLM 内容安全拦截 | 部分章节无标题 | 兜底：LLM 失败时用 page_id 列表首词作为标题 |
| Task 4 重组触发 LLM 出现 `list[str]` 响应 | 8 大章正文缺漏 | 沿用 BookResponseRepair path（`polish_llm.py:162-164`） |
| Task 4 重组时 snapshot 与 wiki 漂移 | 新 release freshness=fail，apply 被拒 | 仅在 `snapshot_id` 不变时执行 |
| Task 2 smoke test 修 volumeFor 时意外影响 bookSelect / versionSelect 状态 | 选中章节丢失 | renderToc 仅在 chapter 列表变化时重渲染（已在 `book.js:114-119` 用版本切换事件触发） |
| 用户在 WebUI 选一个章节，重组后该章节被合并 | 跳转到旧 URL 404 | content 路由对未知 path 返回明确的"已合并到 X 章"消息 |
| LLM 输出标题与现有 tag 冲突 | lint 拒绝 | 标题生成前 post-check，冲突回退到 page_id 风格 |
| 重组后页面合计不匹配 1255 | coverage_ratio < 1 | 测试要包含"page_id 出现次数 = 1255" |
| 前端修改引入 CSS 回归 | 目录布局错位 | 手工回归或加 visual diff test |
| `budget_cap=800` 仍不够（实际 LLM > 800 次） | EXIT_BUDGET_EXHAUSTED=6 | 分 4 批跑：Task 3 标题 180 + preface 1 + Task 4 8×2 = 197 次/批，4 批共 788 次 |
| `book retitle --apply` 走 apply-from 失败（中间 release 损坏） | CURRENT 指向坏 release | 旧 release 的 .releases/ 目录保留不动，atomic pointer 失败时回滚到旧 release |
| Playwright 在 Windows CI 缺失 | smoke test 跳过 | CI 增加 `pytest -m "not webui"` 默认排除 webui 用例 |
| **Task 0 fix 后 outline.json 的冒号在 JSON 序列化后变成 `:` (U+003A)**（**第三版新增**）| 同一 chapter 在 `_book_outline_metadata` 缓存层（如果有）出现重复条目 | Task 0 测试断言"同一 chapter 在返回 dict 中只出现一次"；如发现重复，缓存层需去重 |

## 决策

- **Approach**：5 项一揽子，按 Task 0→1→2→3→4 **严格串行**顺序
- **审批门**：每个 Task 完成后由 reviewer 验证，Task 4 完成后再统一由 release acceptance 验证
- **回滚**：每次 `--apply` 前的 staging release 保留旧 manifest hash，可一键回退
- **失败处置**：
  - Task 0 fix 失败 → 整轮阻塞，重做方案
  - Task 3 失败 → 保留现有 release，仅完成 Task 0+1+2
  - Task 4 重组 LLM 调用失败 → 保留 68 块原状，仅完成 Task 0+1+2+3
- **下步**：等用户确认方案 + 批准 budget 800 + 批准 LLM 调用预算后开始编码

## 验收（第三版）

- **Task 0（新增）**：浏览器打开 Book，左目录显示 ≥9 个真名卷（不再 4 桶），每卷章数 > 0；`book_wiki_manifest` 返回的 `chapters[].volume_id` 填充率从 0/179 提升到 179/179
- Task 1：回归测试全绿；产品代码除 Task 0 外无改动
- Task 2：Playwright smoke 全绿；不破坏前端其他交互
- Task 3：每章有 ≤14 字中文标题，首章 preface.md 含 6-8 段主题导读；`book_wiki_manifest` 返回 `preface` 字段；chapters 数组不含 preface
- Task 4：写作技法 68 块 → 8 大章，全部 `content_status=complete`，`coverage_ratio=1.0`，`page_count=1255` 不变
- 端到端：手动按目录顺序读 8 大章，每章开头导读不重复，正文连贯，引用源文件 ≥5 个
- 不破坏：test_kc 全套 836+ 测试不退化（含 21/4/28 三个基线文件）
- Book API：所有 179 章 `volume_title` 100% 填充，53 个真名卷 `chapter_count > 0`
- CLI：`python -m src.cli book retitle --help` 列出 retitle 子命令；`docs/commands/cli-book.md` 含 retitle 用法

## 收益评估（第三版口径）

| 收益维度 | 路径 | 量化指标 | 备注 |
|---|---|---|---|
| A. WebUI 目录可读性 | Task 0 + Task 1 + Task 2 | 单页可见章节数从 179 降到 ~117（按 9-12 卷分桶，首屏下降 ~35%）；章节定位 5-10 分钟 → 30 秒 | **Task 0 是收益 A 的前置条件** |
| B. 章名可读性 | Task 3 | 标题信息密度从 0 → 14 字；无效点击 -50%+ | 与 Task 0 无关，独立达成 |
| C. 总序导读 | Task 3 preface | 新用户 5-10 分钟建立心智模型；与 `tutorial_paths` 互补 | 与 Task 0 无关 |
| D. 写作技法可读性 | Task 4 | 68 章 → 8 大章，主题内阅读效率 5-10× | 与 Task 0 无关 |

**投入**：

- 编码：5 个 Task × 1-2 小时 = **7-10 工时**
- LLM 调用：~377 次（cap 800），按 MiniMax 价格约 **¥15-30**
- 测试：新增 5 个测试文件，~35-45 个用例（含 Task 0 的 8 个）
- 文档：更新 `docs/commands/cli-book.md`、`docs/webui-buttons.md`

**风险与反向影响**：

- Task 0 修复失败 → 收益 A 落空；但 Task 3、4 收益仍成立（章名 + preface + 重组独立于目录分桶）
- `budget_cap=800` 仍不够 → Round 2 加固已有分批策略
- 重组后旧 chapter_id 失效 → 旧 .md 保留 + Round 2 加固"已合并提示"
- acceptance report chapter_count 字段含义变化 → 报告加 baseline 字段
- 一次性改 7-8 个产品代码文件 → TDD 每 Task 一提交；reviewer 每 Task 一审

**ROI**：

- **乐观**（Task 0 成功 + 完整实施）：教程级可读 Book + 后续维护减负 + WebUI 基建 → 强推荐
- **悲观**（Task 0 失败）：仍获得章名 + 总序 + 重组生效，目录分桶失效 → 回本但低于预期
- **底线**（Task 0、3、4 全失败）：仅完成 Task 1、2 review + 测试基建 → 回本

## Audit — 复审闭环（plan-audit §3）

按 `plan-audit` SKILL §3 要求"整改后再次执行第一轮审计"。

### 复审覆盖

| 第二版漏洞 | 第三版处置 | 复审结果 |
|---|---|---|
| Task 1、2 修复目标不存在（基于"代码已正确"判断） | **重新实证发现 key 推导 bug** → Task 0 fix + Task 1、2 改为 review-only | ✅（且修复路径更明确） |
| preface 命名冲突 | Task 3 加豁免 + 字段分离 | ✅ |
| Task 4 破坏 partition 覆盖不变式 | `partition_writing_technique_merged` 透传 111 章 + 严格断言 | ✅ |
| `book retitle` CLI 未注册 | Task 3 加 CLI 注册 + 文档 | ✅ |
| 不走 apply-from seam | Task 4 强制走 `apply_from` | ✅ |
| LLM 预算偏差 30%+ | `budget_cap: 450 → 800` + 实际 < 700 硬约束 | ✅ |
| acceptance 报告缺对比基线 | baseline_release_id 字段 | ✅ |
| 重组 chapter_count 含义变化 | merged_chapter_count / merged_page_count 字段 | ✅ |
| 数据偏差（67/30/18/36） | 修正为 68/21/4/28 | ✅ |

### 第三版新增漏洞（关键）

| 第三版新增 | 处置 | 复审 |
|---|---|---|
| `_safe` 把 outline `:` 转 `_` 导致 lookup miss（179/179） | Task 0 同时索引两种 key（推荐方案 0-A） | ✅ |
| Task 0 fix 后旧 release manifest sha 校验 | 验证 `book_wiki_versions` 仍能列旧 release | ✅ |
| 缓存层（如有）出现重复条目风险 | Task 0 测试断言"同一 chapter 唯一" | ✅ |

### 复审结论

第三版关键修复：**第二版的核心假设被推翻，发现了一个真实的 lookup 路径 bug**。Task 0 是新增的前置修复任务，所有下游 Task 都建立在它之上。

5 个 Task 在第三版中：

- Task 0 是 fix + 回归（必修，无 Task 0 不进 Task 1）
- Task 1、2 是 review-only + smoke（建立回归保护）
- Task 3、4 引入的新文件均经过"测试先于实现"流程
- 所有"第二版漏列"的 4 个致命缺陷 + 1 个重大隐患均在第二版加入对应加固；本版再发现 1 个新致命缺陷 + 2 个新隐患，均已处置

**复审通过**，方案可进入编码阶段（按 `dev-relay` 阶段路由：用户确认后切到 ponytail full）。

## Completion evidence

- Final commit: pending
- Tests: pending（新增 5 个测试文件、约 35-45 个新用例，含 Task 0 的 8 个）
- LLM 调用记录：pending（预算 ≈ 377 次，cap 800）
- 文档更新：`docs/commands/cli-book.md`（新增 retitle）、`docs/webui-buttons.md`（补 Book 视图分组规则）
- Progress ledger 更新：`.superpowers/sdd/2026-09-10-novel-wiki-book-readability/progress.md`
- Memory entry：`.memory/feedback-novel-wiki-book-readability-2026-09-10.md`（含 Task 0 关键发现：`_safe` 与 outline `:` 的命名分裂）
