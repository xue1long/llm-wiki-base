from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kc.views.book.wiki.compiler import build_from_wiki, resolve_active_version


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "book.rules.md").write_text(
        "# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8"
    )
    (root / ".llm-wiki").mkdir()
    (root / ".llm-wiki" / "project.json").write_text(
        '{"schema_version":"v2.0","id":"project-1"}', encoding="utf-8"
    )
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,'
        '"approver":"test","budget_cap":4}', encoding="utf-8"
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    for page_id, taxonomy in (("p1", "alpha"), ("p2", "beta")):
        (root / "wiki" / "concepts" / f"{page_id}.md").write_text(
            f"---\nid: {page_id}\ntitle: {page_id}\ntype: concept\n"
            f"primary_taxonomy: {taxonomy}\nsources: [raw/{page_id}.md]\n---\n"
            f"Body for {page_id}.\n",
            encoding="utf-8",
        )
    return root


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, **_kwargs):
        self.calls += 1
        payload = json.loads(messages[0]["content"])
        sections = payload["allowed_sections"]
        page_ids = [page["page_id"] for page in payload["source_pages"]]
        body = "这是基于来源页面生成的章节正文。\n\n"
        body += "本段用于验证中断恢复后正文仍由同一个 fake provider 产生。"
        result = {
            "chapter_id": payload["chapter_id"],
            "content_status": "complete",
            "sections": [{
                "section_id": section["section_id"],
                "title": section["title"],
                "body": body,
                "source_page_ids": page_ids,
                "status": "normal",
            } for section in sections],
        }
        return type("Response", (), {
            "content": json.dumps(result, ensure_ascii=False), "truncated": False,
        })()


def test_fake_provider_interrupt_resume_finalize_apply_from(tmp_path: Path):
    root = _project(tmp_path)
    state_path = root / ".index" / "book-wiki" / "batch.json"

    first_provider = _FakeProvider()
    first = build_from_wiki(
        root, output_dir=root / "book-wiki", scope_mode="full_knowledge",
        use_llm=True, polish=True, provider=first_provider,
        batch_size=1, max_batches=1, max_attempts=0,
        max_llm_calls=2, budget_cap=2, budget_manifest=state_path,
    )
    assert first["status"] == "partial"
    assert first_provider.calls == 1
    assert not (root / "book-wiki" / "CURRENT.json").exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert sum(row["status"] == "complete" for row in state["chapters"].values()) == 1

    resume_provider = _FakeProvider()
    resumed = build_from_wiki(
        root, output_dir=root / "book-wiki", scope_mode="full_knowledge",
        use_llm=True, polish=True, provider=resume_provider,
        batch_size=1, max_batches=1, max_attempts=0,
        max_llm_calls=2, budget_cap=2, resume=True,
        budget_manifest=state_path,
    )
    assert resumed["status"] == "partial"
    assert resume_provider.calls == 1

    class _FailProvider:
        async def complete(self, *_args, **_kwargs):
            raise AssertionError("finalize must not call provider")

    finalized = build_from_wiki(
        root, output_dir=root / "book-wiki", scope_mode="full_knowledge",
        finalize=True, budget_manifest=state_path,
    )
    assert finalized["status"] == "planned"
    release_id = finalized["run_id"]
    manifest = json.loads(
        (Path(finalized["version_dir"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["release_status"] == "complete"

    promoted = build_from_wiki(
        root, output_dir=root / "book-wiki", apply=True,
        apply_from=release_id, provider=_FailProvider(),
    )
    assert promoted["status"] == "committed", promoted
    assert promoted["llm_calls_used"] == 0
    assert resolve_active_version(root / "book-wiki").name == release_id


@pytest.mark.parametrize("kwargs", [{"max_batches": 1}, {"finalize": True}])
def test_batch_controls_do_not_change_pilot_or_legacy_paths(tmp_path: Path, kwargs):
    result = build_from_wiki(
        _project(tmp_path), output_dir=tmp_path / "project" / "book-wiki",
        scope_mode="pilot", **kwargs,
    )

    assert result["status"] == "failed"
    assert result["reason_codes"] == ["E_BATCH_CONTROLS_REQUIRE_FULL_SCOPE"]
