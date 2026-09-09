from pathlib import Path
import json
import pytest

from src.kc.views.book.wiki.compiler import compile_book, publish_book, resolve_active_version
from src.kc.views.book.wiki.compiler import build_from_wiki
from src.kc.views.book.wiki.editorial_state import build_editorial_state, save_editorial_state
from src.kc.views.book.wiki.scanner import scan_wiki_snapshot
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.polish_llm import GeneratedChapter, GeneratedSection


@pytest.fixture(autouse=True)
def _minimal_book_rules(tmp_path):
    (tmp_path / "book.rules.md").write_text(
        "# Book rules\n\n- Audience: general readers\n",
        encoding="utf-8",
    )


def _write_project_rules(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.rules.md").write_text(
        "# Book rules\n\n- Audience: general readers\n",
        encoding="utf-8",
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


def test_plan_manifest_does_not_advertise_unwritten_chapter_files(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    artifact = compile_book(
        snapshot, outlines, pages, fingerprint={}, state_dir=tmp_path / ".index",
        plan_only=True,
    )

    assert not (artifact.version_dir / "v1__c1.md").exists()
    assert artifact.manifest["chapter_files"] == {}
    assert artifact.manifest["planned_chapters"] == ["c1"]


def test_compile_does_not_label_llm_chapter_as_rule_only(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    generated = GeneratedChapter(
        "c1",
        (GeneratedSection("c1--content", "Chapter", "整理后的正文", ("p1",)),),
        "complete",
    )
    artifact = compile_book(
        snapshot, outlines, pages, fingerprint={}, state_dir=tmp_path / ".index",
        polish=True, generated_chapters={"c1": generated},
    )

    text = (artifact.version_dir / "v1__c1.md").read_text(encoding="utf-8")
    assert "本章为规则版排序" not in text
    assert "按主题合并后的章节结构编排" in text


def test_compile_copies_editorial_state_into_release_sidecars(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    editorial_outline = {**outlines[0], "schema_version": "book-outline-v1"}
    state = build_editorial_state(snapshot, book_id="book-1", outline=editorial_outline)
    artifact = compile_book(
        snapshot,
        outlines,
        pages,
        fingerprint={},
        state_dir=tmp_path / ".index",
        editorial_state=state,
    )

    assert artifact.validation_errors == ()
    assert artifact.manifest["generation_mode"] == "rule_only"
    assert artifact.manifest["editorial_state_hash"]
    for relative in (
        "editorial/book.json",
        "editorial/curation.json",
        "editorial/outline.json",
        "editorial/paths.json",
    ):
        assert (artifact.version_dir / relative).is_file()
        assert artifact.manifest["files"][relative]

    output = tmp_path / "book-wiki"
    assert publish_book(artifact, output, apply=False, lock=None).status == "planned"
    assert resolve_active_version(output) is None


def test_compile_labels_conflict_content_in_rule_only_output(tmp_path):
    snapshot, outlines, pages = _fixture(tmp_path)
    editorial_outline = {**outlines[0], "schema_version": "book-outline-v1"}
    state = build_editorial_state(snapshot, book_id="book-1", outline=editorial_outline)
    rows = [dict(row) for row in state.curation["pages"]]
    rows[0]["disposition"] = "conflict"
    state = state.with_curation_pages(tuple(rows))
    artifact = compile_book(
        snapshot, outlines, pages, fingerprint={}, state_dir=tmp_path / ".index",
        editorial_state=state,
    )

    assert artifact.validation_errors == ()
    assert artifact.manifest["disputed_page_ids"] == ["p1"]
    assert "内容状态：争议" in (artifact.version_dir / "v1__c1.md").read_text(encoding="utf-8")


def test_build_from_wiki_uses_persisted_editorial_state(tmp_path):
    project = tmp_path / "project"
    _write_project_rules(project)
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text('{"external_llm_allowed":true}', encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    (project / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody 1\n", encoding="utf-8")
    snapshot = scan_wiki_snapshot(project / "wiki")
    state = build_editorial_state(
        snapshot,
        book_id="book-1",
        outline={
            "schema_version": "book-outline-v1",
            "volumes": [{
                "volume_id": "v1",
                "chapters": [{"chapter_id": "c1", "title": "Chapter", "page_ids": ["p1"]}],
            }],
        },
    )
    output = project / "book-wiki"
    from src.kc.views.book.wiki.editorial_state import save_editorial_state
    save_editorial_state(output, state)

    result = build_from_wiki(project, output_dir=output)
    assert result["status"] == "planned"
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outline_generation_mode"] == "persisted"
    assert manifest["generation_mode"] == "rule_only"


def test_build_from_wiki_full_knowledge_scope_ignores_pilot_curation(tmp_path):
    project = tmp_path / "project"
    _write_project_rules(project)
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text('{"external_llm_allowed":true}', encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    for page_id, title in (("p1", "One"), ("p2", "Two")):
        (project / "wiki" / "concepts" / f"{page_id}.md").write_text(
            f"---\nid: {page_id}\ntitle: {title}\ntype: concept\n---\nBody {page_id}\n",
            encoding="utf-8",
        )
    snapshot = scan_wiki_snapshot(project / "wiki")
    state = build_editorial_state(
        snapshot,
        book_id="book-1",
        outline={
            "schema_version": "book-outline-v1",
            "volumes": [{
                "volume_id": "v1",
                "chapters": [{"chapter_id": "c1", "title": "Chapter", "page_ids": ["p1"]}],
            }],
        },
    )
    output = project / "book-wiki"
    save_editorial_state(output, state)

    result = build_from_wiki(project, output_dir=output, scope_mode="full_knowledge")
    assert result["status"] == "planned"
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["page_count"] == 2
    assert manifest["scope_mode"] == "full_knowledge"


def test_polish_blocks_persisted_outline_without_theme_sections(tmp_path):
    project = tmp_path / "project"
    _write_project_rules(project)
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"owner","budget_cap":3}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    (project / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\n---\nBody\n", encoding="utf-8")
    snapshot = scan_wiki_snapshot(project / "wiki")
    state = build_editorial_state(
        snapshot,
        book_id="book-1",
        outline={
            "schema_version": "book-outline-v1",
            "volumes": [{
                "volume_id": "v1",
                "chapters": [{"chapter_id": "c1", "title": "Chapter", "page_ids": ["p1"], "sections": []}],
            }],
        },
    )
    output = project / "book-wiki"
    save_editorial_state(output, state)

    class Provider:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("missing theme sections must block before provider")

    provider = Provider()
    result = build_from_wiki(
        project, output_dir=output, use_llm=True, polish=True, provider=provider,
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["E_BOOK_THEME_SECTIONS_INVALID"]
    assert result["error"] == "theme_sections_required"
    assert provider.calls == 0


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
