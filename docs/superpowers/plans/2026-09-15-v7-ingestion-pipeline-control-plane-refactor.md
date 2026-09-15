# V7 Ingestion Pipeline Control Plane Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Each task must complete its own test cycle and commit. Steps use checkbox syntax for tracking.

**Goal:** 让 V7 摄取对每个 source 产生一个真实、可恢复、可审计的最终状态，并确保报告、审核队列、checkpoint 与实际 Wiki 文件一致。

**Architecture:** 保留现有 Collector/Stage 1/3/4/5/Writer 的语义能力，把现有 `ExtractionResult` 深化为唯一的 source outcome。脚本拥有 item/page identity，Writer 返回实际写盘结果，编排器在 durable outcome 后才更新 source checkpoint。关系抽取作为可选后处理，不进入首轮 source→concept 主链路。

**Tech Stack:** Python 3.11+, `asyncio`, `dataclasses`, JSON 原子写入，现有 `WikiWriter`、review queue、pytest；不新增依赖。

**Spec:** `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md` 与
`docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`；
本方案同时吸收四角度摄取流水线审计报告和 Plan 2 apply smoke 结果。

## 启动前置条件(强制,Wave 0 必须逐条校验)

本计划**不是** v3 实施的替代方案,而是 v3 Phase 2(Stage 改造)完成之后的**控制面插队任务**。
Wave 0 启动前必须满足:

- [ ] **A1**. v3 实施 Phase 1.0~2.5 全部 commit 已落地
      (`grep "feat(v7-prompts): add PromptAST\|feat(v7-stages): async rewrite" .superpowers/sdd/progress.md` 可见)
- [ ] **A2**. `src/pipeline/v7_extract/_legacy.py` 已存在且 `V7_USE_V3=false` 回退路径已验证
      (v3 T1.0)
- [ ] **A3**. `classify_doc` / `check_completeness` / `cluster_topics` / `fill_slots`
      全部顶层 `async def`,且 `_extract_one(root, path, relative, *, llm, page_sink)` 已 async
      (v3 T2.1-T2.4 + T3.1)
- [ ] **A4**. WikiWriter 的 P4/__other__ 闸门已落地
      (`grep "__other__" src/pipeline/v7_extract/wiki_writer.py` 有结果,v3 T2.5)
- [ ] **A5**. 当前 `_extract_one()` 实际签名快照已贴入本计划第 1.5 节
      (Wave 0 第 1 项输出)
- [ ] **A6**. 当前 `.superpowers/sdd/progress.md` 中 v3 阶段全部勾选完成
- [ ] **A7**. 本计划专属 ledger `.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/progress.md`
      已由 Wave 0 主 agent 创建

未满足任一条,**禁止启动 Wave 1**。

## Global Constraints

- 不修改 raw source 内容,不触碰工作树中与本计划无关的 dirty files。
- 不重写 Stage 1/3/4/5 的语义目标;LLM 仍负责分类、完整性判断、主题语义和槽位正文。
- item ID、page ID、路径和跨文档隔离必须由脚本决定。
- `--dry-run` 默认行为和 `V7_ALLOW_APPLY=1` apply 确认门保持不变。
  **新增:**dry-run 不写 Wiki page,但仍产出 source outcome 报告与
  dry-run 标记的 checkpoint(避免二次 apply 被 dry-run 结果 skip)。
- 质量阻断必须可见且不写入 Wiki;技术失败不得被 checkpoint 记为成功。
- 不新增数据库、worker、并发锁服务或新的 prompt 配置层。
- **新增:**不破坏 v3 实施的 P2 原则("任何 stage 失败 = needs_review,不抛异常"),
  `ExtractionResult` 改造必须保留 P2 兼容性,Stage 内部失败一律降级为 `blocked`/`failed`
  outcome,不得向上抛未处理异常。
- **新增:**与 v3 实施计划的写入集合冲突时,以"脚本身份契约优先 / queue schema
  保持兼容 / P2 原则不破坏"为裁决原则,由主 agent 按此原则解决冲突。
- 每个任务采用"先失败测试 → 最小实现 → 定向回归 → 单独 commit"。
- **新增:**Wave 2 完成后必须 `git tag v7-control-plane-wave2`,作为后续 Wave 失败
  的回滚快照点。

> 状态：待人工确认；本计划用于替代“只改 Stage 5 证据门槛”的局部方案。
>
> 依据：`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`、
> 2026-09-15 四角度审计结论，以及一次真实单文档 apply：`errors=0` 但页面被
> Writer 阻断、报告仍显示 `pages=1`。

## 1. 文件职责地图

| 文件 | 重构后的唯一职责 |
|---|---|
| `src/pipeline/v7_extract/failures.py` | 定义和序列化 source outcome；持久化失败/审核记录 |
| `src/pipeline/v7_extract/slot_filler.py` | 把 LLM 的 item index 映射为 canonical item ID，产出候选 page |
| `scripts/extract_pilot.py` | 驱动单 source 的 Stage 1/3/4/5，返回统一结果 |
| `src/pipeline/v7_extract/wiki_writer.py` | 执行页面闸门和原子写盘，返回 `WriteReport` |
| `scripts/extract_full.py` | 按 source 编排、重试、更新 checkpoint、汇总报告 |
| `src/wiki/storage/reviews_queue.py` | 提供现有 queue 的原子读写能力，不引入新队列系统 |
| `tests/test_*` | 覆盖 ID、状态、失败恢复、真实文件结果和幂等性 |

### 1.5 前置现状快照(Wave 0 必须重新核对并更新)

本节由 Wave 0 主 agent 在 `git rev-parse HEAD` 后填写,所有 Task 改造必须以此
为基线;基线变更时**先更新本节再启动对应 Task**。

- **`scripts/extract_pilot.py:144`** 当前签名:
  ```python
  async def _extract_one(
      root: Path,
      path: Path,
      relative: str,
      *,
      llm: Any = None,
      page_sink: Callable[[Any], None] | None = None,
  ) -> dict[str, Any]:
  ```
  返回值是 `dict[str, Any]`,字段:`source / characters / doc_type / confidence /
  rationale / complete / completeness_reason / topics / pages / error`。
  topic 失败时附加 `failed=True`,page 用 `page.__dict__["topic_id"] = topic.id`
  动态注入 topic_id。**改造目标:**统一为 `ExtractionResult` dataclass,topic_id
  改为正式字段,删除 `__dict__` 注入。

- **`scripts/extract_pilot.py:226-229`** 异常路径:try/except 包整段,失败时打印
  traceback 并返回带 `error` 字段的 dict。**改造目标:**不再返回 dict,改返回
  `ExtractionResult(status=FAILED, ...)`,仅记录 `failure_stage` 与截断的 reason,
  不打印完整 traceback(避免敏感 payload 泄露)。

- **`src/pipeline/v7_extract/wiki_writer.py:44-49`** `WriteReport` 当前字段:
  `written / skipped / blocked / failed`。**改造目标:**新增
  `page_writes: dict[str, Path]`(实际写盘路径)与 `dry_run: bool`,供 Task 4
  source checkpoint 消费。

- **`src/pipeline/v7_extract/failures.py:125-153`** 当前 API:**已实现**
  `enqueue_failure(source_id, stage, reason, payload=None, *, queue_path=...)`
  函数。**整改前 audit 误判"没有 enqueue_failure",实际方法存在**,但:
  - **签名缺** `page_id / topic_id / content_hash` 参数,无法生成稳定 hash ID
  - **review ID 用** `uuid4().hex[:12]` 随机,**重跑不幂等**(同失败产生新 ID)
  **改造目标:**扩展签名加 `page_id / topic_id / content_hash` 参数;review ID
  改为 `sha1(source + stage + page_id + topic_id + reason + content_hash)[:12]`,
  保证重跑幂等。`tests/fixtures/v7_control_plane/` 提供跨文件 ID 测试样本。

- **`src/pipeline/v7_extract/v7_checkpoint.json`(由 WikiWriter 写入)** 当前 schema:
  `{"completed": [page_ids]}`,page-level。**改造目标:**本次升级为 source-level,
  与现有 page-level 共存;`extract_full.py:33` 写 `v7_full_checkpoint.json`
  (batch-level,`completed_batches: [int]`),**两者都已存在**,本次计划不动
  WikiWriter 的 page-level checkpoint。

- **`src/pipeline/v7_extract/relation_extractor.py:37`** 已实现
  `extract_relations(pages, *, llm=None)`,但**无 scripts/ 调用方**。
  v3 架构文档第 5 节流程图把 Stage 6 画在 Stage 5 与 Stage 7 之间,与"scripts 未
  接入"的现实不符。**Task 6 修订文档:**明确 Stage 6 是可选 best-effort 后处理,
  默认不接入首轮 apply。**代码侧保留** `relation_extractor.py`,无需 disable
  配置(H6 调研结论)。

- **`src/pipeline/v7_extract/_legacy.py`** 是 22 行 placeholder,**不是真回退实现**。
  `__init__.py:74-77` 引用 `_legacy_<module_name>` 4 个分离文件,**这些文件根本不存在**。
  `V7_USE_V3=false` 路径会 ImportError。**Wave 0 决策(2026-09-15,用户确认):**
  本次 plan **仅依赖** `V7_USE_V3_CONTROL_PLANE` 单一回退(默认 `true`),**不修复**
  `_legacy.py` placeholder 问题(留给 v3 实施后续 task)。若本次 plan 改造出问题,
  设 `V7_USE_V3_CONTROL_PLANE=false` 跳过本次新增逻辑,直接走 v3 默认实现路径。
  `failures.py`、`wiki_writer.py`、`extract_full.py` 在导入时检查该开关,跳过
  本次 plan 引入的新行为。

- **`src/pipeline/v7_extract/_queue_lock.py`**(Wave 0 新增,O1 加固)
  提供软 PID 锁 `acquire_queue_lock(root) / release_queue_lock(root)`,
  `extract_full.py` 入口调用,避免多进程并发写 `.index/reviews_queue.json`
  损坏队列。**软提示,非强保证**;SIGKILL 残留需人工清理。

## 2. 目标与结论

### 目标

让 V7 从 raw source 到 Wiki page 满足一个简单、可恢复的终局：

1. 每个 source 最终只有一个真实状态：`written`、`blocked`、`failed`、
   `incomplete` 或 `skipped`。
2. 报告、审核队列和 checkpoint 记录同一个结果；不再出现“报告成功但没有
   页面”的假成功。
3. item ID、page ID、路径和跨文档隔离由脚本负责，LLM 只负责语义判断和内容。
4. 任何质量阻断都可见、可复核、可重新处理；任何技术失败都不会被 checkpoint
   误记为已完成。
5. 保留当前 Stage 1/3/4/5 的语义能力和 Stage 7 的安全闸门，只重构编排与
   持久化控制面。

### 审计结论

当前真正的架构缺陷不是“某个 prompt 不够严格”，而是状态分裂：

```text
_extract_one dict  ─┐
ExtractionResult    ├─ 没有共同的最终状态
WriteReport         ┤
reviews_queue       ┤─ 各自记录、各自失败
v7_full_checkpoint  ┘
```

因此本次不做全流水线重写，也不继续叠加更多 prompt gate；先把现有
`ExtractionResult` 深化为唯一的 source outcome，让上层只需处理“处理一个
source，返回并持久化一个结果”。

## 3. 目标接口与不变量

### 2.1 身份归属

| 对象 | 责任方 | 规则 |
|---|---|---|
| source ID | 脚本 | source 相对路径；内容变化用 md5 区分 |
| item ID | 脚本 | `relative#item-N`，从 1 开始，稳定且属于当前 source |
| topic key | LLM | 仅用于语义分组，不直接作为文件名或全局 page ID |
| page ID | 脚本 | `source-digest + topic-slug`，同 topic 跨文档也必须不同 |
| slot evidence item_id | 脚本 | LLM 返回 `item_index`，脚本映射为 canonical item ID |

不变量：LLM 不能创建、修改或决定最终 item/page ID；所有进入 Writer 的 ID
均经过脚本校验，且不能包含路径分隔符或路径穿越。

### 2.2 唯一结果对象

复用并扩展现有 `src/pipeline/v7_extract/failures.py` 中的
`ExtractionResult`，不新建平行结果类型。它至少包含：

```text
source_id, source_md5, status, failure_stage, reasons
page_ids, written_page_ids, blocked_page_ids, failed_page_ids
attempts
legacy_status   # v3 三态兼容字段,见下方映射表
```

`status` 的持久化值只有：

- `written`：候选页面全部有终局写盘结果，至少一个页面写入或已幂等跳过。
- `blocked`：页面因 `needs_review`、`__other__`、content filter 等质量规则被
  阻断；审核项已持久化。
- `failed`：LLM、解析、文件或写盘技术失败；失败项已持久化，但 source 不可
  作为成功完成处理。
- `incomplete`：Stage 3 判定原文不适合抽取；记录结果，不生成页面。
- `skipped`：同一 source md5 已有上述终局结果，且本次没有强制重跑。

内部允许短暂的 `candidate` 状态，但不得写入“已完成” checkpoint。

#### 2.2.1 与 v3 `ExtractionStatus` 的状态映射(F3 整改)

v3 架构定义的 `ExtractionStatus`(OK / NEEDS_REVIEW / INCOMPLETE)与本次五态
**不重合**。`ExtractionResult.to_dict()` 同时输出新 `status` 与 `legacy_status`,
下游消费者按需选择:

| v3 `ExtractionStatus` | 本次 `status` | `legacy_status` | 触发场景 |
|---|---|---|---|
| `OK` | `written` | `ok` | 全部页面写入或幂等跳过 |
| `OK` + 部分 page blocked | `written` | `ok` | 至少 1 个页面写盘,blocked page 入 queue |
| `NEEDS_REVIEW`(全部 page) | `blocked` | `needs_review` | Stage 1/3/4/5 任一 quality gate |
| `INCOMPLETE` | `incomplete` | `incomplete` | Stage 3 判定原文不适合抽取 |
| (新增) | `failed` | `needs_review` | LLM 抛异常 / JSON 解析失败 / 文件 IO / Writer 写盘 retry 耗尽 |
| (新增) | `skipped` | `ok`(若 skip 命中 written) / `needs_review`(若 skip 命中 blocked) | md5 命中已有终局 |

**兼容性规则:**

- `failures.py` 提供 `ExtractionResult.from_v3_status(v3_status, ...)` 工厂,
  旧消费者用 `legacy_status` 仍能正确分类。
- 报告 summary 字段同时输出 `by_status: {written, blocked, failed, incomplete,
  skipped}` 与 `by_legacy_status: {ok, needs_review, incomplete}`,供回退分析。
- **LLM 返回 schema 不合规**统一归 `failed`(技术失败),不再归 `blocked`
  (避免 P2 的 needs_review 降级掩盖 schema 重试机制 D2)。
- **缺失 evidence** 永远走 `blocked` 分支,即使其他 slot 全部成功(H11 加固)。

### 2.3 持久化顺序

单个 source 的正确顺序固定为：

```text
抽取 candidate
  → 写入/幂等确认 page，得到 WriteReport
  → blocked/failed 写入 review queue
  → 写入 source outcome checkpoint
  → 汇总报告
```

checkpoint 只能在前两步已有可恢复结果后更新。质量阻断可以成为终局；技术
失败不能伪装成成功终局。

## 4. 实施任务

每个任务先写回归测试、确认测试失败，再实现、验证、单独提交。不要把当前工作树
中与本计划无关的报告、prompt 或 `knowledge/novel-wiki/wiki` 删除混入提交。

### Task 0：建立基线和隔离测试根目录

**目的：**防止旧 checkpoint、现有大规模 wiki 变更和真实数据影响验证。

**Files:**

- Test: `tests/test_scripts/test_extract_full.py`
- Test: `tests/test_scripts/test_extract_pilot.py`
- Test: `tests/test_pipeline/test_v7_extract_*`

**步骤：**

- [ ] 记录当前 `git status --short`，确认不触碰既有 dirty files。
- [ ] 运行：

   ```powershell
   $env:PYTHONPATH="."
   python -m pytest tests/test_scripts/test_extract_full.py tests/test_scripts/test_extract_pilot.py tests/test_pipeline/test_v7_extract_* -q
   ```

- [ ] 将仍使用同步 Stage 4/5/7 调用的旧测试迁移到 async 调用；不删除测试意图。
- [ ] 增加一个临时 root fixture，至少包含两个 source、一个同名 topic，供后续
   跨文档 ID 和 resume 测试复用。

**验收：**基线结果可重复；测试不读取真实 `knowledge/novel-wiki`，且没有
`RuntimeWarning: coroutine was never awaited`。

### Task 1：脚本接管 item/page ID，并收紧 Stage 5 输入契约

**Files:**

- Modify: `src/pipeline/v7_extract/slot_filler.py`
- Modify: `src/pipeline/v7_extract/prompts/builtin/fill_slots.toml`
- Modify: `scripts/extract_pilot.py`
- Modify: `src/pipeline/v7_extract/topic_clusterer.py`（仅在需要时复用已存在的
  canonical item 映射）
- Test: `tests/test_pipeline/test_v7_extract_slot_filler.py`
- Test: `tests/test_scripts/test_extract_pilot.py`

**实现：**

- [ ] Stage 5 prompt 给 LLM 的 evidence 输入改为带序号的 item 列表；输出字段
   改为 `item_index`，不再要求 LLM 回填 item ID。
- [ ] `_payload_to_page()` 校验 index 是整数、在当前 topic 的范围内，然后映射为
   `Topic.item_ids[index]`；无效 index、缺失 evidence、空 body 继续标记
   `needs_review`。
- [ ] `source_text_excerpt` 保留为人工参考，不再做全文精确匹配硬门；这解决个人
   使用场景下 paraphrase 导致的误阻断，但不删除合法 item 来源校验。
- [ ] Stage 5 返回后,由 `_extract_one()` 将 page ID 改为
   `_stable_page_id(relative, topic.id)`,并以正式字段保存 `topic_id`,不再用
   `page.__dict__` 动态注入。
- [ ] `ConceptPage` 的构造兼容现有调用方;不要扩大为新对象层或新依赖。
- [ ] **H2 加固:** 新增 `src/pipeline/v7_extract/_page_id.py`(独立 helper 模块),
   集中 page ID 生成规则:
   ```python
   import hashlib, re
   _SLUG_RE = re.compile(r"[^\w-]+", re.UNICODE)
   def _slugify(title: str) -> str:
       s = _SLUG_RE.sub("-", title.lower()).strip("-")
       return s[:32] or "untitled"
   def _stable_page_id(relative: str, topic_title: str) -> str:
       # relative 必须用 POSIX 风格(将 \\ 替换为 /),保证跨 OS 一致
       rel = relative.replace("\\", "/")
       digest = hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
       return f"{digest}-{_slugify(topic_title)}"
   ```
   - 单元测试覆盖:同一 relative + topic 在 Windows/Linux 路径下产生相同 ID;
     跨 source 同名 topic 产生不同 ID;非法字符被归一;空 title 兜底为 "untitled"。
   - **禁止**在 `_extract_one()` 或 slot_filler 内 inline 实现该逻辑。

**必须新增的回归：**

- 合法 `item_index` 会得到 canonical `relative#item-N`。
- 越界、负数、非整数 index 会 review，且不会进入 Writer。
- 两个 source 返回相同 topic slug 时，page ID 不相同。
- 合法 item index + 非 literal excerpt 可以通过；空 slot body 不能通过。
- `__other__` 仍不会被误写。
- **H2 加固:** 同一 source 在 Windows(`raw\sources\a.md`)和 Linux(`raw/sources/a.md`)
  路径下产生相同 page ID。

**验收命令：**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_slot_filler.py tests/test_pipeline/test_v7_extract_topic_clusterer.py tests/test_scripts/test_extract_pilot.py -q
```

**提交：**`fix(v7-extract): make Stage 5 provenance script-owned`

### Task 2：把 `_extract_one()` 收敛到 `ExtractionResult`

**Files:**

- Modify: `src/pipeline/v7_extract/failures.py`
- Modify: `scripts/extract_pilot.py`
- Modify: `scripts/extract_full.py`
- Test: `tests/test_pipeline/test_v7_extract_failures.py`
- Test: `tests/test_scripts/test_extract_pilot.py`
- Test: `tests/test_scripts/test_extract_full.py`

**实现：**

- [ ] 扩展现有 `ExtractionStatus`/`ExtractionResult`，保留必要的旧字段兼容报告，
   但统一由 `to_dict()` 序列化，不再由每个 caller 拼不同 dict。
- [ ] `_extract_one()` 对 Stage 1、Stage 3、Stage 4、Stage 5、文件读取和解析
   失败都返回结构化结果；异常只在最外层转换成 `failed`，不打印完整原文或
   敏感 payload。
- [ ] 质量类结果和技术类结果分开：`blocked/incomplete` 可进入终局，`failed`
   保留 retry 信息并阻止 source 被记为成功。
- [ ] page 级列表始终包含 `generated`、`blocked`、`failed` 的明确数量，避免
   `pages=len(candidate pages)` 被误读为“已写入页面数”。

**验收：**单 source 的每个异常分支都能通过同一对象表达；JSON 结果不再依赖
`error` 字段是否存在来猜状态。

**提交：**`refactor(v7-extract): unify source extraction outcomes`

### Task 3：修复审核队列的 root 归属和幂等性

**Files:**

- Modify: `src/pipeline/v7_extract/failures.py`
- Modify: `src/wiki/storage/reviews_queue.py`（只补共享写入所需的最小能力）
- Modify: `scripts/extract_pilot.py`
- Modify: `src/pipeline/v7_extract/wiki_writer.py`
- Test: `tests/test_pipeline/test_v7_extract_failures.py`
- Test: `tests/test_pipeline/test_v7_extract_wiki_writer.py`

**实现：**

- [ ] **H4 加固(强制):** `extract_pilot.py` 与 `extract_full.py` 的 `--root`
   必须显式传入,**缺则 `sys.exit(2)` 并打印 usage**,不允许 fall back 到 CWD。
   入口参数校验放在 `argparse` 之后、`main()` 第一行。
   **Wave 0 决策(2026-09-15,用户确认):** 改为 `required=True`,**删除**
   `default=DEFAULT_ROOT`,确保用户必须显式传 `--root`。
   ```python
   parser.add_argument("--root", required=True,
                      help="project root directory (required)")
   if not getattr(args, "root", None):
       parser.error("--root is required (use --root <project_root>)")
   ```
- [ ] `extract_pilot` 和 `WikiWriter` 显式传入
   `root/.index/reviews_queue.json`，禁止失败记录落到当前工作目录。
- [ ] `enqueue_failure()` 用 `source + stage + page_id/topic_id + reason +
   content_hash` 生成稳定 review ID;同一失败重跑只更新已有项,不产生重复审核项。
   实现签名:
   ```python
   def enqueue_failure(
       self, source_id: str, stage: str, *,
       page_id: str = "", topic_id: str = "",
       reason: str, content_hash: str = "",
   ) -> str:
       identity = f"{source_id}\0{stage}\0{page_id}\0{topic_id}\0{reason}\0{content_hash}"
       review_id = "v7fail-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
       # 命中已有项则更新 attempts/last_seen_at,否则追加
   ```
- [ ] Writer 的每个阻断分支(`__other__`、needs review、无 evidence、filter)
   都写入 queue;页面路径非法、写盘重试耗尽也写入技术失败项(归 `failed` 而非
   `blocked`,与 §2.2.1 映射一致)。
- [ ] 对 queue 使用现有原子写入模式;本次不引入数据库、后台 worker 或复杂并发
   锁。明确记录限制:**多进程并发跑同一 root 时,queue 写入不保证原子**,
   必须用 `O_EXCL` 创建 `.index/.queue-lock` 做软提示(详见 §6 O1)。
- [ ] **P12 加固:** reason 字符串拼接 `prompt_kind` 与 `provider` 标签,
   便于 triage(例:`"stage5_llm_error prompt=fill_slots provider=ollama"`)。

**验收：**

- 自定义 root 的 queue 只出现在该 root 的 `.index` 下。
- 同一失败执行两次，queue 条目数量不增加。
- blocked 页面不写文件；failed 页面有可重试记录。
- 非法 page ID 不会让整个 batch 抛出未处理异常。

**提交：**`fix(v7-extract): persist blocked and failed outcomes idempotently`

### Task 4：将 full runner 从 batch checkpoint 改为 source checkpoint

**Files:**

- Modify: `scripts/extract_full.py`
- Modify: `src/pipeline/v7_extract/wiki_writer.py`（只复用其
  `WriteReport`，不重复实现写盘）
- Test: `tests/test_scripts/test_extract_full.py`

**目标接口：**`run_full()` 仍保留 `batch_size` 参数，作为报告/批次输出大小，
不再作为成功状态的唯一粒度。

**实现：**

- [ ] checkpoint 升级为版本化 source 记录，例如：

   ```json
   {
     "version": 2,
     "schema_version": 2,
     "created_at": 1700000000000,
     "sources": {
       "raw/sources/a.md": {
         "md5": "...",
         "status": "written",
         "legacy_status": "ok",
         "written_page_ids": ["..."],
         "blocked_page_ids": [],
         "failed_page_ids": [],
         "attempts": 1,
         "last_attempt_at": 1700000000000,
         "llm_provider": "ollama:qwen2.5:7b",
         "dry_run": false
       }
     }
   }
   ```

   **H3 加固(强制):** `attempts` 语义定义为 **"该 source 进入 `_extract_one()` 的
   轮次"**,Stage 7 内部 LLM retry 不计入;只有 source-level 处理轮次计入。
   `failed` source 重试时 `attempts` 累加,**永不重置**;提供 `max_attempts`
   配置(默认 5)防止无限重试。

- [ ] **H3 加固(强制):** checkpoint `page_ids` 拆分为
   `written_page_ids / blocked_page_ids / failed_page_ids` 三列(P8 加固);
   **只有 `written_page_ids` 非空才视为该 source 写盘成功**,进入 skip 判定;
   `blocked_page_ids` 不阻塞下次跑(可重新 triage)。

- [ ] 只有同一相对路径、同一 md5 且 status 为 `written`、`blocked` 或
   `incomplete` 时才 skip;`failed` 自动重试(直到 `max_attempts`)。

- [ ] 每处理完一个 source，先拿到 `WriteReport`，再写 queue/checkpoint；不要等
   整个 batch 成功才统一 checkpoint。
   **P7 加固:** Writer 写盘成功的 page,原子地记录到当前 source 的 in-memory
   `pending_checkpoint`,`atexit` 注册 flush hook 保证进程被 kill 时落盘。

- [ ] 兼容旧 `completed_batches`：读取时不把旧 batch 直接转换为新的 source 成功
   记录；必要时允许一次安全重跑，避免旧 checkpoint 隐藏未写入页面。
   **P5 加固:** 加载 checkpoint 时 `try/except (JSONDecodeError, ValueError)`:
   ```python
   try:
       payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
   except (OSError, ValueError):
       # 损坏:备份并视为空 checkpoint
       shutil.copy2(checkpoint_path, checkpoint_path.with_suffix(".json.corrupt"))
       payload = {"version": 2, "sources": {}}
   ```
   备份文件保留,人工可恢复。

- [ ] **P6 加固:** dry-run 时 checkpoint 不更新 `status`(保留上一轮终局);
   仅追加 `dry_run: true` 标记供审计。第二次跑 apply 时,被 dry-run 命中的 source
   **不视作已完成**,必须用真实 `WriteReport` 重新结算。

- [ ] **P1 加固:** checkpoint 加 `llm_provider` 字段(provider_name +
   model + adapter_version);加载时与当前 provider 比对,不同时给出警告
   `provider_changed_since_last_run`,**不强制重跑**(允许用户决定)。

- [ ] `batch_size` 仍用于分组进度输出，不能改变 source 集合，也不能被描述为
   “只处理 N 篇”。

**必须新增的回归：**

- 一个 batch 内第 1 个 source 写成功、第 2 个失败，resume 只重跑第 2 个。
- source 内容变化后 md5 不匹配，不被旧结果 skip。
- blocked source 可 resume skip，failed source 不可 resume skip。
- dry-run 不创建 Wiki page,但仍产生可复用 source outcome 报告;二次 apply 不被
  dry-run 结果 skip。
- 旧 checkpoint 不会造成 apply 假跳过。
- **H3:** `attempts` 累加规则:Stage 7 内部 retry 3 次只算 1 次 attempts;
  source-level 重跑才累加;达到 `max_attempts` 不再重试,标记 `failed_max_attempts`。
- **P5:** 手动损坏 checkpoint JSON,加载不抛异常,损坏文件备份为 `.corrupt`。
- **P8:** 同一 source 拆出 3 topic(topic1 written / topic2 blocked /
  topic3 __other__),checkpoint 中 `written_page_ids=[t1.id]`、
  `blocked_page_ids=[t2.id, t3.id]`,下次跑时该 source 仍可重新处理
  topic2/topic3(若 triage 后允许)。
- **P7:** 进程在 Writer 写盘后、checkpoint flush 前被 kill,重启后该 source
  被正确识别为"已写盘但未 checkpoint",不重复写盘且最终补 checkpoint。

**验收命令：**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_scripts/test_extract_full.py tests/test_pipeline/test_v7_extract_wiki_writer.py -q
```

**提交：**`refactor(v7-extract): checkpoint source outcomes after durable writes`

### Task 5：让报告反映真实终局，并完成一文档 apply 验收

**Files:**

- Modify: `scripts/extract_full.py`
- Modify: `scripts/extract_pilot.py`（复用统一序列化）
- Test: `tests/test_scripts/test_extract_full.py`
- Modify: `.superpowers/sdd/progress.md`

**报告 summary 最少包含：**

```text
selected, processed, skipped, written, blocked, failed, incomplete,
generated_pages, batches, batches_skipped, results_reused
```

`errors` 保留兼容，但定义为 `failed` 数量，不再把 blocked 混成 0 error 的
成功。

**最小 smoke：**

- [ ] 建立临时 root，只复制一个真实 raw source；不要移动/删除正式 raw。
- [ ] 在启动 Python 前设置变量，且显式使用临时 checkpoint：

   ```powershell
   $smokeRoot = "E:\tmp-v7-ingest-smoke"
   New-Item -ItemType Directory -Force -Path "$smokeRoot\raw\sources" | Out-Null
   Copy-Item -LiteralPath "knowledge\novel-wiki\raw\sources\必备资料11月28号创酷中文网女频现言讲课记录_8c363e.md" -Destination "$smokeRoot\raw\sources" -Force
   $env:PYTHONPATH="."
   $env:V7_ALLOW_APPLY="1"
   python scripts/extract_full.py --apply --batch-size 1 `
     --checkpoint "$smokeRoot\.index\v7_full_checkpoint.json" `
     --json-out "E:\tmp-v7-ingest-smoke.json" `
     --markdown-out "E:\tmp-v7-ingest-smoke.md" `
     --root $smokeRoot 2>&1 | Tee-Object "E:\tmp-v7-ingest-smoke.log"
   ```

- [ ] 同时检查报告、queue、checkpoint 和实际 `wiki/concepts` 文件。若该真实文档
   被 evidence/review gate 阻断，`written=0, blocked>=1` 是正确结果；不能把
   “没有概念页”判定为 smoke 失败，也不能把 `pages>=1` 判定为已写入。
- [ ] 再跑一次，验证 source 被 skip 且没有重复 queue 条目。
- [ ] **O2 加固(前置):** smoke 启动前**必须**先确认 `extract_full.py` 已支持
      `--root / --checkpoint / --json-out / --markdown-out` 参数:
      ```powershell
      python scripts/extract_full.py --help
      ```
      若参数缺失,在 smoke 前补齐(允许 Wave 4 Luna-G 一次性 commit)。
- [ ] **O3 加固:** smoke 前确认 WikiPage frontmatter 当前已支持字段(`grep
      "generated_by_v7_extract" src/pipeline/v7_extract/`),本次 plan 不
      引入新 frontmatter 字段;若确需新增,必须同步更新 `to_frontmatter_dict()`
      与 `from_dict()`。
- [ ] **P10 加固:** smoke 完成后确认 queue 文件位于
      `$smokeRoot\.index\reviews_queue.json`,而非 CWD;执行
      `python -m src.cli cache cleanup --dry-run --project <id>` 看是否会把
      queue 清掉(应被 `--preserve-reviews` 保留)。若未实现该参数,Wave 4
      Luna-G 同步补齐。

**通过标准：**命令退出码为 0；报告状态与实际文件一致；checkpoint 能解释
该 source 的终局；raw 文件 hash 不变。

**提交：**`test(v7-extract): verify one-source apply terminal outcomes`

## 5. 并行 Subagent 执行编排（gpt-5.6-luna）

本节是执行层计划，不改变上面的代码契约。所有 agent 使用
`model="gpt-5.6-luna"`，每个 agent 在自己的隔离工作区工作；主 agent 只负责
合并 commit、处理审查意见和更新本计划专属 ledger。任何两个 agent 不得同时写
同一个文件。

### Wave 0：主 agent 本地准备

主 agent 先完成，不占用 subagent：

- [ ] 记录 `BASE=$(git rev-parse HEAD)` 和现有 dirty files。
- [ ] **逐条校验本文档"启动前置条件"小节(A1-A7),未满足则停止 Wave 1**。
- [ ] **H6 加固(强制):** 执行 Stage 6 调研命令,把输出贴入 ledger:
      ```bash
      git grep "extract_relations\|relation_extractor" src/ scripts/
      cat src/pipeline/v7_extract/relation_extractor.py | head -80
      ```
      调研结果决定 Task 6 是否需要新增"Stage 6 默认 disable"代码改动。
- [ ] **H5 加固(强制):** 创建共享 fixture
      `tests/fixtures/v7_control_plane/`(目录 + 两个 sample source
      `source_a.md` / `source_b.md` + `expected_ids.json`),Wave 1 三 lane
      **禁止**各自新建 fixture 目录。
- [ ] 建立本计划专属 `.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/` ledger。
- [ ] 对计划中的共享文件做冲突表,**包含测试文件 import 依赖**(P2 加固):
      列出 Luna-A 测试是否 import Luna-B 的新接口、Luna-C 测试是否需要
      Luna-A 的新 helper,确保 import 顺序正确。
- [ ] **O5 加固:** 确认执行 agent 身份与目标模型(`gpt-5.6-luna`);若主会话
      不是该模型,Wave 1-4 必须通过外部 orchestrator 派发,**不与主会话共享
      context**,避免污染。
- [ ] **O1 加固(代码):** 创建 `src/pipeline/v7_extract/_queue_lock.py`:
      ```python
      def acquire_queue_lock(root: Path) -> bool:
          lock_path = root / ".index" / ".queue-lock"
          try:
              fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
              os.write(fd, str(os.getpid()).encode())
              os.close(fd)
              return True
          except FileExistsError:
              return False  # 已有进程持有锁
      def release_queue_lock(root: Path) -> None:
          (root / ".index" / ".queue-lock").unlink(missing_ok=True)
      ```
      `extract_full.py` 入口 acquire,`atexit` + try/finally 释放;失败时
      abort 并打印"另一进程正在写 queue"。这是**软提示**(PID 锁不可靠),
      文档明确多进程并发仍需另行升级。
- [ ] 不把现有 `docs/superpowers/reports/*`、`classify.toml` 或 wiki 删除混入任何 agent。

### Wave 1：三个可并行 lane

| Agent | 负责内容 | 允许写入 | 依赖 |
|---|---|---|---|
| Luna-A：provenance | Task 1；脚本接管 item/page ID 和 Stage 5 item index | `_page_id.py`(新)、`slot_filler.py`、`fill_slots.toml`、`extract_pilot.py`、`test_v7_extract_slot_filler.py`、`test_v7_extract_topic_clusterer.py`、`test_extract_pilot.py` | 读取当前代码；不改 failures/Writer；复用 Wave 0 共享 fixture |
| Luna-B：queue core | Task 3 的 queue 基础能力和稳定 review ID | `reviews_queue.py`(加 `enqueue_failure`)、`failures.py`(queue 调用)、`test_v7_extract_failures.py`、`test_reviews_queue_failure.py` | 读取当前代码；不改 extract_pilot/Writer 集成 |
| Luna-C：async regression | Task 0 的旧同步测试迁移和独立 fixture | `test_v7_extract_stage4.py`、`test_v7_extract_stage5.py`、`test_v7_extract_stage7.py`(仅迁移,不改 src) | 读取当前接口；**必须**复用 Wave 0 共享 fixture,不允许新建 |

每个 lane 必须：

- [ ] 先写失败测试并运行单文件测试。
- [ ] 只修改自己的写集合。
- [ ] 运行自己的定向测试、`git diff --check` 和 `compileall`。
- [ ] 提交一个逻辑 commit，并把测试结果写入自己的 report 文件。

主 agent 不等待某一个 lane 时自行修改这些文件；三个 lane 完成后统一检查
diff，再依次合并 A、B、C 的 commit。若 cherry-pick 产生冲突，停止并由主
agent 按"脚本身份契约优先、queue schema 保持兼容 / P2 原则不破坏"的原则
裁决,不让 agent 互相覆盖修改。

### Wave 2：统一结果对象（串行）

由 Luna-D 承接 Wave 1 合并后的状态，执行 Task 2。原因是它必须同时看到
Luna-A 对 `_extract_one()` 的返回影响和 Luna-B 对 `enqueue_failure()` 的最终
接口。写集合：`failures.py`、`extract_pilot.py`、`extract_full.py` 及对应脚本
测试；不得回退 Wave 1 的 canonical ID 规则。

完成标准：统一 `ExtractionResult` 已能表达 source 状态，且不再由 caller 通过
`error` 字段猜测结果。完成后先做 Task 2 review，再进入 Wave 3。

### Wave 3：写盘与恢复（串行）

由 Luna-E 执行 Task 3 的 Writer 集成，再由 Luna-F 执行 Task 4 的 source
checkpoint。两者不能并行：checkpoint 必须消费 Writer 的真实 `WriteReport`。

- Luna-E 写 `wiki_writer.py` 和 Writer 测试；接入 Wave 1 queue core。
- Luna-F 只写 `extract_full.py` 和 full runner 测试；实现 source+md5 checkpoint，
  不重复实现 Writer 或 queue。

每个 agent 完成后都必须经过 task reviewer；前一任务存在 Critical/Important
问题时，不得派发后一任务。

### Wave 4：报告、smoke、文档和最终审查

Wave 3 clean 后并行进行两个只读/文档 lane：

| Agent | 负责内容 | 写集合 |
|---|---|---|
| Luna-G：验收 | Task 5 的报告字段、单文档 apply 测试和 smoke 记录 | `extract_full.py` 的报告部分、`test_extract_full.py`、本计划 ledger 的 smoke artifact |
| Luna-H：文档 | Task 6 的架构修订、ADR 和 progress 条目草稿 | 架构计划、实施计划、`docs/adr/0011-*`；不改运行时代码 |

若 Luna-G 与 Luna-H 都需要修改 `progress.md`，由主 agent 最后合并，避免文档
冲突。完成后由主 agent 使用 Luna-I 做最终 whole-branch review；Luna-I 读取
完整 review package、ledger 和所有 deferred minor。最终 review 的模型仍固定为
`gpt-5.6-luna`，这是本次用户指定的模型约束。

### 并行执行的停止条件

- 任一 agent 发现需要删除/覆盖正式 wiki 或 raw，立即停止该 agent。
- 任一 task reviewer 报告 Critical/Important，先进入该 task 的 fix loop，不继续
  派发下游 agent。
- 同一 task 最多 5 轮修复；第 4/5 轮仍使用 Luna，但换一个全新 agent，携带原
  review findings。
- 只要 `written/blocked/failed` 与实际文件不一致，就不能进入全量 apply。

### Task 6：同步架构文档，明确 Stage 6 的边界

**Files:**

- Modify: `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
- Modify: `docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
- Modify: `.superpowers/sdd/progress.md`
- Add: `docs/adr/0011-v7-ingestion-outcome-control-plane.md`
  (**O4 加固:** Wave 0 启动前 `ls docs/adr/00*.md` 确认 0011 仍空闲;
  若已被占用,顺延为 0012,文档 commit 引用同步更新)

**内容：**

- [ ] 将“Stage 6 默认在主链路执行”改成准确描述：关系抽取是可选的 best-effort
   后处理，不是首轮 source→concept 写盘的成功条件；后续接入时必须复用同一
   page ID、queue、checkpoint 和 outcome 契约。
- [ ] 将 Stage 5 的摘录精确匹配从硬验收改为可选人工参考；保留 item provenance
   和页面级 source 闭环。
- [ ] 增加 source outcome 状态机、checkpoint 顺序和报告字段定义。
- [ ] 记录明确不做的工作：不引入事件总线重写、不引入数据库、不做并发 worker、
   不做全量 prompt 热加载重构、不在本计划内追求 80% spot-check。

**提交：**`docs(v7-extract): document outcome control plane`

### Task 7：整体验收与交接

运行：

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_scripts/test_extract_full.py tests/test_scripts/test_extract_pilot.py tests/test_pipeline/test_v7_extract_* -q
python -m compileall -q src/pipeline/v7_extract scripts/extract_full.py scripts/extract_pilot.py
git diff --check
git status --short
```

检查：

- 无未 await coroutine warning。
- 无 source outcome 与实际文件不一致。
- blocked/failed 都能在正确 root 的 queue 找到。
- checkpoint 可从中断点恢复，旧 checkpoint 不会隐藏数据。
- 真实 smoke 不修改正式 raw；所有正式 wiki 删除仍保持为用户原有 dirty 状态。

完成后更新 `.memory/`：记录新的 checkpoint schema、queue 路径规则、一次真实
smoke 的精确 summary 和任何未解决的 provider/LLM 问题。

## 6. 不做的重构

以下项目在当前个人使用目标下会增加复杂度，却不直接修复审计发现的控制面问题：

- 不重写 Collector/Analyzer/Generator 全套模块。
- 不把所有 Stage 变成独立队列或后台 worker。
- 不新增 PromptAST/多层热加载配置。
- 不将 Stage 1/3 的软判断继续升级成更多硬阻断。
- 不把 Stage 6 关系抽取塞回首轮写盘主链路；需要关系时单独做后处理任务。
- 不恢复 80% spot-check 作为 apply 前置门槛；`V7_ALLOW_APPLY` 仍是显式确认，
  review queue 是低置信结果的安全网。

## 7. 方案审查

### Round 1：全面漏洞审计

| 级别 | 风险与位置 | 后果 | 处理 |
|---|---|---|---|
| P0 | `wiki_writer.py` 直接信任 `page.id` | 非法 ID 可让全批崩溃 | Task 1 脚本生成 + Task 3 Writer 捕获并入 failed |
| P0 | Stage 5 以 LLM item_id 为准 | provenance 伪造或跨 topic 引用 | Task 1 只接受 item_index，脚本映射 |
| P0 | page.id 只用 topic slug | 跨文档同名主题覆盖/错误 skip | Task 1 source digest page ID 回归 |
| P0 | `extract_full` 忽略 `WriteReport` | 报告显示成功但实际 0 写入 | Task 5 汇总真实 written/blocked/failed |
| P0 | batch checkpoint 先于完整 durable outcome | 部分失败被永久跳过 | Task 4 改 source checkpoint |
| ①致命 F1 | 与 v3 实施计划的写入集合冲突,启动时机不明 | Wave 1 三 lane 撞上 v3 进行中的改造,合并冲突 | 头部"启动前置条件 A1-A7"+ §6 P0 不破坏 v3 P2 原则 |
| ①致命 F2 | `_extract_one()` 当前签名/异常路径未引用 | Task 2 重构无基线,可能破坏 P2 needs_review 降级 | §1.5 前置现状快照(Wave 0 重写) |
| ①致命 F3 | 五态与 v3 三态无映射 | 序列化兼容性破坏,A15/A19 测试失败 | §2.2.1 映射表 + `legacy_status` 字段 |
| P1 | blocked 不进 review queue | 人工无法 triage | Task 3 每个 Writer gate 入队 |
| P1 | queue 默认相对 CWD | 自定义 root 的审核记录丢失 | Task 3 H4 显式传 root queue path + `--root` 必填 |
| P1 | review ID 随机 | resume 重复生成审核项 | Task 3 稳定 ID + 幂等更新 |
| P1 | dict、ExtractionResult、WriteReport 三种状态 | caller 各自解释，无法审计 | Task 2 统一 outcome 序列化 |
| P1 | Stage 6 文档说默认执行但代码未调用 | 误以为关系已生成 | Task 6 改为明确可选后处理 + Wave 0 H6 调研 |
| ②重大 H1 | `_legacy.py` / `V7_USE_V3=false` 回退未被本次覆盖 | Wave 1-3 改造出问题无快速回退 | §1.5 新增 `V7_USE_V3_CONTROL_PLANE` 开关 |
| ②重大 H2 | page ID 的 digest 与 slug 归一化规则缺失 | 跨 OS 产生不同 ID,checkpoint 失效 | Task 1 H2 加固:`_page_id.py` helper + POSIX 归一 |
| ②重大 H3 | `attempts` 语义不清 | resume 行为不可预测 | Task 4 H3:source-level 轮次 + `max_attempts=5` |
| ②重大 H4 | `--root` 必填与默认值未定 | 漏传时审核项落 CWD | Task 3 H4:缺则 exit 2 |
| ②重大 H5 | Wave 1 三 lane 的 fixture 共享未规划 | 主 agent 合并时 fixture 重复 | Wave 0 H5:共享 `tests/fixtures/v7_control_plane/` |
| ②重大 H6 | Stage 6 实际接入情况未核实 | Task 6 文档修订无依据 | Wave 0 H6:`git grep` 输出贴 ledger |
| P2 | excerpt 全文精确匹配误伤 paraphrase | 个人 smoke 大量无谓阻断 | Task 1 摘录降为 annotation |
| P2 | 旧同步测试仍调用 async stage | CI warning/错误假象 | Task 0 迁移测试契约 |
| ③疏漏 O1 | 多进程并发跑同一 queue 未做锁 | 双开终端写竞争 | Wave 0 O1:`_queue_lock.py` 软提示 + 文档明确 |
| ③疏漏 O2 | `--json-out` / `--markdown-out` 参数未对齐 v3 实现 | smoke 命令可能报错 | Task 5 O2:启动前 `--help` 校验 |
| ③疏漏 O3 | page 字段前向兼容性未列 | 可能破坏 WikiPage 序列化 | Task 5 O3:确认现有字段,新增需同步 frontmatter |
| ③疏漏 O4 | ADR 编号冲突未确认 | 占用他人 ADR 编号 | Task 6 O4:Wave 0 前 `ls docs/adr/00*.md` |
| ③疏漏 O5 | Wave 0 默认 Luna 与当前会话模型不一致 | 主会话 context 污染 | Wave 0 O5:外部 orchestrator 派发,不共享 context |

### Round 2：压力测试

| 场景 | 预期行为 | 通过任务 |
|---|---|---|
| LLM 返回未知 item index | page blocked，queue 有一条稳定记录，不写盘 | 1, 3 |
| LLM 返回合法 index 但 paraphrase excerpt | 可继续；canonical item_id 保留 | 1 |
| 同一 topic 出现在两个 source | 两个 page 文件，不互相 skip/覆盖 | 1, 4 |
| Stage 5 第 2 次重试才成功 | attempts=2，最终按 WriteReport 结算 | 2, 4 |
| 写盘异常耗尽 retry | failed 入 queue，source 不写成功 checkpoint | 3, 4 |
| `__other__` topic | blocked 入 queue，不写 page，可解释 | 3 |
| process 在 page 写入后 checkpoint 前退出 | resume 由 page writer 幂等确认后补 checkpoint | 4 |
| source 内容变化 | md5 不匹配，不能 skip 旧结果 | 4 |
| 旧 `completed_batches` checkpoint | 不直接当作 source 成功，允许安全重跑 | 4 |
| dry-run | 不写 wiki，但报告仍有 candidate/block 状态;二次 apply 不被 skip | 5, 4-P6 |
| apply 未设置 `V7_ALLOW_APPLY` | 继续 fail-closed，不触碰任何 output | 5 |
| queue 中存在敏感原文 | 继续使用现有 sanitize/cap 逻辑，不扩大 payload | 3 |
| P1 LLM provider 切换(同 md5) | 不静默覆盖,checkpoint 给出 `provider_changed_since_last_run` 警告 | 4-P1 |
| P2 Wave 1 测试 import 依赖 | 测试文件冲突表覆盖 import 链 | Wave 0-P2 |
| P3 incomplete source 跑全量 | md5 不匹配重跑,result 进 report,但不进 queue | 3 + Task 2 |
| P4 reviewer 拒绝 Luna-E | Wave 2 完成后 `git tag v7-control-plane-wave2` 留快照 | Wave 0 + Wave 3 停止条件 |
| P5 checkpoint JSON 损坏 | 不抛异常,备份 `.corrupt`,视为空 checkpoint | 4-P5 |
| P6 dry-run 后 apply | dry-run 不更新 `status`,apply 强制重新结算 | 4-P6 |
| P7 进程被 kill 在 Writer 后 / checkpoint 前 | `atexit` flush pending_checkpoint,重启后补 checkpoint | 4-P7 |
| P8 同一 source 多 topic 阻塞 | `written_page_ids` 与 `blocked_page_ids` 分列,blocked 不阻塞 resume | 4-P8 + H3 |
| P9 V7_ALLOW_APPLY 未设但目录可写 | fail-closed 在 WikiWriter 第一行,任何调用方不能绕过 | 3-P9 |
| P10 cache cleanup 清掉 queue | queue 移到 `.llm-wiki/` 或加 `--preserve-reviews` 默认开关 | 5-P10 |
| P11 LLM 合法 item_index 但 item_texts 缺 key | 缺失 evidence 永远走 blocked 分支 | Task 1-H11 |
| P12 provider 配置变化导致 prompt kind 找不到 | reason 拼接 `prompt_kind` 与 `provider` 标签,便于 triage | Task 3-P12 |

### 审查结论

**整改后:** F1/F2/F3 三个致命缺陷均已落到具体修订(头部启动前置条件 + §1.5
前置现状快照 + §2.2.1 状态映射表),6 个重大隐患与 5 个优化疏漏均落到对应
Task 的加固 checkbox。**方案可进入编码**,但执行**必须**遵循:

1. **Task 1→4→5 的顺序**不可变;若 Task 4 的 source checkpoint 未完成,不得把
   全量 apply 视为可恢复。
2. **Wave 0 启动前置条件(A1-A7)任一未满足,禁止 Wave 1**。
3. Wave 2 完成后必须 `git tag v7-control-plane-wave2`,作为 Wave 3 失败的
   回滚快照点。
4. 任一 task reviewer 报告 Critical/Important,先进入该 task 的 fix loop,不继续
   派发下游 agent;**同一 task 最多 5 轮修复,第 4/5 轮换全新 agent**。
5. 任一 agent 发现需要删除/覆盖正式 wiki 或 raw,**立即停止该 agent**。
6. 只要 `written/blocked/failed` 与实际文件不一致,就**不能进入全量 apply**。
7. **复审触发条件:** F1/F3 整改后必须执行第二轮复审(本节"R2 复审"流程)。

### R2 复审(plan-audit 第二轮复审)

由主 agent 在 Wave 2 启动前执行,逐条核对:

- [ ] F1 启动前置条件 A1-A7 全部满足
- [ ] F2 §1.5 反映当前真实代码(无 `git grep` 不一致)
- [ ] F3 §2.2.1 映射表 + `legacy_status` 已实现单元测试
- [ ] H2 `_page_id.py` helper 已有 `test_v7_extract_page_id.py` 覆盖
- [ ] H3 `attempts` 累加规则有单元测试(`test_v7_extract_full.py::test_attempts_semantics`)
- [ ] H4 `--root` 缺则 exit 2 已测试
- [ ] H5 共享 fixture 已创建,Wave 1 三 lane 复用
- [ ] H6 Stage 6 调研输出贴入 ledger
- [ ] O1 `_queue_lock.py` 单元测试覆盖
- [ ] 压力测试 P1/P5/P6/P7/P8/P10 全部新增回归用例

未勾选项禁止进入 Wave 3。

## 8. 完成定义

只有同时满足以下条件，才宣布"流水线重构完成"：

1. 聚焦 V7 测试、编译和 diff check 通过(`pytest tests/test_pipeline/test_v7_extract_*
   tests/test_scripts/test_extract_*` 全过,`python -m compileall -q src/pipeline/v7_extract
   scripts/extract_full.py scripts/extract_pilot.py` 零错,`git diff --check` 零警告)。
2. **R2 复审清单全部勾选**(见 §7)。
3. 一文档真实 apply 的报告、queue、checkpoint、文件系统四者一致(见 Task 5 smoke)。
4. 第二次运行能按 source md5 skip,且不重复 queue(幂等性)。
5. 人为注入一个写盘失败后,失败 source 不会被成功 checkpoint 隐藏,并能恢复。
6. progress、ADR、memory 都记录实际验证证据,而不是只记录代码修改。
7. **新增:** `git tag v7-control-plane-final` 已打,作为后续 hotfix 基线。
8. **新增:** 完整 plan-audit 整改记录(§9)与 ledger 对应,审计可追溯。

在这些条件满足前，只能说"控制面重构已部分实现",不能启动 4918/1362 source
全量 apply。

## 9. plan-audit 整改记录

本节记录 2026-09-15 plan-audit 两轮审查与整改过程,供后续追溯。

### 9.1 第一轮审计(Round 1)输入

- 待审文件:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`(554 行原始版)
- 审计基线:plan-audit skill `references/audit-prompts.md` §1
- 审计视角:独立第三方,抛弃方案正向思路
- 对照文档:`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`(830 行) +
  `docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`(1169 行)
- 当前代码:`scripts/extract_pilot.py:144` `_extract_one()` 签名 +
  `src/pipeline/v7_extract/wiki_writer.py:44` `WriteReport` +
  `src/wiki/storage/reviews_queue.py` API

### 9.2 第一轮输出(整改前)

- ①致命缺陷:F1(与 v3 实施冲突)/ F2(_extract_one 无基线)/ F3(状态机无映射)
- ②重大隐患:H1(无回退)/ H2(page ID 规则)/ H3(attempts 语义)/ H4(--root 必填)/
  H5(共享 fixture)/ H6(Stage 6 调研)
- ③优化疏漏:O1(queue 锁)/ O2(smoke 参数对齐)/ O3(frontmatter)/ O4(ADR 编号)/ O5(模型一致性)
- 信息盲区:8 项(见 audit 报告)
- **统计:3 致命 / 6 重大 / 5 疏漏 / 8 盲区 = 22 个问题**(满足 ≥ 8 防敷衍约束)

### 9.3 第二轮审计(Round 2)输入

- 整改后方案:已应用 §9.4 所有修订
- 审计基线:plan-audit skill `references/audit-prompts.md` §2
- 压力测试:12 个失败路径 + 12 个新场景(P1-P12)

### 9.4 整改落实清单

| 编号 | 整改位置 | 整改内容 |
|---|---|---|
| F1 | 头部新增"启动前置条件 A1-A7" | Wave 0 必须逐条校验 |
| F1 | §6(并行编排)裁决原则 | 脚本身份契约 / queue schema 兼容 / P2 不破坏 |
| F1 | §6 增加 `git tag v7-control-plane-wave2` 快照点 | Wave 3 失败可回滚 |
| F2 | §1.5 新增"前置现状快照" | 含 `_extract_one` / `WriteReport` / `reviews_queue` / `_legacy.py` 现状 |
| F2 | Global Constraints 新增 P2 兼容硬约束 | Stage 内部失败一律降级 outcome |
| F3 | §2.2.1 新增映射表 + `legacy_status` 兼容字段 | 五态 ↔ 三态显式映射 |
| F3 | §2.2.1 边界规则:schema 失败归 failed,缺失 evidence 归 blocked | 消除 P2 降级掩盖 D2 |
| H1 | §1.5 新增 `V7_USE_V3_CONTROL_PLANE` 开关 | 本次 plan 改造的回退路径 |
| H2 | Task 1 新增 `_page_id.py` helper checkbox | 集中 digest + slug + 跨 OS 归一 |
| H3 | Task 4 checkpoint schema 扩展 + `attempts` 语义定义 | source-level 轮次,`max_attempts=5` |
| H3 | Task 4 `page_ids` 拆三列 + pending_checkpoint flush | 进程被 kill 不丢数据 |
| H4 | Task 3 `--root` 缺则 exit 2 + `enqueue_failure` 签名 + provider 标签 | 漏传根目录强制 fail |
| H5 | Wave 0 新增共享 fixture `tests/fixtures/v7_control_plane/` | Wave 1 三 lane 复用,禁止新建 |
| H6 | Wave 0 新增 Stage 6 调研命令 | 输出贴 ledger |
| O1 | Wave 0 新增 `_queue_lock.py` 软提示 | 多进程并发可检测 |
| O2 | Task 5 smoke 前 `--help` 校验 | 参数缺失补齐 |
| O3 | Task 5 smoke 前 frontmatter 字段确认 | 不破坏 WikiPage 序列化 |
| O4 | Task 6 ADR 编号 Wave 0 前再确认 | 避免冲突 |
| O5 | Wave 0 新增模型一致性确认 | 外部 orchestrator 派发 |
| R2 复审 | §7 新增"R2 复审清单" | Wave 2 启动前逐条核对 |
| 完成定义 | §8 新增 R2 复审勾选 + `git tag v7-control-plane-final` | 8 条完成标准 |

### 9.5 复审状态

- 第一轮致命缺陷(F1/F2/F3):**已整改,待 Wave 2 启动前 R2 复审确认**
- 第二轮压力测试(P1-P12):**已落入对应 Task 的加固 checkbox,待 Wave 2 启动前 R2 复审确认**
- 重大隐患(H1-H6)与疏漏(O1-O5):**已整改,落地具体 Task 或 Wave 0**
- 后续审计:每次大改后必须重跑 plan-audit,记录于本节 9.6+

### 9.6 待补:Wave 2 启动前 R2 复审记录(执行后填)

(此处由主 agent 在 R2 复审完成后填写,格式:日期 / 复审人 / 勾选项数 / 阻断原因 / 整改 commit)
