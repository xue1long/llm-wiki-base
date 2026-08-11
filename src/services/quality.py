"""Quality judge service — thin wrapper over src/quality/."""
from __future__ import annotations


def run_quality_judge(page_id: str, page_type: str, page_body: str, settings=None) -> dict:
    """Run QualityJudge.judge_page for a single page, return judgment dict."""
    import asyncio

    from ..quality.judge import QualityJudge
    from ..quality.types import QualitySettings as QS

    _settings = settings if settings is not None else QS()
    judge = QualityJudge(settings=_settings)
    return asyncio.run(judge.judge_page(page_id, page_type, page_body)).to_dict()
