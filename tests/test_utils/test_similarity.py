# ruflo-kb/tests/test_utils/test_similarity.py
import pytest
from src.utils.similarity import cosine_similarity, string_similarity

def test_cosine_similarity():
    assert cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)

def test_string_similarity():
    assert string_similarity("hello", "hello") == 1.0
    assert string_similarity("abc", "xyz") == 0.0
    assert string_similarity("hello world", "hello") > 0.5
