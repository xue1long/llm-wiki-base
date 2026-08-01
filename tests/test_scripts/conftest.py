"""Shared fixtures for tests/test_scripts/.

Importing ``scripts.batch_build`` executes module-level code: it inserts the
repo root into ``sys.path`` (so ``src`` resolves) and lazily loads dotenv —
both are wrapped defensively in the script. This conftest ensures the repo
root is importable even if the suite runs without PYTHONPATH=, and documents
that the scripts' own import-time side effects are intentional and harmless.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
