"""Tests for src.knowledge.memory.decision — DecisionRecorder and DecisionRecord."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from src.knowledge.memory.decision import (
    DecisionRecorder,
    DecisionRecord,
    _slugify,
    _read_decision_raw,
)
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paths(tmp_path: Path) -> WikiPaths:
    """Create WikiPaths rooted at tmp_path, ensuring wiki/decisions/ exists."""
    paths = WikiPaths(tmp_path)
    paths.wiki_decisions.mkdir(parents=True, exist_ok=True)
    return paths


def _parse_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from a wiki page file."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"Expected frontmatter start, got: {text[:80]}"
    end = text.find("\n---", 4)
    assert end >= 0, "Frontmatter closing --- not found"
    return yaml.safe_load(text[4:end]) or {}


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_lowercase_and_hyphens(self):
        assert _slugify("Hello World") == "hello-world"

    def test_strips_special_chars(self):
        assert _slugify("What? Decision! #1") == "what-decision-1"

    def test_cjk_preserved(self):
        assert _slugify("是否使用Redis缓存") == "是否使用redis缓存"

    def test_empty_fallback(self):
        assert _slugify("???") == "decision"


# ---------------------------------------------------------------------------
# DecisionRecord dataclass
# ---------------------------------------------------------------------------

class TestDecisionRecord:
    def test_all_fields(self):
        dr = DecisionRecord(
            context="Need caching",
            alternatives=["Redis", "Memcached"],
            rationale="Redis has more features",
            outcome="Redis worked well",
            actual_impact="Reduced latency by 50%",
            decided_at=1700000000000,
            outcome_at=1700100000000,
        )
        assert dr.context == "Need caching"
        assert dr.alternatives == ["Redis", "Memcached"]
        assert dr.rationale == "Redis has more features"
        assert dr.outcome == "Redis worked well"
        assert dr.actual_impact == "Reduced latency by 50%"
        assert dr.decided_at == 1700000000000
        assert dr.outcome_at == 1700100000000

    def test_defaults(self):
        dr = DecisionRecord(
            context="Test",
            alternatives=[],
            rationale="Because",
        )
        assert dr.outcome == ""
        assert dr.actual_impact == ""
        assert dr.decided_at == 0
        assert dr.outcome_at == 0

    def test_to_dict(self):
        dr = DecisionRecord(
            context="Ctx",
            alternatives=["A", "B"],
            rationale="Why",
            outcome="OK",
            actual_impact="Good",
            decided_at=1000,
            outcome_at=2000,
        )
        d = dr.to_dict()
        assert d["context"] == "Ctx"
        assert d["alternatives"] == ["A", "B"]
        assert d["rationale"] == "Why"
        assert d["outcome"] == "OK"
        assert d["actual_impact"] == "Good"
        assert d["decided_at"] == 1000
        assert d["outcome_at"] == 2000

    def test_from_dict(self):
        d = {
            "context": "Ctx",
            "alternatives": ["X"],
            "rationale": "R",
            "outcome": "O",
            "actual_impact": "I",
            "decided_at": 999,
            "outcome_at": 888,
        }
        dr = DecisionRecord.from_dict(d)
        assert dr.context == "Ctx"
        assert dr.alternatives == ["X"]
        assert dr.rationale == "R"
        assert dr.outcome == "O"
        assert dr.actual_impact == "I"
        assert dr.decided_at == 999
        assert dr.outcome_at == 888

    def test_from_dict_partial(self):
        dr = DecisionRecord.from_dict({"context": "Only"})
        assert dr.context == "Only"
        assert dr.alternatives == []
        assert dr.rationale == ""
        assert dr.outcome == ""


# ---------------------------------------------------------------------------
# record_decision
# ---------------------------------------------------------------------------

class TestRecordDecision:
    def test_creates_wiki_page(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Should we use Redis?",
            decision="Yes, use Redis for caching.",
            context="App needs caching layer",
            alternatives=["Memcached", "No cache"],
            rationale="Redis has persistence and rich data types",
        )
        expected_path = paths.wiki_decisions / f"{did}.md"
        assert expected_path.exists(), f"Expected file at {expected_path}"

    def test_returns_id(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Q?", decision="A.", context="C", alternatives=["X"], rationale="R"
        )
        assert isinstance(did, str)
        assert len(did) > 0
        assert did.startswith("card_")

    def test_frontmatter_has_decision(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Test question",
            decision="Test answer",
            context="Test context",
            alternatives=["Alt1", "Alt2"],
            rationale="Test rationale",
        )
        path = paths.wiki_decisions / f"{did}.md"
        fm = _parse_frontmatter(path)
        # C-0 Commit 2: decision_record is a top-level frontmatter key, not
        # buried under _ko_extra.memory.decision.
        decision = fm.get("decision_record")
        assert isinstance(decision, dict), f"decision_record missing: {fm}"
        assert decision.get("context") == "Test context"
        assert decision.get("alternatives") == ["Alt1", "Alt2"]
        assert decision.get("rationale") == "Test rationale"

    def test_all_fields_stored(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Q",
            decision="D",
            context="C",
            alternatives=["A1"],
            rationale="R",
        )
        path = paths.wiki_decisions / f"{did}.md"
        fm = _parse_frontmatter(path)
        # C-0 Commit 2: top-level decision_record (was _ko_extra.memory.decision).
        decision_data = fm["decision_record"]
        assert decision_data["context"] == "C"
        assert decision_data["alternatives"] == ["A1"]
        assert decision_data["rationale"] == "R"
        assert decision_data["outcome"] == ""
        assert decision_data["actual_impact"] == ""
        assert decision_data["decided_at"] > 0
        assert decision_data["outcome_at"] == 0

    def test_default_empty_alternatives(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Simple Q",
            decision="Simple D",
        )
        path = paths.wiki_decisions / f"{did}.md"
        fm = _parse_frontmatter(path)
        # C-0 Commit 2: top-level decision_record.
        decision_data = fm["decision_record"]
        assert decision_data["alternatives"] == []

    def test_wiki_page_type_is_decision(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Type check", decision="Body"
        )
        path = paths.wiki_decisions / f"{did}.md"
        fm = _parse_frontmatter(path)
        assert fm["type"] == "decision"

    def test_title_is_question(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        question = "What is the best approach?"
        did = recorder.record_decision(question=question, decision="Answer")
        path = paths.wiki_decisions / f"{did}.md"
        fm = _parse_frontmatter(path)
        assert fm["title"] == question

    def test_body_is_decision_content(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        decision_text = "We chose option A because it is faster."
        did = recorder.record_decision(question="Q", decision=decision_text)
        path = paths.wiki_decisions / f"{did}.md"
        text = path.read_text(encoding="utf-8")
        end = text.find("\n---", 4)
        body = text[end + 5:].lstrip("\n")
        assert body == decision_text


# ---------------------------------------------------------------------------
# update_outcome
# ---------------------------------------------------------------------------

class TestUpdateOutcome:
    def test_sets_outcome(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Q", decision="D", context="C", rationale="R"
        )
        recorder.update_outcome(did, outcome="It worked perfectly")
        fm = _parse_frontmatter(paths.wiki_decisions / f"{did}.md")
        # C-0 Commit 2: top-level decision_record (was _ko_extra.memory.decision).
        decision_data = fm["decision_record"]
        assert decision_data["outcome"] == "It worked perfectly"

    def test_sets_actual_impact(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(question="Q", decision="D")
        recorder.update_outcome(
            did, outcome="OK", actual_impact="Saved 200 hours"
        )
        fm = _parse_frontmatter(paths.wiki_decisions / f"{did}.md")
        # C-0 Commit 2: top-level decision_record.
        decision_data = fm["decision_record"]
        assert decision_data["outcome"] == "OK"
        assert decision_data["actual_impact"] == "Saved 200 hours"

    def test_sets_outcome_at_timestamp(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(question="Q", decision="D")
        before = int(time.time() * 1000)
        recorder.update_outcome(did, outcome="Done")
        after = int(time.time() * 1000)
        fm = _parse_frontmatter(paths.wiki_decisions / f"{did}.md")
        # C-0 Commit 2: top-level decision_record.
        decision_data = fm["decision_record"]
        oat = decision_data["outcome_at"]
        assert oat > 0
        assert before <= oat <= after + 100  # +100ms buffer for clock skew

    def test_preserves_existing_fields(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Q",
            decision="D",
            context="Original context",
            alternatives=["A"],
            rationale="Original rationale",
        )
        recorder.update_outcome(did, outcome="Done")
        fm = _parse_frontmatter(paths.wiki_decisions / f"{did}.md")
        # C-0 Commit 2: top-level decision_record.
        d = fm["decision_record"]
        assert d["context"] == "Original context"
        assert d["alternatives"] == ["A"]
        assert d["rationale"] == "Original rationale"

    def test_nonexistent_id_raises(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        with pytest.raises(FileNotFoundError, match="not-found-123"):
            recorder.update_outcome("not-found-123", outcome="Done")

    def test_body_preserved_after_update(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(question="Q", decision="Original body")
        recorder.update_outcome(did, outcome="OK")
        path = paths.wiki_decisions / f"{did}.md"
        text = path.read_text(encoding="utf-8")
        end = text.find("\n---", 4)
        body = text[end + 5:].lstrip("\n")
        assert body == "Original body"


# ---------------------------------------------------------------------------
# get_decision_context
# ---------------------------------------------------------------------------

class TestGetDecisionContext:
    def test_returns_full_record(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Should we migrate?",
            decision="Yes, migrate to PostgreSQL.",
            context="MySQL reaching limits",
            alternatives=["Stay on MySQL", "Use MongoDB"],
            rationale="PostgreSQL scales better",
        )
        ctx = recorder.get_decision_context(did)
        assert ctx is not None
        assert ctx["id"] == did
        assert ctx["question"] == "Should we migrate?"
        assert ctx["decision"] == "Yes, migrate to PostgreSQL."
        assert ctx["context"] == "MySQL reaching limits"
        assert ctx["alternatives"] == ["Stay on MySQL", "Use MongoDB"]
        assert ctx["rationale"] == "PostgreSQL scales better"

    def test_before_outcome(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(question="Q", decision="D")
        ctx = recorder.get_decision_context(did)
        assert ctx is not None
        assert ctx["outcome"] == ""
        assert ctx["actual_impact"] == ""

    def test_after_outcome(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(question="Q", decision="D")
        recorder.update_outcome(did, outcome="Success", actual_impact="Faster builds")
        ctx = recorder.get_decision_context(did)
        assert ctx is not None
        assert ctx["outcome"] == "Success"
        assert ctx["actual_impact"] == "Faster builds"

    def test_nonexistent_id_returns_none(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        ctx = recorder.get_decision_context("nonexistent-id")
        assert ctx is None

    def test_returns_record_for_default_alternatives(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(question="Simple", decision="OK")
        ctx = recorder.get_decision_context(did)
        assert ctx is not None
        assert ctx["alternatives"] == []
        assert ctx["context"] == ""
        assert ctx["rationale"] == ""


# ---------------------------------------------------------------------------
# _read_decision_raw (internal helper)
# ---------------------------------------------------------------------------

class TestReadDecisionRaw:
    def test_returns_decision_record(self, tmp_path):
        # C-0 Commit 2: _read_decision_raw now returns the decision dict
        # itself (top-level ``decision_record``), not the surrounding
        # ``_ko_extra`` envelope.
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="Test", decision="Body", context="Ctx"
        )
        path = paths.wiki_decisions / f"{did}.md"
        decision = _read_decision_raw(path)
        assert isinstance(decision, dict)
        assert decision.get("context") == "Ctx"

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = _read_decision_raw(Path(tmp_path) / "nope.md")
        assert result is None


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_multiple_decisions(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)

        id1 = recorder.record_decision(question="Q1", decision="D1")
        id2 = recorder.record_decision(question="Q2", decision="D2")
        assert id1 != id2

        recorder.update_outcome(id1, outcome="O1")
        recorder.update_outcome(id2, outcome="O2", actual_impact="I2")

        ctx1 = recorder.get_decision_context(id1)
        ctx2 = recorder.get_decision_context(id2)
        assert ctx1["outcome"] == "O1"
        assert ctx2["outcome"] == "O2"
        assert ctx2["actual_impact"] == "I2"

    def test_cjk_question(self, tmp_path):
        paths = _make_paths(tmp_path)
        recorder = DecisionRecorder(paths)
        did = recorder.record_decision(
            question="是否应该使用微服务架构？",
            decision="不适合当前阶段",
            context="团队规模小",
            alternatives=["继续单体", "模块化拆分"],
            rationale="微服务运维成本高",
        )
        assert did.startswith("card_")
        path = paths.wiki_decisions / f"{did}.md"
        assert path.exists()
        ctx = recorder.get_decision_context(did)
        assert ctx is not None
        assert ctx["question"] == "是否应该使用微服务架构？"
