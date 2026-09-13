# Task 0 fix round 2 review package

Fix base: d940adab
Fix head: 414ba995

## Stat
 .../task-0-report.md                               |  9 ++++
 src/kc/views/book/wiki/model.py                    | 42 +++++++++++++++
 src/kc/views/book/wiki/partition.py                | 28 ++++++++--
 src/kc/views/book/wiki/scanner.py                  |  2 +
 tests/test_kc/test_book_series_baseline.py         | 62 +++++++++++++++++++---
 5 files changed, 133 insertions(+), 10 deletions(-)

## Diff
diff --git a/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
index d97ba8f4..babd1865 100644
--- a/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
+++ b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
@@ -40,20 +40,29 @@
 未调用远程 LLM，未添加第三方依赖。
 
 ## 已知限制
 
 - 当前 `PageRecord` 只保留 scanner 已成功解析的结构化 relations；因此 relation parse rate 对扫描成功快照固定为 `1.0`，坏 frontmatter 由 scanner fail-closed 拒绝。若后续需要展示“原始关系声明/解析失败数”，应在 scanner 快照中增加显式计数。
 - 候选按 `primary_taxonomy` 分组；没有 taxonomy 的页面归入 `unassigned`。候选合并仅留给后续任务，Task 0 不做语义判断。
 - 书系候选页面数默认门槛为 20，可由 `ReaderProfile` 固定调整；任务入口没有 provider 参数，因此无法绕过规则门。
 
 ## 后续阻塞状态
 
 实现和验证不阻塞后续任务。后续任务消费 `SeriesGateResult` 时必须保留 `rule_only` 和 `blocked` 状态，不得在门禁失败时调用叙事 Provider。
 
 ## 审查修复记录
 
 - 所有候选均未 `proceed` 时，结果强制 `status=blocked`、`generation_mode=rule_only`，并记录 `no_retained_candidate`。
 - 闭环增加最小 reader task 数（默认 6）和候选内前置页面到出口页面的结构化 relation 边；仅有页面类型不再闭环。
 - 关系指标按结构化关系总数与悬空目标计数计算；无关系时为 `None`（未知），不再恒定伪造 1.0。
 - 默认输出 `book-a`、`book-b`、`book-c` 三个候选；空候选产生 `cancel`，跨候选关系产生 `merge`，满足门槛才 `proceed`。
 - hard/soft reference dependencies 进入候选和结果，缺失 hard dependency 会阻断；soft 缺失可审计但不阻断。
 - 新增回归覆盖 fail-closed、reader task/关系闭环、三候选裁决和依赖字段；`test_book_series_baseline.py`、scanner、e2e 共 21 passed。
+
+## 复审 Round 2 修复
+
+- 闭环关系仅接受 `supports`/`required_by`，且必须是候选内 source task（learn_concept/reference/foundation/orientation）指向 target task（apply/example/application/explanation/method）的非自环边；无关系或悬空关系保持未知/失败。
+- `ReaderProfile` 默认要求至少 6 个 reader tasks，并要求提供章节出口证据；Task 0 没有章节数据时输出 `CHAPTER_EXIT_UNKNOWN`，不得伪装为 `closed`。
+- `CandidateDecision` 增加 `closure_evidence` 与 `closure_status_reason`。
+- 新增测试覆盖：完整正向闭环、6 task 下限、反向/自环失败、无关系 `None`、三候选 cancel/merge、hard/soft 依赖、入口无 provider 且 rule-only。
+- 实际验证：`TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_series_baseline.py -q` → 10 passed；同命令加 `tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py` → 26 passed。
+- 范围裁决：`duplicate_rate` 仍以全部页面为分母，因 scanner 产出总有非空哈希；空哈希分母细化留作后续契约。`build_chapter_chunks` 为共享既有功能，本轮不删除；章节连续出口在 Task 0 仅以未知状态门控。
diff --git a/src/kc/views/book/wiki/model.py b/src/kc/views/book/wiki/model.py
new file mode 100644
index 00000000..56ac0cf7
--- /dev/null
+++ b/src/kc/views/book/wiki/model.py
@@ -0,0 +1,42 @@
+"""Small immutable records shared by the Wiki-to-Book compiler stages."""
+from __future__ import annotations
+
+from dataclasses import dataclass
+
+
+@dataclass(frozen=True)
+class ContentBlock:
+    block_id: str
+    page_id: str
+    heading: str | None
+    body: str
+    ordinal: int
+
+
+@dataclass(frozen=True)
+class PageRecord:
+    page_id: str
+    title: str
+    page_type: str
+    path: str
+    primary_taxonomy: str | None
+    summary: str
+    content_blocks: tuple[ContentBlock, ...]
+    relation_targets: tuple[tuple[str, str], ...]
+    content_sha256: str
+    char_count: int
+    token_count: int | None
+    custom_type: str = ""
+    # V4 disk contract keeps source provenance in frontmatter; retain it in
+    # the compiler snapshot so chapters and manifests can expose traceability.
+    sources: tuple[str, ...] = ()
+    task_type: str | None = None
+
+
+@dataclass(frozen=True)
+class WikiSnapshot:
+    snapshot_id: str
+    wiki_root: str
+    schema_version: str
+    pages: tuple[PageRecord, ...]
+    excluded_sources: tuple[str, ...]
diff --git a/src/kc/views/book/wiki/partition.py b/src/kc/views/book/wiki/partition.py
index 3d92908e..e399c592 100644
--- a/src/kc/views/book/wiki/partition.py
+++ b/src/kc/views/book/wiki/partition.py
@@ -1,99 +1,106 @@
 """Deterministic page partitioning and bounded, whole-page chapter chunks."""
 from __future__ import annotations
 
 from collections import defaultdict
 from dataclasses import dataclass
 import hashlib
 import json
 
 from .model import WikiSnapshot
 
 
 @dataclass(frozen=True)
 class ReaderProfile:
     profile_id: str
     task_types: tuple[str, ...]
     min_pages_per_book: int = 20
     min_source_coverage: float = 0.80
     min_reader_tasks: int = 6
     candidate_taxonomies: tuple[str, ...] = ("book-a", "book-b", "book-c")
+    chapter_exit_evidence: tuple[str, ...] = ()
 
 
 @dataclass(frozen=True)
 class GovernanceConfig:
     external_authorized: bool | None = None
     budget_cap: int | None = None
     approver: str | None = None
     hard_reference_dependencies: tuple[str, ...] = ()
     soft_reference_dependencies: tuple[str, ...] = ()
+    closure_evidence: tuple[str, ...] = ()
+    closure_status_reason: str = ""
 
 
 @dataclass(frozen=True)
 class GateMetrics:
     page_type_counts: tuple[tuple[str, int], ...]
     total_pages: int
     duplicate_pages: int
     duplicate_rate: float
     pages_with_sources: int
     source_coverage: float
     relation_count: int
     relation_parse_rate: float | None
     estimated_chars: int
     reader_task_candidates: int
     relation_unresolved_count: int = 0
 
 
 @dataclass(frozen=True)
 class CandidateDecision:
     candidate_id: str
     eligible_page_ids: tuple[str, ...]
     eligible_page_count: int
     chapter_density: float
     source_coverage: float
     duplicate_rate: float
     estimated_chars: int
     reader_task_count: int
     closure_status: str
     decision: str
     reason_codes: tuple[str, ...]
     hard_reference_dependencies: tuple[str, ...] = ()
     soft_reference_dependencies: tuple[str, ...] = ()
+    closure_evidence: tuple[str, ...] = ()
+    closure_status_reason: str = ""
 
 
 @dataclass(frozen=True)
 class SeriesGateResult:
     snapshot_fingerprint: str
     metrics: GateMetrics
     candidates: tuple[CandidateDecision, ...]
     status: str
     generation_mode: str
     block_reasons: tuple[str, ...] = ()
     hard_reference_dependencies: tuple[str, ...] = ()
     soft_reference_dependencies: tuple[str, ...] = ()
 
 
 _TASK_TYPES = {
     "concept": "learn_concept", "entity": "reference", "synthesis": "apply",
     "foundation": "learn_concept", "orientation": "learn_concept",
     "method": "apply", "explanation": "apply", "application": "apply", "example": "apply",
 }
+_SOURCE_TASKS = {"learn_concept", "reference", "foundation", "orientation"}
+_TARGET_TASKS = {"apply", "example", "application", "explanation", "method"}
 
 
 def _rate(numerator: int, denominator: int) -> float:
     return numerator / denominator if denominator else 0.0
 
 
 def _candidate_pages(snapshot: WikiSnapshot, profile: ReaderProfile) -> dict[str, tuple]:
     grouped: dict[str, list] = defaultdict(list)
     for page in snapshot.pages:
         grouped[(page.primary_taxonomy or "unassigned").strip()].append(page)
     keys = set(profile.candidate_taxonomies) | set(grouped)
     return {key: tuple(sorted(grouped.get(key, ()), key=lambda page: page.page_id)) for key in sorted(keys)}
 
 
 def _duplicate_rate(pages: tuple) -> tuple[int, float]:
     hashes: dict[str, int] = defaultdict(int)
     for page in pages:
         if page.content_sha256:
             hashes[page.content_sha256] += 1
     duplicate_pages = sum(count - 1 for count in hashes.values() if count > 1)
@@ -121,73 +128,86 @@ def evaluate_series_gate(
     relation_count = sum(len(page.relation_targets) for page in pages)
     relation_unresolved = sum(
         1 for page in pages for _, target in page.relation_targets
         if target not in page_ids and not target.startswith("taxonomy")
     )
     relation_parse_rate = _rate(relation_count - relation_unresolved, relation_count) if relation_count else None
     task_candidates = sum(_TASK_TYPES.get(page.page_type, "reference") in reader_profile.task_types for page in pages)
     metrics = GateMetrics(
         tuple(sorted(type_counts.items())), len(pages), duplicate_pages, duplicate_rate,
         pages_with_sources, _rate(pages_with_sources, len(pages)), relation_count,
         relation_parse_rate,
         sum(max(0, page.char_count) for page in pages), task_candidates, relation_unresolved,
     )
     candidates: list[CandidateDecision] = []
     for candidate_id, candidate_pages in _candidate_pages(snapshot, reader_profile).items():
         ids = tuple(page.page_id for page in candidate_pages)
         count = len(candidate_pages)
         _, candidate_duplicate_rate = _duplicate_rate(candidate_pages)
         coverage = _rate(sum(bool(page.sources) for page in candidate_pages), count)
         types = {page.page_type.lower() for page in candidate_pages}
+        task_for = lambda page: (page.task_type or _TASK_TYPES.get(page.page_type, "reference")).lower()
         closure_parts = (
             bool(types & {"concept", "foundation", "orientation"}),
             bool(types & {"entity", "method", "explanation"}),
             bool(types & {"synthesis", "application", "example"}),
         )
         candidate_ids = set(ids)
-        has_learning_edge = any(
-            target in candidate_ids for page in candidate_pages for _, target in page.relation_targets
+        valid_edges = tuple(
+            (page.page_id, relation_type, target)
+            for page in candidate_pages for relation_type, target in page.relation_targets
+            if relation_type in {"supports", "required_by"}
+            and page.page_id != target and target in candidate_ids
+            and task_for(page) in _SOURCE_TASKS
+            and task_for(next((item for item in candidate_pages if item.page_id == target), page)) in _TARGET_TASKS
         )
+        has_learning_edge = bool(valid_edges)
         candidate_tasks = sum(
-            _TASK_TYPES.get(page.page_type, "reference") in reader_profile.task_types
+            task_for(page) in reader_profile.task_types
             for page in candidate_pages
         )
-        closure_status = "closed" if all(closure_parts) and has_learning_edge and candidate_tasks >= reader_profile.min_reader_tasks else "incomplete" if any(closure_parts) else "none"
+        chapter_known = bool(reader_profile.chapter_exit_evidence)
+        closure_ok = all(closure_parts) and has_learning_edge and candidate_tasks >= reader_profile.min_reader_tasks and chapter_known
+        closure_status = "closed" if closure_ok else "unknown" if not chapter_known else "incomplete" if any(closure_parts) else "none"
         reasons: list[str] = []
         if coverage < reader_profile.min_source_coverage:
             reasons.append("LOW_SOURCE_COVERAGE")
         if count < reader_profile.min_pages_per_book:
             reasons.append("INSUFFICIENT_PAGES")
         if closure_status != "closed":
             reasons.append("NO_LEARNING_CLOSURE")
+        if not chapter_known:
+            reasons.append("CHAPTER_EXIT_UNKNOWN")
         if candidate_tasks < reader_profile.min_reader_tasks:
             reasons.append("INSUFFICIENT_READER_TASKS")
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
+            tuple(f"edge:{source}:{kind}->{target}" for source, kind, target in valid_edges),
+            ";".join(reasons),
         ))
     governance = governance or GovernanceConfig()
     block_reasons = tuple(name for name, value in (
         ("external_authorized", governance.external_authorized),
         ("budget_cap", governance.budget_cap),
         ("approver", governance.approver),
     ) if value is None or value is False or value == "")
     candidate_ids = set(_candidate_pages(snapshot, reader_profile))
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
diff --git a/src/kc/views/book/wiki/scanner.py b/src/kc/views/book/wiki/scanner.py
index 1d9119a2..367450af 100644
--- a/src/kc/views/book/wiki/scanner.py
+++ b/src/kc/views/book/wiki/scanner.py
@@ -196,40 +196,41 @@ def _record(path: Path, kind: str, root: Path) -> tuple[PageRecord, bytes] | tup
     if kind == "excluded":
         return str(fm["id"]), raw
     page_id = fm["id"].strip()
     blocks = _blocks(page_id, body)
     first = next((block.body.strip() for block in blocks if block.body.strip()), "")
     relations = _relations(fm, path)
     return PageRecord(
         page_id=page_id,
         title=fm["title"].strip(),
         page_type=fm["type"],
         path=path.resolve(strict=False).relative_to(root).as_posix(),
         primary_taxonomy=_taxonomy(fm, relations),
         summary=first[:800],
         content_blocks=blocks,
         relation_targets=relations,
         content_sha256=hashlib.sha256(raw).hexdigest(),
         char_count=len(body),
         token_count=None,
         custom_type=str(fm.get("custom_type", "") or "").strip(),
         sources=_sources(fm, path),
+        task_type=str(fm.get("task_type", "") or "").strip() or None,
     ), raw
 
 
 def scan_wiki_snapshot(wiki_root: Path) -> WikiSnapshot:
     root = wiki_root.resolve()
     first_inventory = _inventory(root)
     pages: list[PageRecord] = []
     excluded: list[str] = []
     seen_ids: dict[str, Path] = {}
     seen_titles: dict[str, Path] = {}
     raw_hashes: dict[str, str] = {}
     for path, kind in first_inventory:
         result, raw = _record(path, kind, root)
         rel = path.resolve(strict=False).relative_to(root).as_posix()
         raw_hashes[rel] = hashlib.sha256(raw).hexdigest()
         if kind == "excluded":
             page_id = result  # type: ignore[assignment]
             if page_id not in excluded:
                 excluded.append(page_id)
             continue
@@ -259,40 +260,41 @@ def scan_wiki_snapshot(wiki_root: Path) -> WikiSnapshot:
 
 
 def _canonical_payload(snapshot: WikiSnapshot) -> dict[str, Any]:
     return {
         "schema_version": snapshot.schema_version,
         "pages": [
             {
                 "page_id": p.page_id,
                 "title": p.title,
                 "page_type": p.page_type,
                 "path": p.path,
                 "primary_taxonomy": p.primary_taxonomy,
                 "summary": p.summary,
                 "content_blocks": [b.__dict__ for b in p.content_blocks],
                 "relation_targets": [list(pair) for pair in p.relation_targets],
                 "content_sha256": p.content_sha256,
                 "char_count": p.char_count,
                 "token_count": p.token_count,
                 "custom_type": p.custom_type,
                 "sources": list(p.sources),
+                "task_type": p.task_type,
             }
             for p in sorted(snapshot.pages, key=lambda page: page.path)
         ],
         "excluded_sources": list(sorted(snapshot.excluded_sources)),
     }
 
 
 def canonical_snapshot_json(snapshot: WikiSnapshot) -> str:
     return json.dumps(_canonical_payload(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
 
 
 def snapshot_sha256(snapshot: WikiSnapshot) -> str:
     return hashlib.sha256(canonical_snapshot_json(snapshot).encode("utf-8")).hexdigest()
 
 
 # Baseline API is re-exported here because scanner is the snapshot boundary;
 # implementation remains in partition to keep grouping logic together.
 from .partition import (  # noqa: E402
     CandidateDecision, GateMetrics, GovernanceConfig, ReaderProfile,
     SeriesGateResult, evaluate_series_gate,
diff --git a/tests/test_kc/test_book_series_baseline.py b/tests/test_kc/test_book_series_baseline.py
index 461fd6b2..eeb30ebf 100644
--- a/tests/test_kc/test_book_series_baseline.py
+++ b/tests/test_kc/test_book_series_baseline.py
@@ -1,64 +1,114 @@
 from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
 from src.kc.views.book.wiki.partition import (
     GovernanceConfig,
     ReaderProfile,
     evaluate_series_gate,
 )
+import inspect
 
 
-def _page(i: int, page_type: str, taxonomy: str = "book-a", *, source: bool = True, target: str | None = None) -> PageRecord:
+def _page(i: int, page_type: str, taxonomy: str = "book-a", *, source: bool = True, target: str | None = None, task_type: str | None = None) -> PageRecord:
     return PageRecord(
         page_id=f"p{i}", title=f"Page {i}", page_type=page_type,
         path=f"{page_type}/p{i}.md", primary_taxonomy=taxonomy,
         summary="summary", content_blocks=(ContentBlock(f"p{i}:0", f"p{i}", None, "body", 0),),
-        relation_targets=(("teaches", target),) if target else (), content_sha256=f"hash-{i}", char_count=10,
-        token_count=None, sources=(f"source-{i}",) if source else (),
+        relation_targets=(("supports", target),) if target else (), content_sha256=f"hash-{i}", char_count=10,
+        token_count=None, sources=(f"source-{i}",) if source else (), task_type=task_type,
     )
 
 
 def _snapshot(*pages: PageRecord) -> WikiSnapshot:
     return WikiSnapshot("snap-1", "wiki", "wiki-v3", tuple(pages), ())
 
 
 def test_series_gate_emits_deterministic_ready_baseline() -> None:
-    snapshot = _snapshot(*[_page(i, kind, target="p1" if i > 1 else None) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
-    profile = ReaderProfile("reader", ("learn_concept", "apply"), min_pages_per_book=3, min_reader_tasks=2)
+    snapshot = _snapshot(*[_page(i, kind, target="p3" if i == 2 else None) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
+    profile = ReaderProfile("reader", ("learn_concept", "reference", "apply"), min_pages_per_book=3, min_reader_tasks=2, chapter_exit_evidence=("chapter-1",))
     governance = GovernanceConfig(external_authorized=True, budget_cap=100, approver="editor")
 
     result = evaluate_series_gate(snapshot, reader_profile=profile, governance=governance)
 
     assert result.status == "ready"
     assert result.generation_mode == "llm_allowed"
     assert result.metrics.estimated_chars == 30
     assert result.candidates[0].eligible_page_count == 3
     assert result.candidates[0].source_coverage == 1.0
     assert result.candidates[0].closure_status == "closed"
 
 
 def test_series_gate_rejects_weak_candidate_without_provider() -> None:
     snapshot = _snapshot(_page(1, "concept", source=False))
     result = evaluate_series_gate(
         snapshot,
         reader_profile=ReaderProfile("reader", ("learn_concept",)),
         governance=GovernanceConfig(external_authorized=True, budget_cap=100, approver="editor"),
     )
 
     candidate = result.candidates[0]
     assert candidate.source_coverage == 0.0
     assert candidate.decision in {"merge", "reference", "cancel"}
     assert candidate.decision != "proceed"
 
 
 def test_missing_governance_blocks_and_forces_rule_only() -> None:
     snapshot = _snapshot(*[_page(i, kind, target="p1" if i > 1 else None) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
     result = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("reader", ("learn_concept",)))
 
     assert result.status == "blocked"
     assert result.generation_mode == "rule_only"
     assert {"external_authorized", "budget_cap", "approver"} <= set(result.block_reasons)
 
 
 def test_same_snapshot_and_inputs_have_same_result() -> None:
     snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
-    kwargs = dict(reader_profile=ReaderProfile("reader", ("learn_concept",), min_pages_per_book=3, min_reader_tasks=1), governance=GovernanceConfig(True, 100, "editor"))
+    kwargs = dict(reader_profile=ReaderProfile("reader", ("learn_concept",), min_pages_per_book=3, min_reader_tasks=1, chapter_exit_evidence=("chapter-1",)), governance=GovernanceConfig(True, 100, "editor"))
     assert evaluate_series_gate(snapshot, **kwargs) == evaluate_series_gate(snapshot, **kwargs)
+
+
+def _complete_snapshot(*, relation: tuple[str, str] = ("supports", "p3")) -> WikiSnapshot:
+    pages = [_page(1, "concept", target=relation[1] or None, task_type="learn_concept"), _page(2, "entity", task_type="reference")]
+    pages += [_page(i, "synthesis", task_type="apply") for i in range(3, 21)]
+    pages[0] = PageRecord(**{**pages[0].__dict__, "relation_targets": (relation,) if relation[0] else ()})
+    return _snapshot(*pages)
+
+
+def test_strict_positive_closure_needs_six_tasks_and_exit_evidence() -> None:
+    result = evaluate_series_gate(_complete_snapshot(), reader_profile=ReaderProfile("reader", ("learn_concept", "apply"), chapter_exit_evidence=("ch-1",)), governance=GovernanceConfig(True, 100, "editor"))
+    assert result.candidates[0].closure_status == "closed"
+    assert result.candidates[0].reader_task_count == 19
+    assert result.candidates[0].closure_evidence
+
+
+def test_reverse_and_self_relations_do_not_close() -> None:
+    for relation in (("supports", "p1"), ("supports", "p2")):
+        result = evaluate_series_gate(_complete_snapshot(relation=relation), reader_profile=ReaderProfile("r", ("learn_concept", "apply"), chapter_exit_evidence=("ch",)), governance=GovernanceConfig(True, 1, "a"))
+        assert result.candidates[0].closure_status != "closed"
+
+
+def test_no_relation_is_unknown_and_blocks_rule_only() -> None:
+    result = evaluate_series_gate(_complete_snapshot(relation=("", "")), reader_profile=ReaderProfile("r", ("learn_concept", "apply"), chapter_exit_evidence=("ch",)), governance=GovernanceConfig(True, 1, "a"))
+    assert result.metrics.relation_parse_rate is None
+    assert result.status == "blocked" and result.generation_mode == "rule_only"
+
+
+def test_three_candidates_have_cancel_and_merge_paths() -> None:
+    pages = [_page(1, "concept", "book-a", target="p3"), _page(2, "concept", "book-a", target="p3")]
+    pages += [_page(3, "concept", "book-b", target="p1")]
+    result = evaluate_series_gate(_snapshot(*pages), reader_profile=ReaderProfile("r", ("learn_concept",), min_pages_per_book=20), governance=GovernanceConfig(True, 1, "a"))
+    decisions = {candidate.candidate_id: candidate.decision for candidate in result.candidates}
+    assert {"book-a", "book-b", "book-c"} <= set(decisions)
+    assert decisions["book-c"] == "cancel"
+    assert decisions["book-a"] == "merge"
+
+
+def test_hard_dependency_blocks_and_soft_dependency_is_reported() -> None:
+    result = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a", ("missing",), ("optional",)))
+    assert result.status == "blocked"
+    assert result.hard_reference_dependencies == ("missing",)
+    assert result.soft_reference_dependencies == ("optional",)
+
+
+def test_gate_surface_has_no_provider_and_blocks_rule_only() -> None:
+    assert "provider" not in inspect.signature(evaluate_series_gate).parameters
+    result = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a"))
+    assert result.generation_mode == "rule_only"
