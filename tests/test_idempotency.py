# ruflo-kb/tests/test_idempotency.py
from src.utils.idempotency import IdempotencyCache, check_duplicate
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

# ── Phase 4 P4 P0 加固：重建轮次维度（plan Phase 4 guidance #7）───────────

def test_generate_hash_round_key_backward_compatible():
    """round_key 缺省时哈希与旧行为一致（队列/文件夹路径调用方不受影响）。"""
    cache = IdempotencyCache()
    h_old = cache.generate_hash(SourceType.FILE, "raw/sources/a.md", "", project_id="p1")
    h_new = cache.generate_hash(SourceType.FILE, "raw/sources/a.md", "", project_id="p1",
                                round_key="")
    assert h_old == h_new


def test_generate_hash_round_key_distinguishes_rounds():
    """同一 raw 在不同重建轮次产生不同哈希 → 轮次内幂等、轮次间可重入。"""
    cache = IdempotencyCache()
    base = dict(source_type=SourceType.FILE, identifier="raw/sources/a.md",
                content_prefix="", project_id="proj")
    r1 = cache.generate_hash(round_key="reingest:b12:raw/sources/a.md", **base)
    r2 = cache.generate_hash(round_key="reingest:b12:raw/sources/a.md", **base)
    r3 = cache.generate_hash(round_key="reingest:b13:raw/sources/a.md", **base)
    assert r1 == r2        # 同轮次幂等
    assert r1 != r3        # 跨轮次不同


def test_generate_hash_round_key_marks_round_then_allows_new_round():
    """check_and_mark 在轮次键下：同轮重复 → True；换轮 → False（可重投）。"""
    cache = IdempotencyCache()
    h1 = cache.generate_hash(SourceType.FILE, "raw/sources/b.md", "", project_id="p",
                             round_key="reingest:b1:raw/sources/b.md")
    assert cache.check_and_mark(h1) is False
    assert cache.check_and_mark(h1) is True     # 同轮重复
    h2 = cache.generate_hash(SourceType.FILE, "raw/sources/b.md", "", project_id="p",
                             round_key="reingest:b2:raw/sources/b.md")
    assert cache.check_and_mark(h2) is False    # 新轮次可重投


def test_generate_hash_round_key_not_required():
    """round_key 为可选参数 —— 不传不炸。"""
    cache = IdempotencyCache()
    h = cache.generate_hash(SourceType.URL, "https://round.test/", "")
    assert isinstance(h, str) and len(h) == 32
