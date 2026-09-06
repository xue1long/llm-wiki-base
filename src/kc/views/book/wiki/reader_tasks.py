"""Evidence-only reader task runner."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from .rubric import EvidenceLocator, RubricSpec

@dataclass(frozen=True)
class ReaderTaskReport:
    spec: RubricSpec
    pass_rate: float
    evaluated_count: int
    expected_count: int
    skipped_count: int
    evidence_found: tuple[str, ...]
    evidence_missing: tuple[str, ...]
    failures: tuple[str, ...]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["spec"] = {"task_id": self.spec.task_id, "scenario": self.spec.scenario}
        return value

def _text(artifact: str | Path) -> str:
    path = Path(artifact)
    if path.is_file(): return path.read_text(encoding="utf-8")
    return "\n".join(p.read_text(encoding="utf-8") for p in path.rglob("*.md") if p.is_file())

def _count(text: str, loc: EvidenceLocator) -> int:
    if loc.locator_type == "wikilink":
        return text.count(loc.pattern)
    if loc.locator_type == "heading":
        return sum(1 for line in text.splitlines() if line.strip() == loc.pattern)
    if loc.locator_type == "quote":
        return text.count(loc.pattern)
    if loc.locator_type == "page_id":
        return len(re.findall(r"(?<![A-Za-z0-9_-])" + re.escape(loc.pattern) + r"(?![A-Za-z0-9_-])", text))
    return 0

def run_reader_task(spec: RubricSpec, artifact: str | Path) -> ReaderTaskReport:
    text = _text(artifact)
    found, missing = [], []
    for loc in spec.expected_evidence:
        label = f"{loc.locator_type}:{loc.pattern}"
        (found if _count(text, loc) >= loc.min_count else missing).append(label)
    total = len(spec.expected_evidence)
    return ReaderTaskReport(spec, len(found) / total if total else 0.0, total, total, 0,
                            tuple(found), tuple(missing), tuple(missing))

def run_reader_tasks(specs: Iterable[RubricSpec], artifact: str | Path) -> tuple[ReaderTaskReport, ...]:
    return tuple(run_reader_task(spec, artifact) for spec in specs)

class ReaderTaskRunner:
    """Small state-free facade matching the V4 task-runner contract."""
    def __init__(self, artifact: str | Path):
        self.artifact = artifact

    def run(self, spec: RubricSpec) -> ReaderTaskReport:
        return run_reader_task(spec, self.artifact)

    def run_all(self, specs: Iterable[RubricSpec]) -> tuple[ReaderTaskReport, ...]:
        return run_reader_tasks(specs, self.artifact)

def task_pass_rate(reports: Iterable[ReaderTaskReport]) -> float:
    values = tuple(reports)
    return sum(r.pass_rate >= r.spec.threshold for r in values) / len(values) if values else 0.0

__all__ = ["ReaderTaskReport", "ReaderTaskRunner", "run_reader_task", "run_reader_tasks", "task_pass_rate"]
