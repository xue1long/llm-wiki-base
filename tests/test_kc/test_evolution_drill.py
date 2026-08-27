"""Tests for B-5.6 evolution e2e drill (spec §14 A9-8 + §17 D-20)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "kc_evolution_drill.py"


def _load_drill():
    """Load scripts/kc_evolution_drill.py via importlib (sibling-safe)."""
    mod_name = "kc_evolution_drill"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def drill():
    return _load_drill()


def test_scenario_correction(drill):
    """场景 1 修正: 新旧 identity_key 不同, 旧 v1 保留."""
    scenario = drill._scenario_correction()
    assert scenario.passed is True
    assert scenario.identity_keys_before != scenario.identity_keys_after
    # 旧 + 新都保留 (2 个 key)
    assert len(scenario.identity_keys_after) == 2


def test_scenario_withdrawal(drill):
    """场景 2 撤回: withdrawn evidence 不支撑发布."""
    scenario = drill._scenario_withdrawal()
    assert scenario.passed is True
    assert "withdrawn" in scenario.state_changes[0]
    assert "withdrawn" in scenario.state_changes[1]


def test_scenario_evidence_invalidation(drill):
    """场景 3 Evidence 失效: stale → 重新验证 → verified."""
    scenario = drill._scenario_evidence_invalidation()
    assert scenario.passed is True
    assert "stale" in scenario.state_changes[1]


def test_scenario_conflict_resolution(drill):
    """场景 4 Conflict 解决: disputed → resolution → verified + resolution_event."""
    scenario = drill._scenario_conflict_resolution()
    assert scenario.passed is True
    assert "disputed" in scenario.state_changes[0]
    assert "resolution_event" in scenario.state_changes[2]


def test_scenario_supersede(drill):
    """场景 5 supersede: 双向 supersedes + historical 降级."""
    scenario = drill._scenario_supersede()
    assert scenario.passed is True
    assert "historical" in scenario.state_changes[1]
    assert scenario.identity_keys_before != scenario.identity_keys_after


def test_run_evolution_drill_all_passed(drill, tmp_path):
    """5 场景全部通过 + 写日志."""
    report = drill.run_evolution_drill(project_root=tmp_path)
    assert len(report.scenarios) == 5
    assert report.passed is True
    assert report.log_path.exists()
    content = report.log_path.read_text(encoding="utf-8")
    assert '"action": "evolution_drill"' in content
    assert '"passed": true' in content
