# Plan: V7 Stage 2 I5 invariant 与 lineage UNIQUE 解锁

status: draft (待 plan-audit 两轮 + 人工复核)
branch: feature/2026-09-19-v7-stage2-lineage-unblock

> **承接**：本 plan 是 `.memory/feedback-v7-stage3-asr-prompt-fix-2026-09-19.md`
> 描述的 Stage 1 灰度期发现的两个**仍未解决**的问题。
> Stage 3 prompt v1.2 修复（commit `cdb274ed`）已落地但**实测证明对 ASR
> 稿无效果**——根因在 Stage 2 invariant I5，本 plan 解决 I5 + 修
> lineage UNIQUE 让 V7 在 novel-wiki-v2 上**真正可摄取**。

## Goal

**用户可见结果**：
1. novel-wiki-v2 上跑 V7 bridge 不再被 Stage 2 invariant I5 误判
   `degraded`（修源头，让 `boundary_confidence` 恢复 1.0，让 Stage 3
   LLM 看到完整信号，能走完 5 阶段）。
2. V7 bridge 成功后，`commit_ingest` 不再被 `pending_wiki_commits`
   表的脏 UNIQUE 约束撞崩（写盘正常完成，wiki/concepts/ 有新页）。

**明确非目标**：
- 不重新设计 Stage 2 invariant 的 5 项契约（保留 I1-I5 的契约面）。
- 不修 Stage 6 关系抽取空转 bug（独立 plan
  `2026-09-19-v7-stage6-relations-landing-fix.md` 已 deferred，未过审查）。
- 不处理 Stage 3 prompt 改动本身（v1.2 commit `cdb274ed` 保留）。
- 不动 `RUFLO_PIPELINE_MODE` 默认值（仍 `candidate`，V7 是 opt-in）。
- 不删 Stage 1 灰度观察期、Stage 2 改默认路径、Stage 3 删旧代码
  （4 阶段 rollout 由 `2026-09-18-v7-replace-candidate-pipeline.md` 控制）。

## 上下文（review 时必读）

**问题 A — Stage 2 invariant I5**：

`src/pipeline/v7_extract/invariants.py:105`

```python
i5 = (total == source_size) and i4
```

I5 要求 `sum(item.end_byte - item.start_byte) == source_size` **严格相等**。

`src/pipeline/v7_extract/segmentation.py:347-349`：

```python
"boundary_confidence": (
    1.0 if segmentation_result.invariants.all_pass else 0.5
),
```

deterministic splitter 用 byline / H2 heading / numbered list 切 ASR 转录稿
时，**末尾会留几十字节尾巴**（典型 ASR 烂尾特征：trailing 标点 / ASR
错误字符 / 无效段落）。`byte_accounting = 0.9995 ~ 1.0`，I5 不过 →
`invariants.all_pass = False` → `status = DEGRADED` →
`boundary_confidence = 0.5`。

Stage 3 LLM 看到这两个结构化信号组合，认为是 "mid-stream truncation" 而
非自然结尾 → INCOMPLETE。**实测证据**：4/5 个 ASR 文件全部触发：

```
status='degraded', boundary_confidence=0.5,
byte_accounting=0.9995~1.0, last_item_truncated=False
```

**问题 B — lineage UNIQUE constraint**：

每次 V7 bridge 成功（2 pages）后调 `commit_ingest`，
`src/lineage/api.py:148` 撞 `sqlite3.IntegrityError: UNIQUE constraint
failed: artifact_sources.artifact_id, artifact_sources.source_id`。

根因：candidate 路径历史脏数据。`.index/lineage/state.db` 的
`pending_wiki_commits` 表里有 kb-20260918145517 留下的记录，**含重复
source_id**（同一 source 在 source_ids 字段出现两次）。

`_recover_pending` 试图恢复时，第 2 次 INSERT 撞 UNIQUE 约束，事务失败
→ `LineageStore.open` 失败 → `commit_ingest` 失败 → 0 wiki 写入。

**候选修复**（已在 memory feedback 中分析，本 plan 选定 A + C）：

| 问题 | 选定方案 | 落空备选 |
|---|---|---|
| A: I5 误判 | **A. Stage 2 把"末尾 gap"显式分类为 `TAIL_RESIDUE`，boundary_confidence = 1.0**（源头修复 + 信号清晰） | B. prompt 教 LLM 忽略；C. 加 ASR 信号 |
| B: lineage UNIQUE | **C. `_recover_pending` 先 `SELECT` 去重 + 用 `INSERT OR IGNORE` 替 INSERT + 加 try/except 兜底**（不破坏数据，幂等恢复） | 清空脏数据（不推荐：丢失历史 pending 状态） |

## Tasks

### Task 1: Stage 2 显式分类"末尾 gap"为 TAIL_RESIDUE（不破坏 I5 严格性）

**Files:**
- `src/pipeline/v7_extract/invariants.py`（**新增** `i5_gap_at_tail` + `i5_gap_bytes` 字段 + 计算；I5 严格性本身**不动**）
- `src/pipeline/v7_extract/segmentation.py`（修改 `wrap_items_as_segmentation_result` 的 status 决策 + `build_structural_summary`；新增 `SegmentationStatus.TAIL_RESIDUE` 枚举值）
- `tests/test_pipeline/test_v7_extract_invariants.py`（若不存在则新建；加 invariant 字段测试）
- `tests/test_pipeline/test_v7_extract_stage2.py`（加 TAIL_RESIDUE 分类测试 + boundary_confidence 测试）
- `tests/test_pipeline/test_v7_extract_completeness_checker.py`（加端到端断言：pack 文本包含 `status=tail_residue` + `boundary_confidence=1.0`）
- `scripts/extract_pilot.py:649-663` 的 re-export 通过 `from src.pipeline.v7_extract.segmentation import (...)` 自动透明跟进（**显式声明**：未来若 re-export 与 canonical 行为发散，记录到 finding 但本 plan 不处理；plan 实施后用 `git grep 'from src.pipeline.v7_extract.segmentation import'` 验证 extract_pilot.py 仍走 canonical）

**前置排查（B-3 整改 — SegmentationStatus 消费者）**：
- `src/pipeline/v7_extract/topic_clusterer.py`：消费 status 字符串（`_ALL_KNOWN_STATUSES` 之类）
- `src/pipeline/v7_extract/wiki_writer.py`：可能消费 status
- `scripts/extract_pilot.py` / `scripts/extract_full.py`：报告 JSON 列出 status 分布
- 排查方法：`grep -rn "SegmentationStatus\." src/ scripts/ tests/`，列出每个消费者；TAIL_RESIDUE 加入后是否要默认过滤（如 wiki_writer 跳过 TAIL_RESIDUE 等同于 DEGRADED）。**实施时先输出清单，确认无遗漏消费者。**

**前置排查（B-6 整改 — byte_accounting 消费者）**：
- `src/pipeline/v7_extract/page_synthesizer.py` / `slot_filler.py`：可能消费 `structural_summary.byte_accounting` 字段
- Stage 5 fill_slots_v2 的 evidence pack 是否读 byte_accounting
- 排查方法：`grep -rn "byte_accounting" src/ tests/`；TAIL_RESIDUE 不改 byte_accounting 计算本身（gap 是 source_size 与 sum 的差，TAIL_RESIDUE 时 byte_accounting 仍是 0.9995），下游如果用 byte_accounting 阈值要确认是否受影响。**实施时先输出清单。**

**思路**：
invariant I5 仍要求 `total == source_size`（**严格性保留**）。
但当 I5 不过时，**显式判断 gap 类型**——这要新增 `i5_gap_at_tail` 字段，
因为 `InvariantReport.all_pass` 是计算属性，不暴露 gap 位置信息。

**Invariants.py 改动**（仅加字段，不动 I5）：
```python
@dataclass
class InvariantReport:
    i1_nonempty: bool
    i2_boundaries_valid: bool
    i3_sorted: bool
    i4_non_overlapping: bool
    i5_complete_accounting: bool
    i5_gap_at_tail: bool = False  # 新增：i5 失败时 gap 是否只在末尾
    i5_gap_bytes: int = 0         # 新增：gap 大小（字节）

    @property
    def all_pass(self) -> bool:
        return all((self.i1_nonempty, self.i2_boundaries_valid,
                    self.i3_sorted, self.i4_non_overlapping,
                    self.i5_complete_accounting))  # 不变
```

```python
def validate_segmentation_invariants(items, *, source_size, status=None):
    # ... 既有 I1-I5 计算
    # 新增：
    if items and items[-1].end_byte < source_size and i4:
        i5_gap_at_tail = True
        i5_gap_bytes = source_size - items[-1].end_byte
    elif items and items[-1].end_byte == source_size and not i5:
        # items 之间有 gap（i4 不过），i5_gap_at_tail = False
        i5_gap_at_tail = False
        i5_gap_bytes = source_size - sum(it.end_byte - it.start_byte for it in items)
    else:
        i5_gap_at_tail = False
        i5_gap_bytes = 0
    return InvariantReport(..., i5_gap_at_tail=i5_gap_at_tail,
                          i5_gap_bytes=i5_gap_bytes)
```

**Segmentation.py 改动**：
```python
# wrap_items_as_segmentation_result 的 status 决策：
if invariants.all_pass:
    status = SINGLE_EXPECTED if len(canonical_items) == 1 else SEGMENTED
elif invariants.i5_gap_at_tail and invariants.i5_gap_bytes <= MAX_TAIL_GAP_BYTES:
    # 新增：末尾小 gap = TAIL_RESIDUE（自然 ASR 烂尾特征）
    status = SegmentationStatus.TAIL_RESIDUE
elif invariants.i1_nonempty and not invariants.i5_complete_accounting:
    status = SegmentationStatus.DEGRADED  # 中间 gap 或大末尾 gap
elif not invariants.i1_nonempty:
    status = SegmentationStatus.UNCERTAIN
else:
    status = SegmentationStatus.FAILED

# build_structural_summary：
"boundary_confidence": (
    1.0 if segmentation_result.status in (
        SegmentationStatus.SEGMENTED,
        SegmentationStatus.SINGLE_EXPECTED,
        SegmentationStatus.TAIL_RESIDUE,  # 新增：1.0
    ) else 0.5
),
```

**新增 SegmentationStatus.TAIL_RESIDUE**：
- 枚举值：`TAIL_RESIDUE = "tail_residue"`
- 阈值 `MAX_TAIL_GAP_BYTES = 1024`（默认 1KB；ASR 烂尾特征是几十字节，
  真分段 bug 通常 gap 远大于此）

**Test-first**（4 条，与 §Acceptance 一致）：
1. **invariants.py** 加测试：`i5_gap_at_tail` 在末尾 gap 时为 True，中间 gap 时为 False
2. **segmentation.py** 加测试：ASR 风格源（确定性 splitter 末尾留 50 字节）→ status=TAIL_RESIDUE，boundary_confidence=1.0
3. **segmentation.py** 加测试：真分段 bug（中间 gap）→ status=DEGRADED/FAILED，boundary_confidence=0.5
4. **completeness_checker.py** 加端到端断言：TAIL_RESIDUE 时 evidence pack 文本含 `status=tail_residue` + `boundary_confidence=1.0`（防止 prompt 文本层面回归但测试假绿）

**MAX_TAIL_GAP_BYTES 阈值边界 case（Round 1 二次复审 ③-C）**：
- 构造 fixture `gap == 1024` 字节 → 断言 status=TAIL_RESIDUE
- 构造 fixture `gap == 1025` 字节 → 断言 status=DEGRADED
- 避免 off-by-one 错误（`<=` vs `<`）

**Acceptance:**
- 4 个新测试 + 阈值边界 2 条 = 6 个新测试 + 既有 stage2 + invariants + completeness_checker 测试全绿
- `python -m pytest tests/test_pipeline/test_v7_extract_stage2.py tests/test_pipeline/test_v7_extract_invariants.py tests/test_pipeline/test_v7_extract_completeness_checker.py` 全绿
- **Round 2 P0 加固（场景 1 人员缺位）**：`assert hasattr(InvariantReport, 'i5_gap_at_tail')` hard check 测试，防止接手 dev 漏改 invariants.py

**Commit:** `fix(v7-stage2): TAIL_RESIDUE status for end-of-source deterministic gaps`

---

### Task 2: lineage 全 4 处 executemany 修复（去重 + INSERT OR IGNORE + 异常隔离）

**Files:**
- `src/lineage/api.py`（新增 helper `_safe_insert_artifact_sources`；4 处 executemany 改用 helper）
- `tests/test_lineage/` 或 `tests/test_services/` 已有测试文件（加 helper 单元测试 + 4 处调用点的回归测试）

**漏洞（Round 1 ①-2 致命）**：
原方案只改 `_recover_pending`（line 148），但 `link_artifact`（line 610）、
`record_book_release`（line 198）、`_recover_book_releases`（line 515）都
有同模式的 `executemany INSERT INTO artifact_sources(...)` 是同样问题。

**Helper 签名（关键 — 解决 Round 1 复审新-①）**：
helper **必须返回 errors list**（不能 `-> None`），调用方据此决定是否
DELETE pending 行 + 写文件。

```python
def _safe_insert_artifact_sources(
    db, artifact_id: str, source_ids: Iterable[str],
) -> list[tuple[str, str]]:
    """去重 + INSERT OR IGNORE + 异常隔离的 artifact_sources 写入。

    Returns:
        [(source_id, error_msg), ...] 失败但被吞掉的（FK 孤儿 / UNIQUE 重复）。
        成功插入的不在返回列表中。调用方据此决定是否写文件 / 清 pending。

    - set() 去重（防止脏数据重复 source_id）
    - INSERT OR IGNORE 吞 UNIQUE；但不吞 FK 违反 → FK 显式 log + 跳过
    - 真正未知的完整性错误必须传播（让上层处理）
    """
    seen: set[str] = set()
    errors: list[tuple[str, str]] = []
    for sid in source_ids:
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            db.execute(
                "INSERT OR IGNORE INTO artifact_sources"
                "(artifact_id, source_id) VALUES (?, ?)",
                (artifact_id, sid),
            )
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "FOREIGN KEY constraint" in msg:
                log.warning("orphan source_id skipped: %s/%s", artifact_id, sid)
                errors.append((sid, "FK violation"))
            elif "UNIQUE constraint" in msg:
                errors.append((sid, "UNIQUE violation"))  # 防御性记录
            else:
                raise  # 真正未知的完整性错误必须传播
    return errors
```

**`_recover_pending` 重构（关键 — 解决 Round 1 复审新-①）**：

```python
@staticmethod
def _recover_pending(db: sqlite3.Connection, root: Path) -> None:
    """恢复 pending_wiki_commits 到 artifact_sources。失败单行写 recovery_errors.log。

    决策表：
    - 文件不存在或 hash 不匹配 → 跳过（不入 DELETE 列表，pending 保留待人工检查）
    - INSERT 全部成功（helper 返回空 errors）→ 入 DELETE 列表
    - INSERT 部分失败（helper 返回 errors）→ 入 DELETE 列表 + 写 recovery_errors.log
    - INSERT 抛非 IntegrityError → 跳过（不入 DELETE 列表，pending 保留待人工检查）
    """
    rows = db.execute(
        "SELECT wiki_page_id, source_ids, path, content_hash "
        "FROM pending_wiki_commits"
    ).fetchall()

    recovery_log = root / ".index" / "lineage" / "recovery_errors.log"
    pending_deletions: list[str] = []  # 仅成功的 page_id 才 DELETE

    for page_id, source_ids, path, expected in rows:
        try:
            target = root / path
            if not target.is_file() or not _hash_matches(target, expected):
                continue  # 跳过，不入 DELETE 列表
            ids = list(x for x in source_ids.split("\n") if x)

            db.execute(
                "INSERT OR REPLACE INTO artifacts"
                "(artifact_kind, artifact_id, path, content_hash, status) "
                "VALUES ('wiki', ?, ?, ?, 'committed')",
                (page_id, path, expected),
            )
            db.execute(
                "DELETE FROM artifact_sources WHERE artifact_id = ?",
                (page_id,),
            )
            errors = _safe_insert_artifact_sources(db, page_id, ids)

            # 成功（含部分孤儿跳过）→ 入 DELETE 列表
            pending_deletions.append(page_id)
            if errors:
                # 部分失败：写 recovery_errors.log（运维可见）
                # **Round 2 P0 加固（场景 2 磁盘满）**：log 写入包 try/except OSError，
                # 即使写失败也强制入 DELETE 列表（避免 pending 永远不被清）
                try:
                    recovery_log.parent.mkdir(parents=True, exist_ok=True)
                    with recovery_log.open("a", encoding="utf-8") as f:
                        f.write(
                            f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                            f"page_id={page_id} skipped={errors}\n"
                        )
                except OSError as log_err:
                    log.warning(
                        "recover_pending: failed to write recovery_errors.log for %s: %s",
                        page_id, log_err,
                    )
                    # 不抛：page_id 已经在 pending_deletions 列表，DELETE 仍执行
        except sqlite3.IntegrityError:
            log.exception("recover_pending IntegrityError for %s", page_id)
            continue  # 不入 DELETE 列表
        except (OSError, ValueError) as e:
            log.warning("recover_pending error for %s: %s", page_id, e)
            continue  # 不入 DELETE 列表

    # 阶段 2：仅 DELETE 成功的 page_id（移 try/except 外 + 条件性）
    if pending_deletions:
        placeholders = ",".join("?" * len(pending_deletions))
        db.execute(
            f"DELETE FROM pending_wiki_commits WHERE wiki_page_id IN ({placeholders})",
            pending_deletions,
        )
    db.commit()
```

**4 处调用点统一改**：
1. `_recover_pending`（line 148）：改用 helper + 收集 errors + 条件 DELETE + 写 recovery_errors.log（完整代码如上）
2. `record_book_release`（line 198）：改用 helper，errors 写到 `book_releases` 自身 metadata（不写 file log）
3. `_recover_book_releases`（line 515）：改用 helper，errors 写到 `recovery_errors.log` 同上模式
4. `link_artifact`（line 610）：改用 helper，errors **抛 `DataConsistencyError`**（运行态新写入路径不应有孤儿，FK 违反 = 真 bug）
```

**Test-first**（4 条）：
1. **helper 单元测试**：重复 source_id → artifact_sources 行数 = set 大小
2. **FK 违反隔离测试**：helper 含孤儿 source_id → 跳过 + log warning + 不抛异常
3. **`_recover_pending` 集成测试**：含重复 + FK 违反的混合数据 → 全部安全恢复（不抛异常）
4. **`_recover_pending` 边界测试**：单条失败后 `DELETE FROM pending_wiki_commits` 仍执行（成功行被清，失败行保留以便运维人工检查）

**Helper 外部依赖（Round 1 二次复审 ③-A）**：
- `src/lineage/api.py` 顶部需新增 `import time` 和 `import logging; log = logging.getLogger(__name__)`
- 当前文件 imports 仅 `json/sqlite3/uuid/hashlib/Path/types`，**未声明**这两个 import 会导致 `NameError: name 'time' is not defined` / `NameError: name 'log' is not defined`
- 实施时必须先补 imports

**4 处调用点的错误处理细化（Round 1 二次复审 ③-B）**：
- `link_artifact`（line 610，**运行态写入路径**）：FK violation 抛 `DataConsistencyError`（运行态不应有 FK 孤儿，是真 bug 必须让运维看到）；UNIQUE violation 不抛（运行态 `executemany` 前已 `DELETE FROM artifact_sources WHERE artifact_id = ?` 清理，不应有 UNIQUE）；其他 errors 抛
- `record_book_release`（line 198，写 book metadata 路径）：errors 写到 `book_releases` 表自身 metadata，**不写 file log**
- `_recover_book_releases`（line 515，恢复 book 路径）：errors 写 `recovery_errors.log` 同上模式
- `_recover_pending`（line 148，恢复 wiki 路径）：errors 写 `recovery_errors.log`，完整代码已展开

**Acceptance:**
- 4 个新测试 + 既有 lineage 测试不变 → lineage 测试套全绿
- 实际跑：保留 novel-wiki-v2 脏数据跑 V7 bridge → 不再撞 UNIQUE/FK
- 实际跑：写文件 `.index/lineage/recovery_errors.log` 可看到失败行

**Commit:** `fix(lineage): _safe_insert_artifact_sources helper + 4-call-site dedup`

---

### Task 3: 集成验证 — novel-wiki-v2 5 跑实测

**Files:** 无代码改动；只跑验证脚本

**测试命令**:
```bash
python -X utf8 scripts/run_v7_5x.py
```

**判据权威定义（修正 Round 1 复审新-②）**：
**判据以 `scripts/verify_v7_ingest.py:131-211` 实际实现为权威**，plan 表格
逐字引用脚本判定逻辑，不二次编造：

| # | 判据 | 脚本定义（line 引用） | 期望 |
|---|---|---|---|
| 1 | succeeded + 有页面 | `verify_v7_ingest.py:131-144`：`failure_stage is None` AND `n_pages > 0` | bridge 没崩 + 写了页面 |
| 2 | health H1/H2/H4/H5 = 0 | `verify_v7_ingest.py:146-166`：`health --project` exit=0 | 现有 KB 健康度不退化 |
| 3 | wiki-quality 无 error | `verify_v7_ingest.py:168-181`：`wiki-quality --strict` exit=0 | 严格质量门不退化 |
| 4 | 幂等性观察 | `verify_v7_ingest.py:183-190`：source/concept 文件数 delta | 仅观察，不主动重摄取 |
| 5 | 失败必须体现为 failed | `verify_v7_ingest.py:192-211`：status in {bridge_failed, succeeded+n_pages>0, gate_failed} | 不静默记为成功 |

**Acceptance（修正）**：
- `python -X utf8 scripts/run_v7_5x.py` 整体 **exit=0**
- 5 个文件全部 `verify_v7_ingest.py` 跑出 `overall: ✓ ALL PASS`
- 否则 plan 失败回 Task 1/2 排查

**实施前必跑（Round 2 P0 加固）**：

1. **Provider sanity probe（场景 3 限流样本不足）**：
   ```bash
   # 跑前先用 1 个小文件 dry-run 30s 内返回非 INCOMPLETE
   timeout 60 python scripts/smoke_v7_bridge.py --no-commit \
     --project-root knowledge/novel-wiki-v2 \
     --source "raw/sources/视频音频转录教程/音频教程/写作技巧-1.md" \
     --provider minimax
   ```
   若 60s 内不返回或返回 stage3_incomplete → 暂停 5 跑，等限流恢复。
   
2. **总耗时预算（场景 3 + 场景 4 慢响应）**：
   - 单文件最坏 4 分钟（实测 ~30s-2 分钟），5 跑合计 ≤ 25 分钟
   - 超过 25 分钟 → 中止并归因（provider 限流 / Stage 5 雪崩）

3. **md5sum 跑前快照（场景 6 重跑覆盖）**：
   ```bash
   # 跑前快照所有 5 个源文件 md5
   md5sum knowledge/novel-wiki-v2/raw/sources/视频音频转录教程/02进阶视频教程/视频-南派三叔1.md \
          knowledge/novel-wiki-v2/raw/sources/视频音频转录教程/02进阶视频教程/写作十大技巧.md \
          knowledge/novel-wiki-v2/raw/sources/视频音频转录教程/02进阶视频教程/小小说写作技巧1-2讲.md \
          knowledge/novel-wiki-v2/raw/sources/视频音频转录教程/音频教程/人物形象写作技巧-1.md \
          knowledge/novel-wiki-v2/raw/sources/视频音频转录教程/02进阶视频教程/大纲写作技巧.md \
     > /tmp/v7-5x-input-md5.txt
   ```
   跑后 `diff /tmp/v7-5x-input-md5.txt <(md5sum ...)` 必须为空
   （source 文件内容不变 — 只变 wiki/ 产物）

4. **lsof 检查 server 进程（场景 5 SQLite lock）**：
   ```bash
   lsof knowledge/novel-wiki-v2/.index/lineage/state.db
   ```
   若有 `python` 在用 state.db → kill server 后再跑 5 跑

**实施前必跑（Round 2 P1 修补，强烈建议）**：

- **SQLite 版本检查（场景 9 FK 抑制版本差异）**：
  ```bash
  python -c "import sqlite3; v=sqlite3.sqlite_version; assert v >= '3.6.19', v"
  ```

**注意事项**：
- LLM temperature 默认 0（`bridge.py` 与 `provider_factory.py` 设定）；
  5 跑结果应是 deterministic。若发现 flaky，需先确认 provider 配置。
- Provider 默认 `minimax`，要求 `RUFLO_LLM_PROVIDER=minimax` 已注册
  且 API key 有效。
- 实施前先 `python -m src.cli llm-providers list` 确认 minimax 存在
  且 **model 字段非空**（避免 `bridge.py` 调用时 NPE；Round 1 二次复审盲-C）
- 实施前先 forensic dump 脏数据：
  ```bash
  sqlite3 knowledge/novel-wiki-v2/.index/lineage/state.db \
    "SELECT * FROM pending_wiki_commits;"
  ```
  —— 记录当前脏数据形态到本 plan §Completion evidence。

**Commit:** 无（仅 evidence）

---

### Task 4: 文档同步 + 后续 plan 衔接

**Files:**
- `.memory/feedback-v7-stage2-i5-lineage-fix-2026-09-19.md`（新增过程账本）
- `.memory/MEMORY.md`（新增索引项，引用 `.memory/TEMPLATE.md` 格式）
- `docs/adr/0015-v7-stage2-tail-residue-classification.md`（**新增** ADR：决策为何用 TAIL_RESIDUE 状态而非改 I5 容差）

**ADR-0015 必含要素**：
- Context: ASR 转录稿在 I5 严格 byte accounting 下全判 degraded
- Decision: 保留 I5 严格性 + 新增 TAIL_RESIDUE 状态
- Alternatives considered: 改 I5 容差（拒绝）、改 Stage 3 prompt 忽略信号（已证明无效）
- Consequences: 1KB 阈值的边界 case 需要后续观察；可能需要项目级配置

**Acceptance:** memory + index + ADR 全部更新；可被未来会话检索

---

## Audit

- Round 1: **DONE** — `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r1.md`（致命 2 / 重大 5 / 优化 6 / 盲区 7）
- Round 1 复审: **DONE** — `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r1-followup.md`（整改后 3 个新发现：新-① 致命 / 新-② 重大 / 新-③ 重大）
- Round 1 复审整改要点（**已 apply 到本 plan 正文**，逐条对照）：
  - **新-① 致命**（helper 返回 None + DELETE 自相矛盾）→ Task 2 helper 改返回 `list[tuple]`；`_recover_pending` 用 `pending_deletions: list[str]` 收集成功行，循环外条件 DELETE；recovery_errors.log 在循环内写
  - **新-② 重大**（判据表与脚本错位）→ Task 3 表格改为逐字引用 `scripts/verify_v7_ingest.py:131-211` line + 实际判定逻辑
  - **新-③ 重大**（§Audit 宣称 vs 正文不一致）→ ③-6 已从整改宣称列表删除（已在 Task 1 §Files 正文显式声明 re-export 影响）
  - **B-1**（forensic dump）→ Task 3 实施前必跑 SQL，dump 结果记到 §Completion evidence
  - **B-2**（ASR fixture 内容）→ Task 1 Test-first 第 2 条已显式描述（50 字节尾巴 ASR），实施时构造 fixture 内容
  - **B-3**（SegmentationStatus 消费者）→ Task 1 前置排查段已显式要求实施时 grep + 列清单
  - **B-4**（LLM 双放行风险）→ 在 ADR-0015 Consequence 段必答：Stage 3 ASR 例外 prompt（v1.2）+ TAIL_RESIDUE/boundary_confidence=1.0 是**两个独立护栏**而非双放行——前者是 LLM 软指引，后者是结构化硬信号；任一失效另一仍可工作
  - **B-5**（lineage schema 演进）→ ADR-0015 Consequence 段必答：pending_wiki_commits 表语义不变（仍是"待恢复的 commit"），只是恢复路径加了去重 + 错误隔离；未来若弃用，单独 schema migration
  - **B-6**（byte_accounting 消费者）→ Task 1 前置排查段已显式要求
  - **B-7**（5 跑前置条件）→ Task 3 注意事项已加 `llm-providers list` 检查
  - ②-1 / ②-2 / ②-3 / ②-4 / ②-5（Round 1 重大）→ 见整改后 Task 2 + Task 3 正文
- Round 2: **DONE** — `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r2.md`（PASS with MANDATORY P0 FIXES；3 重大压力点 + 6 优化压力点）
- Round 2 P0 加固（**已 apply 到本 plan 正文**）：
  - 场景 1 人员缺位 → Task 1 §Acceptance 加 `assert hasattr(InvariantReport, 'i5_gap_at_tail')` hard check
  - 场景 2 磁盘满 log 写失败 → Task 2 helper 实施代码：log 写入包 try/except OSError + 强制入 DELETE 列表
  - 场景 3 限流样本不足 → Task 3 §实施前必跑 加 provider sanity probe + 总耗时预算 ≤ 25 分钟
  - 场景 6 重跑覆盖 → Task 3 §实施前必跑 加 md5sum 跑前快照
  - 场景 7 Stage 5 上游排查缺失 → §Open risks 显式标注"后续 plan 单独处理"
- Round 2 P1 加固（**已 apply 到本 plan 正文**）：
  - 场景 9 SQLite 版本差异 → §实施前必跑 加 `python -c "import sqlite3; assert sqlite3.sqlite_version >= '3.6.19'"`
  - 场景 8 阈值跨项目不可移植 → §Open risks 显式标注"必须通过 quality_settings.json 项目级配置覆盖"
- Human review: pending
- Open risks:
  - Task 1 改 `build_structural_summary` 的 boundary_confidence 计算 → 任何依赖此信号的代码（Stage 3 LLM / 审计 / 报告）行为变化，要回归
  - Task 2 加去重 → 历史脏数据被去重 = 历史信息丢失（**可接受**，因为脏数据本来就错）
  - Task 1 `MAX_TAIL_GAP_BYTES = 1024` 阈值是经验值（Round 2 场景 8 压力点）→ 跨项目不可移植，**必须通过 `quality_settings.json` 项目级配置覆盖**（如 novel-wiki 用 1024，其他项目可能需要 2048 或 4096）；当前 plan 不实现，只在 ADR-0015 Consequence 段记录
  - Task 2 helper 修复了运行态 `link_artifact` 抛 `DataConsistencyError`（让 FK 孤儿显式可见）→ 但 **Stage 5 上游 source_ids 产生逻辑未排查**（Round 2 场景 7 压力点），若 Stage 5 系统性产生重复 source_id，每次 ingest 都失败；当前 plan 排查不深入，归因难度大；后续 plan 单独处理
  - **SQLite 版本依赖**：helper 依赖 SQLite ≥ 3.6.19（`INSERT OR IGNORE` 对 FK 违反行为正确抑制）；老 SQLite dev box 可能静默腐败；Round 2 场景 9 压力点，**ADR-0015 Consequence 段必答**
- Rollback:
  - **Task 1 rollback**：`git revert <commit_sha> --no-edit`；回归测试 `pytest tests/test_pipeline/test_v7_extract_stage2.py tests/test_pipeline/test_v7_extract_invariants.py tests/test_pipeline/test_v7_extract_completeness_checker.py`；不需清数据（invariants.py 改动只新增字段，seg/build_summary 改动只新增 TAIL_RESIDUE 状态，老路径不变）
  - **Task 2 rollback**：`git revert <commit_sha> --no-edit`；回归测试 `pytest tests/test_lineage/` 或 `tests/test_services/test_lineage*.py`；不清 pending_wiki_commits（数据保留待人工检查）

## Completion evidence

- Forensic dump 结果（实施前必跑）:
  ```
  sqlite3 knowledge/novel-wiki-v2/.index/lineage/state.db "SELECT * FROM pending_wiki_commits;"
  ```
  实际行数、重复 source_id 数量、是否含孤儿 source_id → 记录到这里

- Final commit: （待 Task 1/2 落地）
- Tests: stage2 测试套 + lineage 测试套 + 5 跑实测
- Static checks: `git diff --check` exit 0
- Documentation updated: memory + MEMORY.md + ADR-0015
- Progress ledger updated: yes（`.superpowers/sdd/<date>-<topic>/progress.md`）