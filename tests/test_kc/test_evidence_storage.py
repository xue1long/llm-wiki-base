"""Tests for Evidence persistent storage + reader upgrade (路线 v2.2 §C-1 / G1).

7 TDD tests covering:

1. ``EvidenceStorage.write`` creates ``<id>.json`` under ``.index/evidence/``
2. ``EvidenceStorage.read`` round-trips an Evidence instance
3. ``EvidenceStorage.list_all`` returns all stored evidence IDs
4. ``read`` of a missing ID returns ``None`` (does not raise)
5. ``WikiPage.evidence_refs`` round-trips + old pages default to ``[]``
6. ``StrengthPolicy`` demotes to ``weak`` when ``structured_provenance`` is missing
7. ``StrengthPolicy`` demotes to ``weak`` when ``computation_provenance`` is missing

Backed by spec §3.2 (Evidence First) + §5.7 (Provenance fields) + §6 E-14/E-15
(strength demotion rules).
"""
from __future__ import annotations

import json
from pathlib import Path


from src.kc.contracts.evidence import Evidence
from src.kc.contracts.strength_policy import StrengthPolicy
from src.kc.evidence.storage import EvidenceStorage
from src.wiki.core.types import PageType, WikiPage


# ── tests 1–4: EvidenceStorage API ──────────────────────────────────────


def test_evidence_storage_write_creates_json_file(tmp_path: Path) -> None:
    """``write(evidence)`` persists ``<id>.json`` under ``.index/evidence/``."""
    evidence_dir = tmp_path / ".index" / "evidence"
    storage = EvidenceStorage(evidence_dir)

    evidence = Evidence(
        evidence_id="ev_test_001",
        document_id="d1",
        block_id="b1",
        quote="hello world",
        quote_hash="abcd1234",
        confidence=0.95,
        status="verified",
    )
    path = storage.write(evidence)

    assert path == evidence_dir / "ev_test_001.json"
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["evidence_id"] == "ev_test_001"
    assert payload["document_id"] == "d1"
    assert payload["block_id"] == "b1"
    assert payload["quote"] == "hello world"
    assert payload["quote_hash"] == "abcd1234"
    assert payload["confidence"] == 0.95
    assert payload["status"] == "verified"


def test_evidence_storage_read_returns_evidence(tmp_path: Path) -> None:
    """``read(id)`` round-trips an Evidence instance with matching fields."""
    storage = EvidenceStorage(tmp_path / ".index" / "evidence")
    original = Evidence(
        evidence_id="ev_rt_002",
        document_id="d2",
        block_id="b2",
        quote="round-trip quote",
        quote_hash="deadbeef",
        confidence=0.7,
        status="candidate",
    )
    storage.write(original)

    loaded = storage.read("ev_rt_002")
    assert loaded is not None
    assert loaded == original
    # Provenance fields survive the round-trip when populated.
    prov_payload = Evidence(
        evidence_id="ev_rt_003",
        document_id="d3",
        block_id="b3",
        quote="with provenance",
        quote_hash="provhash",
        confidence=0.5,
        status="verified",
        evidence_type="computed",
        computation_provenance={"input_ids": ["x", "y"], "algorithm": "sum", "algorithm_version": "1", "result_hash": "rh"},
    )
    storage.write(prov_payload)
    prov_loaded = storage.read("ev_rt_003")
    assert prov_loaded is not None
    assert prov_loaded.evidence_type == "computed"
    assert prov_loaded.computation_provenance == {
        "input_ids": ["x", "y"], "algorithm": "sum", "algorithm_version": "1", "result_hash": "rh"
    }


def test_evidence_storage_list_all_returns_ids(tmp_path: Path) -> None:
    """``list_all`` returns every evidence ID sorted lexicographically."""
    storage = EvidenceStorage(tmp_path / ".index" / "evidence")
    for eid in ("ev_c", "ev_a", "ev_b"):
        storage.write(Evidence(
            evidence_id=eid,
            document_id="d", block_id="b", quote="q", quote_hash="h",
        ))

    ids = storage.list_all()
    assert ids == ["ev_a", "ev_b", "ev_c"]


def test_evidence_storage_read_missing_returns_none(tmp_path: Path) -> None:
    """``read(unknown_id)`` returns ``None`` instead of raising."""
    storage = EvidenceStorage(tmp_path / ".index" / "evidence")
    result = storage.read("ev_does_not_exist")
    assert result is None


# ── test 5: WikiPage evidence_refs round-trip ───────────────────────────


def test_wiki_page_evidence_refs_default_is_empty_under_v4(tmp_path: Path) -> None:
    """V4 keeps evidence_refs out of frontmatter and defaults it on read."""
    # Fresh page: evidence_refs set explicitly.
    page_with_refs = WikiPage(
        id="card_round_trip",
        title="Round-trip",
        type=PageType.CONCEPT,
        evidence_refs=["d1:b1", "d2"],
    )
    fm = page_with_refs.to_frontmatter_dict()
    assert "evidence_refs" not in fm

    # Round-trip via from_dict preserves the list.
    page_back = WikiPage.from_dict(fm, body="")
    assert page_back.evidence_refs == []

    # Old page (no evidence_refs key, no _ko_extra.evidence) defaults to [].
    legacy_fm = {
        "id": "card_legacy",
        "title": "Legacy",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
    }
    page_legacy = WikiPage.from_dict(legacy_fm, body="")
    assert page_legacy.evidence_refs == []


# ── tests 6–7: StrengthPolicy demotion rules ───────────────────────────


def test_strength_policy_demote_when_structured_provenance_missing() -> None:
    """structured_source missing required fields → strength = weak (spec §6 E-15)."""
    policy = StrengthPolicy()
    # Default base strength for structured_source is "strong" — without
    # structured_provenance, it must be demoted to "weak".
    evidence = Evidence(
        evidence_id="ev_sp_missing",
        document_id="d", block_id="b", quote="q", quote_hash="h",
        evidence_type="structured_source",
        structured_provenance=None,
    )
    assert policy.compute_strength(evidence) == "weak"


def test_strength_policy_demote_when_computation_provenance_missing() -> None:
    """computed missing required fields → strength = weak (spec §6 E-14)."""
    policy = StrengthPolicy()
    # Default base strength for computed is "medium" — without
    # computation_provenance, it must be demoted to "weak".
    evidence = Evidence(
        evidence_id="ev_cp_missing",
        document_id="d", block_id="b", quote="q", quote_hash="h",
        evidence_type="computed",
        computation_provenance=None,
    )
    assert policy.compute_strength(evidence) == "weak"
