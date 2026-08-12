from __future__ import annotations

import time
from pathlib import Path


def log_message(message: str, report: str | Path) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with Path(report).open("a", encoding="utf-8") as file:
        file.write(line + "\n")
