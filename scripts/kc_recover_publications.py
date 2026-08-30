"""Retry staged KC bundles and publish those whose vectors are ready."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.kc.mainline import recover_staged_bundles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    reports = asyncio.run(recover_staged_bundles(args.project_root))
    print(json.dumps([report.__dict__ | {"manifest_path": None} for report in reports], ensure_ascii=False))
    return 0 if all(report.status == "published" for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
