"""Tests for A-0 delivery_report validator (Z-6, spec §16 EX-3).

Validates the CI script `scripts/kc_check_delivery_report.py` against the
hard rule from spec §16 EX-3:

    hard_gate_failures 非空 → next_phase_ready 必须 false

These tests run before either the template or the validator exists, so they
should all FAIL on the first run, then PASS after the implementation lands.
"""
from pathlib import Path


# 测试 1：模板存在且含完整字段
def test_delivery_report_template_has_required_fields():
    """template.yaml 含 spec §16.2 必填字段定义"""
    template_path = Path(".superpowers/sdd/delivery_reports/template.yaml")
    assert template_path.exists()

    content = template_path.read_text(encoding="utf-8")
    required_fields = [
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
        "next_phase_ready",  # spec §16.2 关键字段
    ]
    for field in required_fields:
        assert field in content, f"模板缺少字段: {field}"


# 测试 2：hard_gate_failures 非空 + next_phase_ready=true → FAIL（违反硬规则）
def test_validator_rejects_hard_gate_with_next_phase_ready_true(tmp_path):
    """违反 spec §16.2 硬规则：hard_gate_failures 非空但 next_phase_ready=true"""
    bad_dr = tmp_path / "bad.yaml"
    bad_dr.write_text(
        """
phase: "C-1 Evidence 一等公民"
changed_files: []
contracts_changed: []
tests_run: []
evaluation_dataset_version: "2026-08-26-29case"
metrics: {}
hard_gate_failures:
  - "span_accuracy < 0.95"
  - "evidence_persistence_tests FAIL"
migration_required: false
rollback_procedure: "n/a"
known_limitations: []
next_phase_ready: true  # 违反 spec §16.2 硬规则
""",
        encoding="utf-8",
    )

    from scripts.kc_check_delivery_report import validate_delivery_report

    result = validate_delivery_report(bad_dr)

    assert result["passed"] is False
    violations_text = " ".join(str(v) for v in result.get("violations", []))
    assert "hard_gate_failures" in violations_text


# 测试 3：hard_gate_failures 空 + next_phase_ready=true → PASS
def test_validator_accepts_clean_delivery_report(tmp_path):
    """合规：hard_gate_failures 空 + next_phase_ready=true"""
    good_dr = tmp_path / "good.yaml"
    good_dr.write_text(
        """
phase: "C-1 Evidence 一等公民"
changed_files: ["src/kc/contracts/evidence.py"]
contracts_changed: ["src/kc/contracts/evidence.py"]
tests_run: ["PYTHONPATH=. pytest tests/test_kc --import-mode=importlib"]
evaluation_dataset_version: "2026-08-26-29case"
metrics:
  real_data_span_accuracy: 0.97
hard_gate_failures: []
migration_required: false
rollback_procedure: "删除 .index/evidence/ 即可"
known_limitations: ["MCP semantic 路径不反查 evidence"]
next_phase_ready: true
""",
        encoding="utf-8",
    )

    from scripts.kc_check_delivery_report import validate_delivery_report

    result = validate_delivery_report(good_dr)

    assert result["passed"] is True
    assert len(result.get("violations", [])) == 0


# 测试 4：hard_gate_failures 非空 + next_phase_ready=false → PASS（合规）
def test_validator_accepts_blocked_phase(tmp_path):
    """合规：hard_gate_failures 非空 + next_phase_ready=false（按 spec §16.2 强制）"""
    blocked_dr = tmp_path / "blocked.yaml"
    blocked_dr.write_text(
        """
phase: "C-1 Evidence 一等公民"
changed_files: []
contracts_changed: []
tests_run: []
evaluation_dataset_version: "2026-08-26-29case"
metrics: {}
hard_gate_failures:
  - "span_accuracy < 0.95"
migration_required: false
rollback_procedure: "n/a"
known_limitations: ["span_accuracy 不达标"]
next_phase_ready: false  # 正确：硬门槛失败时不应进入下一阶段
""",
        encoding="utf-8",
    )

    from scripts.kc_check_delivery_report import validate_delivery_report

    result = validate_delivery_report(blocked_dr)

    assert result["passed"] is True


# 测试 5：缺字段 → FAIL
def test_validator_reports_missing_required_fields(tmp_path):
    """缺字段时 CI 校验报告缺失字段清单"""
    incomplete_dr = tmp_path / "incomplete.yaml"
    incomplete_dr.write_text(
        """
phase: "C-1"
hard_gate_failures: []
next_phase_ready: true
""",
        encoding="utf-8",
    )

    from scripts.kc_check_delivery_report import validate_delivery_report

    result = validate_delivery_report(incomplete_dr)

    assert result["passed"] is False
    missing = result.get("missing_fields", [])
    assert "changed_files" in missing
    assert "metrics" in missing
