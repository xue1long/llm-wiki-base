"""Tests for SQLite persistence."""
import time
from pathlib import Path

from src.metrics.persistence import (
    init_db, persist_counter, persist_gauge, cleanup_old,
)


def test_init_db_creates_tables(tmp_path):
    db = tmp_path / "m.db"
    init_db(db)
    assert db.exists()
    # Should be idempotent
    init_db(db)
    assert db.exists()


def test_persist_and_query_counter(tmp_path):
    db = tmp_path / "m.db"
    persist_counter(db, "hits", {"path": "/a"}, 5.0)
    init_db(db)
    # Read back via sqlite3 directly (no read API exposed)
    import sqlite3
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name, value FROM counter WHERE name='hits'"
        ).fetchall()
    assert len(rows) >= 1
    assert rows[-1][1] == 5.0


def test_cleanup_old_removes_old_rows(tmp_path):
    db = tmp_path / "m.db"
    init_db(db)
    persist_counter(db, "old", {}, 1.0)
    # Manually backdate the only row
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE counter SET timestamp = 0")
        conn.commit()
    removed = cleanup_old(db)
    assert removed >= 1


def test_persist_gauge_inserts_row(tmp_path):
    db = tmp_path / "m.db"
    persist_gauge(db, "inflight", {"server": "web"}, 3.0)
    import sqlite3
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT name, value FROM gauge").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == 3.0
