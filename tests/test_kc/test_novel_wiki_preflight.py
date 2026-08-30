from pathlib import Path

from scripts.kc_novel_wiki_preflight import build_preflight


def test_preflight_hashes_sources_and_deduplicates(tmp_path: Path):
    project = tmp_path / "project"
    source_root = project / "raw" / "sources"
    source_root.mkdir(parents=True)
    (source_root / "a.md").write_text("same", encoding="utf-8")
    (source_root / "b.md").write_text("same", encoding="utf-8")
    (project / "schema.md").write_text("schema", encoding="utf-8")
    (project / "purpose.md").write_text("purpose", encoding="utf-8")

    report = build_preflight(project)

    assert report["raw_source_count"] == 2
    assert report["canonical_source_count"] == 1
    assert report["duplicate_source_count"] == 1
    assert report["hard_failures"] == []
