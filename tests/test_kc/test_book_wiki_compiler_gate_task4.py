from __future__ import annotations

import json

import pytest

import src.kc.views.book.wiki.compiler as compiler
from src.kc.views.book.wiki.compiler import BuildArtifact, build_from_wiki, compile_book, publish_book
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.polish_llm import GeneratedChapter


def test_body_llm_status_is_derived_from_chapter_results() -> None:
    assert compiler._body_llm_status(None) == "disabled"
    assert compiler._body_llm_status({
        "c1": GeneratedChapter("c1", (), "complete", None),
    }) == "passed"
    assert compiler._body_llm_status({
        "c1": GeneratedChapter("c1", (), "failed", "provider_error"),
    }) == "failed"


def test_apply_rejects_rule_only_artifact_without_touching_current(tmp_path) -> None:
    output = tmp_path / "book-wiki"
    output.mkdir()
    current = output / "CURRENT.json"
    current.write_text(json.dumps({"version": "old"}), encoding="utf-8")
    before = current.read_bytes()
    artifact = BuildArtifact(
        "snap-1",
        {
            "run_id": "new",
            "release_status": "complete",
            "generation_mode": "rule_only",
            "files": {},
        },
        tmp_path / "staged",
    )

    report = publish_book(artifact, output, apply=True, lock=None)

    assert report.status == "failed"
    assert "llm" in (report.error or "").lower()
    assert current.read_bytes() == before


def test_apply_rejects_partial_llm_artifact_without_touching_current(tmp_path) -> None:
    output = tmp_path / "book-wiki"
    output.mkdir()
    current = output / "CURRENT.json"
    current.write_text(json.dumps({"version": "old"}), encoding="utf-8")
    before = current.read_bytes()
    artifact = BuildArtifact(
        "snap-1",
        {
            "run_id": "new",
            "release_status": "partial",
            "generation_mode": "llm_partial",
            "files": {},
        },
        tmp_path / "staged",
    )

    report = publish_book(artifact, output, apply=True, lock=None)

    assert report.status == "failed"
    assert current.read_bytes() == before


@pytest.mark.parametrize("apply", [False, True])
def test_build_from_wiki_requires_instance_rules_before_any_build_mode(tmp_path, apply: bool) -> None:
    result = build_from_wiki(
        tmp_path,
        output_dir=tmp_path / "book-wiki",
        use_llm=True,
        polish=True,
        apply=apply,
        provider=object(),
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["E_BOOK_RULES_UNAVAILABLE"]


def test_compile_book_persists_rules_hash_and_snapshot_in_manifest(tmp_path) -> None:
    page = PageRecord(
        "p1", "One", "concept", "concepts/p1.md", "tax", "",
        (ContentBlock("p1:0", "p1", "One", "Body", 0),), (), "hash", 4, None,
    )
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outline = [{
        "schema_version": "outline-v1",
        "snapshot_id": "snap-1",
        "volumes": [{"volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "C", "page_ids": ["p1"],
        }]}],
    }]

    artifact = compile_book(
        snapshot,
        outline,
        (page,),
        fingerprint={},
        state_dir=tmp_path / ".index",
        rules_hash="abc123",
        rules_snapshot="Audience: advanced readers.\n",
    )

    assert artifact.manifest["rules_hash"] == "abc123"
    assert artifact.manifest["rules_snapshot"] == "Audience: advanced readers.\n"
    assert artifact.manifest["rules_path"] == "book.rules.md"


def test_plan_only_compiles_outline_metadata_without_chapter_bodies(tmp_path) -> None:
    page = PageRecord(
        "p1", "One", "concept", "concepts/p1.md", "tax", "",
        (ContentBlock("p1:0", "p1", "One", "Body", 0),), (), "hash", 4, None,
    )
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outline = [{
        "schema_version": "outline-v1",
        "snapshot_id": "snap-1",
        "volumes": [{"volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "C", "page_ids": ["p1"],
        }]}],
    }]

    artifact = compile_book(
        snapshot, outline, (page,), fingerprint={}, state_dir=tmp_path / ".index",
        plan_only=True, rules_hash="abc123", rules_snapshot="rules\n",
    )

    assert artifact.manifest["generation_mode"] == "plan"
    assert artifact.manifest["body_generation_mode"] == "none"
    assert artifact.manifest["release_status"] == "planned"
    assert not (artifact.version_dir / "v1__c1.md").exists()
    assert (artifact.version_dir / "outline.json").exists()
