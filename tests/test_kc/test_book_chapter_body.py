from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

from src.kc.views.book.wiki.aggregator import aggregate_chapter
import src.kc.views.book.wiki.compiler as compiler
from src.kc.views.book.wiki.compiler import build_from_wiki, compile_book
from src.kc.views.book.wiki.editorial_state import build_editorial_state, save_editorial_state
from src.kc.views.book.wiki.model import ContentBlock, PageRecord
from src.kc.views.book.wiki.polish_llm import GeneratedChapter, GeneratedSection, generate_chapter_body
from src.kc.views.book.wiki.preflight import PreflightReport


def _write_project_rules(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "book.rules.md").write_text(
        "# Book rules\n\n- Audience: general readers\n",
        encoding="utf-8",
    )


def _draft():
    pages = {
        "p1": PageRecord("p1", "One", "concept", "p1.md", "x", "", (
            ContentBlock("p1:0", "p1", "One", "Body one", 0),
        ), (), "h1", 8, None),
        "p2": PageRecord("p2", "Two", "concept", "p2.md", "x", "", (
            ContentBlock("p2:0", "p2", "Two", "Body two", 0),
        ), (), "h2", 8, None),
    }
    return aggregate_chapter({"chapter_id": "c1", "page_ids": ["p1", "p2"]}, pages)


def _provider(payload):
    class Provider:
        async def complete(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps(payload), truncated=False)
    return Provider()


def _provider_text(content):
    class Provider:
        async def complete(self, *_args, **_kwargs):
            return SimpleNamespace(content=content, truncated=False)
    return Provider()


def test_budget_failure_keeps_prior_contract_failure_reason():
    class BudgetExhausted(RuntimeError):
        budget_exhausted = True

    class Provider:
        def __init__(self):
            self.calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content=json.dumps(["标题一", "标题二"]), truncated=False)
            raise BudgetExhausted("max_llm_calls exhausted")

    provider = Provider()
    result = asyncio.run(generate_chapter_body(
        _draft(), provider,
        section_plan=({"section_id": "s1", "title": "Overview"},),
        retries=1,
    ))

    assert provider.calls == 2
    assert result.failure_code == "E_LLM_BUDGET_EXHAUSTED"
    assert "response_not_structured_chapter" in (result.failure_reason or "")
    assert "max_llm_calls exhausted" in (result.failure_reason or "")


def test_structured_body_requires_compiler_owned_sections_and_provenance():
    draft = _draft()
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider({
            "chapter_id": "c1",
            "content_status": "complete",
            "sections": [{
                "section_id": "s1",
                "title": "Overview",
                "body": "整理后的正文",
                "source_page_ids": ["p1", "p2"],
                "status": "normal",
            }],
        }),
        section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    assert result.content_status == "complete"
    assert result.sections[0].source_page_ids == ("p1", "p2")


def test_invalid_section_or_source_reference_fails_closed():
    draft = _draft()
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider({
            "chapter_id": "c1",
            "content_status": "complete",
            "sections": [{
                "section_id": "invented",
                "title": "Wrong",
                "body": "正文",
                "source_page_ids": ["outside"],
                "status": "normal",
            }],
        }),
        section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    assert result.content_status == "failed"
    assert "section_ids" in (result.failure_reason or "")


def test_structured_body_accepts_fenced_json_response():
    draft = _draft()
    payload = {
        "chapter_id": "c1",
        "content_status": "complete",
        "sections": [{
            "section_id": "s1",
            "title": "Overview",
            "body": "围栏中的结构化正文",
            "source_page_ids": ["p1", "p2"],
            "status": "normal",
        }],
    }
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider_text(f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"),
        section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    assert result.content_status == "complete"
    assert result.sections[0].body == "围栏中的结构化正文"


def test_structured_body_normalizes_a_section_object_array():
    draft = _draft()
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider([{
            "section_id": "s1",
            "title": "Overview",
            "body": "兼容数组响应的正文",
            "source_page_ids": ["p1", "p2"],
            "status": "normal",
        }]),
        section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    assert result.content_status == "complete"
    assert result.sections[0].section_id == "s1"


def test_structured_body_rejects_string_array_as_not_prose():
    draft = _draft()
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider(["第一段", "第二段"]),
        section_plan=({"section_id": "s1", "title": "Overview", "page_ids": ["p1", "p2"]},),
    ))

    assert result.content_status == "failed"
    assert "response_not_structured_chapter:type=list" in (result.failure_reason or "")


def test_malformed_string_array_gets_one_contract_repair_retry():
    draft = _draft()

    class Provider:
        calls = 0

        async def complete(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content=json.dumps(["标题一"]), truncated=False)
            request = json.loads(messages[0]["content"])
            assert "JSON array of strings" in request["retry_feedback"]
            return SimpleNamespace(content=json.dumps({
                "chapter_id": "c1",
                "content_status": "complete",
                "sections": [{
                    "section_id": "s1",
                    "title": "Overview",
                    "body": "修复后的结构化正文",
                    "source_page_ids": ["p1", "p2"],
                    "status": "normal",
                }],
            }), truncated=False)

    provider = Provider()
    result = asyncio.run(generate_chapter_body(
        draft, provider,
        section_plan=({"section_id": "s1", "title": "Overview"},),
        retries=1,
    ))

    assert provider.calls == 2
    assert result.content_status == "complete"
    assert result.sections[0].body == "修复后的结构化正文"


def test_unstructured_body_reports_safe_top_level_shape():
    result = asyncio.run(generate_chapter_body(
        _draft(),
        _provider({"chapter_id": "c1", "content": "not a chapter"}),
        section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    assert result.content_status == "failed"
    assert "response_not_structured_chapter" in (result.failure_reason or "")
    assert "keys=chapter_id,content" in (result.failure_reason or "")


def test_body_prompt_declares_top_level_object_contract():
    captured = {}

    class Provider:
        async def complete(self, messages, **kwargs):
            captured["prompt"] = json.loads(messages[0]["content"])
            captured["kwargs"] = kwargs
            return await _provider({
                "chapter_id": "c1",
                "content_status": "complete",
                "sections": [{
                    "section_id": "s1",
                    "title": "Overview",
                    "body": "正文",
                    "source_page_ids": ["p1", "p2"],
                    "status": "normal",
                }],
            }).complete(messages)

    result = asyncio.run(generate_chapter_body(
        _draft(), Provider(),
        section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    task = captured["prompt"]["task"]
    assert result.content_status == "complete"
    assert captured["kwargs"]["temperature"] == 0
    assert "one top-level JSON object" in task
    assert '"sections"' in task
    assert "Do not return a JSON array" in task
    assert "Do not answer with page titles, headings, or a list of strings" in task
    assert "Even when there is only one allowed section, wrap it in the object" in task
    assert "merge those pages into one explanation" in task
    assert "Deduplicate repeated claims across the chapter" in task
    assert "Do not restate the same definition in adjacent sentences" in task


def test_retry_includes_structured_contract_feedback():
    prompts = []

    class Provider:
        calls = 0

        async def complete(self, messages, **_kwargs):
            self.calls += 1
            prompts.append(json.loads(messages[0]["content"]))
            if self.calls == 1:
                return SimpleNamespace(content=json.dumps(["标题一", "标题二"]), truncated=False)
            return SimpleNamespace(content=json.dumps({
                "chapter_id": "c1",
                "content_status": "complete",
                "sections": [{
                    "section_id": "s1",
                    "title": "Overview",
                    "body": "修复后的正文",
                    "source_page_ids": ["p1", "p2"],
                    "status": "normal",
                }],
            }), truncated=False)

    provider = Provider()
    result = asyncio.run(generate_chapter_body(
        _draft(), provider,
        section_plan=({"section_id": "s1", "title": "Overview"},),
        retries=1,
    ))

    assert result.content_status == "complete"
    assert provider.calls == 2
    assert "retry_feedback" in prompts[1]
    assert "top-level object contract" in prompts[1]["retry_feedback"]


def test_provider_failure_is_terminal_without_retry():
    class Provider:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError("provider down")

    provider = Provider()
    result = asyncio.run(generate_chapter_body(
        _draft(), provider,
        section_plan=({"section_id": "s1", "title": "Overview"},),
        retries=1,
    ))

    assert provider.calls == 1
    assert result.failure_code == "E_LLM_PROVIDER_FAILED"


def test_conflict_source_requires_disputed_section_status():
    draft = _draft()
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider({
            "chapter_id": "c1",
            "content_status": "complete",
            "sections": [{
                "section_id": "s1",
                "title": "Overview",
                "body": "争议内容",
                "source_page_ids": ["p1"],
                "status": "normal",
            }],
        }),
        section_plan=({"section_id": "s1", "title": "Overview"},),
        conflict_page_ids={"p1"},
    ))

    assert result.content_status == "failed"
    assert "conflict_status" in (result.failure_reason or "")


def test_generated_source_must_stay_inside_planned_theme_group():
    draft = _draft()
    result = asyncio.run(generate_chapter_body(
        draft,
        _provider({
            "chapter_id": "c1",
            "content_status": "complete",
            "sections": [{
                "section_id": "s1",
                "title": "Theme one",
                "body": "正文",
                "source_page_ids": ["p2"],
                "status": "normal",
            }, {
                "section_id": "s2",
                "title": "Theme two",
                "body": "正文",
                "source_page_ids": ["p2"],
                "status": "normal",
            }],
        }),
        section_plan=(
            {"section_id": "s1", "title": "Theme one", "page_ids": ["p1"]},
            {"section_id": "s2", "title": "Theme two", "page_ids": ["p2"]},
        ),
    ))

    assert result.content_status == "failed"
    assert "source_page_ids" in (result.failure_reason or "")


def test_body_prompt_carries_theme_page_groups():
    captured = {}

    class Provider:
        async def complete(self, messages, **_kwargs):
            captured["prompt"] = json.loads(messages[0]["content"])
            return await _provider({
                "chapter_id": "c1",
                "content_status": "complete",
                "sections": [{
                    "section_id": "s1",
                    "title": "Theme one",
                    "body": "正文",
                    "source_page_ids": ["p1", "p2"],
                    "status": "normal",
                }],
            }).complete(messages)

    result = asyncio.run(generate_chapter_body(
        _draft(), Provider(),
        section_plan=(
            {"section_id": "s1", "title": "Theme one", "page_ids": ["p1", "p2"]},
        ),
    ))

    assert result.content_status == "complete"
    assert captured["prompt"]["allowed_sections"][0]["page_ids"] == ["p1", "p2"]


def test_provider_failure_returns_non_publishable_state():
    class Provider:
        async def complete(self, *_args, **_kwargs):
            raise TimeoutError("provider down")

    result = asyncio.run(generate_chapter_body(
        _draft(), Provider(), section_plan=({"section_id": "s1", "title": "Overview"},),
    ))

    assert result.content_status == "failed"
    assert result.failure_reason == "TimeoutError: provider down"


def test_compiler_uses_validated_generated_sections_without_changing_chapter_identity(tmp_path):
    draft = _draft()
    pages = {page_id: PageRecord(
        page_id, page_id, "concept", f"{page_id}.md", "x", "", tuple(
            block for block in draft.blocks if block.page_id == page_id
        ), (), f"h-{page_id}", 1, None,
    ) for page_id in draft.page_ids}
    generated = GeneratedChapter(
        "c1",
        (GeneratedSection("s1", "Overview", "LLM 正文", ("p1", "p2")),),
        "complete",
    )
    artifact = compile_book(
        type("Snapshot", (), {"snapshot_id": "snap", "wiki_root": str(tmp_path / "wiki"),
                               "pages": tuple(pages.values()), "excluded_sources": ()})(),
        [{"schema_version": "outline-v1", "snapshot_id": "snap", "volumes": [{
            "volume_id": "v1", "chapters": [{"chapter_id": "c1", "title": "C", "page_ids": ["p1", "p2"]}],
        }]}], pages, fingerprint={}, state_dir=tmp_path / ".index",
        generated_chapters={"c1": generated},
    )

    chapter = artifact.version_dir / "v1__c1.md"
    assert "LLM 正文" in chapter.read_text(encoding="utf-8")
    assert artifact.manifest["generation_mode"] == "llm"
    assert artifact.manifest["release_status"] == "complete"
    assert artifact.manifest["section_source_ids"]["v1__c1.md"]["s1"] == ["p1", "p2"]


def test_build_from_wiki_polish_writes_complete_body_audit_metadata(tmp_path):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"test-owner","budget_cap":3}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody\n",
        encoding="utf-8",
    )

    class Provider:
        async def complete(self, messages, **_kwargs):
            payload = json.loads(messages[0]["content"])
            if "allowed_sections" in payload:
                section = payload["allowed_sections"][0]
                return SimpleNamespace(content=json.dumps({
                    "chapter_id": payload["chapter_id"],
                    "content_status": "complete",
                    "sections": [{
                        "section_id": section["section_id"],
                        "title": section["title"],
                        "body": "结构化正文",
                        "source_page_ids": ["p1"],
                        "status": "normal",
                    }],
                }), truncated=False)
            return SimpleNamespace(content=json.dumps({
                "chapter_id": payload["chapter_id"],
                "title": "Chapter",
                "page_ids": ["p1"],
                "overview_refs": ["p1"],
            }), truncated=False)

    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        provider=Provider(), max_llm_calls=3,
    )

    assert result["status"] == "planned"
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generation_mode"] == "llm"
    assert manifest["release_status"] == "complete"
    assert manifest["llm_metadata"]["approver"] == "test-owner"
    assert manifest["llm_prompt_hashes"]
    metadata = manifest["llm_metadata"]
    assert metadata["llm_calls_used"] == 2
    assert metadata["minimum_llm_calls"] == 2
    assert metadata["configured_max_llm_calls"] == 5
    assert metadata["retry_reserve_shortfall"] == 2
    assert metadata["call_sites"]["outline"]["actual_calls"] == 1
    assert metadata["call_sites"]["chapter_body"]["actual_calls"] == 1
    assert metadata["call_sites"]["outline"]["requested"] is True
    assert metadata["call_sites"]["chapter_body"]["requested"] is True
    assert all("pending" not in site for site in metadata["call_sites"].values())
    assert "结构化正文" in next(Path(result["version_dir"]).glob("*.md")).read_text(encoding="utf-8")


def test_build_from_wiki_constructs_registry_provider_when_not_injected(tmp_path, monkeypatch):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"owner","budget_cap":1}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody\n",
        encoding="utf-8",
    )

    class Provider:
        calls = 0

        async def complete(self, messages, **_kwargs):
            self.calls += 1
            payload = json.loads(messages[0]["content"])
            sections = payload["allowed_sections"]
            return SimpleNamespace(content=json.dumps({
                "chapter_id": payload["chapter_id"],
                "content_status": "complete",
                "sections": [{
                    "section_id": section["section_id"],
                    "title": section["title"],
                    "body": "结构化正文",
                    "source_page_ids": ["p1"],
                    "status": "normal",
                } for section in sections],
            }), truncated=False)

    monkeypatch.setattr(
        compiler,
        "run_preflight",
        lambda *args, **kwargs: PreflightReport(
            str(root), str(root / "book-wiki"), str(root / ".index"),
            "fake", "fake-model", None, 1,
        ),
    )
    monkeypatch.setattr("src.llm.provider_factory.create_llm_provider", lambda _name: Provider())

    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        max_attempts=0, max_llm_calls=1,
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["E_LLM_BUDGET_INSUFFICIENT"]


def test_publication_llm_budget_counts_outline_and_body_requests(tmp_path):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"owner","budget_cap":1}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody\n",
        encoding="utf-8",
    )

    class Provider:
        calls = 0

        async def complete(self, messages, **_kwargs):
            self.calls += 1
            payload = json.loads(messages[0]["content"])
            return SimpleNamespace(content=json.dumps({
                "chapter_id": payload["chapter_id"], "title": "Chapter",
                "page_ids": ["p1"], "overview_refs": ["p1"],
            }), truncated=False)

    provider = Provider()
    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        provider=provider, max_llm_calls=1, apply=False,
    )

    assert result["status"] == "blocked"
    assert provider.calls == 0
    assert result["minimum_llm_calls"] == 2
    assert not (root / "book-wiki" / "CURRENT.json").exists()
    assert result["reason_codes"] == ["E_LLM_BUDGET_INSUFFICIENT"]


def test_apply_reports_specific_llm_failure_code(tmp_path):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,'
        '"approver":"owner","budget_cap":2}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsources: [raw/p1.md]\n---\nBody\n",
        encoding="utf-8",
    )

    class Provider:
        async def complete(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps(["标题一", "标题二"]), truncated=False)

    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        provider=Provider(), max_llm_calls=2, apply=True,
    )

    assert result["status"] == "failed"
    assert "E_LLM_REQUIRED_FOR_APPLY" in result["reason_codes"]
    assert "E_LLM_BUDGET_EXHAUSTED" in result["reason_codes"]
    assert not (root / "book-wiki" / "CURRENT.json").exists()


def test_persisted_outline_blocks_before_insufficient_budget_call(tmp_path):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,'
        '"approver":"owner","budget_cap":2}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    for page_id in ("p1", "p2"):
        (root / "wiki" / "concepts" / f"{page_id}.md").write_text(
            f"---\nid: {page_id}\ntitle: {page_id}\ntype: concept\nsources: [raw/{page_id}.md]\n---\nBody\n",
            encoding="utf-8",
        )
    snapshot = compiler.scan_wiki_snapshot(root / "wiki")
    state = build_editorial_state(
        snapshot,
        book_id="book-1",
        outline={"schema_version": "book-outline-v1", "snapshot_id": snapshot.snapshot_id,
                 "volumes": [{"volume_id": "v1", "title": "v1", "chapters": [
                     {"chapter_id": "c1", "title": "C1", "page_ids": ["p1"]},
                     {"chapter_id": "c2", "title": "C2", "page_ids": ["p2"]},
                 ]}]},
    )
    save_editorial_state(root / "book-wiki", state)

    class Provider:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("budget preflight should run before the provider")

    provider = Provider()
    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        provider=provider, max_llm_calls=1,
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["E_LLM_BUDGET_INSUFFICIENT"]
    assert result["minimum_llm_calls"] == 2
    assert provider.calls == 0
    assert not (root / "book-wiki" / "CURRENT.json").exists()


def test_restricted_source_blocks_before_provider_call(tmp_path):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"content_export_authorized":true,"external_llm_allowed":true,"approver":"owner","budget_cap":3}',
        encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsensitivity: private\nsources: [raw/p1.md]\n---\nBody\n",
        encoding="utf-8",
    )

    class Provider:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("restricted source must not reach provider")

    provider = Provider()
    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True, polish=True,
        provider=provider,
    )

    assert result == {"status": "blocked", "reason_codes": ["E_LLM_RESTRICTED_SOURCE"], "page_ids": ["p1"]}
    assert provider.calls == 0


def test_outline_only_restricted_source_blocks_before_provider_call(tmp_path):
    root = tmp_path / "project"
    _write_project_rules(root)
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (root / ".llm-wiki" / "policy.json").write_text(
        '{"external_llm_allowed":true}', encoding="utf-8",
    )
    for name in ("concepts", "entities", "synthesis"):
        (root / "wiki" / name).mkdir(parents=True)
    (root / "wiki" / "concepts" / "p1.md").write_text(
        "---\nid: p1\ntitle: One\ntype: concept\nsensitivity: restricted\n---\nBody\n",
        encoding="utf-8",
    )

    class Provider:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("restricted outline source must not reach provider")

    provider = Provider()
    result = build_from_wiki(
        root, output_dir=root / "book-wiki", use_llm=True,
        provider=provider,
    )

    assert result == {"status": "blocked", "reason_codes": ["E_LLM_RESTRICTED_SOURCE"], "page_ids": ["p1"]}
    assert provider.calls == 0
