# V7 摄取流水线 v3.0 — 实施计划

**计划 ID**:`2026-09-15-v7-pipeline-v3-implementation`
**基于架构**:`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
**总工作量**:**4.55 天**
**作者**:Codex Agent
**日期**:2026-09-15

---

## Goal

实施 v3.0 架构,达成:

- ✅ spot-check 准确率 ≥ 80%(A1)
- ✅ write_contamination = 0(A2)
- ✅ 16 项原架构验收标准 + 4 项补强验收标准(A1-A20)
- ✅ 根除 v2 的 async/sync 桥接 bug
- ✅ 完整对齐现有 `src/wiki/templates/` 架构

**非目标**(plan 其它 task 的事):
- 模板升级 V7.1.1
- 概念去重
- Stage 6 LLM 关系增强

---

## 依赖关系

```
Phase 1:基础设施(Day 1)
├── 1.0 feature flag 骨架(R10)(0.1天)
├── 1.1 prompts/ast.py(0.2天)
├── 1.2 prompts/parser.py + TOML schema 校验(D9)(0.3天)
├── 1.3 prompts/renderer.py(0.2天)
├── 1.4 prompts/resolver.py + 路径白名单(D9,D6)(0.2天)
├── 1.5 prompts/builtin/*.toml(0.2天)
└── 1.6 failures.py(D4,D10,D11)(0.4天)

Phase 2:Stage 改造(Day 2-3)
├── 2.1 Stage 1 async + 接入 prompts(0.4天)
├── 2.2 Stage 3 async + P5 解耦(0.3天)
├── 2.3 Stage 4 async + P4 兜底(0.4天)
├── 2.4 Stage 5 async + D7 过滤(0.2天)
├── 2.5 Stage 7 强化(0.2天)
└── 2.6 单元测试重写(async + FakeLLMClient)(0.5天)

Phase 3:CLI 迁移(Day 3.5-4)
├── 3.0 调用方调研(R4)(0.05天)
├── 3.1 scripts/extract_pilot.py async 化(0.2天)
├── 3.2 scripts/extract_full.py async 化(0.2天)
└── 3.3 scripts/review_queue_cli.py(0.3天)

Phase 4:验证(Day 4-4.4)
├── 4.1 离线单元测试(0.1天)
├── 4.2 nightly 真实 LLM 集成(0.1天)
├── 4.3 spot-check 回归(0.1天)
└── 4.4 文档更新(0.1天)
```

---

## Phase 1:基础设施(1.6 天,Day 1)

### Task 1.0:`v7_extract/__init__.py` — Feature flag 灰度发布骨架(R10)(0.1 天)

**背景**:
- R10:Phase 2-3 是破坏性改动(删除启发式 + 顶层改 async)
- 一旦改坏,git revert 会丢失所有未提交工作
- feature flag 让 `V7_USE_V3=false` 立即回退到 v2(sync + 启发式)

**Files**:
- 🟡 修改 `src/pipeline/v7_extract/__init__.py`
- 🆕 `src/pipeline/v7_extract/_legacy.py`(v2 API 镜像,作为 fallback)

**Implementation**:
```python
# src/pipeline/v7_extract/__init__.py
"""Public API for v7_extract. v3 by default; v2 fallback via env var."""
import os

USE_V3_PIPELINE = os.environ.get("V7_USE_V3", "true").lower() == "true"

if USE_V3_PIPELINE:
    from .doc_classifier import classify_doc
    from .completeness_checker import check_completeness
    from .topic_clusterer import cluster_topics
    from .slot_filler import fill_slots
else:
    # R10: v2 fallback(sync + 启发式),改坏时立即回退
    from ._legacy import (
        classify_doc,
        check_completeness,
        cluster_topics,
        fill_slots,
    )

__all__ = [
    "USE_V3_PIPELINE",
    "classify_doc",
    "check_completeness",
    "cluster_topics",
    "fill_slots",
]
```

```python
# src/pipeline/v7_extract/_legacy.py
"""R10: v2 fallback — copies of the original sync+heuristic implementations.

Created at Phase 1 Task 1.0 by copying the original files BEFORE Phase 2
modifies them. If v3 causes regressions, set V7_USE_V3=false to fall back.
"""
# 这一文件由 T1.0 末尾执行:
#   cp src/pipeline/v7_extract/{doc_classifier,completeness_checker,topic_clusterer,slot_filler}.py \
#      src/pipeline/v7_extract/_legacy.py
# 然后批量重命名为 v2_xxx (避免命名冲突),并修复内部 import
```

**触发时机**:在 T2.1 Stage 1 改造**之前**,必须完成此任务。否则一旦 T2.1 改了 doc_classifier.py,fallback 就不可用。

**Tests**:`tests/test_pipeline/test_v7_extract_legacy_fallback.py`
- `V7_USE_V3=false` 时,`classify_doc` 是 v2 同步版本(启发式)
- `V7_USE_V3=true` 时,`classify_doc` 是 v3 async 版本

**Acceptance**:
- ✅ R10:feature flag 工作,两个版本可切换
- ✅ R10 验证通过(回退路径可用)

---

### Task 1.1:`prompts/ast.py` — PromptAST 数据模型(0.2 天)

**Files**:
- 🆕 `src/pipeline/v7_extract/prompts/__init__.py`
- 🆕 `src/pipeline/v7_extract/prompts/ast.py`

**Implementation**:
```python
"""PromptAST — mirror of src/wiki/templates/types.py."""
from dataclasses import dataclass, field
from typing import Literal

PromptSource = Literal["project", "user", "bundled"]

@dataclass(frozen=True)
class PromptSlot:
    name: str
    required: bool = True
    default: str = ""
    description: str = ""

@dataclass(frozen=True)
class PromptSection:
    heading: str  # "system" | "user_header" | "user_data"
    body_template: str
    slots: list[PromptSlot] = field(default_factory=list)

@dataclass(frozen=True)
class PromptAST:
    prompt_kind: str
    version: str | None
    sections: list[PromptSection]
    raw: str = ""
    output_schema: dict | None = None

    @property
    def all_slots(self) -> list[PromptSlot]:
        return [s for sec in self.sections for s in sec.slots]

    @property
    def required_slots(self) -> list[str]:
        return [s.name for s in self.all_slots if s.required]

@dataclass(frozen=True)
class PromptTemplate:
    """Resolved Prompt template, ready to render."""
    prompt_kind: str
    version: str | None
    system_section: str
    user_template: str
    output_schema: dict | None
    source: PromptSource
    path: Path
```

**Tests**:`tests/test_pipeline/test_v7_extract_prompts_ast.py`
- dataclass 字段冻结(frozen=True)
- `all_slots` / `required_slots` 计算正确
- 空 sections / 空 slots 边界

**Acceptance**:模块导入无错,dataclass 可序列化。

---

### Task 1.2:`prompts/parser.py` — TOML 解析 + schema 校验(D9)(0.3 天)

**Files**:
- 🆕 `src/pipeline/v7_extract/prompts/parser.py`

**Implementation**:
```python
"""TOML 解析器 + D9 schema 校验(防止恶意 enum 注入)。"""
import tomllib
from pathlib import Path

KNOWN_DOC_TYPES = {
    "single_method", "multi_section", "collection",
    "qa_chat", "list", "tool", "incomplete",
}

class PromptParseError(Exception):
    pass

def parse_prompt(path: Path) -> PromptAST:
    """Parse TOML file into PromptAST + validate output_schema(D9)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PromptParseError(f"Invalid TOML in {path}: {e}")

    sections = []
    for heading in ("system", "user"):
        if heading not in data:
            continue
        text = data[heading].get("text") or data[heading].get("template", "")
        slots = [PromptSlot(**s) for s in data.get("slot", []) if s.get("name")]
        sections.append(PromptSection(heading=heading, body_template=text, slots=slots))

    schema = data.get("output_schema")
    if schema:
        _validate_output_schema(schema)  # D9: 防止未知 enum 绕过 evidence

    return PromptAST(
        prompt_kind=data["meta"]["prompt_kind"],
        version=data["meta"].get("version"),
        sections=sections,
        raw=path.read_text(encoding="utf-8"),
        output_schema=schema,
    )


def _validate_output_schema(schema: dict) -> None:
    """D9: 防止恶意 TOML 通过 enum 注入未知 doc_type。"""
    if "enum" in schema:
        doc_types = schema["enum"].get("doc_type", [])
        if isinstance(doc_types, list):
            unknown = set(doc_types) - KNOWN_DOC_TYPES
            if unknown:
                raise PromptParseError(f"Unknown doc_type in enum: {unknown}")
```

**Tests**:`tests/test_pipeline/test_v7_extract_prompts_parser.py`
- 合法 TOML 解析成功
- 缺少 `[meta]` 报错
- 未知 doc_type 触发 PromptParseError(D9 / A18)
- 无效 TOML 语法报错
- 空 file 报错

**Acceptance**:D9 + A18 验证通过。

---

### Task 1.3:`prompts/renderer.py` — render_prompt + schema 校验 + 重试(0.2 天)

**Files**:
- 🆕 `src/pipeline/v7_extract/prompts/renderer.py`

**Implementation**:
```python
"""Render PromptTemplate + parse LLM response against output_schema."""
import json
import re

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def render_prompt(template: PromptTemplate, slot_values: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) with slots substituted."""
    user = template.user_template
    for name, value in slot_values.items():
        user = user.replace("{" + name + "}", str(value))
    return template.system_section, user


def compute_prompt_fill_status(template: PromptTemplate, available: dict) -> dict:
    """Compute missing/extra slots for audit."""
    required = {s.name for s in template.all_slots if s.required}
    given = required & set(available.keys())
    return {
        "missing": sorted(required - given),
        "extra": sorted(set(available.keys()) - {s.name for s in template.all_slots}),
    }


def parse_llm_response(raw: str, schema: dict | None) -> dict:
    """Parse + validate LLM response against output_schema(D9)。"""
    text = raw.strip()
    if text.startswith("```"):
        text = _JSON_FENCE_RE.sub("", text).strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as e:
        raise LLMResponseError(f"Invalid JSON: {e}")
    if not isinstance(payload, dict):
        raise LLMResponseError("Payload not a JSON object")
    if schema:
        # 必填字段
        for key in schema.get("required", []):
            if key not in payload:
                raise LLMResponseError(f"Missing required key: {key}")
        # enum
        for key, allowed in schema.get("enum", {}).items():
            if key in payload and payload[key] not in allowed:
                raise LLMResponseError(f"{key}={payload[key]!r} not in {allowed}")
        # range
        for key, (lo, hi) in schema.get("range", {}).items():
            if key in payload:
                v = payload[key]
                if not (lo <= v <= hi):
                    raise LLMResponseError(f"{key}={v} out of [{lo}, {hi}]")
    return payload


class LLMResponseError(Exception):
    pass
```

**Tests**:`tests/test_pipeline/test_v7_extract_prompts_renderer.py`
- `render_prompt` slot 替换正确
- `compute_prompt_fill_status` 缺失/多余检测
- `parse_llm_response` 接受合法 JSON
- 缺必填字段报错
- enum 越界报错
- range 越界报错
- code fence 正确剥离

**Acceptance**:D2 重试 3 次在调用方实现,本任务只提供 `LLMResponseError`。

---

### Task 1.4:`prompts/resolver.py` — 三层覆盖 + 路径白名单(D9 + D6)(0.2 天)

**Files**:
- 🆕 `src/pipeline/v7_extract/prompts/resolver.py`

**Implementation**:
```python
"""三层覆盖 + D6 热加载 + D9 路径白名单。"""
from pathlib import Path

ALLOWED_ROOTS = [
    Path("knowledge/novel-wiki/.v7-prompts"),
    Path.home() / ".config" / "ruflo-kb" / "v7-prompts",
]

BUNDLED_ROOT = Path(__file__).parent / "builtin"


def resolve(prompt_kind: str, project_root: Path | None = None) -> PromptTemplate:
    """D1: 三层覆盖;D6: 每次重新解析(热加载);D9: 路径白名单。"""
    search_roots = list(ALLOWED_ROOTS)
    if project_root:
        search_roots.insert(0, project_root / ".v7-prompts")

    for root in search_roots:
        candidate = root / f"{prompt_kind}.toml"
        if candidate.is_file():
            ast = parse_prompt(candidate)
            return _to_template(ast, source=_classify_source(root), path=candidate)

    # bundled fallback
    bundled = BUNDLED_ROOT / f"{prompt_kind}.toml"
    if bundled.is_file():
        ast = parse_prompt(bundled)
        return _to_template(ast, source="bundled", path=bundled)

    raise PromptNotFoundError(f"No prompt found for kind={prompt_kind!r}")


def _classify_source(root: Path) -> PromptSource:
    if ".v7-prompts" in str(root):
        return "project"
    if ".config" in str(root):
        return "user"
    return "bundled"


def _to_template(ast: PromptAST, source: PromptSource, path: Path) -> PromptTemplate:
    system = ""
    user = ""
    for sec in ast.sections:
        if sec.heading == "system":
            system = sec.body_template
        elif sec.heading == "user":
            user = sec.body_template
    return PromptTemplate(
        prompt_kind=ast.prompt_kind,
        version=ast.version,
        system_section=system,
        user_template=user,
        output_schema=ast.output_schema,
        source=source,
        path=path,
    )


class PromptNotFoundError(Exception):
    pass
```

**Tests**:`tests/test_pipeline/test_v7_extract_prompts_resolver.py`
- project 覆盖优先级最高
- user 覆盖次之
- bundled 兜底
- 文件不在 ALLOWED_ROOTS → 抛 PromptParseError(A17)
- 运行时改 .toml → 下次 resolve 立即生效(D6 / A16)

**Acceptance**:D9 + A17 + A16 验证通过。

---

### Task 1.5:`prompts/builtin/*.toml` — 4 个内置 prompt(0.2 天)

**Files**:
- 🆕 `src/pipeline/v7_extract/prompts/builtin/classify.toml`
- 🆕 `src/pipeline/v7_extract/prompts/builtin/completeness.toml`
- 🆕 `src/pipeline/v7_extract/prompts/builtin/cluster.toml`
- 🆕 `src/pipeline/v7_extract/prompts/builtin/fill_slots.toml`

**Implementation**:从 v2 当前代码提取 4 个 prompt,转成 TOML 格式:

`classify.toml` 示例:
```toml
[meta]
prompt_kind = "classify"
version = "1.0"

[system]
text = "You are a V7 document classifier. Reply with a single JSON object and nothing else."

[user]
template = """\
Classify this document into exactly one of the following types:
  - single_method: one author, one topic, complete method article
  - multi_section: one author, many numbered sections (master-class)
  - collection: multiple distinct articles from multiple authors
  - qa_chat: chat-record / Q&A interview between authors
  - list: enumerated numbered items (e.g. 20 个签约条件)
  - tool: reference table / lookup data
  - incomplete: title + intro only — body is empty / truncated

Filename hint: {filename_hint}

Document body (first {content_limit} chars):
```
{content}
```

Respond with a single JSON object:
{{"doc_type": "<one of the 7>", "confidence": <float 0..1>, "rationale": "<short reason>"}}
"""

[output_schema]
type = "json"
required = ["doc_type", "confidence", "rationale"]
enum = { doc_type = ["single_method", "multi_section", "collection", "qa_chat", "list", "tool", "incomplete"] }
range = { confidence = [0.0, 1.0] }

[[slot]]
name = "content"
required = true

[[slot]]
name = "filename_hint"
required = false
default = ""

[[slot]]
name = "content_limit"
required = false
default = "4000"
```

**Tests**:每个 TOML 文件能被 `parse_prompt()` 解析,`output_schema` 校验通过(D9)。

**Acceptance**:A3 + A6 验证通过。

---

### Task 1.6:`failures.py` — 统一失败语义(D4 + D10 + D11)(0.4 天)

**Files**:
- 🆕 `src/pipeline/v7_extract/failures.py`

**Implementation**:
```python
"""统一失败语义。
D4: 复用现有 src/wiki/storage/reviews_queue.py
D10: 所有 v7 失败项带 source="v7_extract" 标记
D11: payload 脱敏(白名单 + 长度截断,不删除 payload)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.wiki.storage.reviews_queue import ReviewQueue, ReviewItem
from src.pipeline.v7_extract.audit_logger import AuditLogger


class ExtractionStatus(str, Enum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    INCOMPLETE = "incomplete"


@dataclass
class ExtractionResult:
    """Per-document processing result — replaces inconsistent return types."""
    status: ExtractionStatus
    source_id: str
    pages: list[Any] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    blocked_topic_ids: list[str] = field(default_factory=list)  # D7
    failure_stage: str | None = None  # stage1/3/4/5/7


# D11: 敏感字段白名单
SENSITIVE_FIELDS = {"api_key", "email", "phone", "id_card", "password", "secret"}


def sanitize_payload(payload: Any) -> Any:
    """R15 / D11: 递归移除敏感字段 + 限制字符串长度,不删除 payload(保留排错信息)。"""
    if isinstance(payload, dict):
        return {k: ("[REDACTED]" if k.lower() in SENSITIVE_FIELDS else sanitize_payload(v))
                for k, v in payload.items()}
    if isinstance(payload, list):
        return [sanitize_payload(v) for v in payload]
    if isinstance(payload, str) and len(payload) > 500:
        return payload[:500] + "..."
    return payload


def enqueue_failure(
    source_id: str,
    stage: str,
    reason: str,
    payload: dict,
    queue: ReviewQueue,
    audit: AuditLogger,
) -> str:
    """D4: 复用现有 reviews_queue。
    D10: source="v7_extract" 区分失败来源。
    D11: payload 脱敏。
    """
    sanitized = sanitize_payload(payload)
    item_id = str(uuid.uuid4())
    item = ReviewItem(
        id=item_id,
        source_id=source_id,
        source="v7_extract",  # D10
        failure_stage=stage,
        reason=reason,
        payload=sanitized,
        created_at=now_ms(),
    )
    queue.add(item)
    audit.record_failure(source_id, stage, reason, sanitized)
    return item_id


def filter_failed_topics(pages, failed_topic_ids):
    """D7: 失败的 topic 从 pages 中过滤,只把成功的传给 WikiWriter。"""
    return [p for p in pages if getattr(p, "topic_id", None) not in failed_topic_ids]


def now_ms() -> int:
    import time
    return int(time.time() * 1000)
```

**Tests**:`tests/test_pipeline/test_v7_extract_failures.py`
- `ExtractionResult` 字段正确
- `sanitize_payload` 脱敏 api_key / email / phone
- `sanitize_payload` 限制字符串 500 字
- `enqueue_failure` 创建的 ReviewItem 带 `source="v7_extract"`(D10 / A19)
- `filter_failed_topics` 正确过滤

**Acceptance**:A15 + A19 + A20 验证通过。

---

## Phase 2:Stage 改造(2.0 天,Day 2-3)

### Task 2.1:Stage 1 `doc_classifier.py` — async + 接入 prompts(0.4 天)

**Files**:
- 🟡 修改 `src/pipeline/v7_extract/doc_classifier.py`

**改动**:
1. 删除 `classify_doc_heuristic()`(~250 行启发式)
2. 删除所有 `_NAMED_SECTION_RE` / `_NUMBERED_LIST_RE` / `_TOOL_MARKERS` 等 regex 常量
3. 删除 `_looks_like_title_only` / `_count_*` 等辅助函数
4. `classify_doc()` 改 `async def`,签名:
   ```python
   async def classify_doc(
       content: str,
       *,
       filename_hint: str = "",
       llm: LLMClient,
       project_root: Path,
   ) -> Classification
   ```
5. 内部用 `prompts_resolver.resolve("classify", project_root)` + `render_prompt` + `parse_llm_response`
6. 失败 → `Classification(doc_type=INCOMPLETE, confidence=0.0, rationale=f"stage1_failed: {e}")`(P2)
7. 旧测试 `tests/test_pipeline/test_v7_extract_doc_classifier.py` 重写为 async + FakeLLMClient

**Tests**:
- `classify_doc` async 调用,FakeLLMClient 返回合法 JSON → 正确解析
- FakeLLMClient 返回缺 doc_type → 返回 confidence=0.0(不抛异常)
- FakeLLMClient 抛异常 → 返回 confidence=0.0
- output_schema enum 越界 → 返回 confidence=0.0

**Acceptance**:A7 + A8 验证通过(`grep classify_doc_heuristic` 无结果)。

---

### Task 2.2:Stage 3 `completeness_checker.py` — async + P5 解耦(0.3 天)

**Files**:
- 🟡 修改 `src/pipeline/v7_extract/completeness_checker.py`

**改动**:
1. 删除 `_check_heuristic()`(~80 行启发式)
2. 删除 `if doc_type is INCOMPLETE: return False, "doc_type=incomplete"` 短路(**P5 关键**)
3. `check_completeness()` 改 `async def`,签名:
   ```python
   async def check_completeness(
       content: str,
       doc_type: DocType,  # soft hint only (P5)
       *,
       llm: LLMClient,
       project_root: Path,
   ) -> tuple[bool, str]
   ```
4. `doc_type` 改名为 `doc_type_hint`,在 prompt 里明确说"以下是 hint,自行判断"
5. 失败 → `return False, f"stage3_failed: {e}"`(不抛异常)

**Tests**:
- FakeLLMClient 返回 `{"complete": true}` → True
- FakeLLMClient 返回 `{"complete": false}` → False
- FakeLLMClient 抛异常 → False
- doc_type=INCOMPLETE 时,LLM 仍独立判断(不短路)

**Acceptance**:A10 验证通过(Stage 1→3 解耦)。

---

### Task 2.3:Stage 4 `topic_clusterer.py` — async + P4 兜底(0.4 天)

**Files**:
- 🟡 修改 `src/pipeline/v7_extract/topic_clusterer.py`

**改动**:
1. 删除 `_cluster_heuristic()`(~120 行)
2. 删除 "综合主题" 兜底逻辑
3. `cluster_topics()` 改 `async def`,签名:
   ```python
   async def cluster_topics(
       items: list[dict],
       *,
       llm: LLMClient,
       project_root: Path,
       min_topics: int = 1,
       max_topics: int = 5,
   ) -> list[Topic]
   ```
4. 增加 `_enforce_full_coverage()`(P4):
   ```python
   def _enforce_full_coverage(topics: list[Topic], items: list[dict]) -> list[Topic]:
       assigned = {iid for t in topics for iid in t.item_ids}
       leftover = [i for i in items if i["id"] not in assigned]
       if leftover:
           topics.append(Topic(
               id="__other__",
               title="其他主题",
               item_ids=[i["id"] for i in leftover],
           ))
       return topics
   ```
5. 失败 → 返回 `[](P2:不抛异常)

**Tests**:
- LLM 返回 3 个 topic,每个都覆盖 items → 不变
- LLM 漏分配 → 自动补 "__other__" 桶(P4 / A9)
- LLM 抛异常 → 返回 []

**Acceptance**:A9 验证通过("其他主题" 桶自动生成)。

---

### Task 2.4:Stage 5 `slot_filler.py` — async(0.2 天)

**Files**:
- 🟡 修改 `src/pipeline/v7_extract/slot_filler.py`

**改动**:
1. `fill_slots()` 改 `async def`,签名:
   ```python
   async def fill_slots(
       topic: Topic,
       source_text: str,
       *,
       llm: LLMClient,
       item_texts: dict[str, str],
       project_root: Path,
   ) -> ConceptPage | None
   ```
2. 返回 `None` 表示该 topic 失败(D7,调用方负责过滤)
3. evidence 校验逻辑保留

**Tests**:
- LLM 返回合法 slots + evidence → ConceptPage.has_evidence = true
- LLM 返回的 evidence item_id 不在 available → slot 标 needs_review
- LLM 抛异常 → 返回 None

**Acceptance**:A7 验证通过(`grep _FORBIDDEN_PLACEHOLDERS` 仍存在但触发 needs_review 而非阻断)。

---

### Task 2.5:Stage 7 `wiki_writer.py` — 强化 P4 阻断(0.2 天)

**Files**:
- 🟡 修改 `src/pipeline/v7_extract/wiki_writer.py`

**改动**:
1. 在 `commit_and_index()` 增加 P4 闸门:
   ```python
   # 闸门 A: P4 "其他主题" 桶
   if getattr(page, "topic_id", None) == "__other__":
       report.blocked.append(page.id)
       continue
   ```
2. 增加 `audit.record_blocked()` 记录(P5)
3. 现有 retry + checkpoint + content_filter 不变

**Tests**:
- topic_id="__other__" → blocked,不写盘
- topic_id 正常 + has_evidence → written
- topic_id 正常 + has needs_review → blocked

**Acceptance**:A9 验证通过(WikiWriter 阻断"其他主题"桶)。

---

### Task 2.6:单元测试重写(async + FakeLLMClient)(0.5 天)

**Files**:
- 🟡 重写 `tests/test_pipeline/test_v7_extract_doc_classifier.py`
- 🟡 重写 `tests/test_pipeline/test_v7_extract_completeness_checker.py`
- 🟡 重写 `tests/test_pipeline/test_v7_extract_topic_clusterer.py`
- 🟡 重写 `tests/test_pipeline/test_v7_extract_slot_filler.py`

**改动模式**(以 doc_classifier 为例):
```python
import pytest
from src.pipeline.v7_extract.doc_classifier import classify_doc, DocType
from src.pipeline.v7_extract.llm_client import FakeLLMClient

@pytest.mark.asyncio
async def test_classify_doc_valid_response(tmp_path):
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "ok"}')

    # 准备 bundled prompt
    (tmp_path / "knowledge" / "novel-wiki" / ".v7-prompts").mkdir(parents=True)
    # ... 写入 classify.toml ...

    result = await classify_doc(
        "some content",
        filename_hint="test.md",
        llm=fake,
        project_root=tmp_path,
    )
    assert result.doc_type == DocType.SINGLE_METHOD
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_classify_doc_invalid_response_returns_failure(tmp_path):
    fake = FakeLLMClient()  # No script → returns ""
    result = await classify_doc(...)
    assert result.confidence == 0.0
```

**关键**:
- 所有测试用 `pytest-asyncio` 装饰(pyproject.toml 已配 `asyncio_mode = "auto"`)
- 用 `FakeLLMClient.script()` 注入 mock 响应
- 测试离线 CI 完全不依赖真实 LLM(A11)

**Acceptance**:A11 验证通过。

---

## Phase 3:CLI 迁移(0.75 天,Day 3.5-4)

### Task 3.0:CLI 调用方调研(R4)(0.05 天)

**背景**:
- R4:T3.1/T3.2 把 extract_pilot / extract_full 顶层 `main()` 改 async
- 如果有其它脚本 `from extract_pilot import run_pilot`,T3.1 后会**静默失败**(返回 coroutine 而非结果)
- 必须先调研清楚

**Commands**:
```bash
grep -rn "from extract_pilot\|import extract_pilot" scripts/ src/
grep -rn "from extract_full\|import extract_full" scripts/ src/
```

**输出预期**:
- 如果 0 个内部调用方:直接进入 T3.1
- 如果有内部调用方:在 T3.1 之前加 0.1 天的子任务,提供双签名兼容(`run_pilot` 既有 sync 版本又有 async 版本)

**Acceptance**:调研报告明确"无内部调用方"或"已加兼容层"。

---

### Task 3.1:`scripts/extract_pilot.py` async 化(0.2 天)

**Files**:
- 🟡 修改 `scripts/extract_pilot.py`

**改动**:
1. `def main()` → `async def main()`
2. `def _extract_one(...)` → `async def _extract_one(...)`
3. `classify_doc(...)` / `check_completeness(...)` / `cluster_topics(...)` / `fill_slots(...)` 全部加 `await`
4. CLI 入口:`sys.exit(asyncio.run(main()))`
5. CLI 参数不变(A9 / P9)

**Tests**:`tests/test_pipeline/test_extract_pilot_async.py`
- `python scripts/extract_pilot.py --count 5 --seed 42` 正常运行
- 输出 JSON / Markdown 格式不变(P9)
- 默认 LLM 自动从 registry 拿(T1 已实现)

**Acceptance**:P9 验证通过(向后兼容)。

---

### Task 3.2:`scripts/extract_full.py` async 化(0.2 天)

**Files**:
- 🟡 修改 `scripts/extract_full.py`

**改动**:同 Task 3.1 模式。

**Acceptance**:P9 验证通过。

---

### Task 3.3:`scripts/review_queue_cli.py` — 新增(D8)(0.3 天)

**Files**:
- 🆕 `scripts/review_queue_cli.py`

**Implementation**:
```python
"""D8: review queue CLI 入口。
list / resolve / stats 三个子命令,支持 --source=v7_extract 过滤(D10)。"""
import argparse
import json
from pathlib import Path

REVIEW_QUEUE_PATH = Path(".index") / "reviews_queue.json"


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list")
    list_p.add_argument("--open", action="store_true")
    list_p.add_argument("--all", action="store_true")
    list_p.add_argument("--source", default=None,
                       help="D10: filter by source, e.g. v7_extract")

    resolve_p = sub.add_parser("resolve")
    resolve_p.add_argument("item_id")
    resolve_p.add_argument("--action", choices=["promoted", "discarded", "retry"], required=True)

    stats_p = sub.add_parser("stats")

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "resolve":
        cmd_resolve(args)
    elif args.cmd == "stats":
        cmd_stats(args)


def cmd_list(args):
    items = load_queue()
    if args.source:
        items = [i for i in items if i.get("source") == args.source]
    for i in items:
        if args.open and i.get("resolved_at"):
            continue
        print(json.dumps(i, ensure_ascii=False, indent=2))


def cmd_resolve(args):
    items = load_queue()
    for i in items:
        if i["id"] == args.item_id:
            i["resolved_at"] = now_ms()
            i["resolution"] = args.action
            save_queue(items)
            return
    print(f"item {args.item_id} not found")


def cmd_stats(args):
    items = load_queue()
    by_source = {}
    by_stage = {}
    open_count = 0
    for i in items:
        by_source.setdefault(i.get("source", "unknown"), 0)
        by_source[i["source"]] += 1
        by_stage.setdefault(i.get("failure_stage", "unknown"), 0)
        by_stage[i["failure_stage"]] += 1
        if not i.get("resolved_at"):
            open_count += 1
    print(f"Total: {len(items)}, Open: {open_count}")
    print(f"By source: {by_source}")
    print(f"By stage: {by_stage}")


def load_queue(): ...
def save_queue(items): ...
def now_ms(): ...

if __name__ == "__main__":
    main()
```

**Tests**:`tests/test_pipeline/test_review_queue_cli.py`
- `list --open --source=v7_extract` 只列 v7 未解决项
- `resolve <id> --action=promoted` 标记成功
- `stats` 输出按 source / stage 分组

**Acceptance**:A14 验证通过。

---

## Phase 4:验证(0.4 天,Day 4-4.4)

### Task 4.1:离线单元测试全过(0.1 天)

**Commands**:
```bash
$env:PYTHONPATH="."; Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
python -m pytest tests/test_pipeline/test_v7_extract_*.py --import-mode=importlib -q
```

**Acceptance**:A11 通过(离线无 LLM 全部测试过)。

---

### Task 4.2:nightly 真实 LLM 集成(0.1 天)

**Setup**:
- 新建 `.github/workflows/v7_nightly.yml`
- 用 MiniMax-M3 跑 10 样本 spot-check
- 通过 `llm-providers.json` 配 provider

**Acceptance**:A12 通过(真实 LLM 跑通)。

---

### Task 4.3:spot-check 回归(0.1 天)

**Fixture**:`tests/fixtures/v7_spot_check/spot_check_v1.json`(10 个真实样本)
**Test**:`tests/test_pipeline/test_v7_spot_check_regression.py`

**Acceptance**:A1 通过(≥ 80% 准确率)。

---

### Task 4.4:文档更新(0.1 天)

**Files**:
- 🆕 `.memory/feedback-v7-pipeline-v3-2026-09-15.md`
- 🟡 更新 `.superpowers/sdd/progress.md` 记录本计划落地过程
- 🟡 更新 `CONTEXT.md` 与 `knowledge/novel-wiki/CONTEXT.md`(可选)

**Acceptance**:所有 plan 任务在 progress.md 标记完成。

---

## 总验收清单(A1-A20)

| ID | 验收项 | 验证 Task |
|---|---|---|
| A1 | spot-check 准确率 ≥ 80% | 4.3 |
| A2 | write_contamination = 0 | 2.5 + 3.1 + 3.2 |
| A3 | Prompt 版本化(`[meta] version`) | 1.5 |
| A4 | 三层覆盖(project > user > bundled) | 1.4 + Phase 4.1 |
| A5 | PromptAST 镜像 TemplateAST | 1.1 |
| A6 | output_schema 校验 + 重试 3 次 | 1.3 + Phase 2 |
| A7 | Stage 1/3/4 启发式删除 | 2.1 + 2.2 + 2.3 |
| A8 | 任何 stage LLM 失败 → needs_review | 1.6 + Phase 2 |
| A9 | P4 "其他主题" 桶不写盘 | 2.3 + 2.5 |
| A10 | Stage 1→3 解耦 | 2.2 |
| A11 | 离线 CI 通过 | 4.1 |
| A12 | async 一致性 | Phase 2 + 4.2 |
| A13 | 现有 wiki 模板架构对齐 | Phase 1 |
| A14 | review_queue CLI 可用 | 3.3 |
| A15 | failures 复用 reviews_queue(D4) | 1.6 |
| A16 | Prompt 热加载 | 1.4 |
| A17 | Prompt 路径白名单(D9) | 1.4 |
| A18 | TOML schema 校验(D9) | 1.2 |
| A19 | review_queue source 标记(D10) | 1.6 + 3.3 |
| A20 | payload 脱敏(D11) | 1.6 |

---

## 工作量明细

| Phase | Task | 工作量 | 累计 |
|---|---|---|---|
| Phase 1 | 1.0 feature flag | 0.1 | 0.1 |
| | 1.1 ast | 0.2 | 0.3 |
| | 1.2 parser + D9 | 0.3 | 0.6 |
| | 1.3 renderer | 0.2 | 0.8 |
| | 1.4 resolver + D9 + D6 | 0.2 | 1.0 |
| | 1.5 builtin TOML × 4 | 0.2 | 1.2 |
| | 1.6 failures + D4 + D10 + D11 | 0.4 | **1.6** |
| Phase 2 | 2.1 Stage 1 | 0.4 | 2.0 |
| | 2.2 Stage 3 | 0.3 | 2.3 |
| | 2.3 Stage 4 + P4 | 0.4 | 2.7 |
| | 2.4 Stage 5 | 0.2 | 2.9 |
| | 2.5 Stage 7 | 0.2 | 3.1 |
| | 2.6 测试重写 | 0.5 | **3.6** |
| Phase 3 | 3.0 调用方调研 | 0.05 | 3.65 |
| | 3.1 extract_pilot | 0.2 | 3.85 |
| | 3.2 extract_full | 0.2 | 4.05 |
| | 3.3 review_queue_cli | 0.3 | **4.35** |
| Phase 4 | 4.1-4.4 验证 | 0.2 | **4.55** |

**总计:4.55 天**

---

## TDD 节奏(每个 Task 都遵循)

```
1. 写测试(red) — 单元测试先写,看到失败
2. 写实现(green) — 让测试通过
3. 重构(refactor) — 清理代码
4. 提交一个 commit:`type(scope): 中文描述`
5. commit 信息包含 task 编号(T1.1 / T2.3 等)
```

**commit 模板示例**:
```bash
git commit -m "feat(v7-prompts): add PromptAST and slot/section dataclasses

T1.1: 创建 prompts/ast.py,镜像 src/wiki/templates/types.py 的设计。
- PromptSlot / PromptSection / PromptAST / PromptTemplate dataclass
- required_slots / all_slots 计算属性
- 单元测试覆盖 dataclass 字段冻结与序列化

Refs: docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md"
```

---

## Risk Mitigation(风险记录)

| 风险 | 缓解 Task |
|---|---|
| async 化导致现有测试失败 | 2.6 + 4.1 |
| extract_pilot / extract_full 行为变化 | 3.0 + 3.1 + 3.2 + 4.1 |
| prompts.py 与 wiki/templates/ 不一致 | Phase 1 严格镜像 |
| **R14 Prompt 注入** | 1.2 + 1.4(D9 路径白名单 + TOML schema) |
| **R13 reviews_queue 字段冲突** | 1.6(D10 source 标记) |
| **R15 payload 敏感数据** | 1.6(D11 字段白名单 + 长度截断) |
| **R10 破坏性改动无回退** | **1.0(feature flag 灰度发布)** |
| **R4 CLI 改动连锁** | **3.0(调用方调研)** |
| TOML 解析依赖 | Phase 1(Python 3.11+ tomllib 自带) |
| LLM 成本 | 1.3 + D2 max_retries=3 上限(§16.x 文档标注) |
| 项目作者不懂 TOML | Phase 4 文档(可选) |

---

## 依赖关系(任务级)

```
Phase 1:
1.0 feature flag → 1.1 ast → 1.2 parser → 1.3 renderer → 1.4 resolver → 1.5 builtin TOML
1.5 + 1.6 互相独立

Phase 2:
2.1 Stage 1 → 2.4 Stage 5(都依赖 Phase 1)
2.2 Stage 3 + 2.3 Stage 4 互相独立
2.5 Stage 7 依赖 2.3 P4 兜底
2.6 测试重写跟随每个 Stage

Phase 3:
3.0 调用方调研 → 3.1 + 3.2(必须先调研!)
3.3 独立

Phase 4:
依赖所有前置 Phase
```

**关键依赖**:
- ⚠️ **1.0 feature flag 必须在 T2.1 之前完成**(否则改坏 doc_classifier 后 fallback 不可用)
- ⚠️ **3.0 调用方调研必须在 T3.1 之前完成**(避免 silent failure)

---

## 何时算"完成"

**Definition of Done**:
- ✅ 所有 20 项验收标准(A1-A20)验证通过
- ✅ 所有单元测试 + 集成测试 + spot-check 通过
- ✅ 文档完整(架构 / 实施 / memory / progress)
- ✅ 无 v2 async/sync 桥接残留(`grep "asyncio.run" src/pipeline/v7_extract/` 无结果)
- ✅ 所有启发式已删除(`grep "heuristic" src/pipeline/v7_extract/` 仅剩注释)
- ✅ `V7_USE_V3=false` fallback 可用(R10 验证)

---

## Final commit

实施完成后,创建 final commit:
```bash
git commit -m "feat(v7-pipeline-v3): complete LLM extract pipeline with PromptAST

实施 docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md,
达成 plan 2026-09-13 的 spot-check ≥ 80% / 写盘不污染目标。

总工作量:4.55 天,11 个决策(D1-D11)全部锁定,20 项验收标准全过。

Refs: docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md"
```

---

## 下一步

**计划评审检查清单**:
- [x] 目标明确(A1-A20 可量化)
- [x] 每个 task 有明确文件 + 工作量 + 验收
- [x] TDD 节奏清晰(red-green-refactor-commit)
- [x] 依赖关系明确(Phase 顺序 + 任务并行)
- [x] 风险缓解到位(R10/R13/R14/R15 已纳入决策,R4 已纳入 T3.0)
- [x] 完成定义明确(Definition of Done)
- [x] T1.0 feature flag + T3.0 调用方调研已加入

**评审通过后即可开始 Phase 1 Task 1.0(feature flag 灰度发布骨架)。**

需要我现在开始实施吗?或者你想先评审/调整计划?