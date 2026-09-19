# Plan: Task 42 — Stage 2 bounded LLM window resolver

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第三批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 42)
**Depends:** Task 41 (`structural_scanner.py`)

## 0. 上下文

Stage 2 现有一阶段 LLM 调用（Task 3-5）：一次 prompt 让 LLM 全文 segmentation。
这违反 Bounded Evidence Contract §3.2（Master plan §3.2 规定 Stage 2 输入每个 window 1500 chars）。

**Task 42 目标**：建立**bounded window resolver**，按 scanner 切出的 paragraph / heading 块分组，
LLM 每次只看到一个 window（≤ 1500 chars），输出该 window 的语义边界 + 候选 item 起点。

**关键原则**：LLM 输入**严格 bounded**（1500 chars max）；scanner 切 + window 合并 + LLM 收
的 pipeline 替代一次性全文 prompt。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `resolve_windows(blocks, *, max_window_chars=1500) -> list[Window]` 纯函数
2. `async def call_window_resolver(windows, llm, ...) -> list[ResolvedItem]` 异步主入口
3. 不替换 Stage 2 segmentation（既不删旧路径，也不切换默认）—— 新模块独立可调用

### 1.2 Non-Goal

- **不**改 `article_segmenter.py` / `segmentation.py` 主流程
- **不**写 prompt（Task 42 是 resolver 基础设施，prompt 留给后续）
- **不**改 frontmatter / wiki writer

## 2. 模型

```python
@dataclass(frozen=True)
class Window:
    window_id: str                          # win-<sha1(canonical_id|block_range)[:12]>
    block_range: tuple[int, int]            # (first_block_index, last_block_index) inclusive
    start_byte: int
    end_byte: int
    text: str                               # concatenated block texts (≤ max_window_chars)
    block_kinds: list[StructuralBlockKind]   # for context

class ResolverVerdict(str, Enum):
    KEEP = "keep"             # block stays as-is (single item)
    SPLIT = "split"           # block contains multiple items; LLM returns split points
    MERGE = "merge"           # block joins adjacent blocks
    NOISE = "noise"           # boilerplate / nav / skip
    UNRESOLVED = "unresolved" # LLM failure

@dataclass
class ResolvedItem:
    window_id: str
    block_range: tuple[int, int]
    verdict: ResolverVerdict
    confidence: float
    split_points: list[int] = field(default_factory=list)  # byte offsets within window
```

## 3. Files

- `src/pipeline/v7_extract/window_resolver.py`（新建）
- `tests/test_pipeline/test_v7_extract_window_resolver.py`（新建）

## 4. Tests

```python
def test_resolve_windows_groups_blocks_under_max_chars():
    """多个小 block 合并成一个 ≤1500 chars window"""

def test_resolve_windows_splits_oversized_block():
    """单个 >1500 chars block 拆成 2 windows"""

def test_resolve_windows_preserves_byte_ranges():
    """window.start_byte/end_byte 准确对应 blocks 的并集"""

def test_resolver_verdict_enum_has_five_values():
    """KEEP / SPLIT / MERGE / NOISE / UNRESOLVED"""

def test_call_window_resolver_invokes_llm_per_window():
    """每 window 一次 LLM 调用"""

def test_call_window_resolver_technical_failure_marks_unresolved():
    """LLM 失败 → 该 window UNRESOLVED"""
```

## 5. Implementation

```python
MAX_WINDOW_CHARS = 1500  # master plan §3.2

def resolve_windows(
    blocks: list[StructuralBlock],
    *,
    max_window_chars: int = MAX_WINDOW_CHARS,
    source_bytes: bytes,
) -> list[Window]:
    """Greedy coalesce blocks into windows, each ≤ max_window_chars.
    
    Each block is added to the current window if its text fits; otherwise
    the current window closes and a new one starts with this block.
    Oversized single blocks (text > max_window_chars) are split into
    multi-block pieces at sentence boundaries (if any) or character
    boundaries.
    """

async def call_window_resolver(
    windows: list[Window],
    *,
    llm: LLMClient,
    template: Any | None = None,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> list[ResolvedItem]:
    """Per-window LLM call. LLM returns ResolverVerdict per window.
    
    Bounded Evidence §3.2: each LLM call sees ONLY window.text (≤ 1500 chars),
    never the whole document.
    
    Technical failure (all retries exhausted) → UNRESOLVED.
    Never raises (Failure Contract §1).
    """
```

## 6. Acceptance

- ✅ 6 个测试全绿
- ✅ window.text 始终 ≤ 1500 chars
- ✅ LLM 输入严格 bounded
- ✅ 现有 v7_extract + reconciliation 测试 0 回归
- ✅ 不引入新依赖