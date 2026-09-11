from src.vector import search


def test_vector_search_deduplicates_chunks_by_page(monkeypatch):
    class FakeTable:
        def __init__(self):
            self.requested_limit = None

        def search(self, _query):
            return self

        def limit(self, value):
            self.requested_limit = value
            return self

        def to_list(self):
            return [
                {"id": "a-0", "task_id": "a", "content": "a0", "path": "wiki/a.md", "_distance": 0.1},
                {"id": "a-1", "task_id": "a", "content": "a1", "path": "wiki/a.md", "_distance": 0.2},
                {"id": "b-0", "task_id": "b", "content": "b0", "path": "wiki/b.md", "_distance": 0.3},
            ]

    table = FakeTable()
    monkeypatch.setattr(search, "get_table", lambda _paths: table)
    result = search.vector_search_chunks([0.1], top_k=2)

    assert table.requested_limit == 10
    assert [item.path for item in result] == ["wiki/a.md", "wiki/b.md"]
