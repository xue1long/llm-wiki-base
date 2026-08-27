"""Tests for B-5.5 incremental evolution drill (spec §14 A9-7 + §17 D-19).

Uses importlib to load scripts/kc_incremental_drill.py directly
(scripts/ is not a package; sibling repo shadows the namespace).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "kc_incremental_drill.py"


def _load_drill():
    """Load scripts/kc_incremental_drill.py via importlib (sibling-safe)."""
    mod_name = "kc_incremental_drill"
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


def test_run_drill_3_batches_passes(drill):
    """3 批 × 10 文件无重复 → 全部 passed."""
    report = drill.run_drill(batch_count=3, files_per_batch=10)
    assert len(report.batches) == 3
    assert all(b.passed for b in report.batches)
    assert report.total_files == 30
    assert report.total_duplicates == 0
    assert report.passed is True


def test_run_drill_20_batches_passes(drill):
    """20 批 × 5 文件无重复 → 全部 passed (spec §17 D-19 核心)."""
    report = drill.run_drill(batch_count=20, files_per_batch=5)
    assert len(report.batches) == 20
    assert report.passed is True
    assert report.total_files == 100
    assert report.total_duplicates == 0
    assert report.total_lost_versions == 0
    assert report.recompile_triggers == 0


def test_run_drill_repeat_content_detects_duplicates(drill):
    """重复内容 → duplicate_keys > 0 → 演练 fail (fail-closed)."""
    report = drill.run_drill(batch_count=3, files_per_batch=5, repeat_content=True)
    assert report.total_duplicates > 0
    assert report.passed is False
    # 第 1 批无重复 (首次导入), 第 2+ 批重复
    assert report.batches[0].duplicate_keys == 0
    assert report.batches[1].duplicate_keys > 0


def test_run_drill_writes_log(drill, tmp_path):
    """演练写 .index/incremental_drill.log."""
    report = drill.run_drill(batch_count=2, files_per_batch=5, project_root=tmp_path)
    assert report.log_path.exists()
    content = report.log_path.read_text(encoding="utf-8")
    assert '"action": "incremental_drill"' in content
    assert '"passed": true' in content
