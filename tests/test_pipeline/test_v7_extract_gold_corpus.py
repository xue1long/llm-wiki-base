"""Tests for the V7 gold corpus framework (Task 46, Commit 1)."""
from __future__ import annotations

import json

from src.pipeline.v7_extract.gold_corpus import (
    CorpusFixture,
    CorpusLoader,
    CorpusRunResult,
    CorpusRunner,
    DEFAULT_CORPUS_ROOT,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient


def test_corpus_discovers_all_fixtures():
    """discover() returns at least the 3 Stage 1 fixtures shipped in Commit 1."""
    paths = CorpusLoader.discover(DEFAULT_CORPUS_ROOT)
    assert len(paths) >= 3
    # All files end with .json.
    assert all(p.suffix == ".json" for p in paths)


def test_corpus_loader_parses_seeded_fixture(tmp_path):
    """Loader reads a fixture with all required fields."""
    fx_path = tmp_path / "stage1_test.json"
    fx_path.write_text(json.dumps({
        "id": "x1",
        "stage": "stage1_classify",
        "description": "test",
        "input": {"content": "x", "filename_hint": "x.md"},
        "expected": {"doc_type": "single_method", "failed": False},
    }), encoding="utf-8")
    fx = CorpusLoader.load(fx_path)
    assert fx is not None
    assert fx.id == "x1"
    assert fx.stage == "stage1_classify"
    assert fx.expected["doc_type"] == "single_method"


def test_corpus_loader_skips_malformed_fixture(tmp_path):
    """Missing required field -> returns None (skipped)."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({
        "id": "x1", "stage": "stage1_classify",
        # missing description / input / expected
    }), encoding="utf-8")
    assert CorpusLoader.load(bad_path) is None

    # Non-JSON content.
    not_json = tmp_path / "notjson.json"
    not_json.write_text("not json", encoding="utf-8")
    assert CorpusLoader.load(not_json) is None


def test_corpus_runner_passes_for_seeded_fixtures(tmp_path):
    """Use a tmp corpus root with 2 fixtures; both pass."""
    fx_dir = tmp_path / "corpus"
    fx_dir.mkdir()
    for i, doc_type in enumerate(["single_method", "multi_section"]):
        (fx_dir / f"f{i}.json").write_text(json.dumps({
            "id": f"f{i}",
            "stage": "stage1_classify",
            "description": f"fixture {i}",
            "input": {
                "content": f"text {i}",
                "filename_hint": f"f{i}.md",
                "llm_responses": {
                    "classify": {
                        "doc_type": doc_type, "confidence": 0.8,
                        "rationale": "ok", "traits": [], "uncertain": False,
                    },
                },
            },
            "expected": {
                "doc_type": doc_type, "failed": False, "min_confidence": 0.5,
            },
        }), encoding="utf-8")

    fixtures = [CorpusLoader.load(p) for p in CorpusLoader.discover(fx_dir)]
    assert all(f is not None for f in fixtures)
    fixtures = [f for f in fixtures if f is not None]

    runner = CorpusRunner(llm=FakeLLMClient())
    results = runner.run(fixtures)
    assert len(results) == 2
    assert all(r.passed for r in results)


def test_corpus_runner_reports_failure_with_diff(tmp_path):
    """Wrong expected doc_type -> failure result with diff text."""
    fx_dir = tmp_path / "corpus"
    fx_dir.mkdir()
    (fx_dir / "f.json").write_text(json.dumps({
        "id": "f",
        "stage": "stage1_classify",
        "description": "intentional mismatch",
        "input": {
            "content": "x",
            "filename_hint": "f.md",
            "llm_responses": {
                "classify": {
                    "doc_type": "single_method", "confidence": 0.8,
                    "rationale": "ok", "traits": [], "uncertain": False,
                },
            },
        },
        "expected": {
            # Mismatch: LLM returns single_method, test expects multi_section.
            "doc_type": "multi_section", "failed": False,
        },
    }), encoding="utf-8")
    fx = CorpusLoader.load(fx_dir / "f.json")
    runner = CorpusRunner(llm=FakeLLMClient())
    results = runner.run([fx])
    assert len(results) == 1
    assert results[0].passed is False
    assert "multi_section" in results[0].diff
    assert "single_method" in results[0].diff


def test_corpus_runner_handles_unknown_stage(tmp_path):
    """Fixture with unregistered stage -> failure result, no crash."""
    fx_dir = tmp_path / "corpus"
    fx_dir.mkdir()
    (fx_dir / "f.json").write_text(json.dumps({
        "id": "f",
        "stage": "stageX_unknown",
        "description": "n/a",
        "input": {},
        "expected": {},
    }), encoding="utf-8")
    fx = CorpusLoader.load(fx_dir / "f.json")
    runner = CorpusRunner(llm=FakeLLMClient())
    results = runner.run([fx])
    assert len(results) == 1
    assert results[0].passed is False
    assert "stageX_unknown" in results[0].diff


def test_stage1_corpus_meets_count_threshold():
    """Master plan §5 Task 46: each stage must have ≥ 16 fixtures.

    Verifies the Stage 1 corpus shipped in this commit meets the
    threshold. Other stages (Stage 2-7 + 6R + Recon) are tracked in
    subsequent commits.
    """
    fixtures = []
    for p in CorpusLoader.discover(DEFAULT_CORPUS_ROOT):
        fx = CorpusLoader.load(p)
        if fx is not None and fx.stage == "stage1_classify":
            fixtures.append(fx)
    assert len(fixtures) >= 16, (
        f"Stage 1 corpus has {len(fixtures)} fixtures, need >= 16 per master plan §5"
    )


def test_stage2_corpus_meets_count_threshold():
    """Stage 2 corpus >= 16 fixtures (master plan §5 Task 46)."""
    fixtures = []
    for p in CorpusLoader.discover(DEFAULT_CORPUS_ROOT):
        fx = CorpusLoader.load(p)
        if fx is not None and fx.stage == "stage2_segment":
            fixtures.append(fx)
    assert len(fixtures) >= 16, (
        f"Stage 2 corpus has {len(fixtures)} fixtures, need >= 16 per master plan §5"
    )


def test_stage3_corpus_meets_count_threshold():
    """Stage 3 corpus >= 16 fixtures (master plan §5 Task 46)."""
    fixtures = []
    for p in CorpusLoader.discover(DEFAULT_CORPUS_ROOT):
        fx = CorpusLoader.load(p)
        if fx is not None and fx.stage == "stage3_completeness":
            fixtures.append(fx)
    assert len(fixtures) >= 16, (
        f"Stage 3 corpus has {len(fixtures)} fixtures, need >= 16 per master plan §5"
    )


def test_stage4_corpus_meets_count_threshold():
    """Stage 4 corpus >= 16 fixtures (master plan §5 Task 46)."""
    fixtures = []
    for p in CorpusLoader.discover(DEFAULT_CORPUS_ROOT):
        fx = CorpusLoader.load(p)
        if fx is not None and fx.stage == "stage4_cluster":
            fixtures.append(fx)
    assert len(fixtures) >= 16, (
        f"Stage 4 corpus has {len(fixtures)} fixtures, need >= 16 per master plan §5"
    )


def test_stage5_corpus_meets_count_threshold():
    """Stage 5 corpus >= 16 fixtures (master plan §5 Task 46)."""
    fixtures = []
    for p in CorpusLoader.discover(DEFAULT_CORPUS_ROOT):
        fx = CorpusLoader.load(p)
        if fx is not None and fx.stage == "stage5_extract_claims":
            fixtures.append(fx)
    assert len(fixtures) >= 16, (
        f"Stage 5 corpus has {len(fixtures)} fixtures, need >= 16 per master plan §5"
    )