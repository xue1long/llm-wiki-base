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
