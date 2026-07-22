"""Metrics registry — module-level list of all registered metrics."""


class MetricsRegistry:
    _metrics: list = []

    @classmethod
    def counter(cls, name: str, help: str, label_names: list[str] | None = None):
        from .counter import Counter
        c = Counter(name, help, label_names)
        cls._metrics.append(c)
        return c

    @classmethod
    def gauge(cls, name: str, help: str, label_names: list[str] | None = None):
        from .gauge import Gauge
        g = Gauge(name, help, label_names)
        cls._metrics.append(g)
        return g

    @classmethod
    def histogram(cls, name: str, help: str, label_names: list[str] | None = None, buckets=None):
        from .histogram import Histogram
        h = Histogram(name, help, label_names, buckets)
        cls._metrics.append(h)
        return h

    @classmethod
    def all_metrics(cls) -> list:
        return list(cls._metrics)

    @classmethod
    def reset(cls) -> None:
        """Test-only: clear all metric state by removing every registered metric."""
        cls._metrics.clear()

    @classmethod
    def reset_values(cls) -> None:
        """Test-only: clear values of all currently registered metrics (keeps instances).

        Mutates the inner `_values` / `_counts` / `_sums` / `_totals` so cumulative
        state across tests is wiped without dropping the singletons that the rest
        of the code (e.g. `from src.metrics import LLM_COST_USD_TOTAL`) holds.
        """
        from .counter import Counter
        from .gauge import Gauge
        from .histogram import Histogram
        for m in list(cls._metrics):
            if isinstance(m, (Counter, Gauge)):
                m._values.clear()
            elif isinstance(m, Histogram):
                m._counts.clear()
                m._sums.clear()
                m._totals.clear()
