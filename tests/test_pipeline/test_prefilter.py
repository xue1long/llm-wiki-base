"""Tests for D3: Rule-based document pre-filtering (src/pipeline/prefilter.py)."""
from src.pipeline.prefilter import prefilter, PrefilterResult


# ---------------------------------------------------------------------------
# Rule 1 — File size
# ---------------------------------------------------------------------------

class TestPrefilterEmptyFile:
    def test_empty_file_skipped(self):
        """<100 bytes → skip."""
        result = prefilter(source_text="", file_size=0)
        assert result.action == "skip"
        assert "100" in result.reason

    def test_tiny_file_processed(self):
        """150 bytes with content → process."""
        result = prefilter(source_text="测试内容 " * 10, file_size=150)
        assert result.action == "process"

    def test_file_at_99_bytes_skipped(self):
        """99 bytes → skip."""
        result = prefilter(source_text="x" * 99, file_size=99)
        assert result.action == "skip"

    def test_file_at_100_bytes_processed(self):
        """100 bytes with Chinese content → process."""
        result = prefilter(source_text="测" * 34, file_size=100)
        assert result.action == "process"


# ---------------------------------------------------------------------------
# Rule 2 — Sanitizer score threshold
# ---------------------------------------------------------------------------

class TestPrefilterLowSanitizerScore:
    def test_low_sanitizer_score_source_only(self, monkeypatch):
        """score 0.2 with SKIP_LLM enabled → source_only."""
        monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")
        result = prefilter(
            source_text="中文内容",
            file_size=500,
            sanitizer_score=0.2,
        )
        assert result.action == "source_only"
        assert result.metadata.get("sanitizer_score") == 0.2

    def test_low_sanitizer_score_without_skip_llm_processed(self, monkeypatch):
        """score 0.2 without SKIP_LLM → process (flag is opt-in)."""
        monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "0")
        result = prefilter(
            source_text="中文内容 " * 20,
            file_size=500,
            sanitizer_score=0.2,
        )
        assert result.action == "process"

    def test_sanitizer_score_none_processed(self, monkeypatch):
        """sanitizer_score=None + SKIP_LLM → process (rule bypassed)."""
        monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")
        result = prefilter(
            source_text="中文内容 " * 20,
            file_size=500,
            sanitizer_score=None,
        )
        assert result.action == "process"

    def test_normal_sanitizer_score_processed(self, monkeypatch):
        """score 0.8 with SKIP_LLM → process."""
        monkeypatch.setenv("RUFLO_SANITIZER_SKIP_LLM", "1")
        result = prefilter(
            source_text="中文内容 " * 20,
            file_size=500,
            sanitizer_score=0.8,
        )
        assert result.action == "process"


# ---------------------------------------------------------------------------
# Rule 4 — English-only detection
# ---------------------------------------------------------------------------

class TestPrefilterEnglish:
    def test_pure_english_marked_skip(self):
        """No Chinese chars → skip, language=en."""
        result = prefilter(
            source_text=(
                "This is a pure English document with no Chinese characters whatsoever. "
                "It contains multiple sentences and paragraphs in English only."
            ),
            file_size=200,
        )
        assert result.action == "skip"
        assert result.metadata.get("language") == "en"

    def test_english_with_chinese_processed(self):
        """Mixed content → process."""
        result = prefilter(
            source_text="This has Chinese 字符 mixed in with English text.",
            file_size=200,
        )
        assert result.action == "process"

    def test_english_only_whitespace_not_skipped_as_english(self):
        """Whitespace-only text should not trigger the English rule
        (the strip() guard prevents false positives)."""
        result = prefilter(
            source_text="   \n  \n  ",
            file_size=200,
        )
        # Whitespace-only has no Chinese, but strip() is empty → not "pure English"
        # The empty rule would have caught it if file_size < 100, but here
        # file_size >= 100 so it falls through to "process".
        assert result.action == "process"

    def test_chinese_only_processed(self):
        """Pure Chinese content → process."""
        result = prefilter(
            source_text="这是一段纯中文内容，没有任何英文字符。",
            file_size=200,
        )
        assert result.action == "process"


# ---------------------------------------------------------------------------
# Rule 3 — List-heavy detection
# ---------------------------------------------------------------------------

class TestPrefilterListHeavy:
    def test_list_heavy_detected(self):
        """>80% list lines → reference_list."""
        lines = []
        for i in range(50):
            lines.append(f"- item {i}")
        lines.append("中文段落内容。")
        lines.append("Another normal line with 中文.")
        result = prefilter(
            source_text="\n".join(lines),
            file_size=500,
        )
        assert result.action == "reference_list"
        assert "list_density" in result.metadata
        assert result.metadata["list_density"] > 0.8

    def test_normal_document_processed(self):
        """Normal content → process."""
        result = prefilter(
            source_text=(
                "这是一段正常的中文文档内容。\n"
                "包含多个段落和描述信息。\n\n"
                "第二段继续描述相关概念和理论框架。"
            ),
            file_size=500,
        )
        assert result.action == "process"

    def test_moderate_list_not_detected(self):
        """~50% list lines → process (below 80% threshold)."""
        lines = []
        for i in range(5):
            lines.append(f"- item {i}")
        for i in range(5):
            lines.append(f"这是第{i}段普通中文段落内容。")
        result = prefilter(
            source_text="\n".join(lines),
            file_size=300,
        )
        assert result.action == "process"


# ---------------------------------------------------------------------------
# PrefilterResult dataclass
# ---------------------------------------------------------------------------

class TestPrefilterResultDataclass:
    def test_default_metadata_is_empty_dict(self):
        result = PrefilterResult(action="process", reason="ok")
        assert result.metadata == {}

    def test_action_literal_values(self):
        """All four action values are accepted."""
        for action in ("process", "skip", "source_only", "reference_list"):
            result = PrefilterResult(action=action, reason="test")
            assert result.action == action

    def test_metadata_passthrough(self):
        result = PrefilterResult(
            action="skip",
            reason="test",
            metadata={"language": "en", "score": 0.5},
        )
        assert result.metadata["language"] == "en"
        assert result.metadata["score"] == 0.5
