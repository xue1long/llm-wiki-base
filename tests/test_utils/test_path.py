# ruflo-kb/tests/test_utils/test_path.py
import sys

import pytest
from src.utils.path import migrate_state_paths, normalize_path, resolve_stored_path

def test_normalize_path():
    assert normalize_path("C:\\Users\\test\\file.md") == "C:/Users/test/file.md"
    assert normalize_path("/home/user/file.md") == "/home/user/file.md"


# ---------------------------------------------------------------------------
# resolve_stored_path
# ---------------------------------------------------------------------------

def test_resolve_stored_path_relative_under_root(tmp_path):
    root = tmp_path / "proj"
    rel = "wiki/sources/foo.md"
    assert resolve_stored_path(rel, root) == root / "wiki" / "sources" / "foo.md"


def test_resolve_stored_path_backslashes(tmp_path):
    root = tmp_path / "proj"
    assert resolve_stored_path(r"wiki\sources\foo.md", root) == root / "wiki" / "sources" / "foo.md"


def test_resolve_stored_path_absolute_inside_root(tmp_path):
    root = tmp_path / "proj"
    inside = root / "wiki" / "sources" / "foo.md"
    assert resolve_stored_path(str(inside), root) == inside


def test_resolve_stored_path_foreign_absolute_returns_none(tmp_path):
    root = tmp_path / "proj"
    outside = tmp_path / "sibling" / "evil.md"
    outside.parent.mkdir(parents=True)
    assert resolve_stored_path(str(outside), root) is None


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows drive-letter semantics")
def test_resolve_stored_path_foreign_drive_returns_none(tmp_path):
    root = tmp_path / "proj"  # on the C: drive
    # A path on a different drive (D:) can never be inside the C: root.
    foreign = r"D:\Users\Other\wiki\sources\x.md"
    assert resolve_stored_path(foreign, root) is None


def test_resolve_stored_path_parent_traversal_returns_none(tmp_path):
    root = tmp_path / "proj"
    assert resolve_stored_path("../evil.md", root) is None
    assert resolve_stored_path("wiki/../../evil.md", root) is None


@pytest.mark.parametrize("stored", ["", None, "   ", "\t"])
def test_resolve_stored_path_blank_returns_none(tmp_path, stored):
    assert resolve_stored_path(stored, tmp_path / "proj") is None


def test_resolve_stored_path_missing_file_still_resolves(tmp_path):
    """Path resolution is lexical — the file need not exist yet."""
    root = tmp_path / "proj"
    assert resolve_stored_path("wiki/sources/missing.md", root) == root / "wiki" / "sources" / "missing.md"


# ---------------------------------------------------------------------------
# migrate_state_paths
# ---------------------------------------------------------------------------

def test_migrate_state_paths_relativizes_and_preserves_digests(tmp_path):
    root = tmp_path / "proj"
    state = {
        "ingested": {str(root / "raw" / "sources" / "a.pdf"): "d1"},
        "archived": {str(root / "wiki" / "sources" / "b.md"): "d2"},
        "failed": {str(root / "wiki" / "concepts" / "c.md"): "err..."},
    }
    out = migrate_state_paths(state, root)
    assert out["ingested"] == {"raw/sources/a.pdf": "d1"}
    assert out["archived"] == {"wiki/sources/b.md": "d2"}
    assert out["failed"] == {"wiki/concepts/c.md": "err..."}


def test_migrate_state_paths_drops_foreign_keys(tmp_path):
    root = tmp_path / "proj"
    state = {
        "archived": {
            str(root / "wiki" / "sources" / "ok.md"): "d1",
            str(tmp_path / "other" / "foreign.md"): "d2",  # outside root -> dropped
        }
    }
    out = migrate_state_paths(state, root)
    assert out["archived"] == {"wiki/sources/ok.md": "d1"}


def test_migrate_state_paths_keeps_relative_and_normalizes_slashes(tmp_path):
    root = tmp_path / "proj"
    state = {"archived": {r"wiki\sources\old.md": "d1", "wiki/sources/new.md": "d2"}}
    out = migrate_state_paths(state, root)
    assert out["archived"] == {"wiki/sources/old.md": "d1", "wiki/sources/new.md": "d2"}


def test_migrate_state_paths_returns_new_dict_and_does_not_mutate(tmp_path):
    root = tmp_path / "proj"
    state = {"archived": {str(root / "wiki" / "sources" / "a.md"): "d1"}}
    original = {"archived": dict(state["archived"])}
    out = migrate_state_paths(state, root)
    assert out is not state
    assert state == original  # input unchanged


def test_migrate_state_paths_skips_non_dict_sections(tmp_path):
    root = tmp_path / "proj"
    state = {"archived": None, "ingested": [], "weird": "x"}
    out = migrate_state_paths(state, root)
    assert out == {"archived": None, "ingested": [], "weird": "x"}


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows absolute-path syntax")
def test_migrate_state_paths_drops_foreign_drive_key(tmp_path):
    root = tmp_path / "proj"
    state = {"archived": {r"C:\Users\HP\OneDrive\LLM-Wiki\wiki\sources\x.md": "d1"}}
    out = migrate_state_paths(state, root)
    assert out["archived"] == {}


def test_migrate_state_paths_posix_foreign_key_dropped(tmp_path):
    root = tmp_path / "proj"
    state = {"archived": {"/Users/me/wiki/sources/x.md": "d1"}}
    out = migrate_state_paths(state, root)
    assert out["archived"] == {}
