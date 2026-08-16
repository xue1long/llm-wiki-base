"""Phase 1.3 tests — KnowledgeGapStore (plan 1.3 gap ledger + guardrails)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.wiki.features.knowledge_gaps import KnowledgeGapStore, _blocklisted


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeGapStore:
    return KnowledgeGapStore(tmp_path)


def test_add_and_persist(store: KnowledgeGapStore) -> None:
    added = store.add_many(["装逼打脸", "力量体系"], referenced_by="p1")
    assert added == ["装逼打脸", "力量体系"]
    store.save()
    reloaded = KnowledgeGapStore(Path(store._path).parent.parent)
    assert reloaded.get("装逼打脸") is not None
    assert reloaded.get("装逼打脸").referenced_by == ["p1"]
    assert reloaded.count() == 2
    assert reloaded.count("open") == 2


def test_blocklist_and_doc_title_variant(store: KnowledgeGapStore) -> None:
    assert _blocklisted("func-教程")
    assert _blocklisted("source-补充")
    assert _blocklisted("琴帝-entity")
    assert _blocklisted("借鉴素材-20-个签约条件新人必看-6a144c5b")  # doc-title hash
    added = store.add_many(
        ["func-教程", "正常概念", "借鉴素材书籍如何商业化-e7e5c9c5"],
        referenced_by="p1", max_entries=5,
    )
    assert added == ["正常概念"]  # other two blocklisted


def test_hard_cap(store: KnowledgeGapStore) -> None:
    added = store.add_many(
        ["a", "b", "c", "d", "e", "f"], referenced_by="p1", max_entries=3)
    assert len(added) == 3
    assert store.count() == 3


def test_dedup_and_reference_accumulation(store: KnowledgeGapStore) -> None:
    store.add_many(["x"], referenced_by="p1")
    store.add_many(["x", "x", "y"], referenced_by="p2")
    gap = store.get("x")
    assert gap.referenced_by == ["p1", "p2"]


def test_status_transitions(store: KnowledgeGapStore) -> None:
    store.add_many(["g1"], referenced_by="p1")
    assert store.resolve("g1") is True
    assert store.get("g1").status == "resolved"
    store.add_many(["g2"], referenced_by="p1")
    assert store.suppress("g2", "") is False  # reason required
    assert store.suppress("g2", "人工判定为幻觉") is True
    assert store.get("g2").status == "suppressed"
    assert store.get("g2").suppressed_reason == "人工判定为幻觉"


def test_json_shape(tmp_path: Path) -> None:
    store = KnowledgeGapStore(tmp_path)
    store.add_many(["装逼打脸"], referenced_by="p1", now=0)
    store.save()
    data = json.loads((tmp_path / ".index" / "knowledge_gaps.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    entry = data["gaps"][0]
    # None fields are omitted from serialization (optional provenance);
    # present keys must be exactly the populated set.
    assert set(entry.keys()) == {"slug", "referenced_by", "created_at", "status"}
    assert entry["slug"] == "装逼打脸"
    assert entry["referenced_by"] == ["p1"]
    assert entry["status"] == "open"
    # a fully-populated entry carries the optional fields
    from src.wiki.features.knowledge_gaps import KnowledgeGap
    full = KnowledgeGap(slug="s", title="T", alias="a", type="concept",
                        raw_hint="raw/x.md", referenced_by=["p1"], created_at=0)
    d = full.to_dict()
    assert d["title"] == "T" and d["raw_hint"] == "raw/x.md" and "suppressed_reason" not in d
