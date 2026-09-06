import hashlib
import json

import pytest

from src.kc.views.book.wiki.series_model import (
    SCHEMA_VERSION, SeriesManifest, canonical_digest, transition_status,
)
from src.kc.views.book.wiki.series_validate import (
    validate_book_manifest, validate_series_manifest, validate_release_files,
    dependency_report, read_legacy_manifest,
)


def book(book_id="a", status="ready", required=True, release_id="r1", **extra):
    return {"book_id": book_id, "required": required, "status": status,
            "outline_id": "o-" + book_id, "hard_dependencies": [],
            "soft_dependencies": [], "release_id": release_id, **extra}


def series(status="ready", books=None, release_id="r1"):
    return {"schema_version": SCHEMA_VERSION, "series_id": "s", "release_id": release_id,
            "status": status, "books": books if books is not None else [book()]}


def test_valid_manifest_roundtrip_and_canonical_digest_does_not_self_reference():
    payload = series()
    model = SeriesManifest.from_dict(payload)
    assert model.to_dict() == payload
    assert canonical_digest({**payload, "manifest_sha256": "wrong"}) == canonical_digest(payload)


def test_schema_and_state_transition_fail_closed():
    assert validate_series_manifest(series())["ok"]
    assert validate_series_manifest({"schema_version": "outline-v1"})["ok"] is False
    assert transition_status("draft", "partial") == "partial"
    with pytest.raises(ValueError):
        transition_status("ready", "partial")
    with pytest.raises(ValueError):
        transition_status("draft", "ready")


def test_required_books_same_release_gate_and_partial_invalid():
    assert validate_series_manifest(series("ready", [book(), book("b", release_id="r2")]))["ok"] is False
    assert validate_series_manifest(series("partial", [book("a", "ready"), book("b", "partial")]))["ok"]
    assert validate_series_manifest(series("ready", [book("a", "invalid")]))["ok"] is False


def test_hashes_and_dependencies():
    p = __import__("pathlib").Path("tests/test_kc/test_book_series_manifest.py")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = {"files": {p.name: digest}}
    assert validate_release_files(manifest, p.parent)["ok"]
    assert validate_release_files({"files": {p.name: "bad"}}, p.parent)["ok"] is False
    books = [book("a", "ready", hard_dependencies=["b"]), book("b", "ready")]
    assert dependency_report(books)["ok"]
    assert dependency_report([book("a", "ready", hard_dependencies=["missing"])])["ok"] is False
    assert dependency_report([book("a", "ready", hard_dependencies=[""])])["ok"] is False
    assert dependency_report([book("a", "ready", soft_dependencies=["missing"])][0:])["soft_missing"] == ["missing"]


def test_legacy_manifest_is_single_book_without_guessed_series_membership():
    result = read_legacy_manifest({"schema_version": "outline-v1", "run_id": "old"})
    assert result["legacy"] is True
    assert result["series_id"] is None and result["book_id"] is None
