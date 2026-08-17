# AtomicContext + BudgetedLLM Design Spec

**Date:** 2026-07-22
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 9e91ab9, post-Metrics spec)
**Inspired by:** Novel-Knowledge-Base v3.4 `src/lib/atomic_ctx.py` + `src/lib/context_budget.py`

## Goal

Two utility modules that solve recurring cross-cutting concerns:

1. **AtomicContext** — A process-global `_suspended` flag + `AtomicContext` context manager that suppresses disk-write side-effects during multi-step operations. Used by `cascade_delete` (delete source + clean wikilinks + rebuild index must commit atomically), `lint --fix` (multi-page fixes must commit together), `dedup auto` (merge + archive + re-index must commit together).

2. **BudgetedLLM** — A `with BudgetedLLM()` context manager that:
   - Estimates token count of the prompt using a conservative character-based heuristic (0.5 token/char, ±20% accuracy)
   - Splits long text by paragraph boundary (`\n\n`) if it exceeds the model's context window
   - Wraps LLM calls in a chunked/recursive fashion, automatically aggregating results
   - Globally wraps all LLM calls (analyzer / generator / judge / chat / web research) — no caller needs to know

## Non-goals

- No tiktoken or model-specific tokenizers (deferred; char-based heuristic is sufficient for safety).
- No streaming output aggregation across chunks (caller responsibility).
- No automatic roll-back on partial failure (caller responsibility — `AtomicContext.flush_callback` runs even on exception via `finally`).
- No multi-process suspension (single-process assumption; v1).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `AtomicContext` context manager (atomic multi-step commits)
- `BudgetedLLM` context manager (token budget chunking)
- `safe_write()` hook (respects AtomicContext)
- 0.5 token/char conservative estimator

**This spec requires from other specs**:

- **src/shared/**: error classes

**Phase**: Phase 1 — Foundations (parallel)
**Priority**: P0 — MVP

## Architecture

```
AtomicContext:
  ┌────────────────────────────────────────────────┐
  │  Process-global _suspended: bool               │
  │  Process-global _stack_depth: int              │
  │  Optional _flush_callbacks: list[Callable]    │
  └────────────────────────────────────────────────┘
       │
       ▼
  Every write hook checks is_suspended() before touching disk:
    def safe_write(path, content):
        if atomic_ctx.is_suspended():
            return  # skip; caller will batch
        path.write_text(content)

  Context manager:
    with AtomicContext(flush_callback=merge_writes):
        do_many_writes()    # all skipped from disk
        # exit: flush_callback() merges all writes + flushes once

  Nested semantics:
    with AtomicContext():
        with AtomicContext():  # inner is no-op
            ...

BudgetedLLM:
  ┌────────────────────────────────────────────────┐
  │  Estimate tokens of prompt                      │
  │  If exceeds model.context_window:               │
  │    Split by \n\n boundary                      │
  │    Loop: call LLM on each chunk                │
  │    Aggregate results (concat for chat,         │
  │      merge for JSON, list for list[T])          │
  │  Else: single LLM call                         │
  └────────────────────────────────────────────────┘
```

## Components

### New modules

```
src/lib/atomic_ctx.py             # AtomicContext + is_suspended() + flush_callback
src/lib/context_budget.py        # estimate_tokens + chunk_by_budget + BudgetedLLM
src/lib/write_hooks.py            # safe_write() wrapper used by all write paths
src/lib/llm_wrapper.py            # budgeted_llm_call() — wraps LLMProvider.complete/stream
tests/test_lib/test_atomic_ctx.py
tests/test_lib/test_context_budget.py
tests/test_lib/test_budgeted_llm.py
tests/test_lib/test_write_hooks.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/wiki/page_writer.py` | All `*.write_text(...)` calls go through `safe_write()` |
| `src/wiki/indexer.py` | `indexer.append_pages()` accumulates in-memory during suspended, flushes on exit |
| `src/wiki/dedup.py` | `merge_duplicate_group` enters `AtomicContext` for atomic commit |
| `src/wiki/cascade_delete.py` | Already uses mutex; wrap multi-step ops in AtomicContext |
| `src/llm/base.py` | `LLMProvider.complete` and `complete_stream` go through `budgeted_llm_call()` |
| `src/pipeline/judge.py` | `judge_batch` uses `with BudgetedLLM()` to ensure each page fits context |

## Data structures

```python
# src/lib/atomic_ctx.py
import threading
from typing import Callable

_lock = threading.Lock()
_suspended: bool = False
_stack_depth: int = 0
_flush_callbacks: list[Callable[[], None]] = []

def is_suspended() -> bool:
    """Returns True if any AtomicContext is active in this process."""
    with _lock:
        return _suspended

class AtomicContext:
    """Suspends all disk-write hooks until exit. Nested = no-op inner.
    
    Usage:
        with AtomicContext(flush_callback=merge_pending_writes):
            page_writer.write(page_a)   # skipped from disk
            page_writer.write(page_b)   # skipped from disk
            # exit: flush_callback() merges page_a + page_b writes + flushes once
    """
    
    def __init__(self, flush_callback: Callable[[], None] | None = None):
        self._flush_callback = flush_callback
        self._is_outer = False
    
    def __enter__(self) -> "AtomicContext":
        global _suspended, _stack_depth
        with _lock:
            if _stack_depth == 0:
                _is_outer = True
                _suspended = True
            _stack_depth += 1
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        global _suspended, _stack_depth
        with _lock:
            _stack_depth -= 1
            if _stack_depth == 0:
                _suspended = False
        # Flush callback runs once, only on outer context, after _suspended reset
        # so flush writes are NOT re-suspended
        if self._is_outer and self._flush_callback:
            try:
                self._flush_callback()
            except Exception as e:
                # Flush failures should not be silently swallowed
                # Re-raise if no inner exception, otherwise log + continue
                if exc_val is None:
                    raise
                logger.error(f"[AtomicContext] flush_callback failed: {e}")
```

```python
# src/lib/context_budget.py
def estimate_tokens(text: str) -> int:
    """Conservative: 0.5 token per character (covers CJK + English + emoji).
    
    For 1000-char Chinese page: ~1500 tokens (BPE usually 1-2 token/char).
    For 1000-char English page: ~250 tokens (BPE usually 0.25-0.5 token/char).
    
    Conservative ensures we under-estimate EN and over-estimate CJK;
    cost is occasionally splitting text that could have fit in one call (acceptable).
    """
    return len(text) // 2

def chunk_by_budget(text: str, max_tokens: int) -> list[str]:
    """Split text by paragraph boundary (\n\n) so each chunk fits in max_tokens.
    
    If a single paragraph exceeds max_tokens, split by sentence boundary (. ! ? 。 ！ ？).
    If a sentence exceeds max_tokens, hard-split by max_tokens chars.
    """
    if estimate_tokens(text) <= max_tokens:
        return [text]
    
    paragraphs = text.split("\n\n")
    chunks = []
    current = []
    current_tokens = 0
    
    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        if current and current_tokens + para_tokens > max_tokens:
            chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks

class BudgetedLLM:
    """Context manager: chunked LLM calls with automatic aggregation.
    
    Usage:
        with BudgetedLLM(model=ctx.settings.llm, op="analyzer") as bl:
            result = await bl.call(prompt=long_text, response_format=AnalysisResult)
            # If prompt fits, single call.
            # If not, split + parallel call + merge.
    """
    
    def __init__(self, model: str, op: str = "general"):
        self.model = model
        self.op = op
        self._chunks_processed: int = 0
    
    async def call(
        self,
        prompt: str,
        response_format: dict | None = None,
        system: str | None = None,
    ) -> dict | list:
        """Call LLM, chunking prompt if exceeds model.context_window."""
        ctx_window = get_model_context_window(self.model)  # from registry
        prompt_tokens = estimate_tokens(prompt)
        
        if prompt_tokens <= ctx_window * 0.8:   # 80% safety margin
            # Single call
            self._chunks_processed += 1
            return await self._single_call(prompt, response_format, system)
        
        # Multi-chunk: split + parallel call + merge
        chunks = chunk_by_budget(prompt, int(ctx_window * 0.6))   # 60% to leave room for output
        self._chunks_processed += len(chunks)
        tasks = [self._single_call(chunk, response_format, system) for chunk in chunks]
        results = await asyncio.gather(*tasks)
        return self._merge_results(results, response_format)
    
    async def _single_call(self, prompt, response_format, system) -> dict:
        return await create_llm_provider(self.model).complete(prompt, response_format, system)
    
    def _merge_results(self, results: list[dict], response_format: dict | None) -> dict | list:
        if not results:
            return {}
        if response_format and response_format.get("type") == "object":
            # Merge objects: concatenate array fields, take first of scalar fields
            merged = {}
            for r in results:
                for k, v in r.items():
                    if isinstance(v, list):
                        merged.setdefault(k, []).extend(v)
                    else:
                        merged.setdefault(k, v)
            return merged
        if response_format and response_format.get("type") == "array":
            # Flatten + dedupe by some key (e.g., 'id' or 'slug')
            merged = []
            seen = set()
            for r in results:
                for item in r.get("items", []):
                    key = item.get("id") or item.get("slug")
                    if key not in seen:
                        seen.add(key)
                        merged.append(item)
            return {"items": merged}
        # Default: concatenate as list
        return results
    
    @property
    def chunks_processed(self) -> int:
        return self._chunks_processed
```

```python
# src/lib/write_hooks.py
from .atomic_ctx import is_suspended
from pathlib import Path

_pending_writes: dict[Path, str] = {}

def safe_write(path: Path, content: str, atomic: bool = True) -> None:
    """Write file respecting AtomicContext.
    
    If suspended: accumulate in _pending_writes (caller will batch via flush_callback).
    Else: write directly.
    """
    if atomic and is_suspended():
        _pending_writes[path] = content
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def flush_pending_writes() -> int:
    """Called by AtomicContext.flush_callback. Returns number of writes flushed."""
    count = len(_pending_writes)
    for path, content in list(_pending_writes.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _pending_writes.clear()
    return count

def get_pending_count() -> int:
    return len(_pending_writes)
```

## CLI surface

```
python -m src.cli atomic status
    # Show current _suspended + _stack_depth

python -m src.cli atomic test
    # Run a sample atomic operation (e.g., delete one source + reindex) and report

python -m src.cli budget estimate <file>
    # Print estimated token count for file contents

python -m src.cli budget check <model> <file>
    # Show whether file fits in model's context window
```

## HTTP endpoint

```
GET /api/v1/projects/{id}/metrics/internal
    # Returns _suspended + _stack_depth + pending_writes count
    # (debug/diagnostic endpoint, localhost-only)
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| AtomicContext flush_callback | Exception during flush | If outer ctx had exception: log + continue (don't mask); else: re-raise |
| safe_write | Path doesn't exist | Create parent dirs (mkdir parents=True) |
| safe_write | Disk full | Raise IOError (let caller decide) |
| AtomicContext nested | Inner ctx exits before outer | Inner is no-op; outer's flush runs once at deepest exit |
| BudgetedLLM | Chunk merge conflict (same key, different values) | First-wins; log warning |
| BudgetedLLM | Single chunk call fails | Other chunks may succeed; partial result with `errors` field |
| BudgetedLLM | Token estimate wildly off | Conservative 0.5 ensures we under-call (safer than over-call which causes API errors) |
| Multi-process | Two processes both suspended | Out of scope; v1 single-process assumption |

## Backwards compatibility

- `AtomicContext` is purely additive — existing code without `with AtomicContext()` continues to write immediately.
- `BudgetedLLM` is opt-in via `with BudgetedLLM():` context manager. **However**, since the spec says "globally wraps all LLM calls", the LLMProvider wrapper is always active. Code that calls `LLMProvider.complete()` directly will get chunked behavior automatically.
- Token estimation is conservative (0.5 token/char); some calls that could have fit in one call may be split. Behavior change is "more reliable, slightly slower" — acceptable trade-off.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/lib/atomic_ctx.py` | Single context; nested; exception in body; flush_callback called once; thread-safe |
| `src/lib/context_budget.py` | estimate_tokens; chunk_by_budget (paragraph + sentence + hard split); merge_results |
| `src/lib/write_hooks.py` | safe_write bypass when suspended; pending_writes accumulation; flush |
| `src/lib/llm_wrapper.py` | Single-call when fits; multi-chunk when exceeds; merge objects/arrays |

### Integration tests

```
tests/test_integration/test_atomic_cascade_delete.py:
    def test_cascade_delete_is_atomic():
        # Create 10 wiki pages with relations
        # Run cmd_cascade_delete
        # Verify: all related pages updated or none (no partial state)

    def test_atomic_context_lint_fix():
        # Run cmd_lint --fix on 5 broken pages
        # Verify: all 5 fixed or none

tests/test_integration/test_budgeted_llm.py:
    def test_long_prompt_chunked():
        # 50K char prompt + 8K context model
        # Verify: multiple chunks called; results merged

    def test_short_prompt_single_call():
        # 1K char prompt
        # Verify: 1 chunk only
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P0)

- AtomicContext with nested semantics
- `safe_write` hook + `flush_pending_writes`
- BudgetedLLM with paragraph chunking
- 0.5 token/char conservative estimator
- CLI: `atomic status / budget estimate / budget check`

### Polish (v2.0.1 or later)

- Per-thread / per-async-task suspension
- Streaming output aggregation across chunks

### Deferred (v2.1+)

- tiktoken / model-specific tokenizers
- Multi-process coordination
- Persistent suspension state across crashes

## Implementation order

5 phases:

1. **AtomicContext core** — `atomic_ctx.py` + thread safety + tests
2. **safe_write + write_hooks** — accumulate writes + flush + tests
3. **BudgetedLLM core** — `context_budget.py` + chunk_by_budget + tests
4. **LLM wrapper + integration** — wrap all LLM calls + chunked execution + tests
5. **Wire into existing modules** — cascade_delete / lint --fix / dedup auto use AtomicContext; pipeline uses BudgetedLLM

## Cost estimation

- AtomicContext: minimal overhead (thread lock + dict ops)
- BudgetedLLM: 0% token overhead (estimation is local)
- Chunked calls: 1-5% additional LLM calls for prompts near boundary (acceptable safety)
- Bundle: ~5KB (no new dependencies)

## Open questions / deferred

- tiktoken / model-specific tokenizer integration.
- Multi-process coordination (lock file on disk).
- Streaming output aggregation across chunks.
- Persistent suspension state across crashes (currently in-memory only).
- Per-thread / per-async-task suspension (currently process-global).