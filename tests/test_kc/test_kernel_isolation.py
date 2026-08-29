"""Per-project isolation tests for ``src.knowledge.kernel.get_kernel``.

Final whole-branch review Finding I-1: ``get_kernel`` used to keep a
single global ``_kernel_instance``, so ``get_kernel(root_a) is
get_kernel(root_b)`` was True — a cross-project collision. The fix keys
instances by normalized root path: same root → same kernel
(deterministic), different roots → different kernels, and
``get_kernel(None)`` after init returns the existing kernel for that
project (never a cross-project kernel).

These tests are additive — the existing singleton tests in
``tests/test_knowledge/test_kernel.py`` keep passing unchanged (they
reset the active kernel via ``km._kernel_instance = None``, which still
works because ``_kernel_instance`` remains the active-kernel slot).
"""
from __future__ import annotations

import pytest

import src.knowledge.kernel as km
from src.knowledge.kernel import get_kernel


@pytest.fixture(autouse=True)
def _reset_kernel_registry():
    """Reset the module-level kernel registry around every test."""
    saved_instances = dict(km._kernel_instances)
    saved_default = km._kernel_instance
    try:
        km._kernel_instances.clear()
        km._kernel_instance = None
        yield
    finally:
        km._kernel_instances.clear()
        km._kernel_instances.update(saved_instances)
        km._kernel_instance = saved_default


def test_get_kernel_different_roots_get_different_kernels(tmp_path):
    """get_kernel(root_a) is not get_kernel(root_b) — per-project isolation."""
    root_a = tmp_path / "proj_a"
    root_b = tmp_path / "proj_b"

    ka = get_kernel(root_a)
    kb = get_kernel(root_b)

    assert ka is not kb
    assert ka.versions.base_path != kb.versions.base_path


def test_get_kernel_same_root_returns_same_instance(tmp_path):
    """The same root always maps to the same kernel (deterministic)."""
    root_a = tmp_path / "proj_a"

    k1 = get_kernel(root_a)
    k2 = get_kernel(root_a)

    assert k1 is k2


def test_get_kernel_none_after_init_returns_existing_project_kernel(tmp_path):
    """get_kernel(None) after init returns the existing kernel for that project."""
    root_a = tmp_path / "proj_a"

    ka = get_kernel(root_a)

    assert get_kernel(None) is ka


def test_get_kernel_none_returns_most_recent_project_not_a_foreign_one(tmp_path):
    """get_kernel(None) never returns a kernel from a different project."""
    root_a = tmp_path / "proj_a"
    root_b = tmp_path / "proj_b"

    ka = get_kernel(root_a)
    kb = get_kernel(root_b)

    # The active kernel tracks the most recent explicit project; the
    # cross-project instance is only reachable through its own root.
    assert get_kernel(None) is kb
    assert get_kernel(root_a) is ka


def test_get_kernel_normalizes_root_path(tmp_path):
    """Equivalent spellings of the same root resolve to the same kernel."""
    root = tmp_path / "proj_a"
    root.mkdir()

    k1 = get_kernel(root)
    k2 = get_kernel(tmp_path / "proj_a" / ".." / "proj_a")

    assert k1 is k2


def test_get_kernel_raises_without_path_before_init():
    """None + no prior initialisation → RuntimeError (unchanged contract)."""
    with pytest.raises(RuntimeError, match="not initiali"):
        get_kernel(None)
