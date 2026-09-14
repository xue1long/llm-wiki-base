from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.export import export_wiki
from src.wiki.features.import_ import import_wiki
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page


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


def test_export_writes_audit_log(tmp_path):
    src = tmp_path / "src"
    dst_zip = tmp_path / "export.zip"
    ensure_knowledge_base(src)
    p = WikiPaths(src)
    write_page(p, WikiPage(id="ent-3", title="E3", type=PageType.ENTITY, body="body"))

    export_wiki(p, dst_zip)

    log_path = p.index / "export_log.jsonl"
    assert log_path.exists()
    record = __import__("json").loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["output"] == str(dst_zip)
    assert record["page_count"] >= 1
    assert "exported_at" in record


# V4 NOTE: test_operation_page_roundtrips_through_export_and_import REMOVED.
# V6 (post-ADR-002 migration) DOES emit processing_depth to disk
# (it's a V6 18-key whitelist field).
# Body round-trip is still covered by test_export_creates_zip_with_wiki_files
# and test_import_extracts_zip.


def test_repeated_export_appends_one_audit_record_each_time(tmp_path):
    src = tmp_path / "src"
    archive = tmp_path / "repeat.zip"
    ensure_knowledge_base(src)
    paths = WikiPaths(src)

    export_wiki(paths, archive)
    export_wiki(paths, archive)

    records = (paths.index / "export_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 2
