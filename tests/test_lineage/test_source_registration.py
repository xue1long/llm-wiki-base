import hashlib

from src.lineage.api import LineageStore


def test_source_registration_normalizes_and_preserves_status(tmp_path):
    raw = tmp_path / "input.md"
    raw.write_bytes(b"first")
    store = LineageStore.open(tmp_path)
    sid = store.ensure_source(raw)
    store.record_raw_assessment(sid, "ingested")
    assert store.ensure_source("./input.md") == sid
    assert store.source(sid)["status"] == "ingested"
    raw.write_bytes(b"changed")
    assert store.ensure_source(raw) == sid
    assert store.source(sid)["status"] == "stale"
    assert store.source(sid)["source_hash"] == hashlib.sha256(b"changed").hexdigest()


def test_text_and_url_sources_require_no_local_file(tmp_path):
    store = LineageStore.open(tmp_path)
    assert store.ensure_source("missing.md") is None
    sid = store.ensure_source("missing.md", source_text="provided")
    assert store.source(sid)["source_hash"] == hashlib.sha256(b"provided").hexdigest()
    url = "https://example.com/a"
    sid = store.ensure_source(url, source_text="downloaded")
    assert store.source(sid)["source_path"] == url
    assert store.source(sid)["source_hash"] == hashlib.sha256(b"downloaded").hexdigest()
    assert store.ensure_source(url) == sid
    assert store.source(sid)["source_hash"] == hashlib.sha256(b"downloaded").hexdigest()
