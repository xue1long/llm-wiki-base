from src.wiki.types import PageType, WikiPage
from src.wiki.export import export_wiki
from src.wiki.import_ import import_wiki
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page


def test_export_creates_zip_with_wiki_files(tmp_path):
    """Export bundles wiki pages into a ZIP."""
    src = tmp_path / "src"
    dst_zip = tmp_path / "export.zip"
    ensure_knowledge_base(src)
    p = WikiPaths(src)
    write_page(p, WikiPage(id="ent-1", title="E", type=PageType.ENTITY, body="body"))

    export_wiki(p, dst_zip)
    assert dst_zip.exists()
    assert dst_zip.stat().st_size > 0


def test_import_extracts_zip(tmp_path):
    """Import restores wiki pages from a ZIP."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    archive = tmp_path / "archive.zip"
    ensure_knowledge_base(src)
    p = WikiPaths(src)
    write_page(p, WikiPage(id="ent-2", title="E2", type=PageType.ENTITY, body="body2"))

    export_wiki(p, archive)
    import_wiki(archive, dst)

    restored = dst / "wiki" / "entities" / "ent-2.md"
    assert restored.exists()
    assert "body2" in restored.read_text(encoding="utf-8")


def test_export_excludes_index_dir(tmp_path):
    """LanceDB files under .index/ must NOT be in the export."""
    src = tmp_path / "src"
    dst_zip = tmp_path / "export.zip"
    ensure_knowledge_base(src)
    p = WikiPaths(src)
    # Plant a fake index file
    (p.index / "fake.lance").write_bytes(b"\x00" * 100)

    export_wiki(p, dst_zip)

    import zipfile
    with zipfile.ZipFile(dst_zip, "r") as zf:
        names = zf.namelist()
    assert not any(".index" in n for n in names)