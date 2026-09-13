# Task 1 review package

Base: 5cd19a4e
Head: 89d54e2b

## Stat
 .../task-1-report.md                               |  46 ++++++++
 src/kc/views/book/wiki/__init__.py                 |   4 +
 src/kc/views/book/wiki/series_model.py             |  89 ++++++++++++++
 src/kc/views/book/wiki/series_validate.py          | 128 +++++++++++++++++++++
 src/server/routes/files.py                         |   9 ++
 src/services/files.py                              |  28 +++++
 tests/test_kc/test_book_series_manifest.py         |  65 +++++++++++
 7 files changed, 369 insertions(+)

## Diff
diff --git a/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-1-report.md b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-1-report.md
new file mode 100644
index 00000000..866d50fa
--- /dev/null
+++ b/.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-1-report.md
@@ -0,0 +1,46 @@
+# Task 1 报告：书系 manifest 和兼容契约
+
+## 改动文件
+
+- `src/kc/views/book/wiki/series_model.py`：`series-manifest-v1` / book manifest 数据模型、canonical SHA-256、严格状态转移。
+- `src/kc/views/book/wiki/series_validate.py`：schema、release 批次、文件哈希、hard/soft dependency 和 legacy 校验。
+- `src/kc/views/book/wiki/__init__.py`：公共 API 导出。
+- `src/services/files.py`：新增 `book_wiki_series_manifest`，优先读取已验证 release 内的 `series-manifest.json`，否则返回匿名单书兼容视图。
+- `src/server/routes/files.py`：新增可选 `GET /api/v1/projects/{project_id}/book-wiki/series`。
+- `tests/test_kc/test_book_series_manifest.py`：契约测试。
+
+## RED / GREEN
+
+RED：`TEMP/TMP/TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest --import-mode=importlib tests/test_kc/test_book_series_manifest.py -q` 无法启动，因为本机没有 `python`/`C:\Python314\python.exe`，可发现的 uv trampoline 返回 `permission denied (os error 5)`。
+
+GREEN：`C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe -m py_compile src/kc/views/book/wiki/series_model.py src/kc/views/book/wiki/series_validate.py src/services/files.py src/server/routes/files.py` 通过。pytest 定向测试和回归测试受同一运行环境限制，未声称通过。
+
+## 接口示例
+
+```python
+from src.kc.views.book.wiki import validate_series_manifest, transition_status
+
+assert validate_series_manifest(payload)["ok"]
+next_status = transition_status("draft", "partial")
+```
+
+`GET /book-wiki/series` 返回 series manifest；旧 `outline-v1` / 无 `series_id` release 返回 `legacy: true`、`series_id: null`、`book_id: null`，并保留可读状态和 books 形状。
+
+## 兼容策略和 ruling
+
+- 旧 release 不迁移、不猜测归属；只有明确写入的 `series_id` / `book_id` 才会被使用。
+- 单书已有 API 字段未修改；series API 是新增可选入口。
+- release 文件路径必须是 release 根下的单段相对路径；每个 `files` 条目按 SHA-256 校验。
+- manifest digest 对 `manifest_sha256` / `canonical_digest` 字段自排除，避免自引用。
+- hard dependency 必须指向存在且 `ready` 的书；空字符串、缺失目标和非 ready 目标均失败。soft dependency 缺失只进入 `soft_missing`。
+- Ruling：series manifest 若缺失，兼容端点按单书匿名视图返回，而不是生成猜测的 `series_id`；这保留旧 UI 可读性并满足 fail-closed 归属边界。
+
+## 已知限制
+
+- 本 Task 未把 manifest 写入现有 compiler 发布流程；后续 Task 负责书系编译与原子指针发布接入。
+- 当前哈希 API 校验 manifest `files` 映射，调用方需把 outline、sidecar、正文列入映射。
+- pytest 因宿主 Python 权限问题未执行。
+
+## 修复追加
+
+首轮定向 pytest 由协作环境发现 round-trip 失败：输入未提供的可选空 `hashes` 被序列化回 payload。修复为仅序列化非空可选字段；必需字段仍始终输出，校验语义不变。修复后应重跑本测试及相关 book/files 回归。
diff --git a/src/kc/views/book/wiki/__init__.py b/src/kc/views/book/wiki/__init__.py
index 24128b77..64db1274 100644
--- a/src/kc/views/book/wiki/__init__.py
+++ b/src/kc/views/book/wiki/__init__.py
@@ -16,40 +16,44 @@ from .preflight import (
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
 from .partition import (
     CandidateDecision, GateMetrics, GovernanceConfig, ReaderProfile,
     SeriesGateResult, evaluate_series_gate,
 )
+from .series_model import SCHEMA_VERSION as SERIES_MANIFEST_SCHEMA_VERSION, BookManifest, SeriesManifest, canonical_digest, transition_status
+from .series_validate import dependency_report, read_legacy_manifest, validate_book_manifest, validate_release_files, validate_series_manifest
 
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
     "CandidateDecision", "GateMetrics", "GovernanceConfig", "ReaderProfile", "SeriesGateResult", "evaluate_series_gate",
+    "SERIES_MANIFEST_SCHEMA_VERSION", "BookManifest", "SeriesManifest", "canonical_digest", "transition_status",
+    "dependency_report", "read_legacy_manifest", "validate_book_manifest", "validate_release_files", "validate_series_manifest",
 ]
diff --git a/src/kc/views/book/wiki/series_model.py b/src/kc/views/book/wiki/series_model.py
new file mode 100644
index 00000000..71d4b5e7
--- /dev/null
+++ b/src/kc/views/book/wiki/series_model.py
@@ -0,0 +1,89 @@
+"""Versioned book-series manifest contract."""
+from __future__ import annotations
+
+import hashlib
+import json
+from dataclasses import dataclass, field
+from typing import Any
+
+SCHEMA_VERSION = "series-manifest-v1"
+STATUSES = frozenset({"draft", "partial", "ready", "invalid"})
+_TRANSITIONS = {"draft": frozenset({"partial", "invalid"}),
+                "partial": frozenset({"ready", "invalid"}),
+                "ready": frozenset(), "invalid": frozenset()}
+
+
+def _list(value: Any) -> list[str]:
+    return list(value) if isinstance(value, list) else []
+
+
+@dataclass(frozen=True)
+class BookManifest:
+    book_id: str
+    required: bool
+    status: str
+    outline_id: str | None = None
+    hard_dependencies: list[str] = field(default_factory=list)
+    soft_dependencies: list[str] = field(default_factory=list)
+    release_id: str | None = None
+    hashes: dict[str, str] = field(default_factory=dict)
+
+    def to_dict(self) -> dict[str, Any]:
+        data = {"book_id": self.book_id, "required": self.required, "status": self.status,
+                "outline_id": self.outline_id, "hard_dependencies": list(self.hard_dependencies),
+                "soft_dependencies": list(self.soft_dependencies)}
+        if self.release_id is not None:
+            data["release_id"] = self.release_id
+        if self.hashes:
+            data["hashes"] = dict(self.hashes)
+        return data
+
+    @classmethod
+    def from_dict(cls, payload: dict[str, Any]) -> "BookManifest":
+        return cls(str(payload.get("book_id", "")), payload.get("required") is True,
+                   str(payload.get("status", "")), payload.get("outline_id"),
+                   _list(payload.get("hard_dependencies")), _list(payload.get("soft_dependencies")),
+                   payload.get("release_id"), payload.get("hashes") if isinstance(payload.get("hashes"), dict) else {})
+
+
+@dataclass(frozen=True)
+class SeriesManifest:
+    series_id: str
+    release_id: str
+    status: str
+    books: list[BookManifest] = field(default_factory=list)
+    manifest_sha256: str | None = None
+    schema_version: str = SCHEMA_VERSION
+
+    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
+        data = {"schema_version": self.schema_version, "series_id": self.series_id,
+                "release_id": self.release_id, "status": self.status,
+                "books": [book.to_dict() for book in self.books]}
+        if include_digest and self.manifest_sha256:
+            data["manifest_sha256"] = self.manifest_sha256
+        return data
+
+    @classmethod
+    def from_dict(cls, payload: dict[str, Any]) -> "SeriesManifest":
+        books = payload.get("books") if isinstance(payload.get("books"), list) else []
+        return cls(str(payload.get("series_id", "")), str(payload.get("release_id", "")),
+                   str(payload.get("status", "")), [BookManifest.from_dict(x) for x in books if isinstance(x, dict)],
+                   payload.get("manifest_sha256"), str(payload.get("schema_version", "")))
+
+
+def canonical_digest(payload: dict[str, Any]) -> str:
+    """Digest canonical JSON; the manifest's own digest field is excluded."""
+    clean = dict(payload)
+    for key in ("manifest_sha256", "canonical_digest"):
+        clean.pop(key, None)
+    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
+    return hashlib.sha256(encoded).hexdigest()
+
+
+def transition_status(current: str, target: str) -> str:
+    if current not in STATUSES or target not in STATUSES or target not in _TRANSITIONS[current]:
+        raise ValueError(f"illegal manifest status transition: {current!r} -> {target!r}")
+    return target
+
+
+__all__ = ["SCHEMA_VERSION", "STATUSES", "BookManifest", "SeriesManifest", "canonical_digest", "transition_status"]
diff --git a/src/kc/views/book/wiki/series_validate.py b/src/kc/views/book/wiki/series_validate.py
new file mode 100644
index 00000000..463b7bbf
--- /dev/null
+++ b/src/kc/views/book/wiki/series_validate.py
@@ -0,0 +1,128 @@
+"""Fail-closed validation for series/book release manifests."""
+from __future__ import annotations
+
+import hashlib
+import json
+from pathlib import Path
+from typing import Any
+
+from .series_model import SCHEMA_VERSION, STATUSES, canonical_digest
+
+
+def _result(errors: list[str], **extra: Any) -> dict[str, Any]:
+    return {"ok": not errors, "errors": errors, **extra}
+
+
+def validate_book_manifest(payload: object, *, release_id: str | None = None) -> dict[str, Any]:
+    errors: list[str] = []
+    if not isinstance(payload, dict):
+        return _result(["book-type"])
+    for key in ("book_id", "status", "outline_id", "hard_dependencies", "soft_dependencies"):
+        if key not in payload:
+            errors.append(f"missing:{key}")
+    if not isinstance(payload.get("book_id"), str) or not payload.get("book_id"):
+        errors.append("book-id")
+    if not isinstance(payload.get("required"), bool):
+        errors.append("required-type")
+    if payload.get("status") not in STATUSES:
+        errors.append("status")
+    for key in ("hard_dependencies", "soft_dependencies"):
+        value = payload.get(key)
+        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
+            errors.append(f"{key}-type")
+    if release_id is not None and payload.get("release_id") not in (None, release_id):
+        errors.append("release-mismatch")
+    return _result(errors)
+
+
+def dependency_report(books: list[dict[str, Any]]) -> dict[str, Any]:
+    ids = {b.get("book_id") for b in books if isinstance(b, dict)}
+    states = {b.get("book_id"): b.get("status") for b in books if isinstance(b, dict)}
+    errors: list[str] = []
+    soft_missing: list[str] = []
+    for book in books:
+        if not isinstance(book, dict):
+            continue
+        for name, hard in (("hard_dependencies", True), ("soft_dependencies", False)):
+            for dep in book.get(name, []) if isinstance(book.get(name), list) else []:
+                if not dep or dep not in ids or (hard and states.get(dep) != "ready"):
+                    if hard:
+                        errors.append(f"hard-dependency:{book.get('book_id')}:{dep}")
+                    else:
+                        soft_missing.append(str(dep))
+    return _result(errors, soft_missing=sorted(set(soft_missing)))
+
+
+def validate_series_manifest(payload: object) -> dict[str, Any]:
+    errors: list[str] = []
+    if not isinstance(payload, dict):
+        return _result(["series-type"])
+    if payload.get("schema_version") != SCHEMA_VERSION:
+        errors.append("schema-version")
+    for key in ("series_id", "release_id", "status", "books"):
+        if key not in payload:
+            errors.append(f"missing:{key}")
+    if not isinstance(payload.get("series_id"), str) or not payload.get("series_id"):
+        errors.append("series-id")
+    if not isinstance(payload.get("release_id"), str) or not payload.get("release_id"):
+        errors.append("release-id")
+    if payload.get("status") not in STATUSES:
+        errors.append("status")
+    books = payload.get("books")
+    if not isinstance(books, list) or not books:
+        errors.append("books-type")
+        books = []
+    seen: set[str] = set()
+    for book in books:
+        report = validate_book_manifest(book, release_id=payload.get("release_id"))
+        errors.extend(f"book:{e}" for e in report["errors"])
+        if isinstance(book, dict):
+            bid = book.get("book_id")
+            if bid in seen:
+                errors.append(f"duplicate-book:{bid}")
+            seen.add(bid)
+    dep = dependency_report(books)
+    errors.extend(dep["errors"])
+    recorded_digest = payload.get("manifest_sha256")
+    if recorded_digest is not None and recorded_digest != canonical_digest(payload):
+        errors.append("manifest-hash")
+    required = [b for b in books if isinstance(b, dict) and b.get("required") is True]
+    ready = all(b.get("status") == "ready" and b.get("release_id", payload.get("release_id")) == payload.get("release_id") for b in required)
+    if payload.get("status") == "ready" and (not ready or dep["errors"]):
+        errors.append("ready-gate")
+    if payload.get("status") == "ready" and any(b.get("status") in {"invalid", "partial"} for b in required):
+        errors.append("required-not-ready")
+    return _result(errors, soft_missing=dep["soft_missing"], canonical_digest=canonical_digest(payload))
+
+
+def validate_release_files(manifest: dict[str, Any], root: str | Path) -> dict[str, Any]:
+    errors: list[str] = []
+    files = manifest.get("files") if isinstance(manifest, dict) else None
+    if not isinstance(files, dict):
+        return _result(["files-type"])
+    base = Path(root)
+    for name, expected in files.items():
+        path = Path(str(name))
+        if path.is_absolute() or ".." in path.parts or path.name != str(name):
+            errors.append(f"path:{name}"); continue
+        target = base / path
+        try:
+            actual = hashlib.sha256(target.read_bytes()).hexdigest()
+        except OSError:
+            errors.append(f"missing:{name}"); continue
+        if actual != expected:
+            errors.append(f"hash:{name}")
+    return _result(errors)
+
+
+def read_legacy_manifest(payload: object) -> dict[str, Any]:
+    """Expose old releases as one anonymous book; never infer new ownership."""
+    if not isinstance(payload, dict):
+        return {"legacy": True, "series_id": None, "book_id": None, "status": "invalid"}
+    return {"legacy": payload.get("schema_version") != SCHEMA_VERSION,
+            "series_id": payload.get("series_id") if payload.get("schema_version") == SCHEMA_VERSION else None,
+            "book_id": payload.get("book_id") if payload.get("schema_version") == SCHEMA_VERSION else None,
+            "status": payload.get("status", "ready"), "manifest": payload}
+
+
+__all__ = ["validate_book_manifest", "validate_series_manifest", "validate_release_files", "dependency_report", "read_legacy_manifest"]
diff --git a/src/server/routes/files.py b/src/server/routes/files.py
index ba13b927..8ab18fe5 100644
--- a/src/server/routes/files.py
+++ b/src/server/routes/files.py
@@ -42,40 +42,49 @@ async def file_content(project_id: str, path: str):
 
 
 @router.get("/projects/{project_id}/book-wiki")
 async def book_wiki(project_id: str, version: str | None = None):
     """Return the integrity-verified active Wiki-to-Book release."""
     try:
         return files_service.book_wiki_manifest(project_id, version=version)
     except ProjectNotFoundError as e:
         raise HTTPException(404, str(e))
     except files_service.BookWikiUnavailableError as e:
         raise HTTPException(404, str(e))
 
 
 @router.get("/projects/{project_id}/book-wiki/versions")
 async def book_wiki_versions(project_id: str):
     """List integrity-verified Wiki-to-Book releases for the selector."""
     try:
         return files_service.book_wiki_versions(project_id)
     except ProjectNotFoundError as e:
         raise HTTPException(404, str(e))
+
+
+@router.get("/projects/{project_id}/book-wiki/series")
+async def book_wiki_series(project_id: str):
+    """Return the series manifest or the legacy anonymous single-book view."""
+    try:
+        return files_service.book_wiki_series_manifest(project_id)
+    except ProjectNotFoundError as e:
+        raise HTTPException(404, str(e))
     except files_service.BookWikiUnavailableError as e:
         raise HTTPException(404, str(e))
 
 
 @router.get("/projects/{project_id}/book-wiki/content")
 async def book_wiki_content(project_id: str, path: str, version: str | None = None):
     """Read one chapter from the active Wiki-to-Book release."""
     try:
         return files_service.read_book_wiki_content(project_id, path, version=version)
     except ProjectNotFoundError as e:
         raise HTTPException(404, str(e))
     except files_service.BookWikiUnavailableError as e:
         raise HTTPException(404, str(e))
     except files_service.PathTraversalError as e:
         raise HTTPException(403, str(e))
     except files_service.FileNotFoundError as e:
         raise HTTPException(404, str(e))
     except files_service.FileTooLargeError as e:
         raise HTTPException(413, str(e))
 
diff --git a/src/services/files.py b/src/services/files.py
index 838da8cc..cf84a38e 100644
--- a/src/services/files.py
+++ b/src/services/files.py
@@ -284,40 +284,68 @@ def book_wiki_manifest(project_id: str, version: str | None = None) -> dict:
             "size": path.stat().st_size,
             "sources": list(sources) if isinstance(sources, list) else [],
         })
     return {
         "version": manifest.get("run_id"),
         "snapshot_id": manifest.get("snapshot_id"),
         "page_count": manifest.get("page_count", 0),
         "chapter_count": manifest.get("chapter_count", len(chapters)),
         "total_relations": manifest.get("total_relations", 0),
         "unresolved": manifest.get("unresolved", 0),
         "unresolved_ratio": manifest.get("unresolved_ratio", 0),
         "reading_experience_mode": manifest.get("reading_experience_mode", "rule_only"),
         "volumes": [
             {**volume, "chapter_count": sum(1 for chapter in chapters if chapter["volume_id"] == volume["id"])}
             for volume in outline_volumes
         ],
         "chapters": chapters,
     }
 
 
+def book_wiki_series_manifest(project_id: str) -> dict:
+    """Read a verified series manifest, with anonymous single-book fallback."""
+    import json
+    from ..kc.views.book.wiki.series_validate import read_legacy_manifest, validate_series_manifest
+
+    release, manifest = _active_book_wiki(project_id)
+    series_path = release / "series-manifest.json"
+    if series_path.is_file():
+        expected = (manifest.get("files") or {}).get("series-manifest.json")
+        actual = hashlib.sha256(series_path.read_bytes()).hexdigest()
+        if not expected or expected != actual:
+            raise BookWikiUnavailableError("Series manifest failed integrity checks")
+        try:
+            payload = json.loads(series_path.read_text(encoding="utf-8"))
+        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
+            raise BookWikiUnavailableError("Series manifest is unreadable") from exc
+        report = validate_series_manifest(payload)
+        if not report["ok"]:
+            raise BookWikiUnavailableError("Series manifest failed validation")
+        return payload
+    legacy = read_legacy_manifest(manifest)
+    legacy["books"] = [{"book_id": manifest.get("book_id"), "required": True,
+                         "status": "ready", "outline_id": manifest.get("outline_id"),
+                         "hard_dependencies": [], "soft_dependencies": []}]
+    legacy["release_id"] = manifest.get("run_id")
+    return legacy
+
+
 def read_book_wiki_content(project_id: str, path: str, version: str | None = None) -> dict:
     """Read one chapter from the verified active Book release."""
     release, manifest = _active_book_wiki(project_id, version=version)
     normalized = path.replace("\\", "/")
     name = Path(normalized).name
     if normalized != name:
         raise PathTraversalError(f"Path escapes active book-wiki release: {path!r}")
     files = manifest.get("files") or {}
     if name not in files or not name.endswith(".md"):
         raise FileNotFoundError(f"No such book-wiki chapter: {path!r}")
     candidate = safe_resolve(release / name)
     try:
         candidate.relative_to(release.resolve())
     except ValueError as exc:
         raise PathTraversalError(f"Path escapes active book-wiki release: {path!r}") from exc
     if not candidate.is_file():
         raise FileNotFoundError(f"No such book-wiki chapter: {path!r}")
     size = candidate.stat().st_size
     if size > MAX_FILE_BYTES:
         raise FileTooLargeError(f"File too large (>{MAX_FILE_BYTES} bytes): {path!r}")
diff --git a/tests/test_kc/test_book_series_manifest.py b/tests/test_kc/test_book_series_manifest.py
new file mode 100644
index 00000000..31b10282
--- /dev/null
+++ b/tests/test_kc/test_book_series_manifest.py
@@ -0,0 +1,65 @@
+import hashlib
+import json
+
+import pytest
+
+from src.kc.views.book.wiki.series_model import (
+    SCHEMA_VERSION, SeriesManifest, canonical_digest, transition_status,
+)
+from src.kc.views.book.wiki.series_validate import (
+    validate_book_manifest, validate_series_manifest, validate_release_files,
+    dependency_report, read_legacy_manifest,
+)
+
+
+def book(book_id="a", status="ready", required=True, release_id="r1", **extra):
+    return {"book_id": book_id, "required": required, "status": status,
+            "outline_id": "o-" + book_id, "hard_dependencies": [],
+            "soft_dependencies": [], "release_id": release_id, **extra}
+
+
+def series(status="ready", books=None, release_id="r1"):
+    return {"schema_version": SCHEMA_VERSION, "series_id": "s", "release_id": release_id,
+            "status": status, "books": books if books is not None else [book()]}
+
+
+def test_valid_manifest_roundtrip_and_canonical_digest_does_not_self_reference():
+    payload = series()
+    model = SeriesManifest.from_dict(payload)
+    assert model.to_dict() == payload
+    assert canonical_digest({**payload, "manifest_sha256": "wrong"}) == canonical_digest(payload)
+
+
+def test_schema_and_state_transition_fail_closed():
+    assert validate_series_manifest(series())["ok"]
+    assert validate_series_manifest({"schema_version": "outline-v1"})["ok"] is False
+    assert transition_status("draft", "partial") == "partial"
+    with pytest.raises(ValueError):
+        transition_status("ready", "partial")
+    with pytest.raises(ValueError):
+        transition_status("draft", "ready")
+
+
+def test_required_books_same_release_gate_and_partial_invalid():
+    assert validate_series_manifest(series("ready", [book(), book("b", release_id="r2")]))["ok"] is False
+    assert validate_series_manifest(series("partial", [book("a", "ready"), book("b", "partial")]))["ok"]
+    assert validate_series_manifest(series("ready", [book("a", "invalid")]))["ok"] is False
+
+
+def test_hashes_and_dependencies():
+    p = __import__("pathlib").Path("tests/test_kc/test_book_series_manifest.py")
+    digest = hashlib.sha256(p.read_bytes()).hexdigest()
+    manifest = {"files": {p.name: digest}}
+    assert validate_release_files(manifest, p.parent)["ok"]
+    assert validate_release_files({"files": {p.name: "bad"}}, p.parent)["ok"] is False
+    books = [book("a", "ready", hard_dependencies=["b"]), book("b", "ready")]
+    assert dependency_report(books)["ok"]
+    assert dependency_report([book("a", "ready", hard_dependencies=["missing"])])["ok"] is False
+    assert dependency_report([book("a", "ready", hard_dependencies=[""])])["ok"] is False
+    assert dependency_report([book("a", "ready", soft_dependencies=["missing"])][0:])["soft_missing"] == ["missing"]
+
+
+def test_legacy_manifest_is_single_book_without_guessed_series_membership():
+    result = read_legacy_manifest({"schema_version": "outline-v1", "run_id": "old"})
+    assert result["legacy"] is True
+    assert result["series_id"] is None and result["book_id"] is None
