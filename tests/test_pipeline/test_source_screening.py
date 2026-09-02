import pytest

from src.pipeline.prefilter import PrefilterResult
from src.pipeline.source_screening import screen_source


def _prefilter(action="process"):
    return PrefilterResult(action=action, reason="prefilter result")


class _Provider:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_system_skip_does_not_call_llm():
    provider = _Provider('{"relevant": true}')

    result = await screen_source(
        "raw/sources/login.md", "登录/注册", prefilter_result=_prefilter("skip"), provider=provider
    )

    assert result.decision == "skip"
    assert result.method == "rule"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_uncertain_source_uses_llm_and_accepts_high_confidence():
    provider = _Provider('{"relevant": true, "content_type": "tutorial", "confidence": 0.9, "reason": "写作方法"}')

    result = await screen_source(
        "raw/sources/misc.md", "这是一段无法仅凭规则判断用途的内容。",
        prefilter_result=_prefilter(), provider=provider,
    )

    assert result.decision == "accept"
    assert result.content_type == "tutorial"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_low_confidence_is_review_not_skip():
    provider = _Provider('{"relevant": false, "confidence": 0.4, "reason": "无法确定"}')

    result = await screen_source(
        "raw/sources/misc.md", "这是一段内容。",
        prefilter_result=_prefilter(), provider=provider,
    )

    assert result.decision == "review"


@pytest.mark.asyncio
async def test_llm_failure_is_review_not_skip():
    result = await screen_source(
        "raw/sources/misc.md", "这是一段内容。",
        prefilter_result=_prefilter(), provider=_Provider(error=RuntimeError("offline")),
    )

    assert result.decision == "review"
