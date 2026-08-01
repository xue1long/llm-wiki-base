"""NDG Phase 0: tests for calibration helpers (percentile, histogram, rounding)."""
import pytest
from pathlib import Path

from scripts.ndg_calibrate import (
    _pct,
    _round_up_to,
    _histogram_bucket,
    _histogram,
    _scan_raw_files,
)


# ── _pct ──────────────────────────────────────────────────────────────

def test_pct_empty():
    assert _pct([], 0.5) == 0.0

def test_pct_single():
    assert _pct([100], 0.5) == 100.0
    assert _pct([100], 0.99) == 100.0

def test_pct_p50():
    vals = sorted([10, 20, 30, 40, 50])
    assert _pct(vals, 0.50) == 30.0

def test_pct_p99():
    # 100 values 0..99
    vals = list(range(100))
    assert _pct(vals, 0.99) == pytest.approx(98.01, rel=0.01)


# ── _round_up_to ──────────────────────────────────────────────────────

def test_round_up_to_50():
    assert _round_up_to(0, 50) == 0
    assert _round_up_to(1, 50) == 50
    assert _round_up_to(99, 50) == 100
    assert _round_up_to(100, 50) == 100
    assert _round_up_to(101, 50) == 150
    assert _round_up_to(300, 50) == 300
    assert _round_up_to(301, 50) == 350


# ── _histogram_bucket ─────────────────────────────────────────────────

def test_histogram_bucket():
    assert _histogram_bucket(0, 200) == "0-200"
    assert _histogram_bucket(199, 200) == "0-200"
    assert _histogram_bucket(200, 200) == "200-400"
    assert _histogram_bucket(1500, 200) == "1400-1600"


# ── _histogram ────────────────────────────────────────────────────────

def test_histogram_empty():
    assert _histogram([]) == {}

def test_histogram_simple():
    vals = [50, 150, 250, 50]
    h = _histogram(vals, 200)
    assert h == {"0-200": 3, "200-400": 1}


# ── _scan_raw_files ──────────────────────────────────────────────────

def test_scan_raw_files_finds_txt(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.md").write_text("world", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_text("nested", encoding="utf-8")
    # non-text files should be ignored by the glob
    (tmp_path / "img.png").write_text("fake", encoding="utf-8")

    files = _scan_raw_files(tmp_path)
    names = {f.name for f in files}
    assert "a.txt" in names
    assert "b.md" in names
    assert "c.txt" in names
    assert "img.png" not in names

def test_scan_raw_files_empty_dir(tmp_path: Path):
    files = _scan_raw_files(tmp_path)
    assert files == []


# ── Integration: report generation with synthetic data ────────────────

def test_calibration_helpers_chain():
    """Simulate a full calibration pipeline with synthetic run lengths."""
    # Synthetic _long_raw_text_run values
    runs = [50, 80, 120, 200, 250, 300, 350, 500, 800, 2500]
    runs.sort()

    p99 = _pct(runs, 0.99)
    t = _round_up_to(p99, 50)
    # p99 of these values should be near 2500, rounded to 2500
    assert t >= 300  # at least the default T_non
    assert t <= 2550

    h = _histogram(runs, 500)
    assert len(h) > 0
    assert sum(h.values()) == len(runs)
