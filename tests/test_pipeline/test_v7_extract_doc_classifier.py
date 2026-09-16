"""T2.1: Stage 1 doc_classifier — pure-LLM async classification.

Replaces the v2 heuristic-based tests (which used regex + length gates).
The new tests use ``FakeLLMClient`` to inject scripted LLM responses.

Note on D9 path whitelist: tests pass ``project_root=None`` to skip
the whitelist check entirely (legitimate — tests don't need the D9
attack surface). D9 is tested separately in
test_v7_extract_prompts_resolver.
"""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.doc_classifier import (
    Classification,
    classify_doc,
    _payload_to_classification,
    _resolve_classify_template,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient


# ---------------------------------------------------------------------------
# Classification dataclass
# ---------------------------------------------------------------------------

def test_classification_accepts_all_7_doc_types():
    for dt in (
        "single_method", "multi_section", "collection",
        "qa_chat", "list", "tool", "incomplete",
    ):
        c = Classification(doc_type=dt, confidence=0.9, rationale="ok")
        assert c.doc_type == dt


def test_classification_rejects_unknown_doc_type():
    with pytest.raises(ValueError, match="doc_type must be one of"):
        Classification(doc_type="pwned", confidence=0.9, rationale="")


def test_classification_rejects_out_of_range_confidence():
    with pytest.raises(ValueError, match="confidence must be in"):
        Classification(doc_type="single_method", confidence=1.5, rationale="")
    with pytest.raises(ValueError, match="confidence must be in"):
        Classification(doc_type="single_method", confidence=-0.1, rationale="")


def test_classification_repr_includes_fields():
    c = Classification(doc_type="multi_section", confidence=0.7, rationale="test")
    r = repr(c)
    assert "multi_section" in r
    assert "0.7" in r
    assert "test" in r


def test_classification_equality():
    a = Classification("single_method", 0.5, "x")
    b = Classification("single_method", 0.5, "x")
    c = Classification("single_method", 0.5, "y")
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# _payload_to_classification helper
# ---------------------------------------------------------------------------

def test_payload_to_classification_happy_path():
    payload = {
        "doc_type": "single_method",
        "confidence": 0.85,
        "rationale": "looks like a tutorial",
    }
    c = _payload_to_classification(payload)
    assert c.doc_type == "single_method"
    assert c.confidence == 0.85
    assert c.rationale == "looks like a tutorial"


def test_payload_to_classification_defaults_rationale():
    payload = {"doc_type": "list", "confidence": 0.5}
    c = _payload_to_classification(payload)
    assert c.rationale == ""


def test_payload_to_classification_coerces_int_confidence():
    payload = {"doc_type": "tool", "confidence": 1}
    c = _payload_to_classification(payload)
    assert c.confidence == 1.0
    assert isinstance(c.confidence, float)


# ---------------------------------------------------------------------------
# _resolve_classify_template helper
# ---------------------------------------------------------------------------

def test_resolve_classify_template_uses_bundled():
    """No project / user override → bundled/classify.toml is used.

    Pass project_root=None to bypass the D9 whitelist check; we test
    the bundled-vs-user-vs-project logic in test_v7_extract_prompts_resolver.
    """
    template = _resolve_classify_template(project_root=None)
    assert template.prompt_kind == "classify"
    assert template.source == "bundled"


# ---------------------------------------------------------------------------
# classify_doc — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_doc_returns_classification_on_valid_response():
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "ok"}')

    result = await classify_doc(
        "some article body",
        filename_hint="test.md",
        llm=fake,
        project_root=None,
    )

    assert isinstance(result, Classification)
    assert result.doc_type == "single_method"
    assert result.confidence == 0.9
    assert result.rationale == "ok"


@pytest.mark.asyncio
async def test_classify_doc_strips_json_fence():
    fake = FakeLLMClient()
    fake.script(
        "classify",
        '```json\n{"doc_type": "multi_section", "confidence": 0.8, "rationale": "r"}\n```',
    )

    result = await classify_doc("body", filename_hint="x.md", llm=fake,
                               project_root=None)
    assert result.doc_type == "multi_section"
    assert result.confidence == 0.8


@pytest.mark.asyncio
async def test_classify_doc_records_llm_calls():
    """Each classify_doc call triggers exactly one LLM call (no retries)."""
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "list", "confidence": 0.7, "rationale": "r"}')

    await classify_doc("body", filename_hint="x.md", llm=fake,
                       project_root=None)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["prompt_kind"] == "classify"


# ---------------------------------------------------------------------------
# classify_doc — P2 failure modes (NEVER raise, always return Classification)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_doc_returns_incomplete_on_invalid_json():
    """D2: schema-invalid response triggers retry; after max_retries
    P2: returns Classification(incomplete, 0.0)."""
    fake = FakeLLMClient()
    fake.script("classify", "not json at all")
    fake.script("classify", "still not json")
    fake.script("classify", "{not even valid}")

    result = await classify_doc(
        "body", filename_hint="x.md", llm=fake,
        project_root=None,
    )
    assert isinstance(result, Classification)
    assert result.doc_type == "incomplete"
    assert result.confidence == 0.0
    assert "stage1_failed" in result.rationale
    # Verify we tried max_retries=3 times
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_classify_doc_returns_incomplete_on_schema_violation():
    """doc_type not in enum → LLMResponseError → retry → INCOMPLETE."""
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "pwned", "confidence": 0.5, "rationale": "r"}')

    result = await classify_doc(
        "body", filename_hint="x.md", llm=fake,
        project_root=None,
    )
    assert result.doc_type == "incomplete"
    assert result.confidence == 0.0
    assert len(fake.calls) == 3  # retried 3 times


@pytest.mark.asyncio
async def test_classify_doc_succeeds_after_two_invalid_retries():
    """D2: retry succeeds when LLM eventually returns a valid response.

    The 1st call fails (returns empty), 2nd succeeds. We register the
    valid script twice to be safe — once for the successful retry and
    once as a sentinel in case the impl retries more than expected.
    """
    fake = FakeLLMClient()
    fake.script("classify", "")  # 1st call → empty → LLMResponseError
    # Output schema requires doc_type + confidence + rationale
    fake.script("classify", '{"doc_type": "tool", "confidence": 0.6, "rationale": "r"}')
    fake.script("classify", '{"doc_type": "tool", "confidence": 0.6, "rationale": "r"}')

    result = await classify_doc(
        "body", filename_hint="x.md", llm=fake,
        project_root=None,
    )
    assert result.doc_type == "tool"
    assert result.confidence == 0.6
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_classify_doc_handles_llm_raising_exception():
    """An LLM provider exception must NOT propagate — P2 invariant."""
    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise RuntimeError("simulated LLM outage")

    result = await classify_doc(
        "body", filename_hint="x.md", llm=_ExplodingFake(),
        project_root=None,
    )
    assert result.doc_type == "incomplete"
    assert result.confidence == 0.0
    assert "stage1_failed" in result.rationale


# ---------------------------------------------------------------------------
# classify_doc — path / template resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_doc_missing_bundled_raises_runtime_error(monkeypatch):
    """If bundled classify.toml is missing, raise RuntimeError so the
    caller can enqueue this as a config-level failure."""
    import src.pipeline.v7_extract.doc_classifier as dc
    import src.pipeline.v7_extract.prompts.resolver as r

    empty = monkeypatch.fscontext if hasattr(monkeypatch, "fscontext") else None
    # Use tmp_path-free approach: monkeypatch's tmpdir
    import tempfile
    tmp = tempfile.mkdtemp()
    from pathlib import Path
    empty_root = Path(tmp)
    monkeypatch.setattr(r, "BUNDLED_ROOT", empty_root)
    monkeypatch.setattr(r, "_user_root", lambda: empty_root)

    with pytest.raises(RuntimeError, match="V7 classify prompt is not available"):
        await dc.classify_doc(
            "body", filename_hint="x.md", llm=FakeLLMClient(),
            project_root=None,
        )


# ---------------------------------------------------------------------------
# Backwards-compat shim: the v2 doc_classifier.py exposed fixture strings
# (SINGLE_METHOD, MULTI_SECTION, …) at module level for other test
# modules to import. The v3 rewrite removed them, which broke the
# v2 completeness_checker / topic_clusterer / slot_filler tests.
#
# T2.6 will rewrite all those tests from scratch — until then, re-
# expose the fixtures so the old tests can still collect.
# ---------------------------------------------------------------------------

SINGLE_METHOD = """# How to Write Strong Openings

Openings are the most important part of any novel.
Three techniques: 1. Start in media res. 2. Anchor with conflict. 3. Show the genre.
"""

MULTI_SECTION = """# How to Write Network Novels (Beginner's Guide)

## 一、人物个性的刻画
## 二、配角的运用
## 三、桥段的发挥
"""

QA_CHAT = """8难讲课记录
8难(378234368) 19:59:37
8难(378234368) 19:59:43
"""

COLLECTION = """# Editor's Collection

## 作者 314 — 如何更好地包装作品

## 作者 314 — 如何写好作品简介

## 作者 阿零 — 解决卡文的三两招

## 作者 ZENK — 写在新人成功之前

## 作者 314 — 扩句法
"""

LIST_DOC = """# 103 classic bridge sections

1, 别人为求一件上刀山,下油锅的宝物...
2, 小有名气的时候被...
3, 没有名气的时候...
"""

INCOMPLETE_DOC = """# 标题

这是一段很短的引言。
"""

TOOL_DOC = """百家姓

赵 钱 孙 李 周 吴 郑 王
"""


# ---------------------------------------------------------------------------
# v4 Stage 1 remediation (plan 2026-09-17) — Failure Contract + traits +
# fingerprint + evidence_summary.
# ---------------------------------------------------------------------------


def test_classification_has_v4_fields_with_defaults():
    """v4: Classification carries failed/error/uncertain/traits/fingerprint."""
    c = Classification(doc_type="collection", confidence=0.8, rationale="r")
    assert c.failed is False
    assert c.error is None
    assert c.uncertain is False
    assert c.traits == []
    assert c.evidence_summary == {}
    assert c.classifier_fingerprint == ""


def test_payload_to_classification_parses_traits_and_uncertain():
    """v4: LLM output may include ``traits`` list and ``uncertain`` flag."""
    payload = {
        "doc_type": "collection",
        "confidence": 0.7,
        "rationale": "looks like a collection",
        "traits": ["possible_collection", "multi_author"],
        "uncertain": True,
    }
    c = _payload_to_classification(payload)
    assert c.doc_type == "collection"
    assert c.uncertain is True
    assert c.traits == ["possible_collection", "multi_author"]
    assert c.failed is False


def test_payload_to_classification_defaults_traits_when_missing():
    """v4: missing ``traits`` key → empty list, not crash."""
    c = _payload_to_classification({
        "doc_type": "single_method",
        "confidence": 0.9,
        "rationale": "ok",
    })
    assert c.traits == []


def test_payload_to_classification_infers_uncertain_from_low_confidence():
    """v4: confidence < 0.4 → uncertain=True (heuristic)."""
    c = _payload_to_classification({
        "doc_type": "multi_section",
        "confidence": 0.3,
        "rationale": "weak",
    })
    assert c.uncertain is True


@pytest.mark.asyncio
async def test_classify_doc_failed_true_on_llm_timeout():
    """Failure Contract: technical failure → failed=True, NOT doc_type='incomplete' alone."""
    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise TimeoutError("provider outage")

    result = await classify_doc(
        "body", filename_hint="x.md", llm=_ExplodingFake(),
        project_root=None,
    )
    # Backward compat: doc_type still "incomplete" so legacy callers/tests
    # don't break. But the new ``failed`` flag is the source of truth.
    assert result.doc_type == "incomplete"
    assert result.failed is True
    assert result.error is not None
    # str(exception) gives the message body; rationale carries the repr.
    assert "provider outage" in result.error
    # rationale uses str(exception) (body only) for backward compat —
    # downstream consumers can switch to .error / .failed when needed.
    assert "stage1_failed" in result.rationale
    assert result.evidence_summary != {}  # still computed before LLM call
    assert result.classifier_fingerprint.startswith("cls-")


@pytest.mark.asyncio
async def test_classify_doc_failed_true_on_invalid_json():
    """Failure Contract: schema-invalid response → failed=True after retries."""
    fake = FakeLLMClient()
    fake.script("classify", "not json")
    fake.script("classify", "still not json")
    fake.script("classify", "{nope}")

    result = await classify_doc(
        "body", filename_hint="x.md", llm=fake,
        project_root=None,
    )
    assert result.failed is True
    assert result.doc_type == "incomplete"  # legacy compat
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_classify_doc_success_path_failed_false():
    """Happy path: LLM returns valid payload → failed=False."""
    fake = FakeLLMClient()
    fake.script(
        "classify",
        '{"doc_type": "collection", "confidence": 0.85, "rationale": "ok"}',
    )
    result = await classify_doc(
        "body", filename_hint="x.md", llm=fake,
        project_root=None,
    )
    assert result.failed is False
    assert result.doc_type == "collection"
    assert result.uncertain is False  # 0.85 > 0.4 threshold
    assert result.classifier_fingerprint.startswith("cls-")

