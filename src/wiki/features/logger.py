"""Append-only audit log to wiki/log.md."""
import json
import time
from datetime import datetime
from typing import Optional

from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths


LOG_HEADER = "# Wiki Operation Log\n\n"


def log_event(
    paths: WikiPaths,
    event: str,
    task_id: str,
    detail: str,
    extra: Optional[dict] = None,
) -> None:
    """Append event entry to wiki/log.md.

    Format:
        ## <iso-timestamp>
        - <event>: <task_id> — <detail>
        [optional JSON metadata]
    """
    timestamp = datetime.fromtimestamp(time.time()).isoformat()
    entry_md = f"## {timestamp}\n- **{event}**: `{task_id}` — {detail}\n"
    if extra:
        entry_md += f"  ```json\n  {json.dumps(extra, ensure_ascii=False, indent=2)}\n  ```\n"

    if not paths.llm_wiki_log.exists():
        content = LOG_HEADER
    else:
        content = paths.llm_wiki_log.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
    content += entry_md
    safe_write(paths.llm_wiki_log, content)


def read_log(paths: WikiPaths) -> list[dict]:
    """Parse wiki/log.md → list of event dicts (lightweight parser)."""
    if not paths.llm_wiki_log.exists():
        return []

    events = []
    text = paths.llm_wiki_log.read_text(encoding="utf-8")
    current_timestamp = None
    for line in text.split("\n"):
        if line.startswith("## "):
            current_timestamp = line[3:].strip()
        elif line.startswith("- **") and "**: `" in line:
            try:
                rest = line.split("- **", 1)[1]
                event, rest = rest.split("**: `", 1)
                task_id, detail = rest.split("` — ", 1)
                events.append({
                    "timestamp": current_timestamp,
                    "event": event.strip(),
                    "task_id": task_id.strip(),
                    "detail": detail.strip(),
                })
            except ValueError:
                continue
    return events
