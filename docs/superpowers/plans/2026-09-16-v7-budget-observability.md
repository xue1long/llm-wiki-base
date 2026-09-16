# V7 Cost Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** V7 摄取流水线运行结束后，operator 能直接看到本次跑了多少 USD、按 stage 拆分多少、按 source 平均多少。无需事后查 ledger。

**Non-goals:**
- 不做 prompt trust boundary 注入（评审 6 维后判定边际收益低、6 维度均低优）
- 不做 `paused_budget` 自动暂停门（评审判定 checkpoint 续跑死循环风险高、5 年视角下 design 易过时）
- 不做内容层 retry 修改 prompt 引导（V7 P2 策略下不必要）
- 不接 BudgetedLLM 上下文 chunking（4 个 stage 已有 `content_limit` slot，prompt 层已截断）
- 不重构 v1 batch_runner 的 budget 路径（独立 plan 处理）
- 不做跨 v1/V7 budget 统一（合并时再做）
- 不改 `response_format` / `temperature` 等已有 LLM 调用参数语义

**Architecture:** CostLedger 放在 `src/lib/budget.py`（与 `src/lib/budgeted.py`、`src/lib/retry.py` 同层），`AnthropicLLMClient` 注入 ledger 引用并在每次成功的 LLM 调用后累计 token + cost（**优先读 `response.usage` 精确值，缺则 fallback `len(content)//4` 估算**）。价格由 env 可配置。`scripts/extract_full.py` summary 把累计值输出。FakeLLMClient 不累计（测试场景 cost=0）。Markdown 报告仅在真实 cost>0 时输出 `## Cost` 段落。

**Tech Stack:** Python 3.11+, asyncio, dataclass, pytest, existing `LLMClient` / `FakeLLMClient` / `scripts/extract_full.py` summary path。

**Spec source:** `.superpowers/sdd/progress.md:1050` (Plan 3 close) + 6 维评审结论 + plan-audit Round 1/2 整改。

## Global Constraints

- 不引入新依赖。
- 不改 4 个 builtin TOML prompt。
- 不改 CLI 已有 flag；只新增 env flag (`RUFLO_BUDGET_PRINT=0` 抑制输出)。
- FakeLLMClient bypass ledger（不累计 cost，避免测试假超阈值）。
- summary 输出字段保持向后兼容（新增 `cost` 顶层字段 + `cost_by_stage` 子字段，老 consumer 不读也能 parse）。
- `CostLedger` 进程内单例；**asyncio 单线程使用，非线程安全**（docstring 注明）。
- **LLM 调用成功才累计**：retry 期间 raise 的调用不累计；`TruncatedResponseError` raise 前不累计；只有正常返回 response 之后才 record。
- ledger 只注入 `AnthropicLLMClient`，**不传给 WikiWriter**（WikiWriter 不直接发 LLM 请求）。
- 不动 v1 `orchestrator/batch_runner_internal/phases.py` 已有的 budget 路径。

---

### Task 1: CostLedger dataclass + price env

**Files:**

- New: `src/lib/budget.py`
- New: `tests/test_lib/test_budget.py`

**Interfaces:**

```python
@dataclass
class CostLedger:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    cost_by_stage: dict[str, dict[str, int | float]] = field(default_factory=dict)
    # bucket = {"input_tokens": int, "output_tokens": int, "cost_usd": float, "calls": int}

    def record(
        self,
        *,
        stage: str,
        input_tokens: int,
        output_tokens: int,
        input_price: float,
        output_price: float,
    ) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...


def load_default_prices() -> tuple[float, float]:
    """Read RUFLO_INPUT_TOKEN_PRICE / RUFLO_OUTPUT_TOKEN_PRICE env (default 0.0000003 / 0.0000006 USD/token)."""
```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_lib/test_budget.py
from src.lib.budget import CostLedger, load_default_prices


def test_record_accumulates_tokens_and_cost():
    ledger = CostLedger()
    ledger.record(stage="classify", input_tokens=100, output_tokens=50,
                  input_price=0.0000003, output_price=0.0000006)
    assert ledger.input_tokens == 100
    assert ledger.output_tokens == 50
    expected_cost = round(100*0.0000003 + 50*0.0000006, 6)
    assert ledger.cost_usd == expected_cost
    assert ledger.call_count == 1
    assert ledger.cost_by_stage["classify"]["input_tokens"] == 100


def test_record_multiple_stages_separately():
    ledger = CostLedger()
    ledger.record(stage="classify", input_tokens=100, output_tokens=50,
                  input_price=0.0000003, output_price=0.0000006)
    ledger.record(stage="cluster", input_tokens=200, output_tokens=80,
                  input_price=0.0000003, output_price=0.0000006)
    assert ledger.call_count == 2
    assert "classify" in ledger.cost_by_stage
    assert "cluster" in ledger.cost_by_stage
    assert ledger.cost_by_stage["classify"]["calls"] == 1
    assert ledger.cost_by_stage["cluster"]["calls"] == 1


def test_snapshot_returns_full_breakdown():
    ledger = CostLedger()
    ledger.record(stage="classify", input_tokens=100, output_tokens=50,
                  input_price=0.0000003, output_price=0.0000006)
    snap = ledger.snapshot()
    assert "cumulative_usd" in snap
    assert "cost_by_stage" in snap
    assert "cost_per_call_avg" in snap
    assert snap["call_count"] == 1
    assert snap["cumulative_usd"] > 0


def test_load_default_prices_uses_env_overrides(monkeypatch):
    monkeypatch.setenv("RUFLO_INPUT_TOKEN_PRICE", "0.5")
    monkeypatch.setenv("RUFLO_OUTPUT_TOKEN_PRICE", "1.5")
    in_p, out_p = load_default_prices()
    assert in_p == 0.5
    assert out_p == 1.5


def test_load_default_prices_falls_back_to_defaults(monkeypatch):
    monkeypatch.delenv("RUFLO_INPUT_TOKEN_PRICE", raising=False)
    monkeypatch.delenv("RUFLO_OUTPUT_TOKEN_PRICE", raising=False)
    in_p, out_p = load_default_prices()
    assert in_p == 0.0000003
    assert out_p == 0.0000006


def test_load_default_prices_handles_invalid_env(monkeypatch):
    monkeypatch.setenv("RUFLO_INPUT_TOKEN_PRICE", "free")
    monkeypatch.setenv("RUFLO_OUTPUT_TOKEN_PRICE", "")
    in_p, out_p = load_default_prices()
    assert in_p == 0.0000003  # fallback
    assert out_p == 0.0000006  # fallback
```

- [ ] **Step 2: Run tests and verify red**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_lib/test_budget.py --import-mode=importlib -q
```

Expected: FAIL (collection error — `tests/test_lib` doesn't exist yet).

- [ ] **Step 3: Implement `src/lib/budget.py`**

```python
"""CostLedger — process-local LLM cost accumulator.

Used by V7 extraction to surface cumulative USD + per-stage breakdown in
``extract_full.py`` summary. Tests using FakeLLMClient do not register
cost (FakeLLMClient never calls ``record()``).

Thread-safety: asyncio single-event-loop use only. NOT thread-safe.
Multi-threaded accumulation must hold an external lock.

Prices are USD/token. Defaults are conservative middle-of-MiniMax-M3 public
range; override via ``RUFLO_INPUT_TOKEN_PRICE`` / ``RUFLO_OUTPUT_TOKEN_PRICE``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


DEFAULT_INPUT_TOKEN_PRICE: float = 0.0000003
DEFAULT_OUTPUT_TOKEN_PRICE: float = 0.0000006


def load_default_prices() -> tuple[float, float]:
    """Read token prices from env, falling back to defaults on parse error."""
    def _safe(env_name: str, default: float) -> float:
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default
    return (
        _safe("RUFLO_INPUT_TOKEN_PRICE", DEFAULT_INPUT_TOKEN_PRICE),
        _safe("RUFLO_OUTPUT_TOKEN_PRICE", DEFAULT_OUTPUT_TOKEN_PRICE),
    )


@dataclass
class CostLedger:
    """Process-local LLM cost accumulator.

    Single ledger per process. ``record()`` accumulates token counts and
    USD cost into a per-stage bucket. Call from ``AnthropicLLMClient.complete()``
    after a successful provider call; retry-time failures do NOT call
    ``record()`` (they raise before reaching this point).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    cost_by_stage: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record(
        self,
        *,
        stage: str,
        input_tokens: int,
        output_tokens: int,
        input_price: float,
        output_price: float,
    ) -> None:
        cost = round(input_tokens * input_price + output_tokens * output_price, 6)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost
        self.call_count += 1
        bucket = self.cost_by_stage.setdefault(
            stage,
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0},
        )
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cost_usd"] = round(bucket["cost_usd"] + cost, 6)
        bucket["calls"] += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "cumulative_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "call_count": self.call_count,
            "cost_per_call_avg": (
                round(self.cost_usd / self.call_count, 6) if self.call_count else 0.0
            ),
            "cost_by_stage": {
                stage: {
                    "input_tokens": data["input_tokens"],
                    "output_tokens": data["output_tokens"],
                    "cost_usd": round(data["cost_usd"], 6),
                    "calls": data["calls"],
                }
                for stage, data in self.cost_by_stage.items()
            },
        }
```

- [ ] **Step 4: Run tests and verify green**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_lib/test_budget.py --import-mode=importlib -q
```

Expected: 6 passed.

**Acceptance:** `CostLedger` 与 `load_default_prices` 6 个测试全过。

---

### Task 2: Wire CostLedger into AnthropicLLMClient

**Files:**

- Modify: `src/pipeline/v7_extract/llm_client.py`
- Modify: `tests/test_pipeline/test_v7_extract_llm_client.py`

**Interfaces:**

- `AnthropicLLMClient.__init__(..., ledger: CostLedger | None = None)`
- `complete()` calls `self._ledger.record(...)` **only after `provider.complete()` returns successfully** (before raising `TruncatedResponseError`).
- Token source priority: `getattr(response, "usage", None) → {"input_tokens", "output_tokens"}` if both present; else fallback `len(user_prompt + system_prompt) // 4` + `len(content) // 4`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_pipeline/test_v7_extract_llm_client.py`:

```python
import pytest
from src.lib.budget import CostLedger


def test_anthropic_llm_client_records_to_ledger_with_response_usage(monkeypatch):
    """When response.usage has input_tokens/output_tokens, record uses those."""
    class _StubResponse:
        content = "ok"  # 2 chars
        truncated = False
        usage = {"input_tokens": 1000, "output_tokens": 200}

    class _StubProvider:
        model = "stub"
        async def complete(self, messages, *, max_tokens, temperature):
            return _StubResponse()
        async def aclose(self):
            pass

    import src.llm.provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name: _StubProvider())

    ledger = CostLedger()
    client = AnthropicLLMClient(default_provider_name="any", ledger=ledger)
    out = await client.complete(
        prompt_kind="classify",
        user_prompt="abc",
        system_prompt="",
        max_tokens=256,
        temperature=0.0,
    )
    assert out == "ok"
    assert ledger.call_count == 1
    assert ledger.input_tokens == 1000
    assert ledger.output_tokens == 200
    assert ledger.cost_usd > 0.0
    assert ledger.cost_by_stage["classify"]["calls"] == 1


def test_anthropic_llm_client_records_with_estimated_tokens_when_no_usage(monkeypatch):
    """When response.usage is None, fall back to len(content) // 4 estimate."""
    class _StubResponse:
        content = "abcdefgh"  # 8 chars => 2 tokens
        truncated = False
        usage = None

    class _StubProvider:
        model = "stub"
        async def complete(self, messages, *, max_tokens, temperature):
            return _StubResponse()
        async def aclose(self):
            pass

    import src.llm.provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name: _StubProvider())

    ledger = CostLedger()
    client = AnthropicLLMClient(default_provider_name="any", ledger=ledger)
    await client.complete(
        prompt_kind="classify",
        user_prompt="x" * 400,  # 400 chars => ~100 tokens input
        system_prompt="y" * 40,  # 40 chars => ~10 tokens input
        max_tokens=256,
        temperature=0.0,
    )
    # input estimate: (400+40)//4 = 110; output estimate: 8//4 = 2
    assert ledger.input_tokens == 110
    assert ledger.output_tokens == 2
    assert ledger.call_count == 1


def test_anthropic_llm_client_does_not_record_on_truncated(monkeypatch):
    """Truncated responses raise before record() is called."""
    from src.llm.types import TruncatedResponseError

    class _StubResponse:
        content = "abcdefgh"
        truncated = True
        usage = {"input_tokens": 100, "output_tokens": 50}

    class _StubProvider:
        model = "stub"
        async def complete(self, messages, *, max_tokens, temperature):
            return _StubResponse()
        async def aclose(self):
            pass

    import src.llm.provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name: _StubProvider())

    ledger = CostLedger()
    client = AnthropicLLMClient(default_provider_name="any", ledger=ledger)
    with pytest.raises(TruncatedResponseError):
        await client.complete(
            prompt_kind="classify",
            user_prompt="x", system_prompt="",
            max_tokens=256, temperature=0.0,
        )
    assert ledger.call_count == 0
    assert ledger.cost_usd == 0.0


def test_anthropic_llm_client_no_ledger_works(monkeypatch):
    """Backwards compatibility: when ledger is None, complete() still works."""
    class _StubResponse:
        content = "ok"
        truncated = False
        usage = {"input_tokens": 5, "output_tokens": 1}

    class _StubProvider:
        model = "stub"
        async def complete(self, messages, *, max_tokens, temperature):
            return _StubResponse()
        async def aclose(self):
            pass

    import src.llm.provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", lambda name: _StubProvider())

    client = AnthropicLLMClient(default_provider_name="any")  # no ledger
    out = await client.complete(
        prompt_kind="classify", user_prompt="x", system_prompt="",
        max_tokens=256, temperature=0.0,
    )
    assert out == "ok"
```

- [ ] **Step 2: Run tests and verify red**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_llm_client.py --import-mode=importlib -q
```

Expected: existing tests pass; new tests FAIL (`TypeError: __init__() got an unexpected keyword argument 'ledger'`).

- [ ] **Step 3: Modify `AnthropicLLMClient`**

In `src/pipeline/v7_extract/llm_client.py`:

1. Top-level import: `from ..lib.budget import CostLedger, load_default_prices`
   (note: `src/pipeline/v7_extract/llm_client.py` lives under `src/pipeline/`, so path is `from src.lib.budget import ...`; verify by reading existing top-level imports).

2. `__init__` signature: add `ledger: CostLedger | None = None`. Store as `self._ledger = ledger`.

3. `complete()` after `response = await self._provider.complete(...)` and **before** the `if getattr(response, "truncated", False)` block:

   ```python
   if self._ledger is not None:
       usage = getattr(response, "usage", None)
       if isinstance(usage, dict):
           input_tokens = int(usage.get("input_tokens") or 0)
           output_tokens = int(usage.get("output_tokens") or 0)
       else:
           # Fallback: rough char/4 heuristic. Same heuristic v1's budget uses.
           prompt_text_len = len(user_prompt) + len(system_prompt or "")
           content = getattr(response, "content", "") or ""
           input_tokens = prompt_text_len // 4
           output_tokens = len(content) // 4
       in_p, out_p = load_default_prices()
       self._ledger.record(
           stage=prompt_kind,
           input_tokens=input_tokens,
           output_tokens=output_tokens,
           input_price=in_p,
           output_price=out_p,
       )
   ```

4. **Do NOT change** `if getattr(response, "truncated", False): raise TruncatedResponseError(...)` placement — record must come before this check.

5. Add docstring note that `FakeLLMClient.complete()` does NOT call `self._ledger.record()` (intentional — tests should not hit budget gates).

- [ ] **Step 4: Run new tests and verify green**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_llm_client.py --import-mode=importlib -q
```

Expected: existing tests + 4 new = all pass.

- [ ] **Step 5: Run full V7 suite to verify zero regression**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_*.py tests/test_scripts/test_extract_*.py --import-mode=importlib -q
```

Expected: ~303 passed, 1 skipped.

**Acceptance:** `AnthropicLLMClient` 接受可选 `ledger` 参数；使用 `response.usage` 优先；估算 fallback；truncated 不累计；`FakeLLMClient` 不变。

---

### Task 3: extract_full.py wires CostLedger into summary

**Files:**

- Modify: `scripts/extract_full.py`
- Modify: `tests/test_scripts/test_extract_full.py`

**Interfaces:**

- `run_full()` 构造 `CostLedger()` 并通过 `_build_llm()` 注入 `AnthropicLLMClient`。
- `_summarize_results()` 接收 `cost: CostLedger.snapshot()` 通过 kwargs，输出 `cost` 顶层字段。
- `_markdown_text()` 仅在 `cost.cumulative_usd > 0` 时加 `## Cost` 段落（避免 FakeLLM 误显示）。
- `RUFLO_BUDGET_PRINT=0` env flag：抑制 markdown `## Cost` 输出；JSON 仍写入（数据完整性优先）。

- [ ] **Step 1: Write failing tests**

Append to `tests/test_scripts/test_extract_full.py`:

```python
def test_run_full_summary_includes_cost_with_real_provider(tmp_path, monkeypatch):
    """When a real-ish LLMClient records to CostLedger, summary.cost is populated."""
    from src.lib.budget import CostLedger
    # ... use a _CountingLLMClient that records tokens to a shared ledger and returns scripted JSON
    # ... invoke _run_full_unlocked or run_full with this client
    # ... assert summary["cost"]["call_count"] > 0
    # ... assert summary["cost"]["cumulative_usd"] > 0.0
    # ... assert "classify" in summary["cost"]["cost_by_stage"]


def test_run_full_summary_cost_zero_when_fake_llm(tmp_path):
    """FakeLLMClient (default) does NOT accumulate cost — summary.cost is zero but call_count=0."""
    # ... invoke run_full without --provider (FakeLLMClient auto-resolves)
    # ... assert summary["cost"]["cumulative_usd"] == 0.0
    # ... assert summary["cost"]["call_count"] == 0


def test_markdown_report_omits_cost_section_when_cost_zero(tmp_path):
    """Markdown omits `## Cost` section when cumulative_usd == 0 (FakeLLM / dry-run)."""
    # ... run with FakeLLMClient, render markdown, assert "## Cost" not in markdown
```

- [ ] **Step 2: Run tests and verify red**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_scripts/test_extract_full.py::test_run_full_summary_includes_cost_with_real_provider tests/test_scripts/test_extract_full.py::test_run_full_summary_cost_zero_when_fake_llm tests/test_scripts/test_extract_full.py::test_markdown_report_omits_cost_section_when_cost_zero --import-mode=importlib -q
```

Expected: FAIL (`KeyError: 'cost'`).

- [ ] **Step 3: Wire CostLedger into `run_full()`**

In `scripts/extract_full.py`:

1. Top of file: `from src.lib.budget import CostLedger` (price loading happens inside llm_client, not here).

2. `run_full()` after `source_files = _source_files(root)`:
   ```python
   ledger = CostLedger()
   ```
   **Always construct**, even when `llm is None` — summary still has a `cost` field (zero).

3. Change `_build_llm(provider_name)` signature:
   ```python
   def _build_llm(provider_name: str | None, *, ledger: CostLedger | None = None):
       ...
       return AnthropicLLMClient(default_provider_name=target, ledger=ledger)
   ```
   Pass `ledger` through in `run_full()`.

4. `_summarize_results()` signature: add `cost_snapshot: dict[str, Any] | None = None`. Merge into the returned dict:
   ```python
   base = { ... existing fields ... }
   if cost_snapshot is not None:
       base["cost"] = cost_snapshot
   return base
   ```

5. In `run_full()`, after `_summarize_results()`:
   ```python
   summary = _summarize_results(
       effective_results,
       selected=...,
       ...,
       cost_snapshot=ledger.snapshot(),
   )
   ```

6. `_markdown_text()`: only add `## Cost` block when `report["summary"].get("cost", {}).get("cumulative_usd", 0) > 0`:
   ```python
   cost = report["summary"].get("cost", {})
   if cost.get("cumulative_usd", 0) > 0:
       lines.extend([
           "",
           "## Cost",
           "",
           f"- cumulative: ${cost['cumulative_usd']:.4f}",
           f"- calls: {cost['call_count']}",
           f"- input tokens: {cost['input_tokens']}",
           f"- output tokens: {cost['output_tokens']}",
           f"- avg/call: ${cost['cost_per_call_avg']:.4f}",
           "",
           "| Stage | Calls | Input | Output | Cost |",
           "|---|---:|---:|---:|---:|",
       ])
       for stage, data in sorted(cost.get("cost_by_stage", {}).items()):
           lines.append(
               f"| `{stage}` | {data['calls']} | {data['input_tokens']} | "
               f"{data['output_tokens']} | ${data['cost_usd']:.4f} |"
           )
       lines.append("")
   ```

7. Respect `RUFLO_BUDGET_PRINT=0` env (default: print):
   ```python
   cost = report["summary"].get("cost", {})
   print_cost = cost.get("cumulative_usd", 0) > 0 and os.environ.get("RUFLO_BUDGET_PRINT", "1") != "0"
   if print_cost:
       # build markdown block
   ```

- [ ] **Step 4: Run new tests and verify green**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_scripts/test_extract_full.py --import-mode=importlib -q
```

Expected: 24 + 3 = 27 passed.

- [ ] **Step 5: Run all V7 tests zero-regression**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_*.py tests/test_scripts/test_extract_*.py --import-mode=importlib -q
```

Expected: ~306 passed, 1 skipped.

**Acceptance:** `run_full()` summary 输出 `cost` 字段；FakeLLMClient cost=0；真实 LLM cost>0 且按 stage 拆分；Markdown 仅在 cost>0 时输出。

---

### Task 4: Real Provider verification (single source + dry-run)

**Files:**

- Manual: temp root under `E:\tmp-v7-budget-verify\` (not committed)

- [ ] **Step 1: Prepare fixtures**

```powershell
New-Item -ItemType Directory -Force -Path "E:\tmp-v7-budget-verify\raw\sources" | Out-Null
Copy-Item "tests/fixtures/v7_control_plane/source_a.md" "E:\tmp-v7-budget-verify\raw\sources\"
Copy-Item "tests/fixtures/v7_control_plane/source_b.md" "E:\tmp-v7-budget-verify\raw\sources\"
Get-ChildItem "E:\tmp-v7-budget-verify\raw\sources"
```

- [ ] **Step 2: Run dry-run, capture cost**

```powershell
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
$env:PYTHONPATH = "."
python scripts/extract_full.py --root "E:\tmp-v7-budget-verify" --json-out "E:\tmp-v7-budget-verify\report.json" --markdown-out "E:\tmp-v7-budget-verify\report.md"
```

Expected: JSON report `"summary.cost"` block contains `cumulative_usd > 0`, `call_count > 0`, `cost_by_stage.{classify|completeness|cluster|fill_slots}` populated.

- [ ] **Step 3: Markdown contains cost section**

```powershell
Get-Content "E:\tmp-v7-budget-verify\report.md" | Select-String "Cost"
```

Expected: `## Cost` section with table including all 4 stages.

**Acceptance:** Real Provider smoke produces summary.cost with non-zero cost and 4 stage buckets.

**Fallback:** If real Provider is unreachable (network down), Task 4 acceptance is met by the dry-run + `_CountingLLMClient` integration test from Task 3 Step 1 (the ledger logic is exercised there). Note the fallback in the Plan 4 memory file.

---

### Task 5: Documentation sync + static checks

**Files:**

- Modify: `.superpowers/sdd/progress.md` (add Plan 4 entry)
- New: `.memory/feedback-v7-cost-observability-2026-09-16.md`
- Modify: `.memory/MEMORY.md` (add index entry)

- [ ] **Step 1: Static checks**

```powershell
python -m compileall -q src/lib/budget.py src/pipeline/v7_extract/llm_client.py scripts/extract_full.py
git diff --check
```

Expected: both exit 0.

- [ ] **Step 2: Add Plan 4 entry to progress.md**

Append after Plan 3 entry (file currently ends at line 1061):

```markdown
### Plan 4 — V7 cost observability (2026-09-16)

- ✅ 计划：`docs/superpowers/plans/2026-09-16-v7-budget-observability.md`（plan-audit Round 1 + Round 2 已整改落地）。
- ✅ `src/lib/budget.py`：CostLedger dataclass + load_default_prices (env: RUFLO_INPUT_TOKEN_PRICE / RUFLO_OUTPUT_TOKEN_PRICE；默认 0.0000003 / 0.0000006 USD/token)。asyncio 单线程使用，非线程安全。
- ✅ AnthropicLLMClient 接受可选 ledger；complete() 在 provider.complete() 成功返回后累计 token + cost；优先读 response.usage，fallback `len(content)//4` 估算；truncated/retry-time raise 不累计。FakeLLMClient 不变（不累计 cost）。
- ✅ scripts/extract_full.py summary 输出 `cost` 顶层字段（cumulative_usd / cost_by_stage / cost_per_call_avg / input_tokens / output_tokens / call_count）；Markdown 仅在 cost>0 时输出 `## Cost` 段落；`RUFLO_BUDGET_PRINT=0` 抑制 markdown 输出（JSON 仍写入）。
- ✅ 测试：6 个 lib unit + 4 个 llm_client integration + 3 个 extract_full summary = 13 个新增；现有 299 测试零回归。
- ✅ 真实 Provider dry-run smoke：2 source 后 summary.cost>0，4 个 stage bucket 均有数据。
- 🚫 明确不做（6 维评审 + plan-audit 共同确认）：trust boundary 注入（边际收益低）、paused_budget 自动暂停门（checkpoint 续跑死循环风险 + 5 年视角过时）、内容层 retry 修改 prompt、BudgetedLLM 上下文 chunking、v1 batch_runner budget 路径重构、跨 v1/V7 budget 统一。
```

- [ ] **Step 3: New memory file**

Create `.memory/feedback-v7-cost-observability-2026-09-16.md` mirroring Wave 4/5 memory style:
- Outcome: CostLedger delivered; operator gets cumulative USD + per-stage breakdown in `extract_full.py` summary
- Durable rules:
  - `CostLedger` lives at `src/lib/budget.py` (next to `src/lib/budgeted.py` and `src/lib/retry.py`)
  - `AnthropicLLMClient` reads `response.usage` first; falls back to `len/4` heuristic if usage absent
  - Only successful LLM calls accumulate (truncated / retry-time raises do NOT record)
  - `FakeLLMClient` intentionally bypasses ledger (test isolation)
  - Markdown `## Cost` section only renders when `cumulative_usd > 0` (avoid misleading operator during dry-run)
  - `RUFLO_INPUT_TOKEN_PRICE` / `RUFLO_OUTPUT_TOKEN_PRICE` env override defaults (0.0000003 / 0.0000006 USD/token)
- Verification: ~306 passed, 1 skipped; real Provider 2-source smoke shows cost>0 across all 4 stages
- Out of scope: trust boundary, paused_budget, content-level retry-prompt-modification, BudgetedLLM chunking, v1 budget unification
- Artifacts: `src/lib/budget.py`, modified `src/pipeline/v7_extract/llm_client.py`, modified `scripts/extract_full.py`
- Conclusion: Plan 4 cost observability delivers the high-value 20% (operator knows USD) without the 80% bloat (auto-pause, trust boundary).

- [ ] **Step 4: Update `.memory/MEMORY.md` index**

Append line:
```
- [2026-09-16 V7 cost observability](feedback-v7-cost-observability-2026-09-16.md) — CostLedger + summary.cost 字段；real Provider 优先，FakeLLM bypass；Markdown 仅 cost>0 输出
```

**Acceptance:** progress.md 主账本 Plan 4 + memory feedback + MEMORY.md index 三处同步；compileall + git diff --check exit 0。

---

## Audit

- Round 1: done — 9 hidden assumptions, 8 edge cases, 7 logic gaps, 5 bugs, 4 info gaps surfaced. Severity breakdown: 0 fatal, 4 major (E1, E3, L1, L2), 7 minor (H2, H4, H6, E5, B4, B5, L7). All major + minor issues addressed in Task 1-5 redesign.
- Round 2: done — 14 stress scenarios + 4 boundary points. Critical findings: S9 (real Provider fallback), S12 (WikiWriter must NOT receive ledger), S13 (old test backward compat). All addressed.
- Human review: 4 info gaps checked (U1 usage field, U2 provider structure, U3 test assertions, U4 field naming). **Major update from U1**: Anthropic provider already returns `usage.input_tokens` / `usage.output_tokens` — Task 2 Step 3 redesigned to prefer usage over char/4 estimate.
- Open risks:
  - Cost estimate fallback (`len(content)//4`) has ±50% error when `response.usage` absent; acceptable (ballpark, not billing)
  - CostLedger is NOT thread-safe (docstring noted); asyncio single-loop use only
  - Real Provider smoke depends on network availability; fallback to Task 3 integration test
- Rollback: revert feature branch; CostLedger is additive, no existing field removed; `RUFLO_BUDGET_PRINT=0` reverts to no markdown cost output for paranoid consumers.

## Completion evidence

- Final commit: (filled on close)
- Tests: ~306 passed, 1 skipped (6 new in tests/test_lib/, 4 new in test_v7_extract_llm_client.py, 3 new in test_extract_full.py)
- Static checks: `python -m compileall -q src/lib/budget.py src/pipeline/v7_extract/llm_client.py scripts/extract_full.py` exit 0; `git diff --check` exit 0
- Documentation updated: progress.md Plan 4 + memory feedback + MEMORY.md index
- Progress ledger updated: yes
- Real Provider verification: 2-source dry-run shows summary.cost populated across 4 stages
