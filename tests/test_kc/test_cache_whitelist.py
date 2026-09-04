"""Tests for B-4 commit 2 / K-7 cache cleanup whitelist."""
from __future__ import annotations

from pathlib import Path


from src.maintenance.cache_cleanup import cleanup_all


def _make_paths(tmp_path: Path):
    """Build a minimal WikiPaths-compatible object with .index and .llm_wiki."""
    index_dir = tmp_path / ".index"
    llm_wiki_dir = tmp_path / ".llm-wiki"

    class _Paths:
        index = index_dir
        llm_wiki = llm_wiki_dir
        root = tmp_path

    return _Paths()


def test_cleanup_all_does_not_delete_evidence_dir(tmp_path):
    """`.index/evidence/` 目录不被 cleanup_all 删除 (K-7 白名单)."""
    paths = _make_paths(tmp_path)
    evidence_dir = paths.index / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "ev_001.json").write_text("{}", encoding="utf-8")

    cleanup_all(paths)

    assert evidence_dir.exists()
    assert (evidence_dir / "ev_001.json").exists()


def test_cleanup_all_does_not_delete_diffs_dir(tmp_path):
    """`.index/diffs/` 目录不被 cleanup_all 删除 (K-7 白名单)."""
    paths = _make_paths(tmp_path)
    diffs_dir = paths.index / "diffs"
    diffs_dir.mkdir(parents=True, exist_ok=True)
    (diffs_dir / "diff_001.json").write_text("{}", encoding="utf-8")

    cleanup_all(paths)

    assert diffs_dir.exists()
    assert (diffs_dir / "diff_001.json").exists()


def test_cleanup_all_registers_whitelist_entries(tmp_path):
    """cleanup_all 结果包含 kc_evidence_whitelist + kc_diffs_whitelist 登记."""
    paths = _make_paths(tmp_path)

    results = cleanup_all(paths)

    assert "kc_evidence_whitelist" in results
    assert "kc_diffs_whitelist" in results
    assert results["kc_evidence_whitelist"] == 0  # no-op
    assert results["kc_diffs_whitelist"] == 0  # no-op
