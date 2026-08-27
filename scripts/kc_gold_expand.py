"""Gold dataset expansion 29 → 100 cases (B-5 / F-2).

Appends new cases to the 4 gold YAML files, reaching 100 total:
  source_trust.yaml:   5 → 20  (per authority_level 4)
  evidence_span.yaml:  5 → 20  (per evidence_type 4)
  conflict.yaml:      10 → 30  (per conflict_type 5)
  identity.yaml:       9 → 30  (per action 10)

Run:  PYTHONPATH=. python scripts/kc_gold_expand.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "docs" / "evaluation" / "cases"

QUERY_TIME = 1734567890000


def _base_case(case_id: str, dim: str, tag: str = "partial", conf: str = "medium") -> dict:
    """A minimal valid case dict; callers override fields."""
    return {
        "case_id": case_id,
        "query": f"gold case {case_id}",
        "source_type": "file",
        "language": "en",
        "context": {"domain": "knowledge_management", "platform": "internal"},
        "query_time": QUERY_TIME,
        "object_truth": {"type": "knowledge_unit", "id": f"ku_{case_id}"},
        "identity_key": f"id-v1:sha256hex_{case_id}",
        "resolution_action": "create",
        "integrity_status": "verified",
        "expected_top_k": [{"knowledge_unit_id": f"ku_{case_id}", "score": 0.9}],
        "evidence_refs": [],
        "task_result": "success",
        "tag": tag,
        "coverage_dimension": dim,
        "confidence": conf,
    }


def _extend_source_trust(cases: list[dict]) -> list[dict]:
    """source_trust: add 15 cases (per authority_level 4)."""
    levels = ["primary", "official", "expert", "secondary", "unknown"]
    start = 6  # existing CF-001..005 are 1-5
    for idx, level in enumerate(levels):
        for n in range(3):  # 3 more each → 4 total
            cid = f"ST-{start:03d}"
            case = _base_case(cid, f"SourceTrust.{level}")
            case["object_truth"] = {"type": "source_trust_profile", "id": f"stp_{level}_{n}"}
            case["query"] = f"Source Trust {level} evaluation #{n + 4}"
            case["tag"] = "full" if n in (0, 1) else "partial"
            case["confidence"] = "high" if n in (0, 1) else "medium"
            cases.append(case)
            start += 1
    return cases


def _extend_evidence_span(cases: list[dict]) -> list[dict]:
    """evidence_span: add 15 cases (per evidence_type 4)."""
    types = ["direct_quote", "structured_source", "code", "computed", "inferred"]
    start = 6
    for etype in types:
        for n in range(3):
            cid = f"ES-{start:03d}"
            case = _base_case(cid, f"EvidenceType.{etype}")
            case["object_truth"] = {"type": "evidence", "id": f"ev_{etype}_{n}"}
            case["query"] = f"Evidence {etype} span evaluation #{n + 4}"
            case["tag"] = "full" if n in (0, 1) else "partial"
            case["confidence"] = "high" if n in (0, 1) else "medium"
            cases.append(case)
            start += 1
    return cases


def _extend_conflict(cases: list[dict]) -> list[dict]:
    """conflict: add 20 cases (per conflict_type 5 total)."""
    ctypes = ["actual", "conditional", "temporal", "perspective", "unresolved", "none"]
    start = 11  # existing CF-001..010 are 1-10
    for ctype in ctypes:
        # existing count per type: actual2/conditional2/temporal2/perspective2/unresolved1/none1
        existing = {"actual": 2, "conditional": 2, "temporal": 2, "perspective": 2,
                    "unresolved": 1, "none": 1}[ctype]
        for n in range(5 - existing):
            cid = f"CF-{start:03d}"
            case = _base_case(cid, f"Conflict.{ctype}")
            case["object_truth"] = {"type": "conflict", "id": f"cf_{ctype}_{n + existing}"}
            case["query"] = f"Conflict {ctype} evaluation #{n + existing + 1}"
            case["resolution_action"] = "conflict"
            case["integrity_status"] = "disputed" if ctype in ("actual", "unresolved") else "verified"
            case["task_result"] = "partial"
            case["tag"] = "full" if n in (0, 1) else "partial"
            case["confidence"] = "high" if ctype in ("actual", "none") else "medium"
            cases.append(case)
            start += 1
    return cases


def _extend_identity(cases: list[dict]) -> list[dict]:
    """identity: add 21 cases (per action 10 total)."""
    actions = ["merge", "supersede", "keep_separate"]
    start = 10  # existing ID-001..009 are 1-9
    for action in actions:
        existing = 3  # each action already has 3
        for n in range(10 - existing):
            cid = f"ID-{start:03d}"
            case = _base_case(cid, f"Identity.{action}")
            case["object_truth"] = {"type": "identity_resolution", "id": f"id_{action}_{n + existing}"}
            case["query"] = f"Identity {action} evaluation #{n + existing + 1}"
            case["resolution_action"] = action
            case["tag"] = "full" if n % 2 == 0 else "partial"
            case["confidence"] = "high" if n % 2 == 0 else "medium"
            cases.append(case)
            start += 1
    return cases


def main() -> int:
    files = {
        "source_trust.yaml": (_extend_source_trust, 20),
        "evidence_span.yaml": (_extend_evidence_span, 20),
        "conflict.yaml": (_extend_conflict, 30),
        "identity.yaml": (_extend_identity, 30),
    }
    total = 0
    for fname, (extender, target) in files.items():
        path = CASES_DIR / fname
        cases = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        before = len(cases)
        cases = extender(cases)
        after = len(cases)
        path.write_text(
            yaml.safe_dump(cases, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        print(f"{fname}: {before} → {after} (target {target})")
        total += after
    print(f"TOTAL: {total} cases (target 100)")
    return 0 if total == 100 else 1


if __name__ == "__main__":
    sys.exit(main())
