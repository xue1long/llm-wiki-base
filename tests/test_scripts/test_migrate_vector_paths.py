"""Tests for scripts/migrate_vector_paths.py pure helpers.

The script's vector/state wiring is exercised manually; these tests pin the
content-derived task_id, the per-row migration decision, and the archived-state
rebuild logic.
"""
import hashlib
import importlib.util
from pathlib import Path

from src.utils.hashing import sha256_file
from src.wiki.core.paths import WikiPaths

_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "migrate_vector_paths.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_vector_paths", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mvp = _load_module()


def test_task_id_for_digest():
    assert mvp.task_id_for_digest("abc1234567890xyz") == "kb-arch-abc123456789"


def test_migration_action_rewrite():
    index = {"kb-arch-aaaabbbbcccc": "wiki/sources/x.md"}
    assert mvp.migration_action("kb-arch-aaaabbbbcccc", index) == ("rewrite", "wiki/sources/x.md")


def test_migration_action_delete_when_unmatched():
    assert mvp.migration_action("kb-arch-deadbeef00aa", {}) == ("delete", None)


def test_migration_action_skips_non_prefixed():
    index = {"kb-arch-aaaabbbbcccc": "wiki/sources/x.md"}
    assert mvp.migration_action("kb-batch-aaaabbbbcccc", index) == ("skip", None)
    assert mvp.migration_action("t1", index) == ("skip", None)


def test_sha256_file(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello", encoding="utf-8")
    assert mvp.sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_build_index_and_rebuild_state(tmp_path):
    root = tmp_path / "proj"
    paths = WikiPaths(root)
    paths.wiki_sources.mkdir(parents=True)
    note = paths.wiki_sources / "x.md"
    note.write_text("# X\n\ncontent", encoding="utf-8")

    tid_to_rel, rel_to_digest = mvp.build_index(root)
    assert len(tid_to_rel) == 1
    tid = next(iter(tid_to_rel))
    assert tid.startswith("kb-arch-")
    assert tid_to_rel[tid] == "wiki/sources/x.md"

    state = mvp.rebuild_archived_state(
        {"ingested": {}, "archived": {}, "failed": {}},
        {tid},
        tid_to_rel,
        rel_to_digest,
        root,
    )
    assert state["archived"] == {"wiki/sources/x.md": rel_to_digest["wiki/sources/x.md"]}


def test_migrate_vector_paths_uses_shared_sha256_file():
    assert mvp.sha256_file is sha256_file
