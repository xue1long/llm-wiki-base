from pathlib import Path

from src.kc.views.book.wiki.quality_gate import check_quality_gate
from src.kc.views.book.wiki.reader_tasks import run_reader_tasks, task_pass_rate
from src.kc.views.book.wiki.rubric import load_rubric


def test_five_rubric_tasks_pass_at_least_80(tmp_path: Path):
    artifact = tmp_path / "chapter.md"
    artifact.write_text(
        """## 钩子\n[[钩子-悬念]] 开篇抛出悬念\n## 开端\n## 发展\n## 高潮\n## 冲突策略\n[[冲突-升级]] [[冲突-缓和]] [[冲突-反转]]\nfixture-platform-start fixture-platform-tomato\nfixture-case-01 fixture-case-02 fixture-case-03\n""",
        encoding="utf-8",
    )
    specs = load_rubric(Path("docs/fixtures/rubric/writing_handbook_v4.yaml"))
    reports = run_reader_tasks(specs, artifact)
    assert len(reports) == 5
    assert all(r.evaluated_count == r.expected_count for r in reports)
    assert task_pass_rate(reports) >= 0.8


def test_quality_gate_blocks_hard_limit_and_keeps_llm_unavailable():
    report = check_quality_gate({
        "expected_block_ids": ["a", "a", "b"],
        "draft_block_ids": ["a", "b"],
        "unresolved_ratio": 0.2,
        "unmatched_heading_ratio": 0.2,
        "glossary_coverage": 0.5,
    }, llm_status="unavailable")
    assert report.overall == "fail"
    assert len(report.rule_blockers) == 4
    assert report.llm_scores is None
    assert report.llm_status == "unavailable"


def test_rubric_loader_rejects_unknown_locator(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: rubric-spec-v1\ntasks:\n- task_id: x\n  expected_evidence:\n  - locator_type: regex\n    pattern: x\n", encoding="utf-8")
    try:
        load_rubric(path)
    except ValueError as exc:
        assert "locator" in str(exc)
    else:
        raise AssertionError("invalid locator must fail closed")
