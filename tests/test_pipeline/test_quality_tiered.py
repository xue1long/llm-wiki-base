"""Tests for QualityJudge tiered activation (full/sample/off + always_judge)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# QualitySettings tests
# ---------------------------------------------------------------------------


class TestQualitySettingsMode:
    def test_default_mode_is_off(self):
        from src.quality.types import QualitySettings
        s = QualitySettings()
        assert s.mode == "off"
        assert s.is_active() is False

    def test_full_mode_is_active(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="full")
        assert s.is_active() is True

    def test_sample_mode_is_active(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample")
        assert s.is_active() is True

    def test_invalid_mode_raises(self):
        from src.quality.types import QualitySettings
        with pytest.raises(ValueError):
            QualitySettings(mode="bogus")

    def test_invalid_sample_rate_raises(self):
        from src.quality.types import QualitySettings
        with pytest.raises(ValueError):
            QualitySettings(mode="sample", sample_rate=-0.1)
        with pytest.raises(ValueError):
            QualitySettings(mode="sample", sample_rate=1.5)

    def test_backward_compat_enabled_true(self):
        """Legacy enabled=True is equivalent to mode='full'."""
        from src.quality.types import QualitySettings
        s = QualitySettings(enabled=True)
        assert s.mode == "full"
        assert s.is_active() is True

    def test_enabled_true_does_not_override_explicit_mode(self):
        """When mode is explicitly set, enabled flag doesn't change it."""
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", enabled=True)
        assert s.mode == "sample"


class TestShouldJudge:
    def test_off_always_false(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="off")
        assert s.should_judge(page_grade="A") is False
        assert s.should_judge(page_grade="B") is False

    def test_full_always_true(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="full")
        assert s.should_judge(page_grade="B") is True
        assert s.should_judge(page_grade="C") is True

    def test_sample_grade_a_always_true(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", sample_rate=0.0)  # 0% random
        # Grade A always judged (always_judge_grade_a=True by default)
        assert s.should_judge(page_grade="A") is True

    def test_sample_grade_a_disabled(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", sample_rate=0.0, always_judge_grade_a=False)
        # With 0% sample rate and no always_judge, no pages pass
        assert s.should_judge(page_grade="A") is False

    def test_sample_low_confidence_always_true(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", sample_rate=0.0)  # 0% random
        # Confidence < 0.7 always judged
        assert s.should_judge(page_grade="B", page_confidence=0.5) is True

    def test_sample_high_confidence_random(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", sample_rate=0.0, always_judge_grade_a=False)
        # 0% random, no always_judge, high confidence → skipped
        assert s.should_judge(page_grade="B", page_confidence=0.8) is False

    def test_sample_random_at_100_percent(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", sample_rate=1.0, always_judge_grade_a=False)
        # 100% sample rate → always true
        assert s.should_judge(page_grade="B", page_confidence=0.8) is True

    def test_always_judge_low_confidence_zero_disabled(self):
        from src.quality.types import QualitySettings
        s = QualitySettings(mode="sample", sample_rate=0.0,
                            always_judge_low_confidence=0.0, always_judge_grade_a=False)
        # Confidence threshold of 0 means no always_judge by confidence
        assert s.should_judge(page_grade="C", page_confidence=0.3) is False


# ---------------------------------------------------------------------------
# QualityJudge judge_batch tests
# ---------------------------------------------------------------------------


class TestJudgeBatchTiered:
    def test_mode_off_skips_all_pages(self):
        """mode='off' → all pages passed, no LLM calls."""
        from src.quality.types import QualitySettings
        from src.quality.judge import QualityJudge

        s = QualitySettings(mode="off")
        judge = QualityJudge(s)

        pages = [
            {"id": "p1", "type": "concept", "body": "content", "grade": "A"},
            {"id": "p2", "type": "concept", "body": "content", "grade": "B"},
        ]

        import asyncio
        result = asyncio.run(judge.judge_batch(pages))

        assert len(result.pages_passed) == 2
        assert len(result.pages_rejected) == 0
        assert result.pages == {}  # no judgments created

    def test_mode_full_judges_all(self):
        """mode='full' submits all pages to the judge (with mock provider)."""
        from src.quality.types import QualitySettings
        from src.quality.judge import QualityJudge
        from unittest.mock import patch, AsyncMock

        s = QualitySettings(mode="full")
        with patch("src.quality.judge.create_llm_provider") as mock_create:
            mock_provider = MagicMock()
            mock_provider.complete = AsyncMock(return_value=MagicMock(
                content='{"scores":{"source_type_appropriateness":0.8,"factuality":0.8,"completeness":0.8,"clarity":0.8,"readability":0.8,"searchability":0.8},"issues":[],"improvement_suggestions":""}'
            ))
            mock_create.return_value = mock_provider
            judge = QualityJudge(s)

            pages = [
                {"id": "a", "type": "concept", "body": "content", "grade": "A"},
                {"id": "b", "type": "entity", "body": "content", "grade": "B"},
            ]

            import asyncio
            result = asyncio.run(judge.judge_batch(pages))

            # All pages judged (full mode)
            assert "a" in result.pages
            assert "b" in result.pages
            assert mock_provider.complete.call_count >= 2

    def test_mode_sample_skips_based_on_rules(self):
        """mode='sample' with 0% rate → only always_judge pages go through judge."""
        from src.quality.types import QualitySettings
        from src.quality.judge import QualityJudge
        from unittest.mock import patch, AsyncMock

        # 0% sample rate + grade A always judged, no low-confidence rule
        s = QualitySettings(mode="sample", sample_rate=0.0,
                            always_judge_low_confidence=0.0)
        with patch("src.quality.judge.create_llm_provider") as mock_create:
            mock_provider = MagicMock()
            mock_provider.complete = AsyncMock(return_value=MagicMock(
                content='{"scores":{"source_type_appropriateness":0.8,"factuality":0.8,"completeness":0.8,"clarity":0.8,"readability":0.8,"searchability":0.8},"issues":[],"improvement_suggestions":""}'
            ))
            mock_create.return_value = mock_provider
            judge = QualityJudge(s)

            pages = [
                {"id": "a1", "type": "concept", "body": "content", "grade": "A"},
                {"id": "b1", "type": "concept", "body": "content", "grade": "B"},
                {"id": "b2", "type": "entity", "body": "content", "grade": "B"},
            ]

            import asyncio
            result = asyncio.run(judge.judge_batch(pages))

            # All pass, but only grade A was actually judged
            assert len(result.pages_passed) == 3
            assert "a1" in result.pages  # judged
            assert "b1" not in result.pages  # skipped (not sampled)

    def test_mode_sample_low_confidence_judged(self):
        """Low confidence pages are always judged in sample mode (with mock)."""
        from src.quality.types import QualitySettings
        from src.quality.judge import QualityJudge
        from unittest.mock import patch, AsyncMock

        s = QualitySettings(mode="sample", sample_rate=0.0,
                            always_judge_grade_a=False,
                            always_judge_low_confidence=0.7)
        with patch("src.quality.judge.create_llm_provider") as mock_create:
            mock_provider = MagicMock()
            mock_provider.complete = AsyncMock(return_value=MagicMock(
                content='{"scores":{"source_type_appropriateness":0.8,"factuality":0.8,"completeness":0.8,"clarity":0.8,"readability":0.8,"searchability":0.8},"issues":[],"improvement_suggestions":""}'
            ))
            mock_create.return_value = mock_provider
            judge = QualityJudge(s)

            pages = [
                {"id": "low", "type": "concept", "body": "x", "grade": "C", "confidence": 0.5},
                {"id": "high", "type": "concept", "body": "y", "grade": "B", "confidence": 0.9},
            ]

            import asyncio
            result = asyncio.run(judge.judge_batch(pages))

            # low confidence → judged; high confidence → skipped
            assert "low" in result.pages
            assert "high" not in result.pages
            assert len(result.pages_passed) == 2
