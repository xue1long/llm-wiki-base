"""Delivery Report CI Validator (A-0 / Z-6, spec §16 EX-3).

Validates a delivery_report YAML against spec §16.2 requirements.

Hard rule (spec §16.2 EX-3):
    hard_gate_failures 非空 → next_phase_ready 必须 false

Usage:
    PYTHONPATH=. python scripts/kc_check_delivery_report.py <dr.yaml>

Exit codes:
    0 = PASS
    1 = soft fail (hard-rule violation or other violation)
    2 = strict fail (missing fields; --strict mode only)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


# spec §16.2 必填字段
REQUIRED_FIELDS = [
    "phase",
    "changed_files",
    "contracts_changed",
    "tests_run",
    "evaluation_dataset_version",
    "metrics",
    "hard_gate_failures",
    "migration_required",
    "rollback_procedure",
    "known_limitations",
    "next_phase_ready",
]


def validate_delivery_report(dr_path: Path) -> dict[str, Any]:
    """Validate delivery report YAML against spec §16.2 rules.

    Returns dict with:
      - passed: bool (overall)
      - violations: list[str] (specific violations found)
      - missing_fields: list[str] (required fields missing)
      - hard_gate_count: int (number of hard gate failures)
      - next_phase_ready: bool | None (declared value)

    Hard rule: hard_gate_failures 非空 + next_phase_ready=true → FAIL.
    """
    if not dr_path.exists():
        return {
            "passed": False,
            "violations": [f"file 不存在: {dr_path}"],
            "missing_fields": [],
            "hard_gate_count": 0,
            "next_phase_ready": None,
        }

    try:
        dr = yaml.safe_load(dr_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {
            "passed": False,
            "violations": [f"YAML 解析失败: {e}"],
            "missing_fields": [],
            "hard_gate_count": 0,
            "next_phase_ready": None,
        }

    if not isinstance(dr, dict):
        return {
            "passed": False,
            "violations": [
                f"delivery_report 必须为 YAML 字典（实际: {type(dr).__name__}）"
            ],
            "missing_fields": [],
            "hard_gate_count": 0,
            "next_phase_ready": None,
        }

    violations: list[str] = []
    missing_fields: list[str] = []

    # 1. 检查必填字段
    for field in REQUIRED_FIELDS:
        if field not in dr:
            missing_fields.append(field)

    if missing_fields:
        violations.append(f"缺必填字段: {missing_fields}")

    # 2. 硬规则检查（spec §16.2 EX-3）
    hard_gate_failures = dr.get("hard_gate_failures", [])
    next_phase_ready = dr.get("next_phase_ready", None)

    if isinstance(hard_gate_failures, list):
        hard_gate_count = len(hard_gate_failures)
    else:
        hard_gate_count = 0

    if hard_gate_count > 0 and next_phase_ready is True:
        violations.append(
            f"硬规则违反（spec §16.2 EX-3）：hard_gate_failures 非空（{hard_gate_count} 项）"
            f" 但 next_phase_ready=true（必须 false）"
        )

    # 3. 类型校验（仅在字段存在时校验）
    if "changed_files" in dr and not isinstance(dr["changed_files"], list):
        violations.append("changed_files 必须为 list")
    if "metrics" in dr and not isinstance(dr["metrics"], dict):
        violations.append("metrics 必须为 dict")
    if "hard_gate_failures" in dr and not isinstance(dr["hard_gate_failures"], list):
        violations.append("hard_gate_failures 必须为 list")

    passed = len(violations) == 0

    return {
        "passed": passed,
        "violations": violations,
        "missing_fields": missing_fields,
        "hard_gate_count": hard_gate_count,
        "next_phase_ready": next_phase_ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate delivery report (spec §16.2)")
    parser.add_argument(
        "dr_path",
        type=Path,
        help="Delivery report YAML path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：缺字段也视为 FAIL（默认宽松）",
    )
    args = parser.parse_args()

    result = validate_delivery_report(args.dr_path)

    # 输出 JSON 报告
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 退出码
    if not result["passed"]:
        if args.strict and result["missing_fields"]:
            return 2  # 缺字段 = 严重
        return 1  # 软失败（硬规则违反或其他违规）
    return 0


if __name__ == "__main__":
    sys.exit(main())