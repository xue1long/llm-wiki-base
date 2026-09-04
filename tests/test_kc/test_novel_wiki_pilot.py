import sys
import types
import json
from hashlib import sha256
from pathlib import Path

import pytest

sys.modules.setdefault("httpx", types.ModuleType("httpx"))
_yaml_stub = types.ModuleType("yaml")
_yaml_stub.safe_load = lambda *args, **kwargs: {}
_yaml_stub.safe_dump = lambda *args, **kwargs: ""
sys.modules.setdefault("yaml", _yaml_stub)

import scripts.kc_novel_wiki_pilot as pilot_module
from scripts.kc_novel_wiki_pilot import _error_category, _error_summary, run_pilot, select_sources


def test_select_sources_is_deterministic_and_bounded(tmp_path: Path):
    root = tmp_path / "raw" / "sources"
    root.mkdir(parents=True)
    (root / "large.md").write_text("x" * 20, encoding="utf-8")
    (root / "small.md").write_text("x", encoding="utf-8")
    (root / "other.txt").write_text("x", encoding="utf-8")

    selected = select_sources(tmp_path, 1)

    assert selected == [root / "small.md"]


def test_error_summary_preserves_provider_cause():
    root = RuntimeError("HTTP 429: token quota exhausted")
    outer = RuntimeError("retry exhausted")
    outer.__cause__ = root

    assert "HTTP 429" in _error_summary(outer)
    assert "token quota exhausted" in _error_summary(outer)
def test_truncated_provider_response_is_provider_error():
    assert _error_category(RuntimeError("TruncatedResponseError: finish_reason=length")) == "provider_error"


def test_main_prints_unicode_safely_for_legacy_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    async def fake_run_pilot(*args, **kwargs):
        return {"selected": 1, "succeeded": 1, "failed": 0, "title": "零宽字符\u200b"}

    monkeypatch.setattr(pilot_module, "run_pilot", fake_run_pilot)
    monkeypatch.setattr(
        sys,
        "argv",
        ["kc_novel_wiki_pilot.py", "--project-root", str(tmp_path), "--output", str(tmp_path / "report.json")],
    )

    assert pilot_module.main() == 0
    printed = capsys.readouterr().out
    assert "\\u200b" in printed
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["title"] == "零宽字符\u200b"


@pytest.mark.asyncio
async def test_run_pilot_surfaces_binding_audit_fields_and_failure_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "raw" / "sources"
    root.mkdir(parents=True)
    explicit = root / "explicit.md"
    legacy = root / "legacy.md"
    rejected = root / "rejected.md"
    for path in (explicit, legacy, rejected):
        path.write_text(path.stem, encoding="utf-8")

    monkeypatch.setattr(
        pilot_module,
        "select_sources",
        lambda project, limit: [explicit, legacy, rejected][:limit],
    )
    monkeypatch.setattr(pilot_module, "_get_provider", lambda: object(), raising=False)

    async def fake_generate_ingest(**kwargs):
        source = kwargs["source_path"]
        if source == rejected:
            inner = RuntimeError("declared block missing")
            outer = RuntimeError("review rejected")
            outer.__cause__ = inner
            raise outer
        audit = {
            explicit: {
                "source_id": "raw/sources/explicit.md",
                "block_id": "block_explicit",
                "quote": "exact explicit quote",
                "quote_hash": "a" * 64,
                "binding_mode": "explicit_block_binding",
                "evidence_refs": ["doc_explicit:evidence_1"],
                "evidence": [
                    {
                        "source_id": "raw/sources/explicit.md",
                        "block_id": "block_explicit",
                        "quote": "exact explicit quote",
                    }
                ],
                "preprocessing_version": "text-preprocess-v1",
                "input_text_sha256": "c" * 64,
                "canonical_text_sha256": "d" * 64,
                "prompt_text_sha256": "e" * 64,
                "noise_warnings": ["high_repetition"],
            },
            legacy: {
                "source_id": "raw/sources/legacy.md",
                "block_id": "block_legacy",
                "quote": "exact legacy quote",
                "quote_hash": "b" * 64,
                "binding_mode": "legacy_unique_quote",
                "evidence_refs": ["doc_legacy:evidence_1"],
            },
        }[source]
        return [object()], [], {"pilot_audit": audit}

    async def fake_commit_ingest(**kwargs):
        return None

    monkeypatch.setattr(
        pilot_module, "generate_ingest", fake_generate_ingest, raising=False
    )
    monkeypatch.setattr(
        pilot_module, "commit_ingest", fake_commit_ingest, raising=False
    )

    report = await run_pilot(tmp_path, limit=3, concurrency=1)

    assert report["selected"] == 3
    assert report["succeeded"] == 2
    assert report["failed"] == 1
    explicit_result = report["results"][0]
    assert explicit_result["status"] == "success"
    assert explicit_result["decision"] == "skip_no_content"
    assert explicit_result["reason_codes"] == ["metadata_only", "no_evidence_capacity"]
    assert explicit_result["analyzer_called"] is False
    assert explicit_result["source_bytes_sha256"] == sha256(b"explicit").hexdigest()
    assert explicit_result["block_id"] == "block_explicit"
    assert explicit_result["exact_quote"] == "exact explicit quote"
    assert explicit_result["quote_hash"] == "a" * 64
    assert "content_assessment" not in explicit_result

    legacy_result = report["results"][1]
    assert legacy_result["status"] == "success"
    assert legacy_result["binding_mode"] == "legacy_unique_quote"
    assert legacy_result["decision"] == "skip_no_content"
    assert legacy_result["evidence_capacity"]["blocks"] == 0

    rejected_result = report["results"][2]
    assert rejected_result["status"] == "failed"
    assert rejected_result["failure_reason"] == (
        "RuntimeError: review rejected <- RuntimeError: declared block missing"
    )
    assert rejected_result["decision"] == "skip_no_content"
    assert "content_assessment" not in rejected_result
