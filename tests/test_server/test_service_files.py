"""Tests for src.services.files — file listing + content reading.

These services extract logic previously inlined in src/server/routes/files.py
(path traversal check, rglob walk, response shaping). Routes now become
thin wrappers that map service exceptions to HTTPException.
"""
import hashlib
import json

import pytest

from src.services import files as files_service


def test_list_files_returns_markdown_files(monkeypatch, tmp_path):
    """list_files walks the wiki tree and returns file metadata."""
    # Set up a project with some markdown files
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)
    (wiki_dir / "sources" / "a.md").write_text("# A", encoding="utf-8")
    (wiki_dir / "sources" / "b.md").write_text("## B" * 100, encoding="utf-8")
    (wiki_dir / "entities").mkdir()
    (wiki_dir / "entities" / "c.md").write_text("# C", encoding="utf-8")
    (wiki_dir / "not_markdown.txt").write_text("ignored", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_files("u", root="wiki")
    paths = sorted(f["path"] for f in result["files"])
    # 3 .md files, 1 .txt excluded
    assert "wiki/sources/a.md" in paths
    assert "wiki/sources/b.md" in paths
    assert "wiki/entities/c.md" in paths
    assert not any("not_markdown" in p for p in paths)
    assert result["truncated"] is False
    assert result["totalCount"] == 3


def test_list_files_truncates_at_max(monkeypatch, tmp_path):
    """list_files respects max_files limit."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)
    for i in range(5):
        (wiki_dir / "sources" / f"f{i}.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_files("u", root="wiki", max_files=3)
    assert result["truncated"] is True
    assert len(result["files"]) == 3
    assert result["totalCount"] == 5


def test_list_files_missing_dir_returns_empty(monkeypatch, tmp_path):
    """If the wiki dir doesn't exist, return empty list (not an error)."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_files("u", root="wiki")
    assert result == {"files": [], "truncated": False, "totalCount": 0}


def test_read_file_content_returns_text(monkeypatch, tmp_path):
    """read_file_content reads file contents for a path within the wiki root."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)
    (wiki_dir / "sources" / "a.md").write_text("# Hello", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.read_file_content("u", "sources/a.md")
    assert result["content"] == "# Hello"
    # path is relative to project root (which contains the wiki/ subtree)
    assert result["path"] == "wiki/sources/a.md"


def test_read_file_content_blocks_traversal(monkeypatch, tmp_path):
    """read_file_content must reject paths that escape the wiki root."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    with pytest.raises(files_service.PathTraversalError):
        files_service.read_file_content("u", "../../etc/passwd")


def test_read_file_content_raises_not_found(monkeypatch, tmp_path):
    """If the file doesn't exist within wiki, raise FileNotFoundError."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    with pytest.raises(files_service.FileNotFoundError):
        files_service.read_file_content("u", "sources/nonexistent.md")


def test_list_raw_files_detects_ingested_via_frontmatter(monkeypatch, tmp_path):
    """list_raw_files must detect ingestion by reading wiki page frontmatter
    'sources' field, NOT by filename stem matching.

    Regression: wiki pages use generated IDs as filenames (e.g. kb-2026...-.md),
    not the raw file name. The old stem-prefix match always failed, reporting
    every raw file as not-ingested.
    """
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    # Raw files
    raw_dir = project_dir / "raw" / "sources"
    raw_dir.mkdir(parents=True)
    (raw_dir / "doc1.pdf").write_text("pdf content", encoding="utf-8")
    (raw_dir / "doc2.docx").write_text("docx content", encoding="utf-8")
    (raw_dir / "doc3.xlsx").write_text("xlsx content", encoding="utf-8")
    (raw_dir / "no_wiki_page.pdf").write_text("orphan", encoding="utf-8")

    # Wiki source pages — filenames are generated IDs (not raw file names)
    wiki_sources = project_dir / "wiki" / "sources"
    wiki_sources.mkdir(parents=True)
    (wiki_sources / "kb-20260726154545-e84f1b2b.md").write_text(
        "---\n"
        "id: kb-20260726154545-e84f1b2b\n"
        "title: doc1.pdf\n"
        "type: source\n"
        "sources:\n"
        "- raw/sources/doc1.pdf\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )
    (wiki_sources / "kb-20260726154727-87487434.md").write_text(
        "---\n"
        "id: kb-20260726154727-87487434\n"
        "title: doc2.docx\n"
        "type: source\n"
        "sources:\n"
        "- raw\\sources\\doc2.docx\n"  # Windows-style backslash
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )
    # doc3: source path written as absolute-style with forward slashes
    (wiki_sources / "kb-20260726154728-6537763a.md").write_text(
        "---\n"
        "id: kb-20260726154728-6537763a\n"
        "title: doc3.xlsx\n"
        "type: source\n"
        "sources:\n"
        "- raw/sources/doc3.xlsx\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_raw_files("u")
    files_by_name = {f["name"]: f for f in result["files"]}

    # Files referenced by wiki page frontmatter → ingested
    assert files_by_name["doc1.pdf"]["ingested"] is True
    assert files_by_name["doc2.docx"]["ingested"] is True
    assert files_by_name["doc3.xlsx"]["ingested"] is True
    # No wiki page references this file → not ingested
    assert files_by_name["no_wiki_page.pdf"]["ingested"] is False


def test_list_raw_files_missing_dir_returns_empty(monkeypatch, tmp_path):
    """If raw/sources doesn't exist, return empty list (not an error)."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_raw_files("u")
    assert result == {"files": []}


def test_list_raw_files_filters_non_raw_extensions(monkeypatch, tmp_path):
    """Only files with extensions in _RAW_EXTS should appear."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    raw_dir = project_dir / "raw" / "sources"
    raw_dir.mkdir(parents=True)
    (raw_dir / "a.pdf").write_text("pdf", encoding="utf-8")
    (raw_dir / "b.exe").write_text("exe", encoding="utf-8")
    (raw_dir / "c.py").write_text("py", encoding="utf-8")
    (raw_dir / "d.docx").write_text("docx", encoding="utf-8")
    (raw_dir / "subdir").mkdir()
    (raw_dir / "subdir" / "e.txt").write_text("txt", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_raw_files("u")
    names = {f["name"] for f in result["files"]}
    assert names == {"a.pdf", "d.docx", "e.txt"}
    assert "b.exe" not in names
    assert "c.py" not in names


def test_upload_file_writes_to_raw_sources(monkeypatch, tmp_path):
    """upload_file persists bytes to raw/sources/<name> and returns path."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.upload_file("u", "note.md", b"# hello")
    assert result["path"] == "raw/sources/note.md"
    assert result["size"] == 7
    dest = project_dir / "raw" / "sources" / "note.md"
    assert dest.read_bytes() == b"# hello"


def test_upload_file_sanitizes_basename(monkeypatch, tmp_path):
    """upload_file strips path separators to prevent traversal."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.upload_file("u", "../../../evil.txt", b"x")
    # Written under raw/sources/, not outside the project
    assert result["path"] == "raw/sources/evil.txt"
    assert (project_dir / "raw" / "sources" / "evil.txt").exists()
    assert not (project_dir / "evil.txt").exists()


def test_upload_file_rejects_unsupported_ext(monkeypatch, tmp_path):
    """upload_file raises UnsupportedFileTypeError for non-raw extensions."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    import pytest
    with pytest.raises(files_service.UnsupportedFileTypeError):
        files_service.upload_file("u", "script.exe", b"\x00")


def test_book_wiki_versions_lists_verified_releases_and_reads_selected(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    (project_dir / ".llm-wiki").mkdir(parents=True)
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id":"u","name":"p","schema_version":"v2.0"}', encoding="utf-8")
    book_dir = project_dir / "book-wiki"
    for version, title in (("v1", "Old"), ("v2", "New")):
        release = book_dir / ".releases" / version
        release.mkdir(parents=True)
        chapter = f"# {title}\n"
        (release / "v001__c001.md").write_text(chapter, encoding="utf-8")
        (release / "sources-index.md").write_text("# Sources index\n", encoding="utf-8")
        digest = hashlib.sha256((release / "v001__c001.md").read_bytes()).hexdigest()
        sources_digest = hashlib.sha256((release / "sources-index.md").read_bytes()).hexdigest()
        outline = [{"volumes": [{"volume_id": "v001", "title": "第一卷", "chapters": [{"chapter_id": "c001", "title": "第一章"}]}]}]
        (release / "outline.json").write_text(json.dumps(outline), encoding="utf-8")
        outline_digest = hashlib.sha256((release / "outline.json").read_bytes()).hexdigest()
        manifest = {"run_id": version, "chapter_count": 1, "page_count": 1,
                    "scope_mode": "full_knowledge", "coverage_ratio": 1.0,
                    "source_appendix_count": 463,
                    "files": {"v001__c001.md": digest, "outline.json": outline_digest,
                              "sources-index.md": sources_digest}}
        (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    active_manifest = (book_dir / ".releases" / "v2" / "manifest.json").read_bytes()
    (book_dir / "CURRENT.json").write_text(json.dumps({
        "version": "v2", "manifest_sha256": hashlib.sha256(active_manifest).hexdigest()
    }), encoding="utf-8")
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    versions = files_service.book_wiki_versions("u")["versions"]
    assert {item["version"] for item in versions} == {"v1", "v2"}
    assert next(item for item in versions if item["version"] == "v2")["active"] is True
    selected_manifest = files_service.book_wiki_manifest("u", version="v1")
    assert selected_manifest["volumes"][0]["title"] == "第一卷"
    assert selected_manifest["chapters"][0]["title"] == "第一章"
    assert selected_manifest["scope_mode"] == "full_knowledge"
    assert selected_manifest["source_appendix"]["count"] == 463
    assert selected_manifest["chapters"][0]["path"] == "v001__c001.md"
    selected = files_service.read_book_wiki_content("u", "v001__c001.md", version="v1")
    assert selected["content"] == "# Old\n"


def _fake_resolve(project_dir):
    """Build a (ProjectContext, WikiPaths) pair pointing at project_dir."""
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)

# ─── Task 2 HTTP integration smoke (Task 0 fix surface) ─────────────


def _build_release_with_colon_chapter_ids(
    project_dir: Path, *, version: str = "v1",
    chapters=(
        # (volume_id, native_chapter_id, body)
        ("writing-tech", "writing-tech:5", "# Tech chapter 5\n"),
        ("writing-tech", "writing-tech:6", "# Tech chapter 6\n"),
        ("fallback", "fallback:0", "# Fallback chapter 0\n"),
    ),
):
    """Drop a minimal release where chapter_ids contain `:`.

    Matches the real release's naming convention (compiler.py:536
    preserves the outline-supplied `chapter_id`). The on-disk filename
    after `_safe()` is `{vol}__{chapter_id with `:` rewritten to `_`}.md`.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / ".llm-wiki").mkdir(exist_ok=True)
    (project_dir / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "u", "name": "p", "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    book_dir = project_dir / "book-wiki"
    release = book_dir / ".releases" / version
    release.mkdir(parents=True)
    files = {}
    for vol_id, chap_id, body in chapters:
        # Mirror compiler.py:_safe: keep alnum + "._-"; rewrite everything else to `_`.
        safe_vol = "".join(c if c.isalnum() or c in "._-" else "_" for c in vol_id)
        safe_chap = "".join(c if c.isalnum() or c in "._-" else "_" for c in chap_id)
        filename = f"{safe_vol}__{safe_chap}.md"
        (release / filename).write_text(body, encoding="utf-8")
        files[filename] = hashlib.sha256((release / filename).read_bytes()).hexdigest()
    sources_index = release / "sources-index.md"
    sources_index.write_text("# Sources index\n", encoding="utf-8")
    files["sources-index.md"] = hashlib.sha256(sources_index.read_bytes()).hexdigest()
    outline = {
        "volumes": [
            {"volume_id": vol, "title": vol, "chapters": [
                {"chapter_id": chap, "title": chap, "page_ids": [], "overview_refs": []}
            ]}
            for vol, chap, _body in chapters
        ],
    }
    (release / "outline.json").write_text(json.dumps(outline), encoding="utf-8")
    files["outline.json"] = hashlib.sha256((release / "outline.json").read_bytes()).hexdigest()
    manifest = {
        "run_id": version, "chapter_count": len(chapters), "page_count": len(chapters),
        "scope_mode": "full_knowledge", "coverage_ratio": 1.0,
        "source_appendix_count": 0, "files": files,
    }
    (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (book_dir / "CURRENT.json").write_text(json.dumps({
        "version": version, "manifest_sha256": hashlib.sha256(
            (release / "manifest.json").read_bytes()).hexdigest(),
    }), encoding="utf-8")


def test_book_wiki_manifest_populates_volume_id_for_colon_chapter_ids(monkeypatch, tmp_path):
    """Task 2 smoke: the JSON the WebUI consumes (via
    GET /api/v1/projects/{id}/book-wiki) must carry `volume_id` for
    every chapter whose outline id contains `:`. Before the fix, the
    `_safe` filename rewrite caused every chapter to fall through the
    fallback bucket in `web/js/views/book.js`.

    Behavioural equivalent of a Playwright smoke test: instead of
    driving the browser, we drive the same `book_wiki_manifest`
    service the route calls. The WebUI consumes the JSON this returns
    verbatim (see src/server/routes/files.py:44-52).
    """
    from src.services import files as files_service
    project_dir = tmp_path / "kb"
    _build_release_with_colon_chapter_ids(project_dir)
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    manifest = files_service.book_wiki_manifest("u")
    chapters = manifest["chapters"]
    assert len(chapters) == 3, f"expected 3 chapters, got {len(chapters)}"

    # Every chapter must carry volume_id AND volume_title — these are
    # the fields `web/js/views/book.js`'s `volumeFor()` / `volumeLabel()`
    # read to decide the bucket heading.
    for ch in chapters:
        assert ch.get("volume_id"), f"chapter {ch['path']} missing volume_id"
        assert ch.get("volume_title"), f"chapter {ch['path']} missing volume_title"

    # And `volumes[].chapter_count` must reflect the real chapter set,
    # not the pre-fix `0` placeholder.
    volume_counts = {v["id"]: v["chapter_count"] for v in manifest["volumes"]}
    assert volume_counts.get("writing-tech") == 2
    assert volume_counts.get("fallback") == 1
    assert all(count > 0 for count in volume_counts.values()), (
        f"some volume still reports chapter_count=0: {volume_counts}"
    )

    # Spot-check the bucketing shape: chapters share a volume_id iff
    # they share a volume.
    by_volume = {}
    for ch in chapters:
        by_volume.setdefault(ch["volume_id"], []).append(ch["path"])
    assert sorted(by_volume["writing-tech"]) == sorted([
        "writing-tech__writing-tech_5.md",
        "writing-tech__writing-tech_6.md",
    ])
    assert by_volume["fallback"] == ["fallback__fallback_0.md"]


def test_book_wiki_manifest_404s_when_release_missing(monkeypatch, tmp_path):
    """Task 2 edge case: a project with no .releases/ must fail closed
    rather than returning the file-prefix fallback the bug previously
    surfaced. The service raises BookWikiUnavailableError, which the
    route translates to HTTP 404.
    """
    from src.services import files as files_service
    project_dir = tmp_path / "kb"
    (project_dir / ".llm-wiki").mkdir(parents=True)
    (project_dir / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "u", "name": "p", "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    # No book-wiki/ directory at all.
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )
    with pytest.raises(files_service.BookWikiUnavailableError):
        files_service.book_wiki_manifest("u")


def test_book_wiki_manifest_exposes_preface_field(monkeypatch, tmp_path):
    """Task 3 integration pin: a release that ships a `preface.md`
    must surface it as a top-level `preface` field on the manifest,
    excluded from the clickable `chapters` list. This is the only
    way to keep the WebUI from rendering the preface as a 4th
    unstyled bucket heading.
    """
    from src.services import files as files_service
    project_dir = tmp_path / "kb"
    # Reuse the colon-chapter release builder; append a preface on top.
    _build_release_with_colon_chapter_ids(project_dir)
    book_dir = project_dir / "book-wiki"
    release = book_dir / ".releases" / "v1"
    preface_text = (
        "# 总序\n\n"
        "本教程分 8 大主题，从人物塑造到平台规则，"
        "建议按目录顺序阅读，每章约 25-35 分钟。"
    )
    (release / "preface.md").write_text(preface_text, encoding="utf-8")
    # Add the preface to the manifest's files dict AND refresh the
    # manifest hash on CURRENT.json; otherwise the integrity
    # check rejects the release as stale.
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["preface.md"] = hashlib.sha256(
        (release / "preface.md").read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (book_dir / "CURRENT.json").write_text(json.dumps({
        "version": "v1",
        "manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    manifest = files_service.book_wiki_manifest("u")
    assert manifest["preface"] is not None
    assert manifest["preface"]["path"] == "preface.md"
    assert manifest["preface"]["kind"] == "preface"
    assert manifest["preface"]["word_count"] == len(preface_text)
    # And preface must NOT appear in the chapter list.
    chapter_paths = {ch["path"] for ch in manifest["chapters"]}
    assert "preface.md" not in chapter_paths
    # Existing exemptions (index/glossary/sources-index) still work.
    # _build_release_with_colon_chapter_ids doesn't ship those, but the
    # code path for them is the same: the field stays None.
    # Field shape sanity:
    assert set(manifest["preface"].keys()) == {"path", "kind", "word_count", "size"}


def test_book_wiki_manifest_preface_is_none_when_missing(monkeypatch, tmp_path):
    """When the release has no `preface.md`, the field is None and
    the chapters list is unaffected (back-compat with releases
    produced before Task 3)."""
    from src.services import files as files_service
    project_dir = tmp_path / "kb"
    _build_release_with_colon_chapter_ids(project_dir)
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    manifest = files_service.book_wiki_manifest("u")
    assert manifest["preface"] is None
    # Three real chapters still listed.
    assert len(manifest["chapters"]) == 3
