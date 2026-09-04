"""Phase 4.4 tests — src.services.batch_state 统一 batch_build_state.json 读写。

计划 H① 落点：三写者（services/ingest.py / services/files.py / executor）
统一 schema + 文件锁，杜绝并发写丢失更新。

验收：
- schema_version 字段写入；读端容忍缺失/损坏文件
- 写锁（跨进程）：持锁期间另一写者阻塞，成功后读到最新值
- set_raw_status / raw_status 每 raw 状态机助手（pending/in_progress/done/
  failed/permanent_failed/pending_deletion 为 Phase 4 正式枚举）
- 原子写：tmp + os.replace，不留半写文件
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.batch_state import (  # noqa: E402
    SCHEMA_VERSION,
    load_batch_state,
    save_batch_state,
    set_raw_status,
    raw_status,
    batch_state_path,
    BATCH_STATUSES,
)

VALID_STATUSES = {"pending", "in_progress", "done", "failed",
                  "permanent_failed", "pending_deletion", "partial_commit"}


@pytest.fixture
def paths(tmp_path: Path):
    from src.wiki.core.paths import WikiPaths
    return WikiPaths(tmp_path)


def test_schema_version_written(paths) -> None:
    save_batch_state(paths, {"batch_0": {"status": "done"}})
    data = json.loads(batch_state_path(paths).read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION


def test_load_missing_file_returns_empty(paths) -> None:
    assert load_batch_state(paths) == {}


def test_load_corrupt_file_returns_empty(paths) -> None:
    batch_state_path(paths).parent.mkdir(parents=True, exist_ok=True)
    batch_state_path(paths).write_text("{ not json !", encoding="utf-8")
    assert load_batch_state(paths) == {}


def test_roundtrip_preserves_state(paths) -> None:
    save_batch_state(paths, {"batch_0": {"status": "in_progress", "files": ["a.md"]}})
    state = load_batch_state(paths)
    assert state["batch_0"]["status"] == "in_progress"
    assert state["batch_0"]["files"] == ["a.md"]


def test_set_and_read_raw_status(paths) -> None:
    set_raw_status(paths, "batch_0", "raw/sources/a.md", "pending_deletion",
                   round=1)
    assert raw_status(load_batch_state(paths), "batch_0", "raw/sources/a.md") == "pending_deletion"
    # 更新同 raw 状态
    set_raw_status(paths, "batch_0", "raw/sources/a.md", "done")
    assert raw_status(load_batch_state(paths), "batch_0", "raw/sources/a.md") == "done"


def test_raw_status_defaults_to_pending(paths) -> None:
    assert raw_status(load_batch_state(paths), "batch_0", "raw/sources/a.md") == "pending"


def test_set_raw_status_preserves_other_raws(paths) -> None:
    set_raw_status(paths, "batch_0", "raw/sources/a.md", "done")
    set_raw_status(paths, "batch_0", "raw/sources/b.md", "failed")
    state = load_batch_state(paths)
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "done"
    assert raw_status(state, "batch_0", "raw/sources/b.md") == "failed"


def test_set_raw_status_preserves_batch_level_fields(paths) -> None:
    save_batch_state(paths, {"batch_0": {"status": "in_progress", "gate": "pending_gate"}})
    set_raw_status(paths, "batch_0", "raw/sources/a.md", "done")
    state = load_batch_state(paths)
    assert state["batch_0"]["gate"] == "pending_gate"
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "done"


def test_batch_statuses_enum_matches_plan(paths) -> None:
    """Phase 4 正式每 raw 状态机枚举（plan guidance #2，pending_deletion 并入）。"""
    assert set(BATCH_STATUSES) == VALID_STATUSES


def test_concurrent_writers_no_lost_update(paths) -> None:
    """两个线程并发 set_raw_status 不同 raw —— 最终两者都在（锁防丢失更新）。"""
    errors: list[Exception] = []

    def writer(raw: str) -> None:
        try:
            for _ in range(5):
                set_raw_status(paths, "batch_0", raw, "done")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    ts = [threading.Thread(target=writer, args=(f"raw/sources/f{i}.md",))
          for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    state = load_batch_state(paths)
    for i in range(4):
        assert raw_status(state, "batch_0", f"raw/sources/f{i}.md") == "done"


def test_subprocess_lock_blocks_while_held(paths) -> None:
    """跨进程锁：主进程持锁时子进程写必须等待；释放后子进程写入成功。"""
    from src.services.batch_state import batch_state_lock

    batch_state_path(paths).parent.mkdir(parents=True, exist_ok=True)

    holder = batch_state_lock(paths)
    holder.acquire()
    try:
        # 子进程尝试持锁写入 —— 必须阻塞；用短超时探测"确实在等"
        code = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "from pathlib import Path\n"
            "from src.wiki.core.paths import WikiPaths\n"
            "from src.services.batch_state import batch_state_lock, save_batch_state\n"
            "p = WikiPaths(Path(%r))\n"
            "lk = batch_state_lock(p)\n"
            "lk.acquire()\n"
            "try:\n"
            "    save_batch_state(p, {'batch_9': {'status': 'done'}})\n"
            "finally:\n"
            "    lk.release()\n"
            "print('written')\n"
        ) % (str(paths.root),)
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        # 持锁 0.8s 内子进程不应完成
        try:
            out, _ = proc.communicate(timeout=0.8)
            raise AssertionError(
                f"subprocess finished while lock held: {out!r}")
        except subprocess.TimeoutExpired:
            pass
    finally:
        holder.release()

    out, err = proc.communicate(timeout=20)
    assert proc.returncode == 0, err
    assert "written" in out
    state = load_batch_state(paths)
    assert raw_status(state, "batch_9", "x") == "pending"
    assert state["batch_9"]["status"] == "done"
