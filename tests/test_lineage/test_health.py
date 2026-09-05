from pathlib import Path
from hashlib import sha256

from src.lineage import LineageStore


def test_health_reports_pending_outbox_and_missing_artifact(tmp_path: Path) -> None:
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "discovered")
    store.enqueue_outbox("event-1", "raw_discovered", "src-1")
    store.link_artifact("wiki", "wiki-1", ("src-1",), "wiki/missing.md", "b" * 64, "committed")

    health = store.health()

    assert health.ok is False
    assert health.pending_outbox == 1
    assert health.missing_artifacts == 1


def test_health_reports_hash_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "wiki" / "a.md"
    artifact.parent.mkdir()
    artifact.write_text("changed", encoding="utf-8")
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "discovered")
    store.link_artifact("wiki", "wiki-1", ("src-1",), "wiki/a.md", sha256(b"a").hexdigest(), "committed")

    health = store.health()

    assert health.hash_mismatches == 1
    assert health.ok is False


def test_health_is_clean_after_replay_and_existing_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "wiki" / "a.md"
    artifact.parent.mkdir()
    artifact.write_text("a", encoding="utf-8")
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "discovered")
    store.enqueue_outbox("event-1", "raw_discovered", "src-1")
    store.replay_outbox()
    store.link_artifact("wiki", "wiki-1", ("src-1",), "wiki/a.md", sha256(b"a").hexdigest(), "committed")

    assert store.health().ok is True
