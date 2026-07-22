"""SQLite-backed persistence for metrics (24h rolling window)."""
import json
import sqlite3
import time
from pathlib import Path


RETENTION_HOURS = 24


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS counter (
                name TEXT, labels TEXT, value REAL, timestamp INTEGER,
                PRIMARY KEY (name, labels, timestamp)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gauge (
                name TEXT, labels TEXT, value REAL, timestamp INTEGER,
                PRIMARY KEY (name, labels, timestamp)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS histogram (
                name TEXT, labels TEXT, bucket REAL, count INTEGER, sum REAL, total INTEGER, timestamp INTEGER,
                PRIMARY KEY (name, labels, bucket, timestamp)
            )
        """)
        conn.commit()


def persist_counter(db_path: Path, name: str, labels: dict, value: float) -> None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO counter (name, labels, value, timestamp) VALUES (?, ?, ?, ?)",
            (name, json.dumps(labels, sort_keys=True), value, int(time.time() * 1000)),
        )
        conn.commit()


def persist_gauge(db_path: Path, name: str, labels: dict, value: float) -> None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO gauge (name, labels, value, timestamp) VALUES (?, ?, ?, ?)",
            (name, json.dumps(labels, sort_keys=True), value, int(time.time() * 1000)),
        )
        conn.commit()


def cleanup_old(db_path: Path) -> int:
    """Delete rows older than 24h. Returns count."""
    if not db_path.exists():
        return 0
    cutoff = int(time.time() * 1000) - RETENTION_HOURS * 3600 * 1000
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM counter WHERE timestamp < ?", (cutoff,))
        cur2 = conn.execute("DELETE FROM gauge WHERE timestamp < ?", (cutoff,))
        conn.commit()
        return cur.rowcount + cur2.rowcount
