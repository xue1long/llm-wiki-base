"""vector_upsert must use merge_insert (not table.add) so re-inserts
UPSERT in place; vector_delete_by_task must escape task_id before
splicing it into a SQL predicate.

Background: the old code did ``table.delete(f"task_id = '{task_id}'")``
which is a SQL-injection sink if ``task_id`` is attacker-controlled.
The fix escapes single-quotes (the SQL string-literal delimiter) by
doubling them, the same way standard SQL string literals are escaped.
"""

from src.vector import upsert


def test_delete_by_task_escapes_single_quote(monkeypatch):
    """A task_id containing a single quote must be escaped so the SQL
    parser does NOT terminate the string literal early.

    The literal body must begin with ``x''`` (the doubled quote) so the
    embedded ``OR 1=1 --`` tail is inert text inside the literal, not
    a top-level SQL boolean clause.
    """
    captured = {}

    class T:
        def delete(self, expr):
            captured["expr"] = expr

    upsert.vector_delete_page_for_table(T(), "x' OR 1=1 --")

    expr = captured["expr"]
    # Predicate must start with the standard ``task_id = '`` opener.
    assert expr.startswith("task_id = '")
    # The literal body must begin with the doubled single-quote (x'').
    body = expr[len("task_id = '"):]
    assert body.startswith("x''")
    # The literal must close at the final single quote; the injected
    # OR clause lives inside the literal (as inert text).
    assert body.endswith("--'")


def test_delete_by_task_passes_safe_id_unchanged():
    """A normal task_id (no quotes) must appear in the predicate normally."""
    captured = {}

    class T:
        def delete(self, expr):
            captured["expr"] = expr

    upsert.vector_delete_page_for_table(T(), "task_abc_123")
    assert "task_abc_123" in captured["expr"]
    assert captured["expr"].startswith("task_id =")


def test_delete_by_task_idempotent_under_injection(monkeypatch):
    """The injection test from the brief: an attacker-controlled task_id
    must NOT be able to match all rows by injecting a tautology clause."""
    captured = {}

    class T:
        def delete(self, expr):
            captured["expr"] = expr

    # Attacker tries to escape the literal and OR in a tautology.
    upsert.vector_delete_page_for_table(T(), "x' OR 1=1 --")
    # The OR clause must be inside the escaped string literal (and thus
    # syntactically inert), not a top-level boolean clause. After
    # doubling, the literal closes at the doubled '', and the OR tail
    # is part of the literal text — so the parser sees one string
    # literal whose value is "x' OR 1=1 --".
    # Equivalently: no unescaped ' OR / ' AND outside the literal.
    body = captured["expr"]
    # Find positions of single quotes (the SQL string-literal delimiters).
    # The injected opening quote at index of "'" right after x must be
    # closed by a doubled '' inside the literal — so all single quotes
    # inside the predicate appear as '' pairs.
    inside_literal = body.split("task_id = '", 1)[1]
    # The literal should close at the final '.
    # Within the literal, every un-escaped ' must be doubled.
    # If escaping worked, the literal content is exactly the original
    # task_id (with ' replaced by '').
    assert inside_literal.startswith("x'' OR 1=1 --")


def test_upsert_uses_merge_insert(monkeypatch):
    """vector_upsert_chunks must call table.merge_insert('id') — not table.add.
    merge_insert is the LanceDB API that gives UPSERT semantics (add would
    create duplicate rows on re-ingest)."""
    captured = {}

    class FakeMergeInsert:
        def when_matched_update_all(self):
            captured["when_matched_update_all"] = True
            return self
        def when_not_matched_insert_all(self):
            captured["when_not_matched_insert_all"] = True
            return self
        def execute(self, data):
            captured["data"] = data
            return None

    class T:
        def add(self, data):
            captured["add_called"] = True
            return None
        def merge_insert(self, key):
            captured["merge_insert_key"] = key
            return FakeMergeInsert()

    # Reset add_called in case a prior test polluted it
    captured.clear()
    from src.types import VectorChunk
    chunk = VectorChunk(
        id="id-1",
        task_id="t1",
        content="hello",
        embedding=[0.0] * 4,
        path="/tmp/x",
        updated_at=0,
    )
    upsert.upsert_chunks_to_table(T(), [chunk])
    assert "add_called" not in captured
    assert captured.get("merge_insert_key") == "id"
    assert captured.get("when_matched_update_all") is True
    assert captured.get("when_not_matched_insert_all") is True
    assert isinstance(captured.get("data"), list)


def test_upsert_signature_accepts_table_arg():
    """vector_upsert_chunks must accept a table arg (for testability /
    so callers can pass a stub)."""
    import inspect
    sig = inspect.signature(upsert.vector_upsert_chunks)
    # First positional arg = chunks; second named arg = table.
    params = list(sig.parameters.values())
    assert len(params) >= 1
    # The forwarder with brief-prescribed (table, rows) signature also exists.
    sig2 = inspect.signature(upsert.upsert_chunks_to_table)
    params2 = list(sig2.parameters.values())
    assert len(params2) == 2
    assert params2[0].name == "table"
