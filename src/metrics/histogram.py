"""Histogram metric — distribution of observations."""

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))


class Histogram:
    def __init__(self, name: str, help: str, label_names: list[str] | None = None, buckets=None):
        self.name = name
        self.help = help
        self.label_names = label_names or []
        self.buckets = buckets or DEFAULT_BUCKETS
        self._counts: dict[tuple, dict[float, int]] = {}
        self._sums: dict[tuple, float] = {}
        self._totals: dict[tuple, int] = {}

    def observe(self, value: float, **labels) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        bucket_counts = self._counts.setdefault(key, {})
        for b in self.buckets:
            if value <= b:
                bucket_counts[b] = bucket_counts.get(b, 0) + 1
        self._sums[key] = self._sums.get(key, 0) + value
        self._totals[key] = self._totals.get(key, 0) + 1
