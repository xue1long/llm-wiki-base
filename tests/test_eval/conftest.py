"""Local test config for test_eval/.

A sibling project at ``D:\\5-Project\\2026814\\llm-wiki-base\\src\\`` exposes
its own ``scripts`` regular package via ``sys.path``. Python's FileFinder
prefers the regular package over a namespace-package directory of the same
name, so a plain ``import scripts.kc_eval`` from this repo would resolve
to the sibling by mistake. We therefore remove the sibling's ``src`` entry
from ``sys.path`` for the duration of the test session and ensure our own
repo root sits at the front. Tests import via ``importlib`` (see the
``_kc_eval`` helper in ``test_gold_dataset_schema.py``) for extra safety.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# Move repo root to the front.
if str(_REPO) in sys.path:
    sys.path.remove(str(_REPO))
sys.path.insert(0, str(_REPO))

# Drop any sys.path entry that exposes a sibling ``scripts`` regular package.
# A sibling's ``scripts/__init__.py`` (regular package) wins over our
# namespace-package ``scripts/`` regardless of order, so we excise those
# paths for the test session.
_KEEP = []
for _entry in sys.path:
    candidate = Path(_entry) / "scripts" / "__init__.py"
    if candidate.exists() and Path(_entry) != _REPO:
        # Drop the entry that resolves to a *different* scripts package.
        continue
    _KEEP.append(_entry)
sys.path[:] = _KEEP

# Drop any cached ``scripts`` import that might still point to the sibling.
for _name in [n for n in sys.modules if n == "scripts" or n.startswith("scripts.")]:
    del sys.modules[_name]
