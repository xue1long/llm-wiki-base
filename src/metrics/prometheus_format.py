"""Prometheus text format 0.0.4 serialization."""
from .counter import Counter
from .gauge import Gauge
from .histogram import Histogram


def _format_labels(names, values) -> str:
    if not names:
        return ""
    pairs = [f'{n}="{v}"' for n, v in zip(names, values) if v]
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _label_suffix(names, values) -> str:
    pairs = [f'{n}="{v}"' for n, v in zip(names, values) if v]
    return "," + ",".join(pairs) if pairs else ""


def to_prometheus_text(metrics: list) -> str:
    """Serialize metrics to Prometheus text format 0.0.4."""
    lines: list[str] = []
    for m in metrics:
        lines.append(f"# HELP {m.name} {m.help}")
        if isinstance(m, Histogram):
            lines.append(f"# TYPE {m.name} histogram")
            for key, bucket_counts in m._counts.items():
                suffix = _label_suffix(m.label_names, key)
                # bucket_counts is already cumulative (observe() increments every
                # bucket the value falls into), so emit the pre-computed value
                # for each bucket — Prometheus `le` semantics matches our counts.
                for b in m.buckets:
                    b_str = "+Inf" if b == float("inf") else str(b)
                    lines.append(f'{m.name}_bucket{{le="{b_str}"{suffix}}} {bucket_counts.get(b, 0)}')
                labels_str = _format_labels(m.label_names, key)
                lines.append(f"{m.name}_sum{labels_str} {m._sums.get(key, 0)}")
                lines.append(f"{m.name}_count{labels_str} {m._totals.get(key, 0)}")
        elif isinstance(m, Counter):
            lines.append(f"# TYPE {m.name} counter")
            for key, val in m._values.items():
                labels_str = _format_labels(m.label_names, key)
                lines.append(f"{m.name}{labels_str} {val}")
        elif isinstance(m, Gauge):
            lines.append(f"# TYPE {m.name} gauge")
            for key, val in m._values.items():
                labels_str = _format_labels(m.label_names, key)
                lines.append(f"{m.name}{labels_str} {val}")
        else:
            lines.append(f"# TYPE {m.name} unknown")
    return "\n".join(lines) + "\n"
