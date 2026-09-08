from src.kc.views.book.wiki.quality_gate import check_quality_gate


def test_quality_gate_passes_with_complete_metrics() -> None:
    report = check_quality_gate(
        {
            "expected_block_ids": ["p:0"],
            "draft_block_ids": ["p:0"],
            "unresolved_ratio": 0.0,
            "unmatched_heading_ratio": 0.0,
            "glossary_coverage": 1.0,
        }
    )
    assert report.ok


def test_quality_gate_fails_closed_when_metrics_are_missing() -> None:
    report = check_quality_gate(
        {"expected_block_ids": ["p:0"], "draft_block_ids": ["p:0"]}
    )
    assert not report.ok
    assert {
        "unresolved_metric_missing",
        "heading_metric_missing",
        "glossary_metric_missing",
    } <= set(report.rule_blockers)
