"""Phase 4.6/4.7 tests — 向量维度校验（plan Phase 4 guidance #9, B11/H13）。

store schema 384 vs provider 可能 1536 —— 不一致时必须显式决策，
禁止 ``_migrate_schema_if_needed`` 静默 drop 表（数据丢失）。

验收语义：
- ``init_vector_store_for_paths(paths, expected_dim=...)`` 检测到存量表维度
  与期望维度不一致 → 抛 :class:`VectorDimensionMismatchError`，不删表。
- 显式重建 ``rebuild_vector_schema(paths, dim)`` 是唯一合法 drop 路径
  （决策方 = 运维/rollback 脚本），重建前返回旧维度供审计。
"""
import pytest

from src.vector.store import (
    init_vector_store_for_paths,
    get_table,
    rebuild_vector_schema,
    VectorDimensionMismatchError,
    __reset_for_testing,
)
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths


def setup_function(_):
    __reset_for_testing()


def _dim_of(table) -> int:
    """Read the embedding list_size from the live LanceDB table schema."""
    t = table.schema.field("embedding").type
    return int(getattr(t, "list_size", 0))


def _init(tmp_path, expected_dim=None):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    if expected_dim is None:
        init_vector_store_for_paths(paths)
    else:
        init_vector_store_for_paths(paths, expected_dim=expected_dim)
    return paths


def test_default_init_creates_384_dim_table(tmp_path):
    """缺省 expected_dim=384 —— 与既有行为一致。"""
    paths = _init(tmp_path)
    assert _dim_of(get_table(paths)) == 384


def test_init_with_expected_dim_creates_matching_table(tmp_path):
    """provider 为 1536 时创建 1536 维表。"""
    paths = _init(tmp_path, expected_dim=1536)
    assert _dim_of(get_table(paths)) == 1536


def test_dimension_mismatch_raises_and_preserves_table(tmp_path):
    """存量 384 表 + expected_dim=1536 → 抛错且不删表（禁静默 drop）。"""
    paths = _init(tmp_path)  # 384
    # 写入一行验证表里有数据，drop 会丢数据 —— 断言抛错后数据仍在
    table = get_table(paths)
    table.add([{
        "id": "x1", "task_id": "t1", "content": "hello",
        "embedding": [0.0] * 384, "path": "raw/sources/a.md", "updated_at": 1,
    }])
    with pytest.raises(VectorDimensionMismatchError) as ei:
        init_vector_store_for_paths(paths, expected_dim=1536)
    msg = str(ei.value)
    assert "384" in msg and "1536" in msg
    # 表未删、数据未丢
    assert _dim_of(get_table(paths)) == 384
    assert get_table(paths).count_rows() == 1


def test_rebuild_vector_schema_is_explicit_drop(tmp_path):
    """rebuild_vector_schema 是唯一显式 drop 路径：返回旧维度并重建。"""
    paths = _init(tmp_path)  # 384
    old = rebuild_vector_schema(paths, dim=1536)
    assert old == 384
    assert _dim_of(get_table(paths)) == 1536
    # 重建后 init 同维度不再抛错
    init_vector_store_for_paths(paths, expected_dim=1536)


def test_rebuild_vector_schema_same_dim_is_noop(tmp_path):
    """同维度重建不应 drop（无意义）。"""
    paths = _init(tmp_path)
    old = rebuild_vector_schema(paths, dim=384)
    assert old == 384
    assert _dim_of(get_table(paths)) == 384
