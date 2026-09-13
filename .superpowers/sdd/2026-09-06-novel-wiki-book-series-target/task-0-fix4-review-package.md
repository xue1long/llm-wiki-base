# Task 0 fix round 4 review package

Fix base: 981c90ad
Fix head: 5cd19a4e

## Stat
 .../task-0-report.md                               | 28 +++++++++++
 src/kc/views/book/wiki/partition.py                |  2 +-
 tests/test_kc/test_book_series_baseline.py         | 57 +++++++++++++++++++---
 3 files changed, 80 insertions(+), 7 deletions(-)

## Diff
diff --git a/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
index a73469e8..ec116369 100644
--- a/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
+++ b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
@@ -58,20 +58,48 @@
 - hard/soft reference dependencies 进入候选和结果，缺失 hard dependency 会阻断；soft 缺失可审计但不阻断。
 - 新增回归覆盖 fail-closed、reader task/关系闭环、三候选裁决和依赖字段；`test_book_series_baseline.py`、scanner、e2e 共 21 passed。
 
 ## 复审 Round 2 修复
 
 - 闭环关系仅接受 `supports`/`required_by`，且必须是候选内 source task（learn_concept/reference/foundation/orientation）指向 target task（apply/example/application/explanation/method）的非自环边；无关系或悬空关系保持未知/失败。
 - `ReaderProfile` 默认要求至少 6 个 reader tasks，并要求提供章节出口证据；Task 0 没有章节数据时输出 `CHAPTER_EXIT_UNKNOWN`，不得伪装为 `closed`。
 - `CandidateDecision` 增加 `closure_evidence` 与 `closure_status_reason`。
 - 新增测试覆盖：完整正向闭环、6 task 下限、反向/自环失败、无关系 `None`、三候选 cancel/merge、hard/soft 依赖、入口无 provider 且 rule-only。
 - 实际验证：`TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_series_baseline.py -q` → 10 passed；同命令加 `tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py` → 26 passed。
 - 范围裁决：`duplicate_rate` 仍以全部页面为分母，因 scanner 产出总有非空哈希；空哈希分母细化留作后续契约。`build_chapter_chunks` 为共享既有功能，本轮不删除；章节连续出口在 Task 0 仅以未知状态门控。
 
 ## 复审 Round 3 修复
 
 - `min_reader_tasks` 入口统一钳制为至少 6，调用方传入 1/2 不能绕过，并通过 `INSUFFICIENT_READER_TASKS` 留痕。
 - 章节出口证据现在必须是候选内真实 page ID，且页面 task type 属于 target task；无效 token 保持未知/不闭环。
 - taxonomy namespace 仅接受 `taxonomy/` 与 `taxonomy-` 前缀。
 - duplicate rate 分母固定为有有效 `content_sha256` 的页面数，`duplicate_denominator` 写入全局与候选结果；补充空 hash 测试。
 - 新增 required_by 正向边、5/6 task 下限、无效出口、taxonomyfoo、空 hash 边界测试。
 - 实际验证：`TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_series_baseline.py tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q` → 29 passed。
+
+## 复审 Round 4 修复
+
+- 测试现在真实包含 `taxonomyfoo`，并断言单条该目标关系产生 `relation_unresolved_count=1`、`relation_parse_rate=0.0`。
+- reader task 边界夹具分别真实产生 5 和 6 个候选任务，并直接断言 `reader_task_count`；5 个任务得到 `INSUFFICIENT_READER_TASKS`/`incomplete`，6 个任务保留 `required_by` 前置页→出口页正向边并得到 `closed`/`proceed`。
+- hard dependency 仅由非空候选满足。默认空 `book-c` 现在写入候选结果的 `hard_reference_dependencies=("book-c",)` 并增加同名 block reason；加入一个 `book-c` 页面后该缺失字段清空。soft dependency 行为未改。
+- RED 命令：
+
+```powershell
+$tmpPath = (Resolve-Path -LiteralPath '.tmp-pytest').Path
+$env:TEMP = $tmpPath
+$env:TMP = $tmpPath
+$env:TMPDIR = $tmpPath
+$env:PYTHONPATH = '.'
+& 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_kc/test_book_series_baseline.py -q
+```
+
+  结果：1 failed, 13 passed；失败点为默认空 `book-c` 未产生 `hard_reference_dependencies` block reason，符合预期。
+- GREEN 定向命令同上，结果：14 passed in 0.44s。
+- scanner/e2e 回归命令：
+
+```powershell
+& 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_kc/test_book_series_baseline.py tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q
+```
+
+  结果：31 passed in 1.48s。
+- 产品入口仍无 provider 参数；本轮实现与测试没有远程 LLM 调用，也未增加第三方依赖或删除旧功能。
+- `graphify update .` 无法运行：已安装 launcher 指向不存在的 Python 3.12，改用 bundled Python 执行时缺少 `graphify` 模块；未修改 graphify 输出。
diff --git a/src/kc/views/book/wiki/partition.py b/src/kc/views/book/wiki/partition.py
index 10dc626a..1a9006b3 100644
--- a/src/kc/views/book/wiki/partition.py
+++ b/src/kc/views/book/wiki/partition.py
@@ -190,41 +190,41 @@ def evaluate_series_gate(
         cross_candidate = any(
             target not in candidate_ids and target in page_ids
             for page in candidate_pages for _, target in page.relation_targets
         )
         decision = "proceed" if not reasons else "merge" if cross_candidate else "reference" if candidate_pages else "cancel"
         candidates.append(CandidateDecision(
             candidate_id, ids, count, _rate(count, len({page.page_type for page in candidate_pages})),
             coverage, candidate_duplicate_rate, sum(max(0, page.char_count) for page in candidate_pages),
             candidate_tasks, closure_status, decision, tuple(reasons),
             (), (),
             tuple(f"edge:{source}:{kind}->{target}" for source, kind, target in valid_edges),
             ";".join(reasons),
             candidate_duplicate_denominator,
         ))
     governance = governance or GovernanceConfig()
     block_reasons = tuple(name for name, value in (
         ("external_authorized", governance.external_authorized),
         ("budget_cap", governance.budget_cap),
         ("approver", governance.approver),
     ) if value is None or value is False or value == "")
-    candidate_ids = set(_candidate_pages(snapshot, reader_profile))
+    candidate_ids = {candidate_id for candidate_id, candidate_pages in _candidate_pages(snapshot, reader_profile).items() if candidate_pages}
     missing_hard = tuple(sorted(set(governance.hard_reference_dependencies) - candidate_ids))
     if missing_hard:
         block_reasons += ("hard_reference_dependencies",)
     soft_missing = tuple(sorted(set(governance.soft_reference_dependencies) - candidate_ids))
     fingerprint_payload = {
         "snapshot": snapshot.snapshot_id,
         "profile": reader_profile.__dict__,
         "governance": governance.__dict__,
     }
     fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
     blocked = bool(block_reasons) or not candidates or not any(candidate.decision == "proceed" for candidate in candidates)
     if not candidates or not any(candidate.decision == "proceed" for candidate in candidates):
         block_reasons += ("no_retained_candidate",)
     candidates = [CandidateDecision(
         **{**candidate.__dict__,
            "hard_reference_dependencies": missing_hard,
            "soft_reference_dependencies": soft_missing}
     ) for candidate in candidates]
     return SeriesGateResult(
         fingerprint, metrics, tuple(candidates), "blocked" if blocked else "ready",
diff --git a/tests/test_kc/test_book_series_baseline.py b/tests/test_kc/test_book_series_baseline.py
index 5992a5a8..246547fd 100644
--- a/tests/test_kc/test_book_series_baseline.py
+++ b/tests/test_kc/test_book_series_baseline.py
@@ -55,77 +55,122 @@ def test_missing_governance_blocks_and_forces_rule_only() -> None:
     result = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("reader", ("learn_concept",)))
 
     assert result.status == "blocked"
     assert result.generation_mode == "rule_only"
     assert {"external_authorized", "budget_cap", "approver"} <= set(result.block_reasons)
 
 
 def test_same_snapshot_and_inputs_have_same_result() -> None:
     snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
     kwargs = dict(reader_profile=ReaderProfile("reader", ("learn_concept",), min_pages_per_book=3, min_reader_tasks=1, chapter_exit_evidence=("p3",)), governance=GovernanceConfig(True, 100, "editor"))
     assert evaluate_series_gate(snapshot, **kwargs) == evaluate_series_gate(snapshot, **kwargs)
 
 
 def _complete_snapshot(*, relation: tuple[str, str] = ("supports", "p3")) -> WikiSnapshot:
     pages = [_page(1, "concept", target=relation[1] or None, task_type="learn_concept"), _page(2, "entity", task_type="reference")]
     pages += [_page(i, "synthesis", task_type="apply") for i in range(3, 21)]
     pages[0] = PageRecord(**{**pages[0].__dict__, "relation_targets": (relation,) if relation[0] else ()})
     return _snapshot(*pages)
 
 
+def _reader_task_boundary_snapshot(reader_task_count: int) -> WikiSnapshot:
+    pages = list(_complete_snapshot(relation=("required_by", "p3")).pages)
+    counted_ids = {"p1", "p3", *(f"p{i}" for i in range(4, reader_task_count + 2))}
+    task_types = {"p1": "learn_concept", "p3": "apply"}
+    return _snapshot(*[
+        PageRecord(**{**page.__dict__, "task_type": task_types.get(page.page_id, "learn_concept" if page.page_id in counted_ids else "excluded")})
+        for page in pages
+    ])
+
+
 def test_strict_positive_closure_needs_six_tasks_and_exit_evidence() -> None:
     result = evaluate_series_gate(_complete_snapshot(), reader_profile=ReaderProfile("reader", ("learn_concept", "apply"), chapter_exit_evidence=("p3",)), governance=GovernanceConfig(True, 100, "editor"))
     assert result.candidates[0].closure_status == "closed"
     assert result.candidates[0].reader_task_count == 19
     assert result.candidates[0].closure_evidence
 
 
 def test_reverse_and_self_relations_do_not_close() -> None:
     for relation in (("supports", "p1"), ("supports", "p2")):
         result = evaluate_series_gate(_complete_snapshot(relation=relation), reader_profile=ReaderProfile("r", ("learn_concept", "apply"), chapter_exit_evidence=("ch",)), governance=GovernanceConfig(True, 1, "a"))
         assert result.candidates[0].closure_status != "closed"
 
 
 def test_no_relation_is_unknown_and_blocks_rule_only() -> None:
     result = evaluate_series_gate(_complete_snapshot(relation=("", "")), reader_profile=ReaderProfile("r", ("learn_concept", "apply"), chapter_exit_evidence=("ch",)), governance=GovernanceConfig(True, 1, "a"))
     assert result.metrics.relation_parse_rate is None
     assert result.status == "blocked" and result.generation_mode == "rule_only"
 
 
 def test_three_candidates_have_cancel_and_merge_paths() -> None:
     pages = [_page(1, "concept", "book-a", target="p3"), _page(2, "concept", "book-a", target="p3")]
     pages += [_page(3, "concept", "book-b", target="p1")]
     result = evaluate_series_gate(_snapshot(*pages), reader_profile=ReaderProfile("r", ("learn_concept",), min_pages_per_book=20), governance=GovernanceConfig(True, 1, "a"))
     decisions = {candidate.candidate_id: candidate.decision for candidate in result.candidates}
     assert {"book-a", "book-b", "book-c"} <= set(decisions)
     assert decisions["book-c"] == "cancel"
     assert decisions["book-a"] == "merge"
 
 
 def test_hard_dependency_blocks_and_soft_dependency_is_reported() -> None:
     result = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a", ("missing",), ("optional",)))
     assert result.status == "blocked"
     assert result.hard_reference_dependencies == ("missing",)
     assert result.soft_reference_dependencies == ("optional",)
 
 
-def test_required_by_is_valid_forward_edge_and_five_tasks_fail() -> None:
-    snapshot = _complete_snapshot(relation=("required_by", "p3"))
-    ok = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("r", ("learn_concept", "reference", "apply"), chapter_exit_evidence=("p3",)), governance=GovernanceConfig(True, 1, "a"))
-    assert ok.candidates[0].closure_status == "closed"
-    low = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("r", ("learn_concept", "reference"), min_reader_tasks=5, chapter_exit_evidence=("p3",)), governance=GovernanceConfig(True, 1, "a"))
-    assert low.candidates[0].decision != "proceed"
+def test_empty_default_candidate_does_not_satisfy_hard_dependency() -> None:
+    profile = ReaderProfile("r", ("learn_concept",))
+    governance = GovernanceConfig(True, 1, "a", hard_reference_dependencies=("book-c",))
+
+    empty = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=profile, governance=governance)
+    filled = evaluate_series_gate(_snapshot(_page(1, "concept"), _page(2, "concept", "book-c")), reader_profile=profile, governance=governance)
+
+    assert next(candidate for candidate in empty.candidates if candidate.candidate_id == "book-c").eligible_page_count == 0
+    assert empty.hard_reference_dependencies == ("book-c",)
+    assert "hard_reference_dependencies" in empty.block_reasons
+    assert all(candidate.hard_reference_dependencies == ("book-c",) for candidate in empty.candidates)
+    assert next(candidate for candidate in filled.candidates if candidate.candidate_id == "book-c").eligible_page_count == 1
+    assert "hard_reference_dependencies" not in filled.block_reasons
+    assert all(candidate.hard_reference_dependencies == () for candidate in filled.candidates)
+
+
+def test_required_by_forward_edge_closes_at_six_reader_tasks_not_five() -> None:
+    profile = ReaderProfile("r", ("learn_concept", "apply"), min_reader_tasks=1, chapter_exit_evidence=("p3",))
+    governance = GovernanceConfig(True, 1, "a")
+
+    five = evaluate_series_gate(_reader_task_boundary_snapshot(5), reader_profile=profile, governance=governance)
+    six = evaluate_series_gate(_reader_task_boundary_snapshot(6), reader_profile=profile, governance=governance)
+
+    assert five.candidates[0].reader_task_count == 5
+    assert five.candidates[0].closure_status == "incomplete"
+    assert "INSUFFICIENT_READER_TASKS" in five.candidates[0].reason_codes
+    assert six.candidates[0].reader_task_count == 6
+    assert six.candidates[0].closure_status == "closed"
+    assert six.candidates[0].decision == "proceed"
+    assert "edge:p1:required_by->p3" in six.candidates[0].closure_evidence
+
+
+def test_taxonomyfoo_is_an_unresolved_relation_target() -> None:
+    page = _page(1, "concept")
+    page = PageRecord(**{**page.__dict__, "relation_targets": (("supports", "taxonomyfoo"),)})
+
+    result = evaluate_series_gate(_snapshot(page), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a"))
+
+    assert result.metrics.relation_count == 1
+    assert result.metrics.relation_unresolved_count == 1
+    assert result.metrics.relation_parse_rate == 0.0
 
 
 def test_invalid_exit_and_empty_hashes_are_auditable() -> None:
     pages = [_page(1, "concept", source=True, target="p3"), _page(2, "entity", source=True), _page(3, "synthesis", source=True)]
     pages[1] = PageRecord(**{**pages[1].__dict__, "content_sha256": ""})
     result = evaluate_series_gate(_snapshot(*pages), reader_profile=ReaderProfile("r", ("learn_concept", "reference", "apply"), chapter_exit_evidence=("missing",)), governance=GovernanceConfig(True, 1, "a"))
     assert result.candidates[0].closure_status != "closed"
     assert result.metrics.duplicate_denominator == 2
     assert result.candidates[0].duplicate_denominator == 2
 
 
 def test_gate_surface_has_no_provider_and_blocks_rule_only() -> None:
     assert "provider" not in inspect.signature(evaluate_series_gate).parameters
     result = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a"))
     assert result.generation_mode == "rule_only"
