"""0.5.3: stub-entity cap — default tightened to 3, env override still wins.

Regression coverage for ``_get_max_stubs_per_ingest`` (src/pipeline/ingest.py):
  - with the env var unset the default cap is 3 (tightened from 10 to limit
    stub pollution);
  - ``RUFLO_MAX_STUBS_PER_INGEST`` still overrides the default at call time.
"""
from src.pipeline.ingest import _MAX_STUBS_ENV, _get_max_stubs_per_ingest


def test_default_max_stubs_is_3(monkeypatch):
    """Env var unset -> default cap of 3."""
    monkeypatch.delenv(_MAX_STUBS_ENV, raising=False)
    assert _get_max_stubs_per_ingest() == 3


def test_env_override_max_stubs(monkeypatch):
    """RUFLO_MAX_STUBS_PER_INGEST=7 overrides the default cap."""
    monkeypatch.setenv(_MAX_STUBS_ENV, "7")
    assert _get_max_stubs_per_ingest() == 7
