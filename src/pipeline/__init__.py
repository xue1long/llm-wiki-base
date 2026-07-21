# ruflo-kb/src/pipeline/__init__.py
from .collector import collect
from .processor import process, calculate_quality_metrics
from .librarian import archive
from .pipeline import _on_collector_start, _on_collector_done, _on_processor_done

__all__ = [
    "collect",
    "process",
    "calculate_quality_metrics",
    "archive",
]
