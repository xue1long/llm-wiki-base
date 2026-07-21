# ruflo-kb/tests/test_idempotency.py
import pytest
from src.utils.idempotency import IdempotencyCache, generate_task_hash, check_duplicate
from src.types import SourceType

def test_generate_hash():
    cache = IdempotencyCache()
    h1 = cache.generate_hash(SourceType.URL, "https://example.com", "content prefix")
    h2 = cache.generate_hash(SourceType.URL, "https://example.com", "content prefix")
    h3 = cache.generate_hash(SourceType.URL, "https://different.com", "content prefix")

    assert h1 == h2  # 相同输入应产生相同哈希
    assert h1 != h3  # 不同标识符应产生不同哈希

def test_check_and_mark():
    cache = IdempotencyCache()
    task_hash = cache.generate_hash(SourceType.FILE, "/path/to/file.md", "")

    # 第一次检查：不应重复
    assert cache.check_and_mark(task_hash) is False

    # 第二次检查：应重复
    assert cache.check_and_mark(task_hash) is True

def test_check_duplicate_function():
    cache = IdempotencyCache()
    task_hash = cache.generate_hash(SourceType.URL, "https://test.com", "")

    assert check_duplicate(task_hash) is False
    assert check_duplicate(task_hash) is True
