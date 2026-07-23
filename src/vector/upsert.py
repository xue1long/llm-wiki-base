# ruflo-kb/src/vector/upsert.py
"""Vector-store upsert / delete helpers.

All write paths here go through LanceDB's ``merge_insert`` API for
upsert semantics and a SQL-injection-safe filter expression for
deletes.
"""
from .store import get_table
from ..types import VectorChunk


def _escape_sql_string_literal(value: str) -> str:
    """Escape ``value`` for safe interpolation into a SQL string literal.

    Doubles embedded single quotes per the SQL standard (e.g.
    ``"x' OR 1=1 --"`` becomes ``"x'' OR 1=1 --"``). Use this any time
    caller-controlled text is concatenated into a ``table.delete(...)``
    filter expression.
    """
    if not isinstance(value, str):
        raise TypeError(f"expected str, got {type(value).__name__}")
    return value.replace("'", "''")


def vector_upsert_chunks(
    chunks: list[VectorChunk],
    table=None,
) -> None:
    """Upsert chunks into ``table`` using ``merge_insert`` semantics.

    Backwards-compatible: existing callers passing only ``chunks`` still
    work (we resolve the table from the active project). New callers
    should pass ``table`` explicitly per the task-13 brief signature
    ``(table, rows)`` — to do so positionally, pass the table first
    via the :func:`upsert_chunks_to_table` forwarder.

    Uses ``table.merge_insert("id")`` so re-ingesting the same id
    updates the existing row in place rather than creating a duplicate
    (which is what plain ``table.add`` would do).
    """
    if table is None:
        table = get_table()
    data = [
        {
            "id": c.id,
            "task_id": c.task_id,
            "content": c.content,
            "embedding": c.embedding,
            "path": c.path,
            "updated_at": c.updated_at,
        }
        for c in chunks
    ]
    (
        table.merge_insert("id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(data)
    )


def upsert_chunks_to_table(
    table,
    chunks: list[VectorChunk],
) -> None:
    """Forwarder with the brief-prescribed ``(table, rows)`` signature.

    Equivalent to ``vector_upsert_chunks(chunks, table=table)``.
    """
    vector_upsert_chunks(chunks, table=table)


def vector_delete_page(task_id: str) -> None:
    """Delete all vectors for ``task_id`` (default table)."""
    table = get_table()
    vector_delete_page_for_table(table, task_id)


def vector_delete_page_for_table(table, task_id: str) -> None:
    """Delete all vectors for ``task_id`` from the given ``table``.

    Uses :func:`_escape_sql_string_literal` to escape the value before
    splicing it into the SQL filter expression, blocking injection.
    """
    safe = _escape_sql_string_literal(task_id)
    table.delete(f"task_id = '{safe}'")


def vector_clear_chunks() -> None:
    """清空所有向量"""
    table = get_table()
    table.delete("true")
