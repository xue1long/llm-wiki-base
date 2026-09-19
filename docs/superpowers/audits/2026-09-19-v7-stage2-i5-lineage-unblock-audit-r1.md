# Plan-Audit Round 1 Report — 2026-09-19-v7-stage2-i5-lineage-unblock.md

> 审查范围：`docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md`（status: draft）
> 审查依据：`.agents/skills/plan-audit/references/audit-prompts.md` §1（全面漏洞审计，7 维度）
> 审查身份：**独立第三方审计专家**，抛弃方案正向思路，逆向挖掘。

---

## 致命缺陷（①）

### ①-1: `i5_gap_at_tail` 字段不存在 —— Task 1 实施代码 AttributeError
- **漏洞位置**: `docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md:115` 实施代码 `elif invariants.i4_non_overlapping and invariants.i5_gap_at_tail:`，而 `src/pipeline/v7_extract/invariants.py:31-50` 的 `InvariantReport` 数据类**只有** `i1_nonempty / i2_boundaries_valid / i3_sorted / i4_non_overlapping / i5_complete_accounting` 五个字段；`all_pass` 是计算属性，不暴露位置信息。
- **风险后果**: TDD 红→绿流程跑测试时，`wrap_items_as_segmentation_result` 一旦执行就抛 `AttributeError: 'InvariantReport' object has no attribute 'i5_gap_at_tail'`。**红测试根本无法红在该期望上**，会被 Python 自身直接抛出 AttributeError 退出，编码者会误判"我连测试都写错了"然后分叉到其他方案，浪费一整天。Task 1 的 Acceptance 步骤（"4 个新测试 + 既有 stage2 测试不变 → 全绿"）**根本无法执行**，因为基线代码无法编译通过 status 决策分支。
- **整改建议**: 必须在 Task 1 中显式新增 `i5_gap_at_tail: bool` 字段 —— 这意味着 `src/pipeline/v7_extract/invariants.py` **必须改**，与方案 §Tasks "Files 清单中 invariants.py（**不改**——I5 严格性保留）" 互相矛盾。整改必须二选一：
  1. **保留 I5 严格性 + 加新字段**：在 `InvariantReport` 增加 `i5_gap_at_tail: bool`，`all_pass` 仍仅由五个原字段决定（语义上"未全过"），但 `i5_gap_at_tail` 单独暴露尾部 gap 位置信息。`validate_segmentation_invariants` 中加一行 `i5_gap_at_tail = (sum != source_size) and i4 and (last_item_end == source_size)`（或类似判定）。同时补 invariant 测试。
  2. **改方案**：在 `wrap_items_as_segmentation_result` 内**直接判断 gap 位置**（基于 `canonical_items[-1].end_byte < source_size`），不引入新 invariant 字段；这样 `invariants.py` 真的可以"不改"。但这破坏了边界判断的纯函数契约，把位置判断混进 I/O 包装层。
  **无论哪种**，方案当前文字与代码不一致，必须显式修订 Plan 后才能落地。

### ①-2: Task 2 只修 `_recover_pending` 但 `link_artifact` / `record_book_release` / `_recover_book_releases` 仍有相同 UNIQUE 撞约束风险
- **漏洞位置**: `src/lineage/api.py` 共 4 处 `INSERT INTO artifact_sources(artifact_id, source_id) VALUES (?, ?)`（line 148、198、515、610）。方案 §Task 2 "Files: src/lineage/api.py（修改 `_recover_pending`）" **只改 line 148**。
- **风险后果**: V7 bridge 成功（2 pages）→ `commit_ingest` 调 `record_wiki_commit → link_artifact`（line 610）。如果某次 Stage 5 产生的 `source_ids` tuple 里含重复（例如 Stage 5 的 source attribution 把同一 raw source 算两次，或上游 `_current_source_id` 被加进 tuple 时与已存在的 source_id 重复），`executemany` 第二次 INSERT 撞 `(artifact_id, source_id)` 主键 → `IntegrityError` → `with self._db:` 事务回滚 → `_lineage.record_wiki_commit` 抛错 → `_page_path.relative_to(paths.root).as_posix()` 之后的 `commit_ingest` 路径异常退出。**plan 修了一处但同模式的另三处仍是 P0 风险**。这不是历史脏数据 —— 这是运行态新写入路径的同种 bug。实测场景：novel-wiki-v2 上的 Stage 5 `claim_extractor` 在 ASR 转录稿上跑出重复 evidence 引用 → `record_wiki_commit` 抛同种错误 → commit_ingest 全失败。
- **整改建议**: Task 2 应改为**抽出私有 helper `_safe_insert_artifact_sources(db, artifact_id, source_ids)`** 集中去重 + `INSERT OR IGNORE` + FK 错误隔离，line 148、198、515、610 全部改用 helper。helper 实现需考虑 `PRAGMA foreign_keys=ON`（line 48）下 FK 错误（"FOREIGN KEY constraint failed"）和 UNIQUE 错误是不同异常类，必须分类处理：
  ```python
  def _safe_insert_artifact_sources(db, artifact_id, source_ids):
      seen = set()
      for sid in source_ids:
          if not sid or sid in seen:
              continue
          seen.add(sid)
          try:
              db.execute(
                  "INSERT OR IGNORE INTO artifact_sources(artifact_id, source_id) VALUES (?, ?)",
                  (artifact_id, sid),
                  )
          except sqlite3.IntegrityError as e:
              # FK violation: skip orphan source_ids
              if "FOREIGN KEY" in str(e):
                  continue
              raise
  ```
  并补 4 个调用点的回归测试（每个调用点至少一个 dup-source_ids 用例）。

---

## 重大隐患（②）

### ②-1: Task 2 `INSERT OR IGNORE` 不会静默 FK 约束违反，dirty data 含孤儿 source_id 时仍会失败
- **漏洞位置**: `src/lineage/api.py:65-68` `artifact_sources` 表声明 `source_id TEXT NOT NULL REFERENCES sources(source_id)` + `db.execute("PRAGMA foreign_keys=ON")`（line 48）。方案 Task 2 用 `INSERT OR IGNORE INTO artifact_sources` 替代 `INSERT INTO artifact_sources`，但 `INSERT OR IGNORE` **不**吞 `FOREIGN KEY constraint failed`（只吞 `UNIQUE` / `NOT NULL` / `CHECK` 冲突，部分版本有差异）。SQLite 官方文档明确：OR IGNORE 只跳过"constraint conflict"——FK violation 不在 conflict 子类中。
- **风险后果**: 实测场景 —— kb-20260918145517 留下的脏数据如果 `source_ids` 含**孤儿 source_id**（即 `sources` 表里已 delete / 已被 stale 覆盖的 src），那么 `INSERT OR IGNORE` 仍抛 `sqlite3.IntegrityError: FOREIGN KEY constraint failed`。`try/except` 兜底后虽不阻断其他行，但**这一行的 artifact 等于没插入**，`artifact_sources` 行数变少 → 上层 `health()` 报 orphan_links 增大 → 后续 `book_compiled` 时 `materialize_book_manifest` 检查 lineage 而失败。**plan 治了 UNIQUE 但漏了 FK**，脏数据的另一类表现会让 Task 2 失效。
- **整改建议**: Task 2 的 try/except 必须**先尝试插入**、捕到 IntegrityError 后判别异常类型：
  ```python
  except sqlite3.IntegrityError as e:
      msg = str(e)
      if "UNIQUE constraint" in msg:
          log.warning("dup source_id skipped: %s/%s", page_id, sid)
          continue
      if "FOREIGN KEY constraint" in msg:
          log.warning("orphan source_id skipped: %s/%s", page_id, sid)
          continue
      raise
  ```
  同时 `_recover_pending` 的 `INSERT OR IGNORE` 必须包在 `try/except` 内（不是 `executemany` 的隐式事务）。**额外** —— 方案必须记录："孤儿 source_id 被静默丢弃"，写入 `.index/lineage/recovery_errors.log` 且 plan 验收要包括 orphan-source_id 的回归测试。

### ②-2: Task 2 的 `DELETE FROM pending_wiki_commits WHERE wiki_page_id = ?` 在 `try/except` 块内会污染"失败单条"的语义
- **漏洞位置**: 方案 Task 2 实施代码 line 174：
  ```python
  db.execute("DELETE FROM pending_wiki_commits WHERE wiki_page_id = ?", (page_id,))
  ```
  这行位于 `try` 块内，但紧跟在 `INSERT OR IGNORE INTO artifact_sources` 之后。如果 artifact_sources 的 INSERT 抛 `IntegrityError`（如 ②-1 描述的 FK 失败场景），跳过当前 `page_id`、continue 到下一行 → **但本行的 `DELETE FROM pending_wiki_commits` 没执行** → 脏 `pending_wiki_commits` 行**永远存在**，每次 `LineageStore.open()` 都尝试恢复、每次都失败、每次都写 `recovery_errors.log` → 日志噪声无限增长 + 每次启动都慢。这是单行增长。
- **风险后果**: novel-wiki-v2 5 跑实测后，每跑一次都会写一次脏 pending 恢复记录。下次启动服务或下次跑 ingest 时，都会重新走一遍"无效恢复"。8-12 个月后 `.index/lineage/recovery_errors.log` 会成为噪声炸弹；更糟的是 `pending_wiki_commits` 表永远不空 → `book_pending` 永远不会进入 `book_compiled`（因为 `materialize_book_manifest` 检查 pending_wiki_commits）。
- **整改建议**: 重构为"先查后删"模式 —— 先 SELECT 出所有要恢复的行、再去重、再执行所有 INSERT、对**成功恢复的行**才 DELETE：`pending_wiki_commits` 的 DELETE 必须放在 `try/except` 块**外**，仅对成功完成 INSERT 的 `page_id` 才删。或者更激进：把 INSERT 和 DELETE 一起放进 `with db:` 上下文管理器（用 sqlite3 的 explicit BEGIN/COMMIT）保证原子性。方案 Task 2 实施代码应**重新设计为两阶段**：阶段 1 仅 SELECT + 去重 + 准备数据；阶段 2 仅对**成功**的 page_id DELETE pending_wiki_commits。

### ②-3: Task 1 新增 `TAIL_RESIDUE` 状态破坏 `wrap_items_as_segmentation_result` 的 `build_structural_summary` 隐式约定 —— Stage 3 evidence pack 的 `signal_text` 字典键会变化
- **漏洞位置**: 方案 §Task 1 §Implementation（line 121-127）改 `build_structural_summary` 的 `boundary_confidence` 计算逻辑：`1.0 if segmentation_result.status in (SEGMENTED, SINGLE_EXPECTED, TAIL_RESIDUE) else 0.5`。但 `completeness_checker.py:130-131` 把整个 `structural_summary` dict 序列化为 `signal_text = "\n".join(f"{k}={v}" for k, v in structural_summary.items())` 直接喂给 LLM。
- **风险后果**: 现有测试 `tests/test_pipeline/test_v7_extract_completeness_checker.py:341` 断言 `assert "boundary_confidence=0.9" in pack` —— 这种硬编码字符串断言在 `boundary_confidence` 从 0.5 改 1.0 后**仍然通过**（因为字符串"1.0"仍在 pack 里），但 Stage 3 LLM 实际看到的 prompt 文本变了 —— 之前是 `boundary_confidence=0.5` 加 `status=degraded`，现在是 `boundary_confidence=1.0` 加 `status=tail_residue`。LLM 提示词变化 = Stage 3 行为**实质性变化**，但**测试套**仍然全绿 → **假绿**。这正是 R1-F-2 那种"silently passes but actual semantics shifted"风险的翻版。
- **整改建议**: Task 1 验收必须**新增**端到端断言：`build_structural_summary(seg_with_tail_residue)["boundary_confidence"] == 1.0` **且** `seg_with_tail_residue.status == SegmentationStatus.TAIL_RESIDUE.value`（字符串值）。同时必须在 `tests/test_pipeline/test_v7_extract_completeness_checker.py` 增一个集成测试：传入 `status="tail_residue"` + `boundary_confidence=1.0` 的 `structural_summary`，断言 pack 文本包含 `status=tail_residue` 且 `boundary_confidence=1.0`。**必须确保 prompt 文本层面的回归，不是单元测试层面的回归**。

### ②-4: 方案声称"5 跑实测"验收，但没有给出"Stage 3 LLM 真实行为"的判定 —— LLM 是非确定性的，"5/5 PASS" 是 cherry-pick 风险
- **漏洞位置**: 方案 §Task 3 §预期（line 200-205）说 "5 个文件全部 `succeeded + 有页面`" + "判据 1/2/3/4/5 全 PASS"。但 §预期 没说"判据 1 PASS"的具体定义。`feedback-v7-stage3-asr-prompt-fix-2026-09-19.md:36` 已经记录 "判据 2/3/4/5 全部 PASS，**判据 1 仍然 FAIL**" —— 即修 prompt 后 5 跑里 5/5 都不 stage3_incomplete 这个判据本身**未定义**。
- **风险后果**: 修完 Task 1 + Task 2 后，"判据 1"如何定义？如果"5 个文件全部 `succeeded`（bridge 没失败）" 即 PASS，那即便 Stage 3 仍判 INCOMPLETE、wiki/concepts/ 仍 0 新页，"5/5 PASS" 也是空话。这是定义缺失的隐式验收漏洞。`scripts/run_v7_5x.py:172-187` 实际上 `overall = verif.get("overall")` —— 需要查 `verify_v7_ingest.py` 的判据定义。如果判据 1 等价于"概念页数 > 0"，方案没说；如果等价于"failure_stage not in {stage3_incomplete, ...}"，方案也没说。
- **整改建议**: 方案 §Task 3 §预期必须**明确列出** 5 条判据的**精确布尔表达式**，例如：
  - 判据 1 = `wiki/concepts/` 新增 ≥ 1（结构成功）
  - 判据 2 = `failure_stage in {None, "stage6_disabled"}`（5 阶段完整跑过）
  - 判据 3 = `Stage 3 LLM 评估 status == "complete"`（完整性）
  - 判据 4 = `health.status.healthy == true`（不引入新错误）
  - 判据 5 = `wiki-quality HEALTHY`（页面质量）
  
  且必须显式说明 LLM temperature 默认 0.0 是否在所有 provider 上都是真 0 —— 否则 5 跑实测会有 LLM 抖动的 flaky 风险。

### ②-5: Task 2 `recovery_errors.log` 的路径与 `pending_wiki_commits` 的实际写入位置未对齐
- **漏洞位置**: 方案 §Task 2 思路第 5 条（line 150）："失败的单条 pending 写 `.index/lineage/recovery_errors.log`"。但 `LineageStore.open()` 的 db_path 是 `Path(project_root) / ".index" / "lineage" / "state.db"`（line 44）—— `.index/lineage/` 目录确实存在。问题是：`_recover_pending` 是 `@staticmethod`（line 137），没有 `self._project_root` 引用，但 line 140 接受 `root: Path` 参数，方案代码 line 174 的 `db.execute("DELETE FROM pending_wiki_commits WHERE wiki_page_id = ?", (page_id,))` 后**没有写日志** —— 实施代码只在 `except Exception` 分支 `log.warning(...)` 用标准 logging，**没有写文件**。
- **风险后果**: 实施代码与思路描述不对齐 —— 实施代码用 `log.warning`，**不会**写 `.index/lineage/recovery_errors.log`。生产场景下，log 输出默认进 stdout/journald，但运维排错场景**只读文件系统**时，找不到"哪条 pending 失败了"的痕迹。`log.warning` 在批量失败时会刷屏、淹没关键信息。这是"思路与代码不对齐"的语义漏洞。
- **整改建议**: 实施代码必须在 `except Exception as e:` 分支同时：
  ```python
  log.warning("recover_pending failed for %s: %s", page_id, e)
  recovery_log = root / ".index" / "lineage" / "recovery_errors.log"
  recovery_log.parent.mkdir(parents=True, exist_ok=True)
  with recovery_log.open("a", encoding="utf-8") as f:
      f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} page_id={page_id} err={e}\n")
  ```
  或者把思路改为"`log.warning` 即可"，但必须**显式声明哪个 production 场景下需要文件 log**，统一对齐。

---

## 优化疏漏（③）

### ③-1: Task 1 验收的 "4 个新测试"没列出具体断言点
- **漏洞位置**: 方案 §Task 1 §Test-first（line 105-108）列出 3 条测试而非 4 条（与 §Acceptance "4 个新测试" 不一致），且每条都是 1-2 句话断言描述，没有具体 fixture 形状。
- **风险后果**: 编码者实现时按 3 条做、测全绿，但 §Acceptance 要求 4 条 —— 出现"声称 4 / 实际 3"的不一致，可能逃过人工复核。这是计划层面的工程疏漏。
- **整改建议**: §Task 1 §Test-first 必须列出**所有** 4 条（如果 §Acceptance 要求 4 条），并对每条给出：
  - fixture 输入（ASR 风格源具体内容字符串 / 期望的 items 列表 / 期望的 invariants）
  - 期望断言（`assert status == TAIL_RESIDUE` / `assert boundary_confidence == 1.0` 等）
  - 与既有 `test_v7_extract_segmentation.py:117` (test_wrap_items_creates_canonical_items_with_byte_offsets) 的**关系**（是否取代旧断言 / 旧断言是否仍有效）

### ③-2: Task 1 实施代码未定义 `i4_non_overlapping` 在 `wrap_items_as_segmentation_result` 上下文中的引用方式
- **漏洞位置**: 方案 §Task 1 §Implementation line 115: `elif invariants.i4_non_overlapping and invariants.i5_gap_at_tail:`。在原代码 `wrap_items_as_segmentation_result` 内 `invariants` 是 `InvariantReport` 实例，访问属性方式 `invariants.i4_non_overlapping` 是正确的。但 `i5_gap_at_tail` 字段不存在（见 ①-1）。
- **风险后果**: 即便补了 `i5_gap_at_tail` 字段，方案也没解释"tail gap"的具体定义：是 `items[-1].end_byte < source_size`？还是 `(source_size - items[-1].end_byte) < THRESHOLD`（如小于 1KB）？前者会把"末尾少 10 字节"和"末尾少 100KB"都判为 TAIL_RESIDUE，但前者是真 ASR 烂尾、后者是真分段 bug。
- **整改建议**: 必须在方案中显式定义 `i5_gap_at_tail` 的判定条件，例如：
  ```python
  gap_bytes = source_size - items[-1].end_byte if items else source_size
  i5_gap_at_tail = i4 and gap_bytes > 0 and gap_bytes < 64  # 末尾 64 字节内的小 gap
  ```
  64 是经验值（典型的 ASR 烂尾尾巴 < 50 字节），但**必须经实测定标** —— 方案应说明如何选阈值、是否可在 `quality_settings.json` 配置、阈值变化后回归测试是否覆盖。

### ③-3: Task 2 的 try/except 是 `except Exception as e:` 太宽，可能吞掉 OOM / KeyboardInterrupt 之外的隐蔽 bug
- **漏洞位置**: 方案 §Task 2 实施代码 line 175: `except Exception as e:`。这是宽 except，会捕获 sqlite3.DatabaseError、MemoryError、SystemError 等真正应让进程崩溃的异常。
- **风险后果**: 如果 `.index/lineage/state.db` 所在的文件系统突然损坏（IO error / disk full），单条 INSERT 抛 `sqlite3.OperationalError: database is locked` 或 `disk I/O error`，被宽 except 吞掉 → 静默跳过该条 pending → 但**整批 recovery 已经过了一半**，`db.commit()` 仍执行（commit 可能也失败但被忽略）。结局：`pending_wiki_commits` 表状态混乱、`.index/lineage/recovery_errors.log` 没写（`log.warning` 可能被 logging 屏蔽）。
- **整改建议**: except 应精确到 `except sqlite3.IntegrityError as e:` 和 `except (OSError, ValueError) as e:`（覆盖解析错误）。其他异常必须 raise 重抛 —— 否则会**永久掩盖** lineage store 的隐性崩溃。

### ③-4: 方案没列出 rollback 的具体 git revert 命令 + revert 后的验证命令
- **漏洞位置**: 方案 §Audit §Rollback（line 232-233）只说 "Task 1 commit 可独立 revert；I5 严格性不变，影响面 = boundary_confidence 计算" —— 但没给 `git revert <sha>` 命令、没给 revert 后必跑的回归测试、没给"revert 后是否要清 pending_wiki_commits 重新跑"。
- **风险后果**: 紧急回滚时，执行人不知道 revert 是否要带 `--no-edit`、不知道是否要重新跑 `scripts/verify_v7_ingest.py`、不知道 `.index/lineage/state.db` 是否需要手动清理脏数据。这是 runbook 缺漏。
- **整改建议**: §Audit §Rollback 必须扩为：
  ```bash
  git revert <task1-sha> --no-edit    # I5 严格性恢复
  git revert <task2-sha> --no-edit    # lineage 行为回原状
  # 验证：
  PYTHONPATH=. python -m pytest --import-mode=importlib \
    tests/test_pipeline/test_v7_extract_stage2.py \
    tests/test_lineage/test_wiki_recovery.py
  # 数据回滚（如需）：
  sqlite3 knowledge/novel-wiki-v2/.index/lineage/state.db \
    "DELETE FROM pending_wiki_commits WHERE path IN ('wiki/sources/...')"
  ```

### ③-5: 方案 §Tasks §Task 4 文档同步要求新建 memory，但 `.memory/MEMORY.md` 现有索引项的格式未规定
- **漏洞位置**: 方案 §Task 4 line 215-216：`新增 .memory/feedback-v7-stage2-i5-lineage-fix-2026-09-19.md（新增，过程账本）` + `.memory/MEMORY.md（新增索引项）`。但 `.memory/MEMORY.md` 当前的索引格式、字段命名规则、排序约定都未说明。
- **风险后果**: 编码者按自己的理解写索引，与现有索引风格不一致，未来检索工具 / grep 失效。这是长期可维护性疏漏。
- **整改建议**: §Task 4 必须引用 `.memory/TEMPLATE.md` 并列出本任务的 index entry 模板（entry name / date / 触发条件 / 关联 plan / 状态），确保新条目**严格符合** MEMORY.md 既有索引项的 schema。

### ③-6: 方案未提及对 `extract_pilot.py:649 _wrap_items_as_segmentation_result` 的 re-export 是否需要更新
- **漏洞位置**: 方案 §Task 1 §Files（line 89）只列 `src/pipeline/v7_extract/segmentation.py`，**没**列 `scripts/extract_pilot.py`。`extract_pilot.py:649-663` 是 `wrap_items_as_segmentation_result` 的 re-export（`from src.pipeline.v7_extract.segmentation import wrap_items_as_segmentation_result as _impl`）。`extract_pilot.py:264` 调用 `_wrap_items_as_segmentation_result` 写 `segmentation_result`，再 `scripts/extract_pilot.py:267-269` 调 `_build_structural_summary`。新逻辑改 segmentation.py 后 re-export 自动透明，没问题。
- **风险后果**: 没有真实风险（re-export 自动跟随）。但如果未来 `extract_pilot.py` 的 `_wrap_items_as_segmentation_result` 因任何原因 fork 出不同实现（如 `_build_structural_summary` 的 boundary_confidence 计算），方案未追踪。这是潜在的**未来发散风险**。
- **整改建议**: §Task 1 §Files 应**显式声明**："extract_pilot.py:649-663 re-export 通过 import 透明跟进，无需改动；如未来发现 re-export 与 canonical 行为发散，记录到 finding。" 加 1 行注释即可。

---

## 信息盲区

### B-1: novel-wiki-v2 的 `state.db` 当前真实脏数据形态未列具体值
方案称"含重复 source_id"但没说重复几次、source_id 是哪些、是 `kb-20260918145517-6af489eb` 这一条 pending 还是多条、是否含孤儿 source_id（`sources` 表里已 delete 但 pending 还引用）。修复前必须先做一次 forensic dump，否则 ①-2 / ②-1 列举的修复可能"治了这一类但漏了另一类"。

### B-2: 方案未提供 ASR 风格 fixture 的具体内容
方案 §Task 1 §Test-first 说"ASR 风格源（确定性 splitter 切完后末尾留几十字节）"，但没给出 fixture 文本。这导致：
- 编码者自己写的 fixture 可能**恰好**不含边缘情况（如 ASCII-only ASR / 多 byte 字符 ASR / 全 emoji ASR / 带 BOM 的 ASR）。
- 不同编码者写的 fixture 通过了，但生产 ASR 数据的形态**超出 fixture 覆盖**。
应当把 `.memory/feedback-v7-stage3-asr-prompt-fix-2026-09-19.md` 的 5 个实测文件内容节选 200 字节尾巴作为 fixture，确保覆盖"实际碰到的尾部 gap 形态"。

### B-3: `Linkage` 上下游的页面 ID 体系是否受 TAIL_RESIDUE 影响未排查
方案 Task 1 改 `boundary_confidence` 与 `SegmentationStatus`，但 `topic_descriptor.py:91-95` 用 `boundary_sources / byte_span / length`（**不**依赖 status / boundary_confidence）。`page_adapter.py` 读 `SegmentationResult` —— 需要查 page_adapter.py 是否消费 status 字符串。**方案没有排查所有 SegmentationStatus 消费者**，新增 TAIL_RESIDUE 后可能有遗漏的代码路径（如某个报告生成 / 调试视图）期望 status 是 5 个固定值。

### B-4: LLM provider 在 Stage 3 的 ASR 例外 prompt 与新增 boundary_confidence=1.0 是否**双重鼓励**通过
方案 §非目标（line 25）说"不处理 Stage 3 prompt 改动本身（v1.2 commit `cdb274ed` 保留）"。但 Stage 3 prompt 已经包含 ASR 例外条款（`feedback-v7-stage3-asr-prompt-fix-2026-09-19.md:14-21`），加上 boundary_confidence=1.0 等于"双重放行" —— 任何有 ASR signature 的源都会被两个独立机制开绿灯。这会**削弱单点修复的可观测性**：未来如果 ASR 例外 prompt 误判其他内容，方案不知道边界在哪里。

### B-5: 方案的"非目标"清单少了对 lineage schema 演进路径的承诺
方案 §非目标（line 21-28）说"不删 Stage 1 灰度观察期、Stage 2 改默认路径、Stage 3 删旧代码"。但 Task 2 改了 `_recover_pending` 之后，`pending_wiki_commits` 表的语义（"含重复 source_id 是合法的 pending 状态"）发生了微妙变化 —— 现在接受脏数据。但表的 PRIMARY KEY 仍是 `wiki_page_id`，没有变化。**未来 schema 演进**时（如新增 `recovered_at` 列），是否要记录"曾经被去重恢复的 pending"？方案没规划。

### B-6: Stage 5 的 span-based slot filler 是否依赖 `byte_accounting` 数值
`feedback-v7-stage3-asr-prompt-fix-2026-09-19.md:80` 的 probe 数据 `byte_accounting=0.9995~1.0` —— Task 1 改的是 `boundary_confidence` 的离散值（0.5/1.0），但 `byte_accounting` 这个**浮点字段没改**。Stage 5 的 `fill_slots_v2`（被 G9 报告为依赖 span 注册表的路径）若用 `byte_accounting` 做某种启发式判定（如 `byte_accounting >= 0.999` 视为有效），Task 1 改 status 不影响 byte_accounting 数值本身 —— 但 Stage 5 的代码路径是否消费 `structural_summary.byte_accounting`？方案没排查。

### B-7: `scripts/run_v7_5x.py:39` 默认 project_root 是 `knowledge/novel-wiki-v2`，provider 是 `minimax` —— 用户机器上是否真有 `minimax` provider 配置？
方案 §Task 3 跑 `python -X utf8 scripts/run_v7_5x.py`，但脚本默认 `--provider minimax`。如果用户机器只配了 `ollama` 或 `openai`，跑前要先 `python -m src.cli llm-providers add ...` 加 provider。方案没说明 5 跑前置条件。

---

## 总结

- **致命缺陷**: 2 个
  - ①-1: `i5_gap_at_tail` 字段不存在 + 方案说"不改 invariants.py"互相矛盾 → 代码 AttributeError
  - ①-2: Task 2 只修 1 处但同模式 UNIQUE 风险在 4 处均有 → 仍会 P0 失败
- **重大隐患**: 5 个
  - ②-1: `INSERT OR IGNORE` 不吞 FK 违反 → 孤儿 source_id 场景仍失败
  - ②-2: DELETE pending_wiki_commits 在 try 内 → 永久污染 pending 表
  - ②-3: Stage 3 prompt 文本层面回归缺测试 → 假绿风险
  - ②-4: "5/5 PASS" 判据无精确定义 → cherry-pick / 假验收风险
  - ②-5: 实施代码与思路不对齐：recovery_errors.log 不会真被写入
- **优化疏漏**: 6 个
  - ③-1～③-6（fixture 缺失 / 阈值未定 / except 太宽 / rollback 命令缺失 / memory schema 未规定 / re-export 路径未声明）
- **信息盲区**: 7 个（B-1～B-7，覆盖脏数据形态、ASR fixture、SegmentationStatus 消费者、LLM 双放行、lineage schema 演进、byte_accounting 消费者、5 跑前置条件）
- **建议**: **NEEDS-FIX**

### 为什么不是 PASS

即便忽略所有"重大隐患"与"优化疏漏"，仅 ①-1 与 ①-2 两条致命就足以让方案**无法落地**：

- **①-1** 让 Task 1 实施代码无法编译 / 立即 AttributeError；
- **①-2** 让 Task 2 修复**不能解决**实际线上另一类同模式问题（`link_artifact` 的 executemany 也未加 IGNORE）；按方案执行后，`commit_ingest` 在 V7 bridge 成功路径上仍可能撞同种 UNIQUE。

按 §1 第 7 项"漏洞位置 + 风险后果 + 整改建议"原则，这两条必须先修订方案文字（明确 invariants.py 怎么改、补 line 610 的修复），重新过 Round 1，方可进入 Round 2。