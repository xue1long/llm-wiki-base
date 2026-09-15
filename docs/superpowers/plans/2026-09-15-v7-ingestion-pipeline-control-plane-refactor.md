# V7 Ingestion Pipeline Control Plane Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Each task must complete its own test cycle and commit. Steps use checkbox syntax for tracking.

**Goal:** 让 V7 摄取对每个 source 产生一个真实、可恢复、可审计的最终状态，并确保报告、审核队列、checkpoint 与实际 Wiki 文件一致。

**Architecture:** 保留现有 Collector/Stage 1/3/4/5/Writer 的语义能力，把现有 `ExtractionResult` 深化为唯一的 source outcome。脚本拥有 item/page identity，Writer 返回实际写盘结果，编排器在 durable outcome 后才更新 source checkpoint。关系抽取作为可选后处理，不进入首轮 source→concept 主链路。

**Tech Stack:** Python 3.11+, `asyncio`, `dataclasses`, JSON 原子写入，现有 `WikiWriter`、review queue、pytest；不新增依赖。

**Spec:** `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`；本方案同时吸收四角度摄取流水线审计报告和 Plan 2 apply smoke 结果。

## Global Constraints

- 不修改 raw source 内容，不触碰工作树中与本计划无关的 dirty files。
- 不重写 Stage 1/3/4/5 的语义目标；LLM 仍负责分类、完整性判断、主题语义和槽位正文。
- item ID、page ID、路径和跨文档隔离必须由脚本决定。
- `--dry-run` 默认行为和 `V7_ALLOW_APPLY=1` apply 确认门保持不变。
- 质量阻断必须可见且不写入 Wiki；技术失败不得被 checkpoint 记为成功。
- 不新增数据库、worker、并发锁服务或新的 prompt 配置层。
- 每个任务采用“先失败测试 → 最小实现 → 定向回归 → 单独 commit”。

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
- [ ] Stage 5 返回后，由 `_extract_one()` 将 page ID 改为
   `_stable_page_id(relative, topic.id)`，并以正式字段保存 `topic_id`，不再用
   `page.__dict__` 动态注入。
- [ ] `ConceptPage` 的构造兼容现有调用方；不要扩大为新对象层或新依赖。

**必须新增的回归：**

- 合法 `item_index` 会得到 canonical `relative#item-N`。
- 越界、负数、非整数 index 会 review，且不会进入 Writer。
- 两个 source 返回相同 topic slug 时，page ID 不相同。
- 合法 item index + 非 literal excerpt 可以通过；空 slot body 不能通过。
- `__other__` 仍不会被误写。

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

- [ ] `extract_pilot` 和 `WikiWriter` 显式传入
   `root/.index/reviews_queue.json`，禁止失败记录落到当前工作目录。
- [ ] `enqueue_failure()` 用 `source + stage + page/topic + reason + content_hash`
   生成稳定 review ID；同一失败重跑只更新已有项，不产生重复审核项。
- [ ] Writer 的每个阻断分支（`__other__`、needs review、无 evidence、filter）
   都写入 queue；页面路径非法、写盘重试耗尽也写入技术失败项。
- [ ] 对 queue 使用现有原子写入模式；本次不引入数据库、后台 worker 或复杂并发
   锁。明确记录限制：个人单进程场景够用，多进程并发时另行升级。

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
     "sources": {
       "raw/sources/a.md": {
         "md5": "...",
         "status": "written",
         "page_ids": ["..."],
         "attempts": 1
       }
     }
   }
   ```

- [ ] 只有同一相对路径、同一 md5 且 status 为 `written`、`blocked` 或
   `incomplete` 时才 skip；`failed` 自动重试。
- [ ] 每处理完一个 source，先拿到 `WriteReport`，再写 queue/checkpoint；不要等
   整个 batch 成功才统一 checkpoint。
- [ ] 兼容旧 `completed_batches`：读取时不把旧 batch 直接转换为新的 source 成功
   记录；必要时允许一次安全重跑，避免旧 checkpoint 隐藏未写入页面。
- [ ] `batch_size` 仍用于分组进度输出，不能改变 source 集合，也不能被描述为
   “只处理 N 篇”。

**必须新增的回归：**

- 一个 batch 内第 1 个 source 写成功、第 2 个失败，resume 只重跑第 2 个。
- source 内容变化后 md5 不匹配，不被旧结果 skip。
- blocked source 可 resume skip，failed source 不可 resume skip。
- dry-run 不创建 Wiki page，但仍产生可复用 source outcome 报告。
- 旧 checkpoint 不会造成 apply 假跳过。

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
- [ ] 建立本计划专属 `.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/` ledger。
- [ ] 对计划中的共享文件做冲突表，确认以下三个并行 lane 的写集合不重叠。
- [ ] 不把现有 `docs/superpowers/reports/*`、`classify.toml` 或 wiki 删除混入任何 agent。

### Wave 1：三个可并行 lane

| Agent | 负责内容 | 允许写入 | 依赖 |
|---|---|---|---|
| Luna-A：provenance | Task 1；脚本接管 item/page ID 和 Stage 5 item index | `slot_filler.py`、`fill_slots.toml`、`extract_pilot.py`、`test_v7_extract_slot_filler.py`、`test_v7_extract_topic_clusterer.py`、`test_extract_pilot.py` | 读取当前代码；不改 failures/Writer |
| Luna-B：queue core | Task 3 的 queue 基础能力和稳定 review ID | `failures.py`、`reviews_queue.py`、`test_v7_extract_failures.py` | 读取当前代码；不改 extract_pilot/Writer 集成 |
| Luna-C：async regression | Task 0 的旧同步测试迁移和独立 fixture | `test_v7_extract_stage4.py`、`test_v7_extract_stage5.py`、`test_v7_extract_stage7.py` 及专属 fixture 文件 | 读取当前接口；不改 src |

每个 lane 必须：

- [ ] 先写失败测试并运行单文件测试。
- [ ] 只修改自己的写集合。
- [ ] 运行自己的定向测试、`git diff --check` 和 `compileall`。
- [ ] 提交一个逻辑 commit，并把测试结果写入自己的 report 文件。

主 agent 不等待某一个 lane 时自行修改这些文件；三个 lane 完成后统一检查
diff，再依次合并 A、B、C 的 commit。若 cherry-pick 产生冲突，停止并由主
agent 按“脚本身份契约优先、queue schema 保持兼容”的原则裁决，不让 agent
互相覆盖修改。

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
| P1 | blocked 不进 review queue | 人工无法 triage | Task 3 每个 Writer gate 入队 |
| P1 | queue 默认相对 CWD | 自定义 root 的审核记录丢失 | Task 3 显式传 root queue path |
| P1 | review ID 随机 | resume 重复生成审核项 | Task 3 稳定 ID + 幂等更新 |
| P1 | dict、ExtractionResult、WriteReport 三种状态 | caller 各自解释，无法审计 | Task 2 统一 outcome 序列化 |
| P1 | Stage 6 文档说默认执行但代码未调用 | 误以为关系已生成 | Task 6 改为明确可选后处理 |
| P2 | excerpt 全文精确匹配误伤 paraphrase | 个人 smoke 大量无谓阻断 | Task 1 摘录降为 annotation |
| P2 | 旧同步测试仍调用 async stage | CI warning/错误假象 | Task 0 迁移测试契约 |

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
| dry-run | 不写 wiki，但报告仍有 candidate/block 状态 | 5 |
| apply 未设置 `V7_ALLOW_APPLY` | 继续 fail-closed，不触碰任何 output | 5 |
| queue 中存在敏感原文 | 继续使用现有 sanitize/cap 逻辑，不扩大 payload | 3 |

### 审查结论

方案可进入编码，但必须按 Task 1→4→5 的顺序实施；若 Task 4 的 source
checkpoint 未完成，不得把全量 apply 视为可恢复。Task 6 的文档修订不能替代
Task 3/4 的实际持久化修复。

## 8. 完成定义

只有同时满足以下条件，才宣布“流水线重构完成”：

1. 聚焦 V7 测试、编译和 diff check 通过。
2. 一文档真实 apply 的报告、queue、checkpoint、文件系统四者一致。
3. 第二次运行能按 source md5 skip，且不重复 queue。
4. 人为注入一个写盘失败后，失败 source 不会被成功 checkpoint 隐藏，并能恢复。
5. progress、ADR、memory 都记录实际验证证据，而不是只记录代码修改。

在这些条件满足前，只能说“控制面重构已部分实现”，不能启动 4918/1362 source
全量 apply。
