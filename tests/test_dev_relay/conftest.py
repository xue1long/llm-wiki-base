"""Local test config for test_dev_relay/.

Adds the repo root to sys.path AND strips the sibling repo's src/ from
sys.path. The sibling `D:\\5-Project\\2026814\\llm-wiki-base` repo is
editable-installed as `ruflo-kb` (so its `src/scripts/__init__.py` ends up
on sys.path), and Python prefers the on-disk package over our namespace
package — without this strip our `scripts.kc_check_delivery_report` import
gets blocked.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Remove sibling repo's src/ from sys.path (must be done BEFORE any
# `import scripts.*` so our namespace package is picked up instead).
_SIBLING_SRC_CANDIDATES = [
    "D:\\5-Project\\2026814\\llm-wiki-base\\src",
    "D:/5-Project/2026814/llm-wiki-base/src",
]
sys.path[:] = [p for p in sys.path if p not in _SIBLING_SRC_CANDIDATES]