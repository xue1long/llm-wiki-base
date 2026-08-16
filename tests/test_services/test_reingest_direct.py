"""Phase 4.4 tests — src.services.ingest reingest 直跑分支 + pending_deletion 补偿.

计划 C2 P0 加固（plan guidance #3/#4）：
- 每 raw 分支：有 source 页 → reingest_source（cascade_delete 旧产出 + 删向量
  + 重建，直跑 run_ingest，不经队列）；无 source 页 → 首摄分支；
  reingest_source 抛 ValueError（源页被删）→ 走首摄分支而非 failed。
- 删除/重建补偿：重建调度成功 → 记 pending_deletion → cascade_delete →
  记 done；崩溃在删除后、重建前 → 续跑时对 pending_deletion 文件重跑重建；
  禁止"先删后建"裸窗口。

注意：monkeypatch 一律用「显式 import 模块 + setattr(模块, ...)」而非
点路径字符串 —— 兄弟 conftest 级联（SETUP.md §4）下 `src.pipeline.ingest`
等子模块未必已作为属性挂在包命名空间，字符串解析会失败。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.batch_state import (  # noqa: E402
    load_batch_state,
    raw_status,
    set_raw_status,
)
from src.services.ingest import (  # noqa: E402
    probe_source_page,
    reingest_source_direct,
)
from src.wiki.core.types import PageType, WikiPage  # noqa: E402
from src.wiki.storage.ensure import ensure_knowledge_base  # noqa: E402

# 被 patch 的目标模块 —— 显式导入，保证在任意收集顺序下都可 setattr。
import src.pipeline.ingest as _pi_mod  # noqa: E402
import src.services.batch_state as _bs_mod  # noqa: E402
import src.vector.store as _vec_mod  # noqa: E402
import src.wiki.features.cascade_delete as _cd_mod  # noqa: E402


def _mk_source_page(root: Path, raw_rel: str, source_id: str = "src-x") -> None:
    """Write a minimal wiki/sources page referencing raw_rel."""
    d = root / "wiki" / "sources"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{source_id}.md").write_text(
        "---\n"
        f"id: {source_id}\n"
        f"title: 源页\n"
        "type: source\n"
        f"sources:\n- {raw_rel}\n"
        "created_at: 1\n"
        "updated_at: 1\n"
        "---\n\n正文\n", encoding="utf-8")


def _mk_raw(root: Path, raw_rel: str) -> None:
    p = root / raw_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 原始内容\n\n素材正文", encoding="utf-8")


@pytest.fixture
def paths(tmp_path: Path):
    ensure_knowledge_base(tmp_path)
    from src.wiki.core.paths import WikiPaths
    return WikiPaths(tmp_path)


# ── probe_source_page ──────────────────────────────────────────────

def test_probe_finds_source_page(paths) -> None:
    _mk_raw(paths.root, "raw/sources/a.md")
    _mk_source_page(paths.root, "raw/sources/a.md", source_id="src-a")
    assert probe_source_page(paths, "raw/sources/a.md") == "src-a"


def test_probe_returns_none_when_no_source_page(paths) -> None:
    _mk_raw(paths.root, "raw/sources/b.md")
    assert probe_source_page(paths, "raw/sources/b.md") is None


# ── reingest_source_direct 分支 ────────────────────────────────────

async def test_direct_reingest_has_source_page(
    paths, monkeypatch,
) -> None:
    """有 source 页 → cascade_delete + 删向量 + 直跑重建（不经队列）。"""
    _mk_raw(paths.root, "raw/sources/a.md")
    _mk_source_page(paths.root, "raw/sources/a.md", source_id="src-a")

    calls = {"cascade": 0, "delete_vec": 0, "run_ingest": 0, "enqueue": 0}

    async def _fake_run_ingest(*a, **k):
        calls["run_ingest"] += 1
        return [WikiPage(id="new-src", title="新源", type=PageType.SOURCE,
                         sources=["raw/sources/a.md"], body="新正文")]

    def _fake_cascade(paths, sid):
        calls["cascade"] += 1
        return {"deleted_pages": ["src-a"], "updated_pages": []}

    def _fake_delete_by_source(paths, raw):
        calls["delete_vec"] += 1
        return 3

    def _fake_init_vector_store(paths, expected_dim=None):
        return None

    def _fake_enqueue(*a, **k):
        calls["enqueue"] += 1
        return {}

    monkeypatch.setattr(_cd_mod, "cascade_delete", _fake_cascade)
    monkeypatch.setattr(_pi_mod, "run_ingest", _fake_run_ingest)
    monkeypatch.setattr(_vec_mod, "delete_by_source", _fake_delete_by_source)
    monkeypatch.setattr(_vec_mod, "init_vector_store_for_paths", _fake_init_vector_store)

    import src.services.ingest as _svc
    monkeypatch.setattr(_svc, "enqueue_source", _fake_enqueue)

    result = await reingest_source_direct(
        paths, "raw/sources/a.md", provider=object(),
        batch_key="batch_1", task_id="b1",
    )
    assert calls["cascade"] == 1
    assert calls["delete_vec"] == 1
    assert calls["run_ingest"] == 1
    assert calls["enqueue"] == 0          # 直跑不经队列
    assert result["status"] == "done"
    assert result["branch"] == "reingest"
    assert result["cleaned"]["source_id"] == "src-a"
    assert result["cleaned"]["deleted_vectors"] == 3
    # 补偿状态：最终 done
    assert raw_status(load_batch_state(paths), "batch_1", "raw/sources/a.md") == "done"


async def test_direct_reingest_no_source_page_takes_first_ingest(
    paths, monkeypatch,
) -> None:
    """无 source 页 → 走首摄分支（run_ingest 直接首摄），不抛错。"""
    _mk_raw(paths.root, "raw/sources/b.md")
    calls = {"cascade": 0, "run_ingest": 0, "enqueue": 0}

    async def _fake_run_ingest(*a, **k):
        calls["run_ingest"] += 1
        return [WikiPage(id="first-src", title="首摄", type=PageType.SOURCE,
                         sources=["raw/sources/b.md"], body="新正文")]

    def _fake_cascade(*a, **k):
        calls["cascade"] += 1
        return {}

    def _fake_enqueue(*a, **k):
        calls["enqueue"] += 1
        return {}

    monkeypatch.setattr(_cd_mod, "cascade_delete", _fake_cascade)
    monkeypatch.setattr(_pi_mod, "run_ingest", _fake_run_ingest)
    import src.services.ingest as _svc
    monkeypatch.setattr(_svc, "enqueue_source", _fake_enqueue)

    result = await reingest_source_direct(
        paths, "raw/sources/b.md", provider=object(),
        batch_key="batch_1", task_id="b1",
    )
    assert calls["cascade"] == 0          # 无旧产出可删
    assert calls["run_ingest"] == 1
    assert calls["enqueue"] == 0
    assert result["status"] == "done"
    assert result["branch"] == "first_ingest"


async def test_direct_reingest_source_page_deleted_between_probe_and_delete(
    paths, monkeypatch,
) -> None:
    """探到 source 页后、cascade 前被并发删除 → 降级首摄而非 failed。"""
    _mk_raw(paths.root, "raw/sources/c.md")
    _mk_source_page(paths.root, "raw/sources/c.md", source_id="src-c")
    calls = {"run_ingest": 0}

    def _cascade_raises(paths, sid):
        raise FileNotFoundError(f"Source page not found: {sid}")

    async def _fake_run_ingest(*a, **k):
        calls["run_ingest"] += 1
        return [WikiPage(id="src-c2", title="新", type=PageType.SOURCE,
                         sources=["raw/sources/c.md"], body="新正文")]

    monkeypatch.setattr(_cd_mod, "cascade_delete", _cascade_raises)
    monkeypatch.setattr(_pi_mod, "run_ingest", _fake_run_ingest)

    result = await reingest_source_direct(
        paths, "raw/sources/c.md", provider=object(),
        batch_key="batch_1", task_id="b1",
    )
    assert calls["run_ingest"] == 1
    assert result["status"] == "done"
    assert result["branch"] == "first_ingest"
    assert "deleted_between" in result.get("note", "")


# ── pending_deletion 补偿（plan guidance #4）───────────────────────

async def test_pending_deletion_recorded_before_cascade(paths, monkeypatch) -> None:
    """重建调度成功 → 记 pending_deletion → cascade_delete → 记 done。"""
    _mk_raw(paths.root, "raw/sources/d.md")
    _mk_source_page(paths.root, "raw/sources/d.md", source_id="src-d")
    # 单一交错时间线：状态机事件与 cascade/rebuild 事件混排比较相对顺序。
    timeline: list[str] = []

    def _cascade(paths, sid):
        timeline.append("cascade")
        return {"deleted_pages": ["src-d"], "updated_pages": []}

    async def _fake_run_ingest(*a, **k):
        timeline.append("rebuild")
        return [WikiPage(id="new-d", title="新", type=PageType.SOURCE,
                         sources=["raw/sources/d.md"], body="新正文")]

    def _fake_init_vector_store(paths, expected_dim=None):
        return None

    monkeypatch.setattr(_cd_mod, "cascade_delete", _cascade)
    monkeypatch.setattr(_pi_mod, "run_ingest", _fake_run_ingest)
    monkeypatch.setattr(_vec_mod, "init_vector_store_for_paths", _fake_init_vector_store)

    real_set = set_raw_status

    def _spy_set(paths, batch_key, raw_rel, status, **kw):
        timeline.append(f"status:{status}")
        real_set(paths, batch_key, raw_rel, status, **kw)

    monkeypatch.setattr(_bs_mod, "set_raw_status", _spy_set)

    await reingest_source_direct(paths, "raw/sources/d.md", provider=object(),
                                 batch_key="batch_1", task_id="b1")
    # 顺序：pending_deletion → cascade → rebuild → done
    assert timeline.index("status:pending_deletion") < timeline.index("cascade")
    assert timeline.index("status:pending_deletion") < timeline.index("rebuild")
    assert timeline[-1] == "status:done"


async def test_resume_pending_deletion_reruns_rebuild(paths, monkeypatch) -> None:
    """崩溃在删除后、重建前 → 续跑时对 pending_deletion 文件重跑重建。"""
    _mk_raw(paths.root, "raw/sources/e.md")
    # 模拟崩溃后的残留状态：pending_deletion，且 source 页已删（先删后建窗口）
    set_raw_status(paths, "batch_1", "raw/sources/e.md", "pending_deletion")
    calls = {"run_ingest": 0, "cascade": 0}

    async def _fake_run_ingest(*a, **k):
        calls["run_ingest"] += 1
        return [WikiPage(id="resumed-e", title="续跑", type=PageType.SOURCE,
                         sources=["raw/sources/e.md"], body="新正文")]

    def _fake_cascade(*a, **k):
        calls["cascade"] += 1
        return {}

    def _fake_init_vector_store(paths, expected_dim=None):
        return None

    monkeypatch.setattr(_cd_mod, "cascade_delete", _fake_cascade)
    monkeypatch.setattr(_pi_mod, "run_ingest", _fake_run_ingest)
    monkeypatch.setattr(_vec_mod, "init_vector_store_for_paths", _fake_init_vector_store)

    # 续跑：pending_deletion 文件 → 直跑重建（run_ingest 兜底，无队列）
    result = await reingest_source_direct(
        paths, "raw/sources/e.md", provider=object(),
        batch_key="batch_1", task_id="b1", resume_from_pending_deletion=True,
    )
    assert calls["run_ingest"] == 1
    assert result["status"] == "done"
    assert result["branch"] in ("first_ingest", "reingest")
    assert raw_status(load_batch_state(paths), "batch_1", "raw/sources/e.md") == "done"


# ── review I1：续跑必须清理残留向量 ───────────────────────────────

async def test_resume_cleans_stale_vectors(paths, monkeypatch) -> None:
    """崩溃在 cascade 与 delete_by_source 之间 → 续跑（resume 分支）仍删旧向量。"""
    _mk_raw(paths.root, "raw/sources/f.md")
    set_raw_status(paths, "batch_1", "raw/sources/f.md", "pending_deletion")
    calls = {"delete_vec": 0, "init": 0, "run_ingest": 0}

    async def _fake_run_ingest(*a, **k):
        calls["run_ingest"] += 1
        return [WikiPage(id="f2", title="新", type=PageType.SOURCE,
                         sources=["raw/sources/f.md"], body="新正文")]

    def _fake_delete(paths, raw):
        calls["delete_vec"] += 1
        return 2

    def _fake_init(paths, expected_dim=None):
        calls["init"] += 1
        return None

    monkeypatch.setattr(_vec_mod, "delete_by_source", _fake_delete)
    monkeypatch.setattr(_vec_mod, "init_vector_store_for_paths", _fake_init)
    monkeypatch.setattr(_pi_mod, "run_ingest", _fake_run_ingest)

    result = await reingest_source_direct(
        paths, "raw/sources/f.md", provider=object(),
        batch_key="batch_1", task_id="b1", resume_from_pending_deletion=True,
    )
    assert calls["init"] == 1
    assert calls["delete_vec"] == 1          # 旧向量仍被清理（幂等）
    assert calls["run_ingest"] == 1
    assert result["status"] == "done"


# ── review I2：重建失败契约（禁止 pending_deletion 悬空）──────────

async def test_rebuild_failure_marks_failed(paths, monkeypatch) -> None:
    """重建段异常 → 先落 failed 状态再抛（pending_deletion 不悬空）。"""
    _mk_raw(paths.root, "raw/sources/g.md")
    _mk_source_page(paths.root, "raw/sources/g.md", source_id="src-g")
    calls = {"cascade": 0}

    def _fake_cascade(paths, sid):
        calls["cascade"] += 1
        return {"deleted_pages": ["src-g"], "updated_pages": []}

    async def _boom(*a, **k):
        raise RuntimeError("provider down")

    def _fake_init(paths, expected_dim=None):
        return None

    monkeypatch.setattr(_cd_mod, "cascade_delete", _fake_cascade)
    monkeypatch.setattr(_pi_mod, "run_ingest", _boom)
    monkeypatch.setattr(_vec_mod, "init_vector_store_for_paths", _fake_init)

    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="provider down"):
        await reingest_source_direct(
            paths, "raw/sources/g.md", provider=object(),
            batch_key="batch_1", task_id="b1",
        )
    state = load_batch_state(paths)
    assert raw_status(state, "batch_1", "raw/sources/g.md") == "failed"
    assert "provider down" in state["batch_1"]["raw_states"]["raw/sources/g.md"]["last_error"]


async def test_rebuild_missing_raw_marks_permanent_failed(paths, monkeypatch) -> None:
    """raw 文件缺失 → permanent_failed（非瞬态，不重投）。"""
    _mk_raw(paths.root, "raw/sources/h.md")
    _mk_source_page(paths.root, "raw/sources/h.md", source_id="src-h")
    (paths.root / "raw/sources/h.md").unlink()   # raw 被删

    def _fake_cascade(paths, sid):
        return {"deleted_pages": ["src-h"], "updated_pages": []}

    def _fake_init(paths, expected_dim=None):
        return None

    monkeypatch.setattr(_cd_mod, "cascade_delete", _fake_cascade)
    monkeypatch.setattr(_vec_mod, "init_vector_store_for_paths", _fake_init)

    import pytest as _pytest
    with _pytest.raises(FileNotFoundError):
        await reingest_source_direct(
            paths, "raw/sources/h.md", provider=object(),
            batch_key="batch_1", task_id="b1",
        )
    state = load_batch_state(paths)
    assert raw_status(state, "batch_1", "raw/sources/h.md") == "permanent_failed"
