from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.kc.views.book.wiki.compiler import PublishReport, build_from_wiki
from src.lineage import LineageStore


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    (root / "book.rules.md").write_text("# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8")
    for directory in ("concepts", "entities", "synthesis"):
        (root / "wiki" / directory).mkdir(parents=True)
    (root / "raw" / "sources").mkdir(parents=True)
    (root / ".llm-wiki").mkdir()
    (root / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "project-1", "name": "project-1", "schema_version": "v2.0"}),
        encoding="utf-8",
    )
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"test","budget_cap":3}',
        encoding="utf-8",
    )
    raw = root / "raw" / "sources" / "a.md"
    raw.write_text("raw", encoding="utf-8")
    (root / "wiki" / "concepts" / "a.md").write_text(
        "---\n"
        "id: page-a\n"
        "title: Page A\n"
        "type: concept\n"
        "sources:\n"
        "  - raw/sources/a.md\n"
        "---\n"
        "# A\n\nBody\n",
        encoding="utf-8",
    )
    store = LineageStore.open(root)
    store.register_source(
        "src-a",
        "raw/sources/a.md",
        hashlib.sha256(raw.read_bytes()).hexdigest(),
        "ingested",
    )
    return root


class _PolishedProvider:
    async def complete(self, messages, **_kwargs):
        request = json.loads(messages[0]["content"])
        if "source_pages" in request:
            section = request["allowed_sections"][0]
            payload = {
                "chapter_id": request["chapter_id"],
                "content_status": "complete",
                "sections": [{
                    "section_id": section["section_id"],
                    "title": section["title"],
                    "body": "Polished body.",
                    "source_page_ids": [page["page_id"] for page in request["source_pages"]],
                    "status": "normal",
                }],
            }
        else:
            page_ids = [page["page_id"] for page in request["pages"]]
            payload = {"chapter_id": request["chapter_id"], "title": "Polished chapter",
                       "page_ids": page_ids, "overview_refs": page_ids[:1]}
        return type("Response", (), {"content": json.dumps(payload)})()


def test_apply_records_book_lineage_after_file_publish(tmp_path: Path) -> None:
    root = _project(tmp_path)

    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True, apply=True,
        provider=_PolishedProvider(), quality_gate="rule"
    )

    assert result["status"] == "committed", result
    store = LineageStore.open(root)
    run = store.build_run(result["run_id"])
    assert run is not None
    assert run["status"] == "published"
    assert run["wiki_snapshot"] == result["snapshot_id"]
    assert store.artifacts(artifact_kind="book", status="published")
    assert store.build_members(result["run_id"])


def test_publish_failure_marks_lineage_failed(monkeypatch, tmp_path: Path) -> None:
    root = _project(tmp_path)

    def fail_publish(artifact, output_dir, *, apply, lock):
        return PublishReport("failed", artifact.manifest["run_id"], error="blocked")

    monkeypatch.setattr(
        "src.kc.views.book.wiki.compiler.publish_book", fail_publish
    )
    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True, apply=True,
        provider=_PolishedProvider(), quality_gate="rule"
    )

    assert result["status"] == "failed"
    store = LineageStore.open(root)
    run = store.build_run(result["run_id"])
    assert run is not None
    assert run["status"] == "failed"
    assert store.artifacts(artifact_kind="book", status="published") == ()
