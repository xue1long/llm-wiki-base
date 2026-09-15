"""Tests for scripts/extract_pilot.py — v3.0 (async run_pilot)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.extract_pilot import _extract_one, run_pilot
from src.pipeline.v7_extract.failures import ExtractionResult, ExtractionStatus
from src.pipeline.v7_extract.llm_client import FakeLLMClient


@pytest.fixture(autouse=True)
def _scrub_d9_temp_whitelist(monkeypatch):
    """D9: the resolver rejects tmp_path (which lives under %TEMP%) unless
    we clear the temp env vars. Pilot tests always pass a tmp_path as
    project_root, so this scrub is required."""
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TMP", raising=False)


def _write_source(root: Path, name: str, content: str) -> None:
    path = root / "raw" / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_run_pilot_selects_deterministic_sources_and_never_writes_wiki(
    tmp_path: Path,
) -> None:
    for index in range(4):
        _write_source(
            tmp_path,
            f"source-{index}.md",
            f"# 主题 {index}\n\n这是一个足够长的来源正文。" * 120,
        )

    report = asyncio.run(run_pilot(tmp_path, count=3, seed=7))

    assert report["mode"] == "dry-run"
    assert report["summary"]["selected"] == 3
    assert len(report["sources"]) == 3
    assert report["sources"] == asyncio.run(
        run_pilot(tmp_path, count=3, seed=7)
    )["sources"]
    assert not (tmp_path / "wiki").exists()
    assert not (tmp_path / ".index").exists()


def test_run_pilot_reports_classification_and_pages(tmp_path: Path) -> None:
    """v3: doc_type is now a plain string (was DocType.value)."""
    # Long enough to pass Stage 3 completeness heuristic (was 800 chars)
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    _write_source(tmp_path, "short.md", "# 只有标题\n\n简介")

    fake = FakeLLMClient()
    fake.script(
        "classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}'
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "Topic 1", "item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": '
        '{"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": '
        '{"definition": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"characteristics": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"examples": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"related_concepts": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"references": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}}}'
    ))

    report = asyncio.run(run_pilot(tmp_path, count=10, seed=1, llm=fake))
    by_name = {item["source"]: item for item in report["results"]}

    # doc_type is a string, not an enum
    assert by_name["raw/sources/short.md"]["doc_type"] == "incomplete"
    assert by_name["raw/sources/short.md"]["pages"] == []


def test_write_report_emits_json_and_markdown_without_wiki_writes(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    report = asyncio.run(run_pilot(
        tmp_path,
        count=1,
        seed=1,
        json_output=json_path,
        markdown_output=markdown_path,
    ))

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# V7 Extract Pilot Report" in markdown
    assert "dry-run" in markdown
    assert not (tmp_path / "wiki").exists()


def test_direct_script_entrypoint_bootstraps_repo_imports(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)
    json_path = tmp_path / "direct.json"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts" / "extract_pilot.py"),
            "--root",
            str(tmp_path),
            "--count",
            "1",
            "--json-out",
            str(json_path),
            "--markdown-out",
            str(tmp_path / "direct.md"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json_path.exists()


def test_run_pilot_records_llm_enabled_when_injected(tmp_path: Path) -> None:
    """The report's `llm_enabled` flag reflects whether an LLM was injected."""
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)

    without_llm = asyncio.run(run_pilot(tmp_path, count=1, seed=1))
    assert without_llm["llm_enabled"] is False

    fake = FakeLLMClient()
    fake.script(
        "classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}'
    )
    fake.script("completeness", '{"complete": false, "reason": "too short"}')
    with_llm = asyncio.run(run_pilot(tmp_path, count=1, seed=1, llm=fake))
    assert with_llm["llm_enabled"] is True
    assert fake.calls, "FakeLLMClient should have been invoked for at least one prompt_kind"


def test_run_pilot_broken_llm_keeps_pipeline_running(tmp_path: Path) -> None:
    """v3 (P2): a broken LLM doesn't crash the pilot — classification
    falls back to INCOMPLETE, no pages are written, error is recorded."""
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    fake = FakeLLMClient()
    # queue garbage for every prompt kind
    for kind in ("classify", "completeness", "cluster", "fill_slots"):
        for _ in range(5):
            fake.script(kind, "this is not json")

    report = asyncio.run(run_pilot(tmp_path, count=1, seed=1, llm=fake))
    assert report["llm_enabled"] is True
    by_name = {item["source"]: item for item in report["results"]}
    page = by_name["raw/sources/complete.md"]
    # No pages because LLM failed every retry
    assert page["pages"] == []
    # doc_type is "incomplete" because classify_doc returned fallback
    assert page["doc_type"] == "incomplete"
    # completeness is False because Stage 3 LLM also failed
    assert page["complete"] is False
    # No exception propagated up — the pilot ran to completion (P2)
    assert all("error" in item for item in report["results"])


# ---------------------------------------------------------------------------
# T1 / H2 加固 — page IDs are script-owned (H2)
#
# Two fixture sources that happen to share a topic slug (e.g. "writing
# techniques" in both source_a and source_b) must produce two distinct
# page IDs after extraction. extract_pilot is responsible for mapping
# Topic.id (LLM output) → stable page ID via _page_id._stable_page_id.
# ---------------------------------------------------------------------------

from src.pipeline.v7_extract._page_id import _stable_page_id, validate_page_id  # noqa: E402


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "v7_control_plane"


def _stage_scripts_for_source(_source_text: str, topic_id: str) -> FakeLLMClient:
    """Queue deterministic scripts for classify / completeness / cluster / fill_slots.

    The fake LLM client pops one script per call in FIFO order; pilot runs
    one classify + one completeness + one cluster + N fill_slots (one per
    topic). We queue enough copies to cover any number of topics.
    """
    fake = FakeLLMClient()
    fake.script(
        "classify",
        '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}',
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "' + topic_id + '", "title": "' + topic_id + '", "item_indexes": [0]}]}',
    )
    # fill_slots: cite item_index 0 → maps to Topic.item_ids[0]
    for _ in range(8):
        fake.script(
            "fill_slots",
            '{"slots": '
            '{"definition":"def","characteristics":"c",'
            '"examples":"e","related_concepts":"rc","references":"ref"}, '
            '"evidence": '
            '{"definition":{"item_index":0,"source_text_excerpt":"x"},'
            '"characteristics":{"item_index":0,"source_text_excerpt":"x"},'
            '"examples":{"item_index":0,"source_text_excerpt":"x"},'
            '"related_concepts":{"item_index":0,"source_text_excerpt":"x"},'
            '"references":{"item_index":0,"source_text_excerpt":"x"}}}',
        )
    return fake


def test_run_pilot_page_ids_are_unique_across_fixture_sources(tmp_path: Path) -> None:
    """Cross-document fixture: source_a + source_b share topic slug
    "writing-techniques-intro" but the script-owned page IDs must NOT
    collide (different md5 prefix from relative path).

    Uses tests/fixtures/v7_control_plane/ fixtures (Wave 0 shared fixture,
    per .superpowers/sdd/.../wave0/shared-fixture.md).
    """
    assert FIXTURE_DIR.exists(), f"shared fixture missing at {FIXTURE_DIR}"

    # Copy fixture sources into a tmp raw/sources tree so the pilot can pick
    # them up via the normal source selector.
    for name in ("source_a.md", "source_b.md"):
        (tmp_path / "raw" / "sources").mkdir(parents=True, exist_ok=True)
        (tmp_path / "raw" / "sources" / name).write_text(
            (FIXTURE_DIR / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    # Both fixtures share topic slug "writing-techniques-intro" — different
    # sources must yield two different stable page IDs.
    fake_a = _stage_scripts_for_source("fixture-a", "writing-techniques-intro")
    fake_b = _stage_scripts_for_source("fixture-b", "writing-techniques-intro")

    # Two pilots, one per source, to keep the fake-LLM script counts independent.
    report_a = asyncio.run(run_pilot(
        tmp_path, count=1, seed=1, llm=fake_a,
        sources=["raw/sources/source_a.md"],
    ))
    report_b = asyncio.run(run_pilot(
        tmp_path, count=1, seed=1, llm=fake_b,
        sources=["raw/sources/source_b.md"],
    ))

    pages_a = report_a["results"][0]["pages"]
    pages_b = report_b["results"][0]["pages"]

    assert pages_a, "fixture A produced no pages"
    assert pages_b, "fixture B produced no pages"

    id_a = pages_a[0]["id"]
    id_b = pages_b[0]["id"]

    # IDs must not collide even though the topic slug is the same.
    assert id_a != id_b, (
        f"cross-document page IDs must differ; got {id_a!r} for both "
        f"sources — extract_pilot is not script-owning page IDs"
    )
    # IDs must validate (no path separators / '..').
    validate_page_id(id_a)
    validate_page_id(id_b)
    # IDs must equal _page_id._stable_page_id for the relative the pilot
    # assigned — extract_pilot computes relative from root + path, so under
    # the pilot's tmp_path layout it's 'raw/sources/source_a.md' / '_b.md'.
    assert id_a == _stable_page_id(
        "raw/sources/source_a.md", "writing-techniques-intro",
    )
    assert id_b == _stable_page_id(
        "raw/sources/source_b.md", "writing-techniques-intro",
    )


def test_run_pilot_page_id_matches_expected_ids_json(tmp_path: Path) -> None:
    """Pin the contract: the IDs we ship must equal the values recorded in
    tests/fixtures/v7_control_plane/expected_ids.json (md5 prefixes
    48d50307 / 5ae5acd5). If anyone renames the fixtures this test
    fails loudly instead of silently bumping the IDs.
    """
    expected = json.loads(
        (FIXTURE_DIR / "expected_ids.json").read_text(encoding="utf-8")
    )
    prefix_a = expected["sources"]["v7_control_plane/source_a.md"]["md5_prefix"]
    prefix_b = expected["sources"]["v7_control_plane/source_b.md"]["md5_prefix"]
    assert prefix_a == "48d50307"
    assert prefix_b == "5ae5acd5"

    # Verify the script computes the same prefixes directly.
    id_a = _stable_page_id("v7_control_plane/source_a.md", "x")
    id_b = _stable_page_id("v7_control_plane/source_b.md", "x")
    assert id_a.startswith(prefix_a + "-")
    assert id_b.startswith(prefix_b + "-")


# ---------------------------------------------------------------------------
# Wave 2 / Task 2: _extract_one() returns ExtractionResult (plan §2.2.1).
# ---------------------------------------------------------------------------


def test_extract_one_returns_extraction_result(tmp_path: Path) -> None:
    """_extract_one now returns an ExtractionResult dataclass, not a raw dict."""
    path = tmp_path / "raw" / "sources" / "short.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 只有标题\n\n简介", encoding="utf-8")

    result = asyncio.run(_extract_one(tmp_path, path, "raw/sources/short.md"))
    assert isinstance(result, ExtractionResult)
    assert result.source_id == "raw/sources/short.md"
    # source_md5 is the file-content md5, not the relative path.
    assert len(result.source_md5) == 32 and all(
        ch in "0123456789abcdef" for ch in result.source_md5
    )


def test_extract_one_to_dict_exposes_five_state_legacy_fields(tmp_path: Path) -> None:
    """ExtractionResult.to_dict() merges legacy dict fields so the
    JSON contract survives unchanged (source / doc_type / complete /
    topics / pages / error)."""
    path = tmp_path / "raw" / "sources" / "short.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 只有标题\n\n简介", encoding="utf-8")

    result = asyncio.run(_extract_one(tmp_path, path, "raw/sources/short.md"))
    d = result.to_dict()
    # Five-state fields (plan §2.2.1).
    assert d["status"] in {
        ExtractionStatus.WRITTEN.value,
        ExtractionStatus.INCOMPLETE.value,
        ExtractionStatus.BLOCKED.value,
        ExtractionStatus.FAILED.value,
        ExtractionStatus.SKIPPED.value,
    }
    assert d["legacy_status"] in {
        ExtractionStatus.OK.value,
        ExtractionStatus.NEEDS_REVIEW.value,
        ExtractionStatus.INCOMPLETE.value,
    }
    assert d["source_md5"] == result.source_md5
    assert d["written_page_ids"] == []
    # Legacy contract: source / doc_type / complete / topics / pages.
    assert d["source"] == "raw/sources/short.md"
    assert "doc_type" in d
    assert "complete" in d
    assert "topics" in d
    assert "pages" in d


def test_extract_one_exception_returns_failed(tmp_path: Path) -> None:
    """An unexpected exception inside the pipeline yields
    ExtractionStatus.FAILED with failure_stage='extract_one'."""
    # Trigger the path's read to raise: a directory as a file path.
    bad_path = tmp_path / "raw" / "sources" / "broken.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.mkdir()  # directory, not a file → read_text raises

    result = asyncio.run(_extract_one(tmp_path, bad_path, "raw/sources/broken.md"))
    assert isinstance(result, ExtractionResult)
    assert result.status == ExtractionStatus.FAILED
    assert result.failure_stage == "extract_one"
    assert result.review_reasons, "expected at least one review reason"
    # Legacy compat: error string is non-empty.
    assert result.metadata.get("error")
    # source_md5 may be empty (read_bytes failed before md5 could be
    # computed) or a real md5 (failure happened later); either is fine,
    # the contract is just "FAILED result is well-formed".


def test_extract_one_page_sink_receives_concept_page(tmp_path: Path) -> None:
    """page_sink signature is unchanged: it's still called with the
    ConceptPage object (not an ExtractionResult)."""
    long = "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n" + "正文。" * 200
    path = tmp_path / "raw" / "sources" / "complete.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(long, encoding="utf-8")

    fake = FakeLLMClient()
    fake.script(
        "classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}'
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": '
        '{"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": '
        '{"definition": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"characteristics": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"examples": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"related_concepts": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}, '
        '"references": {"item_id": "raw/sources/complete.md", "source_text_excerpt": "定义"}}}'
    ))

    seen: list = []
    result = asyncio.run(_extract_one(
        tmp_path, path, "raw/sources/complete.md",
        llm=fake, page_sink=seen.append,
    ))
    assert isinstance(result, ExtractionResult)
    assert seen, "page_sink should have received the ConceptPage"
    # The page object has an .id attribute (ConceptPage), not a string.
    assert hasattr(seen[0], "id")
    # The ExtractionResult's written_page_ids carry the script-owned
    # stable page id (different from the LLM-supplied topic id).
    expected_stable_id = _stable_page_id(
        "raw/sources/complete.md", seen[0].id,
    )
    assert expected_stable_id in result.written_page_ids
