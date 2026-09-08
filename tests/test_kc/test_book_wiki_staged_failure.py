from __future__ import annotations

import json
import pytest

import src.kc.views.book.wiki.compiler as compiler
from src.kc.views.book.wiki.compiler import build_from_wiki, compile_book, publish_book, resolve_active_version
from src.kc.views.book.wiki.editorial_state import build_editorial_state, save_editorial_state
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.polish_llm import GeneratedChapter, GeneratedSection
from src.kc.views.book.wiki.scanner import scan_wiki_snapshot


class _PolishedProvider:
    async def complete(self, messages, **_kwargs):
        request = json.loads(messages[0]["content"])
        if "source_pages" in request:
            section = request["allowed_sections"][0]
            payload = {"chapter_id": request["chapter_id"], "content_status": "complete",
                       "sections": [{"section_id": section["section_id"], "title": section["title"],
                                     "body": "Polished body.",
                                     "source_page_ids": [p["page_id"] for p in request["source_pages"]],
                                     "status": "normal"}]}
        else:
            ids = [p["page_id"] for p in request["pages"]]
            payload = {"chapter_id": request["chapter_id"], "title": "Polished chapter",
                       "page_ids": ids, "overview_refs": ids[:1]}
        return type("Response", (), {"content": json.dumps(payload)})()


def _project(tmp_path, pages=1):
    root = tmp_path / "project"
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"test","budget_cap":3}',
        encoding="utf-8",
    )
    (root / "book.rules.md").write_text("# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    for index in range(pages):
        (root / "wiki" / "concepts" / f"p{index}.md").write_text(
            f"---\nid: p{index}\ntitle: Page {index}\ntype: concept\n---\nBody {index}\n",
            encoding="utf-8",
        )
    return root


def _inputs(tmp_path):
    page = PageRecord(
        "p1", "One", "concept", "concepts/p1.md", "tax", "",
        (ContentBlock("p1:0", "p1", "One", "Body", 0),), (), "hash", 4, None,
    )
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{"chapter_id": "c1", "title": "C", "page_ids": ["p1"]}],
    }]}]
    return snapshot, outline, {"p1": page}


def test_partial_llm_release_cannot_replace_current(tmp_path):
    snapshot, outline, pages = _inputs(tmp_path)
    old = compile_book(
        snapshot, outline, pages, fingerprint={}, state_dir=tmp_path / ".index",
        generated_chapters={"c1": GeneratedChapter(
            "c1", (GeneratedSection("s1", "Chapter", "LLM body", ("p1",)),), "complete"
        )},
    )
    output = tmp_path / "book-wiki"
    assert publish_book(old, output, apply=True, lock=None).status == "committed"
    old_current = (output / "CURRENT.json").read_bytes()

    partial = compile_book(
        snapshot, outline, pages, fingerprint={}, state_dir=tmp_path / ".index",
        generated_chapters={"c1": GeneratedChapter("c1", (), "failed", "budget_exhausted")},
    )
    assert partial.manifest["release_status"] == "partial"
    result = publish_book(partial, output, apply=True, lock=None)

    assert result.status == "failed"
    assert (output / "CURRENT.json").read_bytes() == old_current
    assert resolve_active_version(output) is not None


def test_wiki_change_reports_stale_without_touching_current(tmp_path):
    root = tmp_path / "project"
    root.mkdir(parents=True)
    (root / "book.rules.md").write_text("# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8")
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"test","budget_cap":3}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    page_path = root / "wiki" / "concepts" / "p1.md"
    page_path.write_text("---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody\n", encoding="utf-8")
    snapshot = scan_wiki_snapshot(root / "wiki")
    state = build_editorial_state(snapshot, book_id="book-1", outline={
        "schema_version": "book-outline-v1", "snapshot_id": snapshot.snapshot_id,
        "volumes": [{"volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "C", "page_ids": ["p1"], "sections": [],
        }]}],
    })
    save_editorial_state(root / "book-wiki", state)
    first = build_from_wiki(root, output_dir=root / "book-wiki")
    assert first["status"] == "planned", first
    page_path.write_text(page_path.read_text(encoding="utf-8") + "Changed\n", encoding="utf-8")

    stale = build_from_wiki(root, output_dir=root / "book-wiki")

    assert stale["status"] == "stale"
    assert stale["book_freshness"] == "stale"


def test_late_manifest_failure_keeps_current_release(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir(parents=True)
    (root / "book.rules.md").write_text("# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8")
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"test","budget_cap":3}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody\n",
        encoding="utf-8",
    )
    output = root / "book-wiki"
    first = build_from_wiki(
        root, output_dir=output, use_llm=True, polish=True, apply=True,
        provider=_PolishedProvider(),
    )
    assert first["status"] == "committed"
    old_current = (output / "CURRENT.json").read_bytes()

    original = compiler._write_manifest
    calls = 0

    def fail_on_final_manifest(path, manifest):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("manifest finalization failed")
        return original(path, manifest)

    monkeypatch.setattr(compiler, "_write_manifest", fail_on_final_manifest)
    with pytest.raises(OSError, match="manifest finalization failed"):
        build_from_wiki(
            root, output_dir=output, use_llm=True, polish=True, apply=True,
            provider=_PolishedProvider(),
        )

    assert (output / "CURRENT.json").read_bytes() == old_current


def test_acceptance_write_failure_keeps_current_release(tmp_path, monkeypatch):
    root = _project(tmp_path, pages=1)
    output = root / "book-wiki"
    first = build_from_wiki(
        root, output_dir=output, use_llm=True, polish=True, apply=True,
        provider=_PolishedProvider(),
    )
    assert first["status"] == "committed"
    old_current = (output / "CURRENT.json").read_bytes()

    def fail_acceptance(*_args, **_kwargs):
        raise OSError("acceptance disk full")

    monkeypatch.setattr(compiler, "write_release_acceptance_report", fail_acceptance)
    result = build_from_wiki(
        root, output_dir=output, use_llm=True, polish=True, apply=True,
        provider=_PolishedProvider(),
    )

    assert result["status"] == "failed"
    assert result["reason_codes"] == ["E_RELEASE_ACCEPTANCE_WRITE_FAILED"]
    assert (output / "CURRENT.json").read_bytes() == old_current
