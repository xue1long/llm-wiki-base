"""Token usage metrics collection for LLM calls.

Collects prompt/completion token counts, retry rates, and error breakdowns
per prompt type (analyzer, generator, etc.) to support optimization decisions.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TokenMetric:
    """Single LLM call metric record."""
    timestamp: int
    prompt_name: str  # "analyzer", "analyzer-json", "generator", "unified", etc.
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    retry_count: int
    success: bool
    error_type: Optional[str] = None


class TokenMetricsCollector:
    """Collects LLM token usage data to JSONL files.

    Usage:
        collector = TokenMetricsCollector(Path(".index/metrics"))
        collector.record(TokenMetric(...))

        summary = collector.get_summary()
        by_prompt = collector.get_summary(prompt_name="analyzer")
    """

    def __init__(self, metrics_dir: Path):
        self.metrics_dir = metrics_dir
        self._session_start = int(time.time())

    def record(self, metric: TokenMetric) -> None:
        """Write a metric record to the session's JSONL file."""
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.metrics_dir / f"metrics_{self._session_start}.jsonl"
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(metric), ensure_ascii=False) + "\n")

    def get_summary(self, prompt_name: str | None = None) -> dict:
        """Get aggregated statistics across all recorded metrics.

        Args:
            prompt_name: If provided, filter to this prompt type only.

        Returns:
            Dict with total_calls, success_count, avg_prompt_tokens, etc.
        """
        total_prompt = 0
        total_completion = 0
        total_retries = 0
        success_count = 0
        error_counts: dict[str, int] = {}
        call_count = 0

        for file_path in self.metrics_dir.glob("metrics_*.jsonl"):
            try:
                for line in file_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if prompt_name and data.get("prompt_name") != prompt_name:
                        continue
                    call_count += 1
                    total_prompt += data.get("prompt_tokens", 0)
                    total_completion += data.get("completion_tokens", 0)
                    total_retries += data.get("retry_count", 0)
                    if data.get("success"):
                        success_count += 1
                    error_type = data.get("error_type")
                    if error_type:
                        error_counts[error_type] = error_counts.get(error_type, 0) + 1
            except (json.JSONDecodeError, OSError):
                continue

        return {
            "total_calls": call_count,
            "success_count": success_count,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "avg_prompt_tokens": total_prompt // max(success_count, 1),
            "avg_completion_tokens": total_completion // max(success_count, 1),
            "total_retries": total_retries,
            "avg_retries": total_retries / max(success_count, 1),
            "error_breakdown": error_counts,
        }

    def get_by_prompt(self) -> dict[str, dict]:
        """Get statistics grouped by prompt_name."""
        result: dict[str, dict] = {}
        for file_path in self.metrics_dir.glob("metrics_*.jsonl"):
            try:
                for line in file_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    name = data.get("prompt_name", "unknown")
                    if name not in result:
                        result[name] = {
                            "total_calls": 0,
                            "success_count": 0,
                            "total_prompt_tokens": 0,
                            "total_completion_tokens": 0,
                            "errors": {},
                        }
                    result[name]["total_calls"] += 1
                    if data.get("success"):
                        result[name]["success_count"] += 1
                    result[name]["total_prompt_tokens"] += data.get("prompt_tokens", 0)
                    result[name]["total_completion_tokens"] += data.get("completion_tokens", 0)
                    if data.get("error_type"):
                        err = data["error_type"]
                        result[name]["errors"][err] = result[name]["errors"].get(err, 0) + 1
            except (json.JSONDecodeError, OSError):
                continue
        return result


# Module-level collector instance (initialized by init_metrics_collector)
_collector: TokenMetricsCollector | None = None


def init_metrics_collector(metrics_dir: Path) -> None:
    """Initialize the global metrics collector."""
    global _collector
    _collector = TokenMetricsCollector(metrics_dir)


def get_metrics_collector() -> TokenMetricsCollector | None:
    """Get the global collector, or None if not initialized."""
    return _collector


def record_metric(metric: TokenMetric) -> None:
    """Record a metric if collector is initialized."""
    if _collector:
        _collector.record(metric)