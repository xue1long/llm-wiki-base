from __future__ import annotations

import json
from pathlib import Path

from src.kc.views.book.wiki.compiler import build_from_wiki, resolve_active_version


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    (root / "book.rules.md").write_text("# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8")
    (root / ".llm-wiki").mkdir()
    (root / ".llm-wiki" / "project.json").write_text(
        '{"schema_version":"v2.0","id":"project-1"}', encoding="utf-8"
    )
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


class _CountingProvider:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, **_kwargs):
        self.calls += 1
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


def test_apply_from_promotes_preview_without_provider_calls(tmp_path):
    root = _project(tmp_path)
    provider = _CountingProvider()
    preview = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        apply=False, provider=provider, max_llm_calls=3, budget_cap=3,
    )
    assert preview["status"] == "planned"
    assert provider.calls > 0
    release_id = preview["run_id"]

    class _FailProvider:
        async def complete(self, *_args, **_kwargs):
            raise AssertionError("promotion must not call provider")

    promoted = build_from_wiki(
        root, output_dir=root / "book-wiki", apply=True, apply_from=release_id,
        provider=_FailProvider(),
    )
    assert promoted["status"] == "committed"
    assert promoted["source_release_id"] == release_id
    assert promoted["llm_calls_used"] == 0
    active = resolve_active_version(root / "book-wiki")
    assert active is not None and active.name == release_id


def test_full_scope_apply_from_reuses_candidate_release(tmp_path):
    root = _project(tmp_path)
    provider = _CountingProvider()
    state_path = root / ".index" / "book-wiki" / "batch.json"
    preview = build_from_wiki(
        root, output_dir=root / "book-wiki", scope_mode="full_knowledge",
        use_llm=True, polish=True, apply=False, provider=provider,
        max_llm_calls=2, budget_cap=2, budget_manifest=state_path,
    )
    assert preview["status"] == "planned"
    release_id = preview["run_id"]
    calls_before_apply = provider.calls

    promoted = build_from_wiki(
        root, output_dir=root / "book-wiki", scope_mode="full_knowledge",
        apply=True, apply_from=release_id,
    )

    assert promoted["status"] == "committed"
    assert promoted["llm_calls_used"] == 0
    assert provider.calls == calls_before_apply
    active = resolve_active_version(root / "book-wiki")
    assert active is not None and active.name == release_id


def test_apply_from_rejects_stale_preview_without_replacing_current(tmp_path):
    root = _project(tmp_path)
    provider = _CountingProvider()
    preview = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        apply=False, provider=provider, max_llm_calls=3, budget_cap=3,
    )
    release_id = preview["run_id"]
    (root / "wiki" / "concepts" / "p1.md").write_text(
        (root / "wiki" / "concepts" / "p1.md").read_text(encoding="utf-8") + "Changed\n",
        encoding="utf-8",
    )

    promoted = build_from_wiki(root, output_dir=root / "book-wiki", apply=True, apply_from=release_id)
    assert promoted["status"] == "failed"
    assert "snapshot" in str(promoted).lower()
    assert resolve_active_version(root / "book-wiki") is None
