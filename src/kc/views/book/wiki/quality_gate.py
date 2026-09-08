"""Deterministic V4 rule quality gate (no LLM, no guessed scores)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_THRESHOLDS = {
    "unresolved_ratio": 0.05,
    "unmatched_heading_ratio": 0.10,
    "glossary_coverage": 0.95,
}


@dataclass(frozen=True)
class QualityGateReport:
    rule_blockers: tuple[str, ...]
    llm_scores: dict[str, float] | None = None
    llm_status: str = "disabled"
    rule_thresholds: dict[str, float] | None = None
    overall: str = "pass"

    @property
    def ok(self) -> bool:
        return self.overall == "pass"


def _metric(data: Mapping[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in data:
            try:
                return float(data[name])
            except (TypeError, ValueError):
                return float("inf")
    return default


def _has(data: Mapping[str, Any], *names: str) -> bool:
    return any(name in data for name in names)


def check_quality_gate(
    artifact: Any,
    *,
    manifest: Mapping[str, Any] | None = None,
    thresholds: Mapping[str, float] | None = None,
    llm_scores: Mapping[str, float] | None = None,
    llm_status: str = "disabled",
) -> QualityGateReport:
    """Evaluate the four hard limits. ``artifact`` may be a manifest or object.

    Block IDs are compared as multisets when both sides are supplied. Missing
    metrics are blockers: a gate must fail closed rather than infer success.
    """
    data: Mapping[str, Any] = manifest or (artifact if isinstance(artifact, Mapping) else getattr(artifact, "manifest", {}))
    cfg = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        cfg.update({str(k): float(v) for k, v in thresholds.items()})
    blockers: list[str] = []
    expected = data.get("expected_block_ids", data.get("source_block_ids"))
    actual = data.get("draft_block_ids", data.get("block_ids"))
    if expected is None or actual is None:
        blockers.append("block_ids_missing")
    elif Counter(map(str, expected)) != Counter(map(str, actual)):
        blockers.append("block_id_multiset_mismatch")

    unresolved = _metric(data, "unresolved_ratio", default=-1)
    if unresolved < 0:
        if not _has(data, "total_relations", "total") or not _has(data, "unresolved"):
            blockers.append("unresolved_metric_missing")
        total = _metric(data, "total_relations", default=0)
        unresolved = _metric(data, "unresolved", default=0) / total if total else 0.0
    if unresolved > cfg["unresolved_ratio"]:
        blockers.append("unresolved_relation_ratio")

    headings = _metric(data, "unmatched_heading_ratio", default=-1)
    if headings < 0:
        if not _has(data, "total_headings", "total") or not _has(data, "unmatched_headings"):
            blockers.append("heading_metric_missing")
        total = _metric(data, "total_headings", default=0)
        headings = _metric(data, "unmatched_headings", default=0) / total if total else 0.0
    if headings > cfg["unmatched_heading_ratio"]:
        blockers.append("unmatched_heading_ratio")

    coverage = _metric(data, "glossary_coverage", default=-1)
    if coverage < 0:
        if not _has(data, "glossary_term_count", "glossary_expected") or not _has(data, "glossary_resolved_count", "glossary_resolved"):
            blockers.append("glossary_metric_missing")
        denom = _metric(data, "glossary_term_count", "glossary_expected", default=0)
        numer = _metric(data, "glossary_resolved_count", "glossary_resolved", default=0)
        coverage = numer / denom if denom else 0.0
    if coverage < cfg["glossary_coverage"]:
        blockers.append("glossary_coverage")
    if "editorial_state_hash" in data:
        if not data.get("chapter_body_present", False):
            blockers.append("chapter_body_missing")
        if not data.get("section_source_ids_present", False):
            blockers.append("section_source_ids_missing")
        if not data.get("curation_revision_present", False):
            blockers.append("curation_revision_missing")
        if not data.get("outline_revision_present", False):
            blockers.append("outline_revision_missing")
        if data.get("disputed_page_ids") and not data.get("disputed_section_status", True):
            blockers.append("disputed_section_status_missing")
    return QualityGateReport(tuple(blockers), dict(llm_scores) if llm_scores is not None else None,
                             llm_status, cfg, "fail" if blockers else "pass")

evaluate_quality_gate = check_quality_gate


__all__ = ["DEFAULT_THRESHOLDS", "QualityGateReport", "check_quality_gate", "evaluate_quality_gate"]
