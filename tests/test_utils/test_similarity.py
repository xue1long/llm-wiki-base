# ruflo-kb/tests/test_utils/test_similarity.py
import pytest
from src.utils.similarity import cosine_similarity, string_similarity
from src.wiki.features.dedup import _cosine_similarity

def test_cosine_similarity():
    assert cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)


@pytest.mark.parametrize("left,right", [([], []), ([1.0], [1.0, 2.0]), ([0.0], [1.0])])
def test_dedup_cosine_wrapper_preserves_edge_cases(left, right):
    assert _cosine_similarity(left, right) == cosine_similarity(left, right) == 0.0

def test_string_similarity():
    assert string_similarity("hello", "hello") == 1.0
    assert string_similarity("abc", "xyz") == 0.0
    # After the T16 fix, prefix matches return the proper length ratio
    # (5/11 ≈ 0.45), not 1.0. The shorter token is "hello", the longer is
    # "hello world"; the ratio is 5/11.
    assert abs(string_similarity("hello world", "hello") - (5 / 11)) < 1e-9


def test_prefix_returns_proper_ratio():
    # 'a' is a prefix of 'apple' → 1/5 = 0.2, NOT 1.0
    assert string_similarity("a", "apple") < 0.5
    assert abs(string_similarity("a", "apple") - (1 / 5)) < 1e-9


def test_symmetric_score():
    # string_similarity must be symmetric
    assert abs(string_similarity("hello", "helo") - string_similarity("helo", "hello")) < 1e-9
