"""Metrics CLI.

Provides two metric types:
1. System metrics (Prometheus format) - counters, gauges for app monitoring
2. Token metrics (LLM usage) - prompt/completion tokens for optimization

Usage:
    python -m src.cli metrics show                    # System metrics (Prometheus)
    python -m src.cli metrics token show              # Token usage summary
    python -m src.cli metrics token by-prompt         # Token usage by prompt type
    python -m src.cli metrics cost                    # LLM cost summary
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ..metrics import MetricsRegistry
from ..metrics.prometheus_format import to_prometheus_text


def cmd_metrics_show(_args: argparse.Namespace) -> None:
    """Print current metrics in Prometheus text format."""
    print(to_prometheus_text(MetricsRegistry.all_metrics()))


def cmd_metrics_reset(_args: argparse.Namespace) -> None:
    """Reset all in-memory metric values (testing only). Keeps registered metric instances."""
    MetricsRegistry.reset_values()
    print("Metrics reset")


def cmd_metrics_export(args: argparse.Namespace) -> None:
    """Export all metric values to JSON file."""
    data = []
    for m in MetricsRegistry.all_metrics():
        if hasattr(m, "_values") and not hasattr(m, "_counts"):
            for key, val in m._values.items():
                type_name = "counter" if m.__class__.__name__ == "Counter" else "gauge"
                data.append({
                    "name": m.name,
                    "type": type_name,
                    "labels": dict(zip(m.label_names, key)),
                    "value": val,
                })
    try:
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Exported {len(data)} metric rows to {args.path}")


def cmd_metrics_cost(_args: argparse.Namespace) -> None:
    """Print LLM cost summary from LLM_COST_USD_TOTAL metric."""
    from ..metrics import LLM_COST_USD_TOTAL
    total = 0.0
    print("LLM cost by provider/model:")
    for key, val in LLM_COST_USD_TOTAL._values.items():
        provider, model = (key + ("", ""))[:2]
        print(f"  {provider}/{model}: ${val:.4f}")
        total += val
    print(f"Total: ${total:.4f}")


# ---------------------------------------------------------------------------
# Token metrics commands (for LLM usage optimization)
# ---------------------------------------------------------------------------

def _get_token_metrics_dir(args: argparse.Namespace) -> Path:
    """Get the metrics directory from args or project."""
    if hasattr(args, "project") and args.project:
        from ..lib.project import resolve_project
        _, paths = resolve_project(args.project, by_id_only=True)
        return paths.index / "metrics"
    return Path(".index/metrics")


def cmd_token_show(args: argparse.Namespace) -> None:
    """Show overall token usage summary."""
    from ..llm.token_metrics import TokenMetricsCollector

    metrics_dir = _get_token_metrics_dir(args)
    if not metrics_dir.exists():
        print("No token metrics data available. Run some ingestions first.")
        return

    collector = TokenMetricsCollector(metrics_dir)
    summary = collector.get_summary()

    print("=== Token Usage Summary ===")
    print(f"Total calls:        {summary['total_calls']}")
    print(f"Successful calls:   {summary['success_count']}")
    print(f"Success rate:       {summary['success_count'] / max(summary['total_calls'], 1) * 100:.1f}%")
    print(f"Avg prompt tokens:  {summary['avg_prompt_tokens']}")
    print(f"Avg completion:     {summary['avg_completion_tokens']}")
    print(f"Avg retries:        {summary['avg_retries']:.2f}")
    if summary['error_breakdown']:
        print("\nErrors:")
        for err_type, count in sorted(summary['error_breakdown'].items(), key=lambda x: -x[1]):
            print(f"  {err_type}: {count}")


def cmd_token_by_prompt(args: argparse.Namespace) -> None:
    """Show token usage grouped by prompt type."""
    from ..llm.token_metrics import TokenMetricsCollector

    metrics_dir = _get_token_metrics_dir(args)
    if not metrics_dir.exists():
        print("No token metrics data available.")
        return

    collector = TokenMetricsCollector(metrics_dir)
    by_prompt = collector.get_by_prompt()

    if not by_prompt:
        print("No token metrics data available.")
        return

    print("=== Token Metrics by Prompt Type ===")
    for prompt_name, data in sorted(by_prompt.items()):
        success_rate = data['success_count'] / max(data['total_calls'], 1) * 100
        avg_prompt = data['total_prompt_tokens'] // max(data['success_count'], 1)
        avg_completion = data['total_completion_tokens'] // max(data['success_count'], 1)

        print(f"\n{prompt_name}:")
        print(f"  Calls:        {data['total_calls']} ({data['success_count']} success)")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Avg prompt:   {avg_prompt} tokens")
        print(f"  Avg completion: {avg_completion} tokens")
        if data['errors']:
            print(f"  Errors:       {json.dumps(data['errors'])}")
