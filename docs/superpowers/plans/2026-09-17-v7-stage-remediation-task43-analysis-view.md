# Plan: Task 43 — AnalysisView + offset mapping（HTML 解析）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第三批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 43)

## 0. 上下文

现在 scanner 只处理 markdown/plain（Task 41）。HTML source（URL 摄取、.html
本地）的结构信息没单独分析层——HTML 解析散落在 extract.py / extract_full.py
的若干 helper 里。

**Task 43 目标**：独立 `AnalysisView` 模块，提供 HTML 解析 + 偏移映射。
LLM 看到的是 **rendered text**（去除 tags 后）；byte offset 是 **原始 HTML byte
offset**。这两个映射关系是 view 层核心。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `AnalysisView.from_html(html_bytes) -> AnalysisView` —— 解析 HTML，保留
   (raw_byte_offset, rendered_text_offset, tag, attrs) 映射
2. `view.to_rendered_text()` —— 拼接所有 text node 后的纯文本
3. `view.lookup_rendered_offset(raw_byte_offset) -> rendered_offset | None`
4. `view.lookup_raw_offset(rendered_offset) -> raw_byte_offset | None`
5. 不依赖 BeautifulSoup（避免新依赖）；用 stdlib `html.parser.HTMLParser`

### 1.2 Non-Goal

- **不**做 CSS 选择器 / XPath
- **不**改 Stage 1/2/3 主流程（独立可调用）
- **不**改 frontmatter

## 2. 模型

```python
@dataclass(frozen=True)
class TextMapping:
    raw_byte_start: int       # raw HTML byte offset where text starts
    raw_byte_end: int         # raw HTML byte offset where text ends
    rendered_offset: int      # offset in view.to_rendered_text()

@dataclass
class AnalysisView:
    raw_bytes: bytes
    rendered_text: str
    mappings: list[TextMapping]    # sorted by raw_byte_start
    tag_stack_at_offset: dict[int, str]   # raw_byte_offset → enclosing tag name
```

## 3. Files

- `src/pipeline/v7_extract/analysis_view.py`（新建）
- `tests/test_pipeline/test_v7_extract_analysis_view.py`（新建）

## 4. Tests

```python
def test_analysis_view_extracts_text_from_simple_html():
    """<p>hello</p> → rendered_text = 'hello'"""

def test_analysis_view_preserves_byte_offsets_against_raw_html():
    """raw_byte_start 指向 <p> 标签后，raw_byte_end 指向 </p> 前"""

def test_analysis_view_lookup_rendered_offset_returns_correct_index():
    """raw_byte → rendered_text 位置映射"""

def test_analysis_view_handles_nested_tags():
    """嵌套 <div><span>nested</span></div> → rendered 含 'nested'"""

def test_analysis_view_skips_script_and_style():
    """<script>code</script> / <style>css</style> 不进入 rendered_text"""

def test_analysis_view_round_trip_offset_mapping():
    """raw → rendered → raw 同一 raw_byte_offset"""
```

## 5. Implementation

```python
from html.parser import HTMLParser

class _ViewBuilder(HTMLParser):
    """Walks HTML, builds TextMapping list + rendered_text.
    
    - Skip <script>, <style>, <head> contents (treat as non-text)
    - For each text-bearing tag (p, div, span, li, h1-h6, td, ...),
      record the [raw_byte_start, raw_byte_end] of the inner text
    - Concatenate text into rendered_text with single space separator
    """

def AnalysisView.from_html(raw_bytes: bytes) -> "AnalysisView": ...

def lookup_rendered_offset(self, raw_byte_offset: int) -> int | None: ...
def lookup_raw_offset(self, rendered_offset: int) -> int | None: ...
```

## 6. Acceptance

- ✅ 6 个测试全绿
- ✅ 偏移映射 round-trip 一致
- ✅ script/style 内容不进入 rendered
- ✅ 现有 v7_extract + reconciliation 测试 0 回归
- ✅ 不引入新依赖（stdlib `html.parser`）