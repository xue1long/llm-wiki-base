"""R10: feature flag test for v3 / v2 implementation toggle.

Validates that ``V7_USE_V3=false`` routes the public API through the
legacy v2 implementation in ``_legacy.py``. Until Phase 2 fills in the
v3 implementation the v3 branch is expected to raise (loud failure
rather than silent).
"""
from __future__ import annotations

import importlib
import sys


def test_use_v3_pipeline_default_is_true(monkeypatch):
    """Default V7_USE_V3 is 'true' → USE_V3_PIPELINE = True."""
    monkeypatch.delenv("V7_USE_V3", raising=False)
    # Drop cached imports so the env var is re-read.
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.pipeline.v7_extract"):
            del sys.modules[mod_name]
    pkg = importlib.import_module("src.pipeline.v7_extract")
    assert pkg.USE_V3_PIPELINE is True


def test_use_v3_pipeline_explicit_false(monkeypatch):
    """V7_USE_V3=false → USE_V3_PIPELINE = False."""
    monkeypatch.setenv("V7_USE_V3", "false")
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.pipeline.v7_extract"):
            del sys.modules[mod_name]
    pkg = importlib.import_module("src.pipeline.v7_extract")
    assert pkg.USE_V3_PIPELINE is False


def test_use_v3_pipeline_case_insensitive(monkeypatch):
    """V7_USE_V3 accepts 'True', 'TRUE', 'true'."""
    for val in ("true", "TRUE", "True"):
        monkeypatch.setenv("V7_USE_V3", val)
        for mod_name in list(sys.modules):
            if mod_name.startswith("src.pipeline.v7_extract"):
                del sys.modules[mod_name]
        pkg = importlib.import_module("src.pipeline.v7_extract")
        assert pkg.USE_V3_PIPELINE is True, f"failed for {val!r}"


def test_v3_branch_routes_to_v3_modules(monkeypatch):
    """V7_USE_V3=true → v3 branch imports the actual stage modules.

    Even before Phase 2 finishes, this should NOT raise — the v3 modules
    currently still contain the heuristic + sync code that will be
    rewritten in T2.1-T2.4. The point of T1.0 is that the routing
    machinery works; the actual async rewrite is Phase 2.
    """
    monkeypatch.delenv("V7_USE_V3", raising=False)
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.pipeline.v7_extract"):
            del sys.modules[mod_name]
    pkg = importlib.import_module("src.pipeline.v7_extract")
    for fn_name in ("classify_doc", "check_completeness", "cluster_topics", "fill_slots"):
        fn = getattr(pkg, fn_name)
        assert callable(fn)


def test_v2_branch_routes_to_legacy_module(monkeypatch):
    """V7_USE_V3=false → v2 branch imports _legacy_* and returns its function."""
    monkeypatch.setenv("V7_USE_V3", "false")
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.pipeline.v7_extract"):
            del sys.modules[mod_name]
    pkg = importlib.import_module("src.pipeline.v7_extract")
    fn = getattr(pkg, "classify_doc")
    assert callable(fn)
    # v2 classify_doc is sync (not async)
    import inspect
    assert not inspect.iscoroutinefunction(fn), \
        "v2 classify_doc must be sync (heuristic), not async"


def test_legacy_modules_exist():
    """The four _legacy_*.py files must exist as fallback."""
    from src.pipeline.v7_extract import _legacy_doc_classifier
    from src.pipeline.v7_extract import _legacy_completeness_checker
    from src.pipeline.v7_extract import _legacy_topic_clusterer
    from src.pipeline.v7_extract import _legacy_slot_filler
    assert callable(_legacy_doc_classifier.classify_doc)
    assert callable(_legacy_completeness_checker.check_completeness)
    assert callable(_legacy_topic_clusterer.cluster_topics)
    assert callable(_legacy_slot_filler.fill_slots)
