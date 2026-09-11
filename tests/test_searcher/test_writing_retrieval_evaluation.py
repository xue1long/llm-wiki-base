"""Contract checks for the small writing retrieval evaluation input."""

from pathlib import Path

import yaml


def test_writing_evaluation_has_required_case_counts_and_real_bindings():
    root = Path(__file__).parents[2]
    data = yaml.safe_load(
        (root / "docs/evaluation/writing_retrieval_cases.yaml").read_text(encoding="utf-8")
    )
    cases = data["cases"]
    assert len(cases) == 20
    assert sum(case["kind"] == "positive" for case in cases) == 15
    assert sum(case["kind"] == "negative" for case in cases) == 5
    for case in cases:
        if case["expected_page_id"]:
            page = root / "knowledge/novel-wiki/wiki/concepts" / f'{case["expected_page_id"]}.md'
            assert page.exists()
            assert page.read_text(encoding="utf-8").split("---", 2)[-1].strip()
        for source in case["evidence_sources"]:
            assert (root / "knowledge/novel-wiki" / source).exists()
