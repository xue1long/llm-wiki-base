from pathlib import Path

from src.services.batch_state import update_raw_fail_streak
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


def test_fail_streak_read_modify_write_is_atomic(tmp_path: Path) -> None:
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    for _ in range(3):
        update_raw_fail_streak(paths, "batch_0", "raw/a.md", "failed")

    from src.services.batch_state import load_batch_state
    entry = load_batch_state(paths)["batch_0"]["raw_states"]["raw/a.md"]
    assert entry["fail_streak"] == 3
    assert entry["blocklisted"] is True
