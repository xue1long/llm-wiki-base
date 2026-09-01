from types import SimpleNamespace

from src.orchestrator.batch_runner import _snapshot_page_hashes
from src.wiki.core.types import PageType
from src.wiki import schema_registry
from src.wiki.storage import page_writer


def test_snapshot_page_hashes_uses_current_page_path_api(tmp_path, monkeypatch):
    page_path = tmp_path / "wiki_concepts" / "concept.md"
    page_path.parent.mkdir()
    page_path.write_bytes(b"page")

    monkeypatch.setattr(
        schema_registry.SchemaRegistry,
        "from_project",
        staticmethod(lambda _: object()),
        raising=False,
    )
    monkeypatch.setattr(
        page_writer,
        "page_path_for",
        lambda paths, page_type, slug: page_path,
    )

    page = SimpleNamespace(type=PageType.CONCEPT, id="concept", custom_type="")
    paths = SimpleNamespace(root=tmp_path)

    assert _snapshot_page_hashes(paths, [page])
