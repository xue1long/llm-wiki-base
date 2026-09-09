from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from src.kc.views.book.wiki.acceptance import (
    _check_provenance,
    build_release_acceptance_report,
    derive_book_freshness,
    load_human_approval,
    load_release_acceptance_report,
    write_human_approval,
)
from src.kc.views.book.wiki.compiler import build_from_wiki, resolve_active_version


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    (root / "book.rules.md").write_text("# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8")
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0","id":"project-1"}', encoding="utf-8")
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
            payload = {
                "chapter_id": request["chapter_id"],
                "title": "Polished chapter",
                "page_ids": page_ids,
                "overview_refs": page_ids[:1],
            }
        return type("Response", (), {"content": json.dumps(payload)})()


def _apply(root: Path):
    return build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        apply=True, provider=_PolishedProvider(),
    )


def test_acceptance_report_is_deterministic_and_human_review_is_advisory(tmp_path):
    root = _project(tmp_path)
    result = _apply(root)
    assert result["status"] == "committed"
    release = resolve_active_version(root / "book-wiki")
    assert release is not None

    first = build_release_acceptance_report(root, release, publication_status="committed")
    second = build_release_acceptance_report(root, release, publication_status="committed")

    assert first == second
    assert first["automated_acceptance"] == "pass"
    assert first["human_readability_review"] == "not_requested"
    assert first["human_content_review"] == "not_requested"
    assert "approval" not in first
    assert "manual_gates" not in first


def test_full_scope_provenance_requires_complete_coverage_and_appendix():
    ok, errors = _check_provenance({
        "scope_mode": "full_knowledge",
        "eligible_page_count": 2,
        "covered_page_count": 1,
        "coverage_ratio": 0.5,
        "source_appendix_count": 1,
        "files": {},
        "chapter_count": 2,
        "chapter_sources": {"c1": []},
    })

    assert not ok
    assert {
        "full_scope_coverage_incomplete",
        "source_appendix_missing",
        "full_scope_chapter_provenance_incomplete",
    } <= set(errors)


def test_acceptance_freshness_is_derived_and_stale_is_not_approval(tmp_path):
    root = _project(tmp_path)
    result = _apply(root)
    release = resolve_active_version(root / "book-wiki")
    assert release is not None
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))

    (root / "wiki" / "concepts" / "p1.md").write_text(
        (root / "wiki" / "concepts" / "p1.md").read_text(encoding="utf-8") + "Changed\n",
        encoding="utf-8",
    )
    freshness, reason = derive_book_freshness(root, manifest)
    report = build_release_acceptance_report(root, release, publication_status="committed")

    assert freshness == "stale"
    assert reason == "snapshot_differs_from_release"
    assert report["freshness"] == "stale"
    assert report["automated_acceptance"] == "fail"
    assert report["human_readability_review"] == "not_requested"
    assert report["human_content_review"] == "not_requested"


def test_tampered_acceptance_sidecar_is_not_returned(tmp_path):
    root = _project(tmp_path)
    result = _apply(root)
    release = resolve_active_version(root / "book-wiki")
    assert result["status"] == "committed" and release is not None
    path = release / "release-acceptance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["release_id"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_release_acceptance_report(release) is None


def test_acceptance_allows_nested_editorial_sidecars(tmp_path):
    release = tmp_path / "release-1"
    sidecar = release / "editorial" / "book.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("{}\n", encoding="utf-8")
    files = {"editorial/book.json": hashlib.sha256(sidecar.read_bytes()).hexdigest()}
    manifest = {
        "run_id": release.name,
        "snapshot_id": "snap-1",
        "release_status": "complete",
        "generation_mode": "rule_only",
        "chapter_sources": {},
        "files": files,
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["release_manifest_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = build_release_acceptance_report(tmp_path, release)

    assert report["checks"]["manifest_integrity"] == "pass"


def test_human_approval_sidecar_is_optional_and_bound_to_manifest(tmp_path):
    root = _project(tmp_path)
    result = _apply(root)
    release = resolve_active_version(root / "book-wiki")
    assert result["status"] == "committed" and release is not None
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))

    assert load_human_approval(release, manifest) is None
    path = write_human_approval(
        release,
        {
            "schema_version": "human-approval-v1",
            "release_id": manifest["run_id"],
            "manifest_sha256": hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest(),
            "human_readability_review": "approved",
            "human_content_review": "not_requested",
            "reviewer": "test",
        },
    )
    assert path.name == "human-approval.json"
    approval = load_human_approval(release, manifest)
    assert approval is not None
    assert approval["human_readability_review"] == "approved"
    report = build_release_acceptance_report(root, release, publication_status="committed")
    assert report["automated_acceptance"] == "pass"
    assert report["human_readability_review"] == "approved"


def test_invalid_human_approval_does_not_change_manifest(tmp_path):
    root = _project(tmp_path)
    result = _apply(root)
    release = resolve_active_version(root / "book-wiki")
    assert result["status"] == "committed" and release is not None
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_before = manifest_path.read_bytes()

    with pytest.raises(ValueError, match="manifest_sha256"):
        write_human_approval(
            release,
            {
                "schema_version": "human-approval-v1",
                "release_id": manifest["run_id"],
                "manifest_sha256": "wrong",
                "human_readability_review": "approved",
                "human_content_review": "not_requested",
            },
        )
    assert manifest_path.read_bytes() == manifest_before

    (release / "human-approval.json").write_text(
        json.dumps({
            "schema_version": "human-approval-v1",
            "release_id": manifest["run_id"],
            "manifest_sha256": hashlib.sha256(manifest_before).hexdigest(),
            "project_id": "wrong-project",
            "human_readability_review": "approved",
            "human_content_review": "not_requested",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="project_id"):
        load_human_approval(release, manifest)


def test_old_acceptance_report_with_pending_manual_gates_still_loads(tmp_path):
    root = _project(tmp_path)
    result = _apply(root)
    release = resolve_active_version(root / "book-wiki")
    assert result["status"] == "committed" and release is not None
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": "release-acceptance-v1",
        "release_id": manifest["run_id"],
        "snapshot_id": manifest["snapshot_id"],
        "manifest_sha256": hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest(),
        "approval": "pending",
        "manual_gates": {"real_provider_readability": "pending", "human_acceptance": "pending"},
    }
    (release / "release-acceptance.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_release_acceptance_report(release)
    assert loaded is not None
    assert loaded["approval"] == "pending"
    assert loaded["human_readability_review"] == "pending"
