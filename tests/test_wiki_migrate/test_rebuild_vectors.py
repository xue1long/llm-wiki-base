import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class Page:
    id: str
    body: str
    path: str


class FakeMerge:
    def __init__(self, table):
        self.table = table

    def when_matched_update_all(self):
        return self

    def when_not_matched_insert_all(self):
        return self

    def execute(self, rows):
        self.table.rows.update({row["id"]: row for row in rows})


class FakeTable:
    def __init__(self):
        self.rows = {}

    def merge_insert(self, _key):
        return FakeMerge(self)

    def count_rows(self):
        return len(self.rows)


class FakeDb:
    def __init__(self):
        self.table = None

    def open_table(self, _name):
        if self.table is None:
            raise RuntimeError("missing table")
        return self.table

    def create_table(self, _name, schema=None, exist_ok=False):
        del schema, exist_ok
        self.table = FakeTable()
        return self.table


class FakeProvider:
    model = "fake-embedding"

    def __init__(self, dim=3, failures=None):
        self.dim = dim
        self.failures = list(failures or [])
        self.calls = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        if self.failures:
            error = self.failures.pop(0)
            if error is not None:
                raise error
        return [[float(index)] * self.dim for index, _ in enumerate(texts)]


def run(coro):
    return asyncio.run(coro)


def test_dry_run_counts_chunks_without_writing(tmp_path):
    from scripts.rebuild_vectors import rebuild_vectors

    pages = [Page("p1", "one", "wiki/concepts/p1.md"), Page("p2", "two", "wiki/concepts/p2.md")]
    result = run(
        rebuild_vectors(
            tmp_path,
            dry_run=True,
            page_loader=lambda _root: pages,
            provider=FakeProvider(),
        )
    )

    assert result.dry_run is True
    assert result.page_count == 2
    assert result.chunk_count == 2
    assert result.replaced is False
    assert not (tmp_path / ".index" / "staging").exists()


def test_rebuild_uses_provider_dimension_and_replaces_only_after_row_check(tmp_path):
    from scripts.rebuild_vectors import rebuild_vectors

    old_live = tmp_path / ".index" / "lancedb"
    old_live.mkdir(parents=True)
    (old_live / "sentinel").write_text("old", encoding="utf-8")

    pages = [Page("p1", "one", "wiki/concepts/p1.md")]
    provider = FakeProvider(dim=7)
    dbs = []

    def db_factory(_path):
        db = FakeDb()
        dbs.append(db)
        return db

    result = run(
        rebuild_vectors(
            tmp_path,
            page_loader=lambda _root: pages,
            provider=provider,
            db_factory=db_factory,
            table_factory=lambda db, _dim: db.create_table("chunks"),
            sleep=lambda _delay: asyncio.sleep(0),
        )
    )

    assert result.dimension == 7
    assert result.chunk_count == 1
    assert result.vector_row_count == 1
    assert result.replaced is True
    assert (old_live / "sentinel").exists() is False
    assert len(dbs[-1].table.rows) == 1


def test_retry_only_retries_429_and_5xx_and_resume_uses_checkpoint(tmp_path):
    from scripts.rebuild_vectors import rebuild_vectors

    pages = [Page(f"p{i}", f"body-{i}", f"wiki/concepts/p{i}.md") for i in range(3)]
    provider = FakeProvider(
        failures=[RuntimeError("429 rate limit"), RuntimeError("500 server"), None]
    )
    delays = []

    async def no_wait(delay):
        delays.append(delay)

    dbs = []

    def db_factory(_path):
        db = FakeDb()
        dbs.append(db)
        return db

    result = run(
        rebuild_vectors(
            tmp_path,
            run_id="resume-me",
            provider=provider,
            page_loader=lambda _root: pages,
            db_factory=db_factory,
            table_factory=lambda db, _dim: db.create_table("chunks"),
            sleep=no_wait,
        )
    )

    assert result.replaced is True
    assert delays == [1.0, 2.0]
    checkpoint = Path(result.checkpoint_path)
    assert checkpoint.exists()
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert data["processed_pages"] == 3
    assert data["page_manifest_hash"] == result.page_manifest_hash


def test_non_retryable_error_does_not_touch_existing_live_store(tmp_path):
    from scripts.rebuild_vectors import rebuild_vectors

    old_live = tmp_path / ".index" / "lancedb"
    old_live.mkdir(parents=True)
    sentinel = old_live / "sentinel"
    sentinel.write_text("old", encoding="utf-8")
    provider = FakeProvider(failures=[ValueError("bad input")])
    pages = [Page("p1", "one", "wiki/concepts/p1.md")]

    with pytest.raises(ValueError, match="bad input"):
        run(
            rebuild_vectors(
                tmp_path,
                run_id="failed-run",
                provider=provider,
                page_loader=lambda _root: pages,
                db_factory=lambda _path: FakeDb(),
                table_factory=lambda db, _dim: db.create_table("chunks"),
                sleep=lambda _delay: asyncio.sleep(0),
            )
        )

    assert sentinel.read_text(encoding="utf-8") == "old"
