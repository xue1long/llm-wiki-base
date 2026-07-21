from src.lib.context_budget import estimate_tokens, chunk_by_budget


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_uses_half_chars():
    """Conservative 0.5 token per char."""
    assert estimate_tokens("a" * 100) == 50
    assert estimate_tokens("hello world") == 5  # 11 chars / 2 = 5 (floor)
    assert estimate_tokens("中文测试") == 2  # 4 chars / 2


def test_estimate_tokens_chinese():
    """Chinese: 0.5 token/char (conservative)."""
    assert estimate_tokens("中") == 0  # 1 char → 0
    assert estimate_tokens("中文") == 1


def test_chunk_by_budget_no_split_when_fits():
    text = "short text"
    chunks = chunk_by_budget(text, max_tokens=100)
    assert chunks == [text]


def test_chunk_by_budget_splits_long_text():
    """Long text splits into multiple chunks at paragraph boundary."""
    para1 = "Para 1. " * 100   # 900 chars
    para2 = "Para 2. " * 100   # 900 chars
    text = para1 + "\n\n" + para2

    chunks = chunk_by_budget(text, max_tokens=200)  # 400 chars
    assert len(chunks) >= 2
    # Each chunk under 200 tokens = 400 chars
    for c in chunks:
        assert estimate_tokens(c) <= 200


def test_chunk_by_budget_empty():
    assert chunk_by_budget("", max_tokens=100) == []
