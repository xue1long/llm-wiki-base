# plan-audit 第二轮：v0.3 压力测试推演（独立）

## 场景 1: 真实 wiki 在 S1+S3 后 `has_learning_edge` 真的 True 吗？

**推演**：
- partition.py 重写后 has_learning_edge 过滤条件：
  ```python
  relation_type in set(reader_profile.allowed_learning_edge_types)
  AND (not reader_profile.require_target_task_match OR task_for(target) in _TARGET_TASKS)
  AND source in candidate_ids
  AND target in candidate_ids
  AND task_for(source) in _SOURCE_TASKS
  ```
- 真实 `写作技法` 540 concept + 1 synthesis，114 in-candidate supports+required_by 边
- source task = `learn_concept` ∈ `_SOURCE_TASKS` ✓
- target task = `learn_concept` ∉ `_TARGET_TASKS`，但 `require_target_task_match=False` → 跳过 ✓
- **结果**：has_learning_edge 应该 True ✓

**边界**：如果 `写作技法` 的边都跨 candidate（target 不在 541 页内），仍 False。closure_probe 显示 in-can supports=112 + required_by=71 = 183 边 → 应该 True ✓

## 场景 2: `closure_strict_types=("concept|foundation|orientation", "synthesis|application|example")` 长度为 2

**推演**：
- `closure_required_sets = (frozenset({"concept","foundation","orientation"}), frozenset({"synthesis","application","example"}))`
- `closure_parts = (bool(types & req0), bool(types & req1))`
- 写作技法 types = {concept, synthesis} → `(True, True)` ✓
- 旧 3-tuple 期望被覆盖（不再硬编码）

**边界**：如果未来用户写 `closure_strict_types=("")` → frozenset({""}) → types & frozenset({""}) = set() → False。但默认是 3-tuple，default behavior 不变 ✓

## 场景 3: frontmatter 在 baseline 与 dry-run 间被改

**推演**：
- `build_from_wiki` 内部 `scan_wiki_snapshot` 重新扫描，不读 `.llm-wiki/book-series/baselines/*.json`
- baseline.json 是 audit 证据，**不是** gate 输入
- S6 显式断言 CURRENT.json sha 不变

**边界**：S4 写 baseline.json 的 snapshot_sha 与 dry-run 时的 snapshot_sha 不一致 — 是审计层面的差异，不影响 gate 输出

## 场景 4: --book 写作技法 含 CJK

**推演**：
- PowerShell: `python -m src.cli book build-from-wiki --book 写作技法` — PowerShell argv UTF-8 OK
- `_require_id` (cli.py:580) 仅检查非空，不影响 CJK
- `book_id` 透传到 `manifest["book_id"]` 和 `series-manifest.json.books[0].book_id`，JSON 序列化 UTF-8 安全
- `_safe()` (compiler.py:65) 仅用于文件名（`v1__c1.md`），不用于 book_id

**边界**：如果用户 `--book book-a`（历史默认），partition `candidate_id="book-a"` 无 0 页 → decision=cancel → dry-run blocked

## 场景 5: `chapter_exit_evidence` 派生失败（无 synthesis 页）

**推演**：
- `derive_chapter_exit_evidence(snap, "未知名")` → pages in that taxonomy 过滤 → synth=[] → return ()
- `exit_ids=()` → `bool(exit_ids)=False` → `chapter_known=False`
- `closure_status = "closed" if closure_ok else "unknown" if not chapter_known else "incomplete" if any(closure_parts) else "none"`
- closure_ok 包含 chapter_known=False → False → closure_status="unknown" → decision ≠ "proceed"

**边界**：用户选一个没有 synthesis 页的 taxonomy → gate 阻断。这与"无 retained candidate"行为一致 ✓

## 场景 6: cross-link dangling 在 dry-run 才发现

**推演**：
- S5 在 compile_book 后、publish_book 前调用 validate_cross_links
- 失败：return `{"status": "blocked", "reason_codes": ["E_DANGLING_CROSS_LINKS"], "cross_link_diagnostics": ...}`
- 不调用 publish_book(apply=True)，CURRENT.json sha 不变

**边界**：如果 outline 没设 cross_link_candidates（默认），validate_cross_links 返回 ok=True，dry-run 继续 planned

## 场景 7: cross-candidate 关系导致决策变 merge 而非 proceed

**推演**：
- decision 逻辑：`"proceed" if not reasons else "merge" if cross_candidate else "reference" if candidate_pages else "cancel"`
- "reasons" 包含 NO_LEARNING_CLOSURE/CHAPTER_EXIT_UNKNOWN/...
- 写作技法有 183 in-candidate 边 + cross-candidate 边（指向 unassigned 等）
- `cross_candidate = any(target not in candidate_ids and target in page_ids ...)`
- 写作技法页可能引用 unassigned 页 → cross_candidate=True → decision="merge"
- **这会让 S0 acceptance 测试失败**！

**修复**：S3 中 derive_chapter_exit_evidence 应排除 cross-candidate 干扰；或 partition.py 把 cross_candidate 决策改为仅当 closure_ok=True 时才考虑

实际上 partition.py line 194 是 `decision = "proceed" if not reasons else "merge" if cross_candidate else "reference" if candidate_pages else "cancel"`。
"not reasons" 是 closure_ok=True AND no reasons。
当 closure_ok=True 且 reasons 空时，decision=proceed。
但 cross_candidate 仅在 not proceed 时判断。
所以 closure_ok=True → proceed 优先于 cross_candidate ✓

## 场景 8: 既有 17 个 relations_safety 测试不受影响

**推演**：
- relations_safety 测试用 `dependency_report()` 和 `validate_series_manifest()`，不直接调 `evaluate_series_gate`
- closure_strict_types 字段 default = 旧硬编码值（pipe-separated 字符串），partition 重写后的 closure_parts 与旧硬编码计算结果等价
- 既有 baseline 测试如 `test_strict_positive_closure_needs_six_tasks_and_exit_evidence` 用 default profile → closure_strict_types=("concept|foundation|orientation", "entity|method|explanation", "synthesis|application|example")，frozenset 拆分后与旧代码布尔表达式等价

**风险**：`test_required_by_forward_edge_closes_at_six_reader_tasks_not_five` 用 default profile，has_learning_edge 应仍 True（forward edge is supports→apply，task apply ∈ _TARGET_TASKS，require_target_task_match=True 不跳过）

## 场景 9: 9 个先前失败的 e2e 测试不受影响

**推演**：
- e2e 测试用 `_project` helper，frontmatter 无 primary_taxonomy → all pages unassigned
- gate `_candidate_pages` 返回 unassigned 桶（candidate_pages 非空）
- NOVEL_WIKI_PROFILE 不启用（series_id != "writing-craft"）
- S3 改动仅在 series_id in NOVEL_WIKI_PROFILE.candidate_taxonomies 时启用 → 既有 e2e 测试不受影响 ✓

## 场景 10: 完整 dry-run 链路 7 步成功概率

**推演步骤**：
1. `scan_wiki_snapshot` → 1747 页成功（已验证）
2. `evaluate_series_gate` 用 NOVEL_WIKI_PROFILE → 写作技法 closure_ok=True（依赖 S1+S2+S3 wiring）
3. `validate_series_manifest` → 单 candidate ready（series 不在 S3 wiring 内）
4. `compile_book` → version_dir 生成（既有逻辑，未动）
5. `validate_cross_links` → ok=True（outline 无 cross_link_candidates 默认）
6. `quality_gate` → rule 模式过
7. `publish_book(apply=False)` → return planned

**关键失败点**：第 2 步。若 S3 wiring 不正确，gate 阻断。

## 总结

v0.3 在 v0.2 基础上补齐：
- S0 acceptance 契约（先写失败测试，验证接受标准）
- S0b 真实 wiki 边数据前置断言
- S2 profiles.py + derive_chapter_exit_evidence
- S3 compiler.py wiring（关键）
- S5 cross-link validate 在 dry-run 路径
- 路径用 .llm-wiki/ gitignored
- book_id CJK round-trip 显式考虑

**第二轮审查通过**：v0.3 可进入人工复核。
