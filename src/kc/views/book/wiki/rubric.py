"""Strict, versioned reader-task rubric loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class EvidenceLocator:
    locator_type: str
    pattern: str
    min_count: int = 1

@dataclass(frozen=True)
class RubricSpec:
    task_id: str
    scenario: str
    expected_evidence: tuple[EvidenceLocator, ...]
    rubric_dimensions: tuple[str, ...]
    threshold: float = 0.8

def load_rubric(path: str | Path) -> tuple[RubricSpec, ...]:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("YAML rubric requires PyYAML; install pyyaml or use JSON") from exc
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "rubric-spec-v1":
        raise ValueError("schema_version must be rubric-spec-v1")
    tasks = raw.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a non-empty list")
    result = []
    for item in tasks:
        if not isinstance(item, dict) or not isinstance(item.get("task_id"), str) or not item["task_id"]:
            raise ValueError("task_id is required")
        evidence = item.get("expected_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{item['task_id']}: expected_evidence is required")
        locators = []
        for loc in evidence:
            if not isinstance(loc, dict) or loc.get("locator_type") not in {"wikilink", "heading", "quote", "page_id"}:
                raise ValueError(f"{item['task_id']}: invalid locator_type")
            pattern = loc.get("pattern")
            count = loc.get("min_count", 1)
            if not isinstance(pattern, str) or not pattern or not isinstance(count, int) or count < 1:
                raise ValueError(f"{item['task_id']}: invalid locator")
            locators.append(EvidenceLocator(loc["locator_type"], pattern, count))
        dims = item.get("rubric_dimensions", [])
        threshold = item.get("threshold", 0.8)
        if not isinstance(dims, list) or not all(isinstance(x, str) and x for x in dims):
            raise ValueError(f"{item['task_id']}: rubric_dimensions must be strings")
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError(f"{item['task_id']}: threshold must be in [0,1]")
        result.append(RubricSpec(item["task_id"], str(item.get("scenario", "")), tuple(locators), tuple(dims), float(threshold)))
    if len({x.task_id for x in result}) != len(result):
        raise ValueError("task_id values must be unique")
    return tuple(result)

load_rubric_specs = load_rubric

__all__ = ["EvidenceLocator", "RubricSpec", "load_rubric", "load_rubric_specs"]
