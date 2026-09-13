# Review package

Base: ef0aa752
Head: 267cd6c3

## Stat
 .../task-0-report.md                               |  50 ++++
 docs/reports/2026-09-06-book-series-baseline.md    |   9 +
 src/kc/views/book/wiki/__init__.py                 |   5 +
 src/kc/views/book/wiki/partition.py                | 239 ++++++++++++++++
 src/kc/views/book/wiki/scanner.py                  | 307 +++++++++++++++++++++
 tests/test_kc/test_book_series_baseline.py         |  64 +++++
 6 files changed, 674 insertions(+)

## Diff
diff --git a/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
new file mode 100644
index 00000000..5959d466
--- /dev/null
+++ b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md
@@ -0,0 +1,50 @@
+# Task 0：书系基线与前置数据门报告
+
+状态：VERIFIED（实现、定向测试和相关回归测试通过）。
+
+## 改动文件
+
+- `src/kc/views/book/wiki/partition.py`：新增 `ReaderProfile`、`GovernanceConfig`、基线指标/候选裁决数据结构及纯规则入口 `evaluate_series_gate`。候选按 snapshot taxonomy 稳定分组；统计页类型、重复率、来源覆盖率、关系数/解析率、估算字数和 reader task 候选；页面数、来源覆盖率或最小学习闭环不足时只返回 `proceed` 以外的裁决。
+- `src/kc/views/book/wiki/scanner.py`：从扫描边界导出基线入口，保持 scanner 的 Wiki 快照契约。
+- `src/kc/views/book/wiki/__init__.py`：导出基线公共类型和入口。
+- `tests/test_kc/test_book_series_baseline.py`：覆盖 ready、低覆盖/页面不足、治理缺失 blocked、重复运行一致性。
+
+## 基线示例
+
+输入为 `snapshot_id=snap-1` 的三个页面（concept/entity/synthesis），每页 10 字符且有一个 source，治理配置为授权、预算 100、审批人 `editor`：
+
+```json
+{
+  "total_pages": 3,
+  "source_coverage": 1.0,
+  "duplicate_rate": 0.0,
+  "estimated_chars": 30,
+  "candidate": {
+    "eligible_page_count": 3,
+    "closure_status": "closed",
+    "decision": "reference"
+  },
+  "status": "ready",
+  "generation_mode": "llm_allowed"
+}
+```
+
+该示例因页面数小于默认 20，候选会被降级为 `reference`；系统不会用 Provider 补齐页面。缺少授权、预算上限或审批人时，结果为 `status=blocked`、`generation_mode=rule_only`，并列出缺失字段。
+
+## 测试命令与结果
+
+- `TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_series_baseline.py -q`：通过，4 passed。
+- `TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q`：通过，17 passed。
+- `git diff --check`：通过（仅已有工作树 CRLF 提示）。
+
+未调用远程 LLM，未添加第三方依赖。
+
+## 已知限制
+
+- 当前 `PageRecord` 只保留 scanner 已成功解析的结构化 relations；因此 relation parse rate 对扫描成功快照固定为 `1.0`，坏 frontmatter 由 scanner fail-closed 拒绝。若后续需要展示“原始关系声明/解析失败数”，应在 scanner 快照中增加显式计数。
+- 候选按 `primary_taxonomy` 分组；没有 taxonomy 的页面归入 `unassigned`。候选合并仅留给后续任务，Task 0 不做语义判断。
+- 书系候选页面数默认门槛为 20，可由 `ReaderProfile` 固定调整；任务入口没有 provider 参数，因此无法绕过规则门。
+
+## 后续阻塞状态
+
+实现和验证不阻塞后续任务。后续任务消费 `SeriesGateResult` 时必须保留 `rule_only` 和 `blocked` 状态，不得在门禁失败时调用叙事 Provider。
diff --git a/docs/reports/2026-09-06-book-series-baseline.md b/docs/reports/2026-09-06-book-series-baseline.md
new file mode 100644
index 00000000..312deb05
--- /dev/null
+++ b/docs/reports/2026-09-06-book-series-baseline.md
@@ -0,0 +1,9 @@
+# Book Series Baseline
+
+Task 0 uses `scan_wiki_snapshot` output and deterministic taxonomy partitioning to produce `SeriesGateResult` before any outline or Provider call.
+
+The gate records page type counts, duplicate pages/rate by non-empty `content_sha256`, page-level source coverage, structured relation count and parse rate, estimated characters, reader task candidates, and candidate-local `eligible_page_count`, `source_coverage`, `duplicate_rate`, `estimated_chars`, `reader_task_count`, `closure_status`, and `decision`.
+
+Candidate decisions are rule-only. Any candidate below 20 pages, below 0.80 source coverage, or without concept/entity/synthesis (or their structural aliases) is not `proceed`. Missing external authorization, budget cap, or approver sets `status=blocked` and `generation_mode=rule_only`.
+
+The snapshot fingerprint includes the snapshot ID, reader profile, and governance configuration. The baseline contains no absolute paths or credentials.
diff --git a/src/kc/views/book/wiki/__init__.py b/src/kc/views/book/wiki/__init__.py
index f89b6bee..24128b77 100644
--- a/src/kc/views/book/wiki/__init__.py
+++ b/src/kc/views/book/wiki/__init__.py
@@ -12,39 +12,44 @@ public Task 0 surface so callers can ``from src.kc.views.book.wiki import run_pr
 """
 from .preflight import (
     LockBusyError,
     PreflightReport,
     RunLock,
     ValidationError,
     acquire_run_lock,
     release_run_lock,
     run_preflight,
 )
 from .compiler import BuildArtifact, PublishReport, compile_book, publish_book, resolve_active_version
 from .quality_gate import QualityGateReport, check_quality_gate, evaluate_quality_gate
 from .rubric import EvidenceLocator, RubricSpec, load_rubric, load_rubric_specs
 from .reader_tasks import ReaderTaskReport, ReaderTaskRunner, run_reader_task, run_reader_tasks, task_pass_rate
 from .encyclopedic_outline import EncyclopedicUnavailable, generate_encyclopedic_outline, safe_summary
 from .cross_links import build_cross_link_candidates
 from .theme_outline import (
     ThemeOutlineError, load_theme_outline, plan_theme_outline,
     place_page_summaries, save_theme_outline, validate_theme_outline,
 )
+from .partition import (
+    CandidateDecision, GateMetrics, GovernanceConfig, ReaderProfile,
+    SeriesGateResult, evaluate_series_gate,
+)
 
 __all__ = [
     "LockBusyError",
     "PreflightReport",
     "RunLock",
     "ValidationError",
     "acquire_run_lock",
     "release_run_lock",
     "run_preflight",
     "BuildArtifact",
     "PublishReport",
     "compile_book",
     "publish_book",
     "resolve_active_version",
     "QualityGateReport", "check_quality_gate", "evaluate_quality_gate", "EvidenceLocator", "RubricSpec", "load_rubric", "load_rubric_specs",
     "ReaderTaskReport", "ReaderTaskRunner", "run_reader_task", "run_reader_tasks", "task_pass_rate",
     "EncyclopedicUnavailable", "generate_encyclopedic_outline", "safe_summary", "build_cross_link_candidates",
     "ThemeOutlineError", "load_theme_outline", "plan_theme_outline", "place_page_summaries", "save_theme_outline", "validate_theme_outline",
+    "CandidateDecision", "GateMetrics", "GovernanceConfig", "ReaderProfile", "SeriesGateResult", "evaluate_series_gate",
 ]
diff --git a/src/kc/views/book/wiki/partition.py b/src/kc/views/book/wiki/partition.py
new file mode 100644
index 00000000..2302b248
--- /dev/null
+++ b/src/kc/views/book/wiki/partition.py
@@ -0,0 +1,239 @@
+"""Deterministic page partitioning and bounded, whole-page chapter chunks."""
+from __future__ import annotations
+
+from collections import defaultdict
+from dataclasses import dataclass
+import hashlib
+import json
+
+from .model import WikiSnapshot
+
+
+@dataclass(frozen=True)
+class ReaderProfile:
+    profile_id: str
+    task_types: tuple[str, ...]
+    min_pages_per_book: int = 20
+    min_source_coverage: float = 0.80
+
+
+@dataclass(frozen=True)
+class GovernanceConfig:
+    external_authorized: bool | None = None
+    budget_cap: int | None = None
+    approver: str | None = None
+    hard_reference_dependencies: tuple[str, ...] = ()
+    soft_reference_dependencies: tuple[str, ...] = ()
+
+
+@dataclass(frozen=True)
+class GateMetrics:
+    page_type_counts: tuple[tuple[str, int], ...]
+    total_pages: int
+    duplicate_pages: int
+    duplicate_rate: float
+    pages_with_sources: int
+    source_coverage: float
+    relation_count: int
+    relation_parse_rate: float
+    estimated_chars: int
+    reader_task_candidates: int
+
+
+@dataclass(frozen=True)
+class CandidateDecision:
+    candidate_id: str
+    eligible_page_ids: tuple[str, ...]
+    eligible_page_count: int
+    chapter_density: float
+    source_coverage: float
+    duplicate_rate: float
+    estimated_chars: int
+    reader_task_count: int
+    closure_status: str
+    decision: str
+    reason_codes: tuple[str, ...]
+
+
+@dataclass(frozen=True)
+class SeriesGateResult:
+    snapshot_fingerprint: str
+    metrics: GateMetrics
+    candidates: tuple[CandidateDecision, ...]
+    status: str
+    generation_mode: str
+    block_reasons: tuple[str, ...] = ()
+
+
+_TASK_TYPES = {
+    "concept": "learn_concept", "entity": "reference", "synthesis": "apply",
+    "foundation": "learn_concept", "orientation": "learn_concept",
+    "method": "apply", "explanation": "apply", "application": "apply", "example": "apply",
+}
+
+
+def _rate(numerator: int, denominator: int) -> float:
+    return numerator / denominator if denominator else 0.0
+
+
+def _candidate_pages(snapshot: WikiSnapshot) -> dict[str, tuple]:
+    grouped: dict[str, list] = defaultdict(list)
+    for page in snapshot.pages:
+        grouped[(page.primary_taxonomy or "unassigned").strip()].append(page)
+    return {key: tuple(sorted(pages, key=lambda page: page.page_id)) for key, pages in sorted(grouped.items())}
+
+
+def _duplicate_rate(pages: tuple) -> tuple[int, float]:
+    hashes: dict[str, int] = defaultdict(int)
+    for page in pages:
+        if page.content_sha256:
+            hashes[page.content_sha256] += 1
+    duplicate_pages = sum(count - 1 for count in hashes.values() if count > 1)
+    return duplicate_pages, _rate(duplicate_pages, len(pages))
+
+
+def evaluate_series_gate(
+    snapshot: WikiSnapshot,
+    *,
+    reader_profile: ReaderProfile,
+    governance: GovernanceConfig | None = None,
+) -> SeriesGateResult:
+    """Build a deterministic, rule-only book-series baseline.
+
+    This function intentionally has no provider/callback argument: a result
+    can only authorize later LLM work after all local governance fields exist.
+    """
+    pages = tuple(sorted(snapshot.pages, key=lambda page: page.page_id))
+    type_counts: dict[str, int] = defaultdict(int)
+    for page in pages:
+        type_counts[page.page_type] += 1
+    duplicate_pages, duplicate_rate = _duplicate_rate(pages)
+    pages_with_sources = sum(bool(page.sources) for page in pages)
+    relation_count = sum(len(page.relation_targets) for page in pages)
+    # Scanner only exposes successfully parsed structured relations; malformed
+    # relation frontmatter fails closed during scan, so parsed input is 100%.
+    relation_parse_rate = 1.0 if relation_count else 1.0
+    task_candidates = sum(_TASK_TYPES.get(page.page_type, "reference") in reader_profile.task_types for page in pages)
+    metrics = GateMetrics(
+        tuple(sorted(type_counts.items())), len(pages), duplicate_pages, duplicate_rate,
+        pages_with_sources, _rate(pages_with_sources, len(pages)), relation_count,
+        relation_parse_rate, sum(max(0, page.char_count) for page in pages), task_candidates,
+    )
+    candidates: list[CandidateDecision] = []
+    for candidate_id, candidate_pages in _candidate_pages(snapshot).items():
+        ids = tuple(page.page_id for page in candidate_pages)
+        count = len(candidate_pages)
+        _, candidate_duplicate_rate = _duplicate_rate(candidate_pages)
+        coverage = _rate(sum(bool(page.sources) for page in candidate_pages), count)
+        types = {page.page_type.lower() for page in candidate_pages}
+        closure_parts = (
+            bool(types & {"concept", "foundation", "orientation"}),
+            bool(types & {"entity", "method", "explanation"}),
+            bool(types & {"synthesis", "application", "example"}),
+        )
+        closure_status = "closed" if all(closure_parts) else "incomplete" if any(closure_parts) else "none"
+        reasons: list[str] = []
+        if coverage < reader_profile.min_source_coverage:
+            reasons.append("LOW_SOURCE_COVERAGE")
+        if count < reader_profile.min_pages_per_book:
+            reasons.append("INSUFFICIENT_PAGES")
+        if closure_status != "closed":
+            reasons.append("NO_LEARNING_CLOSURE")
+        decision = "proceed" if not reasons else "reference" if candidate_pages else "cancel"
+        candidates.append(CandidateDecision(
+            candidate_id, ids, count, _rate(count, len({page.page_type for page in candidate_pages})),
+            coverage, candidate_duplicate_rate, sum(max(0, page.char_count) for page in candidate_pages),
+            sum(_TASK_TYPES.get(page.page_type, "reference") in reader_profile.task_types for page in candidate_pages),
+            closure_status, decision, tuple(reasons),
+        ))
+    governance = governance or GovernanceConfig()
+    block_reasons = tuple(name for name, value in (
+        ("external_authorized", governance.external_authorized),
+        ("budget_cap", governance.budget_cap),
+        ("approver", governance.approver),
+    ) if value is None or value is False or value == "")
+    fingerprint_payload = {
+        "snapshot": snapshot.snapshot_id,
+        "profile": reader_profile.__dict__,
+        "governance": governance.__dict__,
+    }
+    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
+    blocked = bool(block_reasons)
+    return SeriesGateResult(
+        fingerprint, metrics, tuple(candidates), "blocked" if blocked else "ready",
+        "rule_only" if blocked else "llm_allowed", block_reasons,
+    )
+
+
+def partition_pages(snapshot: WikiSnapshot) -> dict[str, tuple[str, ...]]:
+    """Group classified pages by type/taxonomy; keep unclassified pages in fallback."""
+    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
+    fallback: list[str] = []
+    pages = {page.page_id: page for page in snapshot.pages}
+    for page in snapshot.pages:
+        taxonomy = (page.primary_taxonomy or "").strip()
+        if taxonomy:
+            groups[(page.page_type, taxonomy)].append(page.page_id)
+        else:
+            fallback.append(page.page_id)
+    result = {
+        f"{page_type}-{taxonomy}": tuple(sorted(ids))
+        for (page_type, taxonomy), ids in sorted(groups.items())
+    }
+    if fallback:
+        result["fallback"] = tuple(sorted(fallback))
+    # Detect malformed caller snapshots early, before any LLM call.
+    if sorted(i for ids in result.values() for i in ids) != sorted(pages):
+        raise ValueError("partition does not cover snapshot page IDs exactly")
+    return result
+
+
+def build_chapter_chunks(
+    snapshot: WikiSnapshot,
+    partitions: dict[str, tuple[str, ...]],
+    *,
+    context_window: int,
+    output_reserve: int,
+) -> dict[str, tuple[str, ...]]:
+    """Pack complete pages in stable order, never splitting a page or content block.
+
+    ``token_count`` is preferred; otherwise ``char_count`` is used as a
+    deliberately conservative estimate so a missing tokenizer cannot cause
+    an over-limit request.
+    """
+    if context_window <= 0 or output_reserve < 0 or output_reserve >= context_window:
+        raise ValueError("context_window must exceed non-negative output_reserve")
+    page_map = {page.page_id: page for page in snapshot.pages}
+    expected = sorted(page_map)
+    actual = sorted(i for ids in partitions.values() for i in ids)
+    if actual != expected or len(actual) != len(set(actual)):
+        raise ValueError("partitions must cover each snapshot page ID exactly once")
+    limit = context_window - output_reserve
+    result: dict[str, tuple[str, ...]] = {}
+    for volume_id in sorted(partitions):
+        current: list[str] = []
+        used = 0
+        ordinal = 0
+        for page_id in sorted(partitions[volume_id]):
+            page = page_map[page_id]
+            cost = max(1, page.token_count if page.token_count is not None else page.char_count)
+            if current and used + cost > limit:
+                result[f"{volume_id}:{ordinal}"] = tuple(current)
+                ordinal += 1
+                current, used = [], 0
+            current.append(page_id)
+            used += cost
+            # An over-limit page is deliberately isolated and rule-only downstream.
+            if used > limit:
+                result[f"{volume_id}:{ordinal}"] = tuple(current)
+                ordinal += 1
+                current, used = [], 0
+        if current:
+            result[f"{volume_id}:{ordinal}"] = tuple(current)
+    return result
+
+
+__all__ = [
+    "partition_pages", "build_chapter_chunks", "ReaderProfile", "GovernanceConfig",
+    "GateMetrics", "CandidateDecision", "SeriesGateResult", "evaluate_series_gate",
+]
diff --git a/src/kc/views/book/wiki/scanner.py b/src/kc/views/book/wiki/scanner.py
new file mode 100644
index 00000000..1d9119a2
--- /dev/null
+++ b/src/kc/views/book/wiki/scanner.py
@@ -0,0 +1,307 @@
+"""Fail-closed, deterministic reader for the Wiki-to-Book input snapshot."""
+from __future__ import annotations
+
+import hashlib
+import json
+import re
+from pathlib import Path
+from typing import Any
+
+import yaml
+
+from .model import ContentBlock, PageRecord, WikiSnapshot
+
+_ELIGIBLE = {"concepts": "concept", "entities": "entity", "synthesis": "synthesis"}
+_EXCLUDED = ("sources", "_stubs", "_archive")
+_SKIP_DIRS = {"media"}
+_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
+
+
+class WikiScanError(ValueError):
+    """A page or the input inventory is unsafe to compile."""
+
+    def __init__(self, message: str, *, code: str = "scan-invalid", path: Path | None = None):
+        self.code = code
+        self.path = path
+        super().__init__(message)
+
+
+class SnapshotChangedError(WikiScanError):
+    def __init__(self, message: str):
+        super().__init__(message, code="scan-changed")
+
+
+class _StrictLoader(yaml.SafeLoader):
+    pass
+
+
+def _mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
+    result: dict[Any, Any] = {}
+    for key_node, value_node in node.value:
+        key = loader.construct_object(key_node, deep=deep)
+        if key in result:
+            raise yaml.constructor.ConstructorError(
+                "while constructing a mapping", node.start_mark,
+                f"found duplicate key {key!r}", key_node.start_mark,
+            )
+        result[key] = loader.construct_object(value_node, deep=deep)
+    return result
+
+
+_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
+
+
+def _inside(path: Path, root: Path) -> bool:
+    try:
+        path.resolve(strict=False).relative_to(root)
+        return True
+    except ValueError:
+        return False
+
+
+def _inventory(root: Path) -> list[tuple[Path, str]]:
+    if not root.exists() or not root.is_dir():
+        raise WikiScanError(f"wiki root does not exist: {root}", code="wiki-root-missing", path=root)
+    root = root.resolve()
+    found: list[tuple[Path, str]] = []
+    for dirname, kind in (*_ELIGIBLE.items(), *[(name, "excluded") for name in _EXCLUDED]):
+        base = root / dirname
+        if not base.exists():
+            continue
+        if not _inside(base, root):
+            raise WikiScanError(f"symlink escapes wiki root: {base}", code="symlink-escape", path=base)
+        pending = [base]
+        while pending:
+            current = pending.pop()
+            try:
+                children = sorted(current.iterdir(), key=lambda p: p.name)
+            except OSError as exc:
+                raise WikiScanError(f"cannot read directory: {current}: {exc}", code="inventory-error", path=current) from exc
+            for child in children:
+                if child.name.startswith("."):
+                    continue
+                if child.is_symlink() and not _inside(child, root):
+                    raise WikiScanError(f"symlink escapes wiki root: {child}", code="symlink-escape", path=child)
+                if child.is_dir():
+                    if child.name in _SKIP_DIRS:
+                        continue
+                    pending.append(child)
+                elif child.suffix.lower() == ".md":
+                    found.append((child, kind))
+    return sorted(found, key=lambda pair: pair[0].resolve(strict=False).relative_to(root).as_posix())
+
+
+def _parse(path: Path, expected_type: str | None, root: Path) -> tuple[dict[str, Any], str, bytes]:
+    try:
+        raw = path.read_bytes()
+    except OSError as exc:
+        raise WikiScanError(f"cannot read page: {path}: {exc}", code="read-error", path=path) from exc
+    try:
+        text = raw.decode("utf-8")
+    except UnicodeDecodeError as exc:
+        raise WikiScanError(f"invalid UTF-8: {path}", code="invalid-utf8", path=path) from exc
+    lines = text.splitlines(keepends=True)
+    if not lines or lines[0].rstrip("\r\n") != "---":
+        raise WikiScanError(f"missing frontmatter: {path}", code="frontmatter-missing", path=path)
+    closing = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---"), None)
+    if closing is None:
+        raise WikiScanError(f"malformed frontmatter: {path}", code="frontmatter-malformed", path=path)
+    fm_text = "".join(lines[1:closing])
+    try:
+        fm = yaml.load(fm_text, Loader=_StrictLoader)
+    except yaml.YAMLError as exc:
+        raise WikiScanError(f"malformed frontmatter: {path}: {exc}", code="frontmatter-malformed", path=path) from exc
+    if not isinstance(fm, dict):
+        raise WikiScanError(f"frontmatter must be a mapping: {path}", code="frontmatter-invalid", path=path)
+    for key in ("id", "title", "type"):
+        if not isinstance(fm.get(key), str) or not fm[key].strip():
+            raise WikiScanError(f"frontmatter field {key!r} is required: {path}", code="frontmatter-invalid", path=path)
+    if expected_type is not None and fm["type"] != expected_type:
+        raise WikiScanError(f"frontmatter type does not match directory: {path}", code="frontmatter-invalid", path=path)
+    body = "".join(lines[closing + 1:]).lstrip("\r\n")
+    if not body.strip():
+        raise WikiScanError(f"empty body: {path}", code="empty-body", path=path)
+    return fm, body, raw
+
+
+def _blocks(page_id: str, body: str) -> tuple[ContentBlock, ...]:
+    blocks: list[ContentBlock] = []
+    heading: str | None = None
+    lines: list[str] = []
+
+    def flush() -> None:
+        nonlocal lines
+        text = "\n".join(lines).strip("\r\n")
+        if heading is not None or text.strip():
+            blocks.append(ContentBlock(f"{page_id}:{len(blocks)}", page_id, heading, text, len(blocks)))
+        lines = []
+
+    for line in body.splitlines():
+        match = _HEADING.match(line)
+        if match:
+            flush()
+            heading = match.group(2).strip()
+        else:
+            lines.append(line)
+    flush()
+    return tuple(blocks)
+
+
+def _relations(fm: dict[str, Any], path: Path) -> tuple[tuple[str, str], ...]:
+    raw = fm.get("relations", [])
+    if raw is None:
+        raw = []
+    if not isinstance(raw, list):
+        raise WikiScanError(f"relations must be a list: {path}", code="frontmatter-invalid", path=path)
+    result: list[tuple[str, str]] = []
+    for relation in raw:
+        if (
+            not isinstance(relation, dict)
+            or not isinstance(relation.get("type"), str)
+            or not relation["type"].strip()
+            or not isinstance(relation.get("target"), str)
+            or not relation["target"].strip()
+        ):
+            raise WikiScanError(f"invalid relation: {path}", code="frontmatter-invalid", path=path)
+        result.append((relation["type"].strip(), relation["target"].strip()))
+    return tuple(result)
+
+
+def _taxonomy(fm: dict[str, Any], relations: tuple[tuple[str, str], ...]) -> str | None:
+    explicit = fm.get("primary_taxonomy") or fm.get("category")
+    if explicit:
+        return str(explicit).strip() or None
+    for kind, target in relations:
+        if kind != "taxonomy_of":
+            continue
+        if target.startswith("taxonomy/"):
+            return target.removeprefix("taxonomy/").strip() or None
+        if target.startswith("taxonomy-"):
+            return target.removeprefix("taxonomy-").strip() or None
+    return None
+
+
+def _sources(fm: dict[str, Any], path: Path) -> tuple[str, ...]:
+    raw = fm.get("sources", [])
+    if raw is None:
+        return ()
+    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
+        raise WikiScanError(f"sources must be a list of non-empty strings: {path}", code="frontmatter-invalid", path=path)
+    return tuple(dict.fromkeys(item.strip() for item in raw))
+
+
+def _record(path: Path, kind: str, root: Path) -> tuple[PageRecord, bytes] | tuple[str, bytes]:
+    expected = None if kind == "excluded" else next(value for dirname, value in _ELIGIBLE.items() if path.resolve().relative_to(root).parts[0] == dirname)
+    fm, body, raw = _parse(path, expected, root)
+    if kind == "excluded":
+        return str(fm["id"]), raw
+    page_id = fm["id"].strip()
+    blocks = _blocks(page_id, body)
+    first = next((block.body.strip() for block in blocks if block.body.strip()), "")
+    relations = _relations(fm, path)
+    return PageRecord(
+        page_id=page_id,
+        title=fm["title"].strip(),
+        page_type=fm["type"],
+        path=path.resolve(strict=False).relative_to(root).as_posix(),
+        primary_taxonomy=_taxonomy(fm, relations),
+        summary=first[:800],
+        content_blocks=blocks,
+        relation_targets=relations,
+        content_sha256=hashlib.sha256(raw).hexdigest(),
+        char_count=len(body),
+        token_count=None,
+        custom_type=str(fm.get("custom_type", "") or "").strip(),
+        sources=_sources(fm, path),
+    ), raw
+
+
+def scan_wiki_snapshot(wiki_root: Path) -> WikiSnapshot:
+    root = wiki_root.resolve()
+    first_inventory = _inventory(root)
+    pages: list[PageRecord] = []
+    excluded: list[str] = []
+    seen_ids: dict[str, Path] = {}
+    seen_titles: dict[str, Path] = {}
+    raw_hashes: dict[str, str] = {}
+    for path, kind in first_inventory:
+        result, raw = _record(path, kind, root)
+        rel = path.resolve(strict=False).relative_to(root).as_posix()
+        raw_hashes[rel] = hashlib.sha256(raw).hexdigest()
+        if kind == "excluded":
+            page_id = result  # type: ignore[assignment]
+            if page_id not in excluded:
+                excluded.append(page_id)
+            continue
+        page = result  # type: ignore[assignment]
+        if page.page_id in seen_ids:
+            raise WikiScanError(f"duplicate page id {page.page_id!r}: {path} and {seen_ids[page.page_id]}", code="duplicate-id", path=path)
+        if page.title in seen_titles:
+            raise WikiScanError(f"duplicate title {page.title!r}: {path} and {seen_titles[page.title]}", code="duplicate-title", path=path)
+        seen_ids[page.page_id] = path
+        seen_titles[page.title] = path
+        pages.append(page)
+    second_inventory = _inventory(root)
+    first_paths = [p.resolve(strict=False).relative_to(root).as_posix() for p, _ in first_inventory]
+    second_paths = [p.resolve(strict=False).relative_to(root).as_posix() for p, _ in second_inventory]
+    if first_paths != second_paths:
+        raise SnapshotChangedError("wiki inventory changed during scan")
+    for path, _ in second_inventory:
+        rel = path.resolve(strict=False).relative_to(root).as_posix()
+        try:
+            digest = hashlib.sha256(path.read_bytes()).hexdigest()
+        except OSError as exc:
+            raise SnapshotChangedError(f"wiki content changed during scan: {rel}") from exc
+        if digest != raw_hashes[rel]:
+            raise SnapshotChangedError(f"wiki content changed during scan: {rel}")
+    snapshot = WikiSnapshot("", str(root), "wiki-v3", tuple(sorted(pages, key=lambda p: p.path)), tuple(sorted(excluded)))
+    return WikiSnapshot(snapshot_sha256(snapshot), str(root), snapshot.schema_version, snapshot.pages, snapshot.excluded_sources)
+
+
+def _canonical_payload(snapshot: WikiSnapshot) -> dict[str, Any]:
+    return {
+        "schema_version": snapshot.schema_version,
+        "pages": [
+            {
+                "page_id": p.page_id,
+                "title": p.title,
+                "page_type": p.page_type,
+                "path": p.path,
+                "primary_taxonomy": p.primary_taxonomy,
+                "summary": p.summary,
+                "content_blocks": [b.__dict__ for b in p.content_blocks],
+                "relation_targets": [list(pair) for pair in p.relation_targets],
+                "content_sha256": p.content_sha256,
+                "char_count": p.char_count,
+                "token_count": p.token_count,
+                "custom_type": p.custom_type,
+                "sources": list(p.sources),
+            }
+            for p in sorted(snapshot.pages, key=lambda page: page.path)
+        ],
+        "excluded_sources": list(sorted(snapshot.excluded_sources)),
+    }
+
+
+def canonical_snapshot_json(snapshot: WikiSnapshot) -> str:
+    return json.dumps(_canonical_payload(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
+
+
+def snapshot_sha256(snapshot: WikiSnapshot) -> str:
+    return hashlib.sha256(canonical_snapshot_json(snapshot).encode("utf-8")).hexdigest()
+
+
+# Baseline API is re-exported here because scanner is the snapshot boundary;
+# implementation remains in partition to keep grouping logic together.
+from .partition import (  # noqa: E402
+    CandidateDecision, GateMetrics, GovernanceConfig, ReaderProfile,
+    SeriesGateResult, evaluate_series_gate,
+)
+
+
+__all__ = [
+    "WikiScanError", "SnapshotChangedError", "scan_wiki_snapshot",
+    "canonical_snapshot_json", "snapshot_sha256", "ReaderProfile",
+    "GovernanceConfig", "GateMetrics", "CandidateDecision", "SeriesGateResult",
+    "evaluate_series_gate",
+]
diff --git a/tests/test_kc/test_book_series_baseline.py b/tests/test_kc/test_book_series_baseline.py
new file mode 100644
index 00000000..f1cd5aaf
--- /dev/null
+++ b/tests/test_kc/test_book_series_baseline.py
@@ -0,0 +1,64 @@
+from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
+from src.kc.views.book.wiki.partition import (
+    GovernanceConfig,
+    ReaderProfile,
+    evaluate_series_gate,
+)
+
+
+def _page(i: int, page_type: str, taxonomy: str = "book-a", *, source: bool = True) -> PageRecord:
+    return PageRecord(
+        page_id=f"p{i}", title=f"Page {i}", page_type=page_type,
+        path=f"{page_type}/p{i}.md", primary_taxonomy=taxonomy,
+        summary="summary", content_blocks=(ContentBlock(f"p{i}:0", f"p{i}", None, "body", 0),),
+        relation_targets=(), content_sha256=f"hash-{i}", char_count=10,
+        token_count=None, sources=(f"source-{i}",) if source else (),
+    )
+
+
+def _snapshot(*pages: PageRecord) -> WikiSnapshot:
+    return WikiSnapshot("snap-1", "wiki", "wiki-v3", tuple(pages), ())
+
+
+def test_series_gate_emits_deterministic_ready_baseline() -> None:
+    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
+    profile = ReaderProfile("reader", ("learn_concept", "apply"))
+    governance = GovernanceConfig(external_authorized=True, budget_cap=100, approver="editor")
+
+    result = evaluate_series_gate(snapshot, reader_profile=profile, governance=governance)
+
+    assert result.status == "ready"
+    assert result.generation_mode == "llm_allowed"
+    assert result.metrics.estimated_chars == 30
+    assert result.candidates[0].eligible_page_count == 3
+    assert result.candidates[0].source_coverage == 1.0
+    assert result.candidates[0].closure_status == "closed"
+
+
+def test_series_gate_rejects_weak_candidate_without_provider() -> None:
+    snapshot = _snapshot(_page(1, "concept", source=False))
+    result = evaluate_series_gate(
+        snapshot,
+        reader_profile=ReaderProfile("reader", ("learn_concept",)),
+        governance=GovernanceConfig(external_authorized=True, budget_cap=100, approver="editor"),
+    )
+
+    candidate = result.candidates[0]
+    assert candidate.source_coverage == 0.0
+    assert candidate.decision in {"merge", "reference", "cancel"}
+    assert candidate.decision != "proceed"
+
+
+def test_missing_governance_blocks_and_forces_rule_only() -> None:
+    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
+    result = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("reader", ("learn_concept",)))
+
+    assert result.status == "blocked"
+    assert result.generation_mode == "rule_only"
+    assert {"external_authorized", "budget_cap", "approver"} <= set(result.block_reasons)
+
+
+def test_same_snapshot_and_inputs_have_same_result() -> None:
+    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
+    kwargs = dict(reader_profile=ReaderProfile("reader", ("learn_concept",)), governance=GovernanceConfig(True, 100, "editor"))
+    assert evaluate_series_gate(snapshot, **kwargs) == evaluate_series_gate(snapshot, **kwargs)
