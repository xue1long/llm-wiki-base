"""Metrics CLI."""
import argparse
import json
import sys

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
