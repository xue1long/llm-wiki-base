from pathlib import Path

from scripts.kc_novel_wiki_pilot import _error_summary, select_sources


def test_select_sources_is_deterministic_and_bounded(tmp_path: Path):
    root = tmp_path / "raw" / "sources"
    root.mkdir(parents=True)
    (root / "large.md").write_text("x" * 20, encoding="utf-8")
    (root / "small.md").write_text("x", encoding="utf-8")
    (root / "other.txt").write_text("x", encoding="utf-8")

    selected = select_sources(tmp_path, 1)

    assert selected == [root / "small.md"]


def test_error_summary_preserves_provider_cause():
    root = RuntimeError("HTTP 429: token quota exhausted")
    outer = RuntimeError("retry exhausted")
    outer.__cause__ = root

    assert "HTTP 429" in _error_summary(outer)
    assert "token quota exhausted" in _error_summary(outer)
