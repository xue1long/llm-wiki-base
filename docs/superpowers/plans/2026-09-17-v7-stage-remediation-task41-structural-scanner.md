# Plan: Task 41 — Stage 2 StructuralScanner 全量扫描

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第三批首个)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 41)

## 0. 上下文

Stage 2 现已落地（Tasks 3-5）：`SegmentationResult` + `CanonicalItem` + 5 条 invariant +
作者署名切分器 + 文档类型软门控。但现有 segmentation 主要靠正则（heading 切分）。
**markdown / code block / boilerplate 的结构扫描器尚未独立成模块**——分散在
`article_segmenter.py` 和 segmentation.py 多个 helper 函数里。

**Task 41 目标**：把 markdown / code block / boilerplate 的结构扫描抽到一个独立的
`StructuralScanner` 模块，提供 **deterministic** 结构检测：
- H1/H2/H3 heading 边界
- Fenced code block (```...```) 边界
- 引用块 / 列表项 / horizontal rule 等 boilerplate
- paragraph 边界（双换行）

**关键原则**：scanner **不**调用 LLM；它是纯 deterministic 文本分析。这是 Bounded
Evidence Contract §3.2 的实现基础——所有 LLM 输入必须先过 scanner 得到 bounded spans。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. 新模块 `src/pipeline/v7_extract/structural_scanner.py` 暴露 `scan_markdown(text)`
   / `scan_plain(text)` 函数
2. 输出 `StructuralBlock` 列表：每 block 含 (kind, start_byte, end_byte, level, text_excerpt)
3. Stage 2 segmentation / canonical span 派生可消费 scanner 输出
4. 100% deterministic（同一输入 → 同一输出；sha1 输出可作 fingerprint 的一部分）

### 1.2 Non-Goal

- **不**改 Stage 2 现有 article_segmenter / segmentation.py 行为（先建 scanner，后续 Task 接入）
- **不**调用 LLM（这是 deterministic 层）
- **不**改 frontmatter / wiki writer

## 2. 模型

```python
class StructuralBlockKind(str, Enum):
    HEADING = "heading"           # # / ## / ### ... 
    PARAGRAPH = "paragraph"       # 双换行分隔的文本段
    CODE_BLOCK = "code_block"     # ```...``` 围栏
    LIST_ITEM = "list_item"       # - / * / 1. / 2. ...
    BLOCKQUOTE = "blockquote"     # > ...（可多行）
    HORIZONTAL_RULE = "hr"       # --- / *** / ___ (整行)
    TABLE = "table"               # | col | col | （可选，本期简化不实现）
    BLANK_LINE = "blank_line"     # 空行（仅用于 debug）

@dataclass(frozen=True)
class StructuralBlock:
    kind: StructuralBlockKind
    start_byte: int               # UTF-8 byte offset against source_bytes
    end_byte: int                 # exclusive
    level: int = 0                # heading level (1-6) or list indent depth
    text: str = ""                # 块原文（解码后）
```

## 3. Files

- `src/pipeline/v7_extract/structural_scanner.py`（新建）
- `tests/test_pipeline/test_v7_extract_structural_scanner.py`（新建）

## 4. Tests

```python
def test_scan_markdown_finds_headings_at_byte_offsets():
    """heading 块 start_byte/end_byte 精确"""

def test_scan_markdown_finds_fenced_code_block():
    """```...``` 围栏被识别为 code_block，byte 范围精确"""

def test_scan_markdown_handles_unclosed_fence_gracefully():
    """未闭合 fence → 剩余文本视为 plain paragraph"""

def test_scan_markdown_separates_paragraphs_by_blank_lines():
    """双换行分块"""

def test_scan_plain_returns_single_paragraph():
    """纯文本（无 markdown 标记）→ 1 个 paragraph block"""

def test_scanner_output_is_deterministic():
    """sha1(blocks) 跨次调用稳定 → 可作 fingerprint 输入"""

def test_block_byte_ranges_cover_full_input_without_overlap():
    """所有 block [start, end) 不重叠 + 覆盖全部 input bytes"""
```

## 5. Implementation

### 5.1 structural_scanner.py

```python
import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

class StructuralBlockKind(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    LIST_ITEM = "list_item"
    BLOCKQUOTE = "blockquote"
    HORIZONTAL_RULE = "hr"
    TABLE = "table"
    BLANK_LINE = "blank_line"

@dataclass(frozen=True)
class StructuralBlock:
    kind: StructuralBlockKind
    start_byte: int
    end_byte: int
    level: int = 0
    text: str = ""

_FENCE_RE = re.compile(r"^(```+|~~~+)(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HR_RE = re.compile(r"^(\s*[-*_])\1{2,}\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?")

def scan_markdown(text: str) -> list[StructuralBlock]:
    """Deterministic markdown structural scanner. Pure function.
    
    Algorithm:
      1. Walk lines, track current state (in_code_block? fence_marker?)
      2. Each line classified as: heading / code_block_line / list_item /
         blockquote / hr / paragraph / blank
      3. Coalesce consecutive same-kind lines into blocks
      4. Compute byte offsets against text.encode('utf-8')
    
    Returns a list of StructuralBlock covering the entire input
    (start_byte of block 0 == 0, end_byte of last block == len(text.encode('utf-8'))).
    No block overlap.
    """

def scan_plain(text: str) -> list[StructuralBlock]:
    """Plain text → 1 paragraph covering the whole text (or empty list if blank)."""

def blocks_to_fingerprint(blocks: list[StructuralBlock]) -> str:
    """sha1 of (kind|start_byte|end_byte|level|text) per block → 'sc-' + 16hex.
    
    Stable across runs given same text input.
    """
    identity = "|".join(
        f"{b.kind.value}|{b.start_byte}|{b.end_byte}|{b.level}|{b.text}"
        for b in blocks
    )
    return "sc-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
```

### 5.2 不动 Stage 2 现有模块

**F8 纪律**：不调用 scanner 进 Stage 2 流程。本 Task 只产出 scanner 模块 + 测试。
Stage 2 接线留给 Task 42 (bounded LLM window resolver)。

## 6. Acceptance

- ✅ 7 个测试全绿
- ✅ block byte 范围覆盖完整 input + 不重叠
- ✅ 100% deterministic（fingerprints match 跨次调用）
- ✅ existing 53+ v7_extract + 32 reconciliation 测试 0 回归
- ✅ 不引入新依赖