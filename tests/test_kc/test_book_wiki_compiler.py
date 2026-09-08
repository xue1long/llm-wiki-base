from pathlib import Path
import json
import pytest

from src.kc.views.book.wiki.compiler import compile_book, publish_book, resolve_active_version
from src.kc.views.book.wiki.compiler import build_from_wiki
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot


@pytest.fixture(autouse=True)
def _minimal_book_rules(tmp_path):
    (tmp_path / "book.rules.md").write_text(
        "# Book rules\n\n- Audience: general readers\n", encoding="utf-8"
    )


def _write_project_rules(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.rules.md").write_text(
        "# Book rules\n\n- Audience: general readers\n", encoding="utf-8"
    )


def _fixture(tmp_path):
    page = PageRecord("p1", "Title", "concept", "concepts/p1.md", "tax", "Summary", (
        ContentBlock("p1:0", "p1", "Heading", "Body", 0),
    ), (), "abc", 4, None)
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outlines = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{"chapter_id": "c1", "title": "Chapter", "page_ids": ["p1"], "overview_refs": ["p1"]}]
    }]}]
    return snapshot, outlines, {"p1": page}


def test_compile_writes_hashed_staging_artifact(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    artifact = compile_book(snapshot, outlines, pages, fingerprint={"renderer": "r1"}, state_dir=tmp_path / ".index")
    assert artifact.validation_errors == ()
    assert artifact.version_dir.is_dir()
    chapter = artifact.version_dir / "v1__c1.md"
    assert chapter.read_text(encoding="utf-8").find("Body") >= 0
    assert artifact.manifest["files"]["v1__c1.md"]


def test_publish_apply_and_reader_fail_closed_on_hash_mismatch(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    artifact = compile_book(snapshot, outlines, pages, fingerprint={}, state_dir=tmp_path / ".index")
    output = tmp_path / "book-wiki"
    report = publish_book(artifact, output, apply=True, lock=None)
    assert report.status == "failed"
    assert resolve_active_version(tmp_path) is None


def test_dry_run_does_not_change_pointer(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    artifact = compile_book(snapshot, outlines, pages, fingerprint={}, state_dir=tmp_path / ".index")
    output = tmp_path / "book-wiki"
    output.mkdir()
    (output / "CURRENT.json").write_text('{"version":"old","manifest_sha256":"x"}', encoding="utf-8")
    publish_book(artifact, output, apply=False, lock=None)
    assert json.loads((output / "CURRENT.json").read_text(encoding="utf-8"))["version"] == "old"


def test_build_from_wiki_scans_real_project_and_dry_runs(tmp_path):
    (tmp_path / ".llm-wiki").mkdir()
    (tmp_path / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    for name in ("entities", "synthesis"):
        (tmp_path / "wiki" / name).mkdir()
    (tmp_path / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\n---\nBody\n", encoding="utf-8")
    result = build_from_wiki(tmp_path, output_dir=tmp_path / "book-wiki")
    assert result["status"] == "planned"
    assert not (tmp_path / "book-wiki" / "CURRENT.json").exists()


def test_apply_requires_quality_gate(tmp_path):
    result = build_from_wiki(tmp_path, output_dir=tmp_path / "book-wiki", apply=True, quality_gate="off")
    assert result["status"] == "failed"
    assert result["reason_codes"] == ["E_QUALITY_GATE_REQUIRED_FOR_APPLY"]


def test_manifest_keeps_ingest_source_provenance(tmp_path):
    page = PageRecord("p1", "Title", "concept", "concepts/p1.md", "tax", "Summary", (
        ContentBlock("p1:0", "p1", "Heading", "Body", 0),
    ), (("references", "source-1"),), "abc", 4, None, "", ("raw/sources/a.md",))
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ("source-1",))
    outlines = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{"chapter_id": "c1", "title": "Chapter", "page_ids": ["p1"], "overview_refs": ["p1"]}]
    }]}]
    artifact = compile_book(snapshot, outlines, {"p1": page}, fingerprint={}, state_dir=tmp_path / ".index")
    assert artifact.manifest["chapter_sources"]["v1__c1.md"] == ["raw/sources/a.md"]
    assert {row["target_id"] for row in artifact.manifest["source_provenance"] if "target_id" in row} == {"source-1"}


def test_encyclopedic_build_uses_injected_provider_and_persists_index(tmp_path):
    project = tmp_path / "project"
    _write_project_rules(project)
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text('{"external_llm_allowed":true}', encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    (project / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\n---\nBody\n", encoding="utf-8")

    class Provider:
        async def complete(self, messages, **kwargs):
            return type("Response", (), {"content": '{"issues":["i"],"consensus":[],"disagreement":[],"cross_link_candidates":[]}'} )()

    result = build_from_wiki(project, output_dir=project / "book-wiki", use_llm=True,
                             encyclopedic=True, provider=Provider())
    assert result["status"] == "planned"
    index = Path(result["version_dir"]) / "encyclopedic_outline.json"
    assert index.is_file()
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["encyclopedic_outline_sha256"]
    assert "encyclopedic_outline.json" in manifest["files"]


def test_llm_outline_is_used_without_polishing_body(tmp_path):
    project = tmp_path / "project"
    _write_project_rules(project)
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text('{"external_llm_allowed":true}', encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    for i in range(2):
        (project / "wiki" / "concepts" / f"p{i}.md").write_text(
            f"---\nid: p{i}\ntitle: Page {i}\ntype: concept\n---\nBody {i}\n", encoding="utf-8"
        )

    class Provider:
        calls = 0

        async def complete(self, messages, **kwargs):
            self.calls += 1
            prompt = json.loads(messages[-1]["content"])
            ids = [page["page_id"] for page in prompt["pages"]]
            return type("Response", (), {"content": json.dumps({
                "chapter_id": prompt["chapter_id"], "title": "LLM chapter",
                "page_ids": ids, "overview_refs": ids[:1],
            })})()

    provider = Provider()
    result = build_from_wiki(project, output_dir=project / "book-wiki", use_llm=True,
                             polish=False, provider=provider)
    assert result["status"] == "planned"
    assert provider.calls > 0
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outline_generation_mode"] == "llm"
    assert manifest["body_generation_mode"] == "rule_aggregate"
    assert manifest["outline_llm_requested"] is True
    assert manifest["polished"] is False
    chapter_files = [p for p in Path(result["version_dir"]).glob("*.md") if p.name not in {"glossary.md", "index.md"}]
    assert chapter_files and "Body 0" in chapter_files[0].read_text(encoding="utf-8")


def test_llm_outline_failure_falls_back_to_rule_outline(tmp_path):
    project = tmp_path / "project"
    _write_project_rules(project)
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text('{"external_llm_allowed":true}', encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    (project / "wiki" / "concepts" / "p0.md").write_text(
        "---\nid: p0\ntitle: Page 0\ntype: concept\n---\nBody 0\n", encoding="utf-8"
    )

    class Provider:
        async def complete(self, messages, **kwargs):
            raise ValueError("invalid response")

    result = build_from_wiki(project, output_dir=project / "book-wiki", use_llm=True,
                             polish=False, provider=Provider())
    assert result["status"] == "planned"
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outline_generation_mode"] == "rule_fallback"
    assert manifest["body_generation_mode"] == "rule_aggregate"
    assert manifest["outline_fallback_reason"]
