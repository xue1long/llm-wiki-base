"""Counter metric — monotonically increasing value."""


class Counter:
    def __init__(self, name: str, help: str, label_names: list[str] | None = None):
        self.name = name
        self.help = help
        self.label_names = label_names or []
        self._values: dict[tuple, float] = {}

    def inc(self, amount: float = 1, **labels) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        self._values[key] = self._values.get(key, 0) + amount

    def get(self, **labels) -> float:
        key = tuple(labels.get(n, "") for n in self.label_names)
        return self._values.get(key, 0)
