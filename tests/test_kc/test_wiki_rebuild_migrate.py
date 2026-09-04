"""Tests for Wiki rebuild migration script (B-3.5 commit 2).

路线 v2.2 §B-3.5 — spec §17 D-18 + H-2 legacy 兜底 (verified_at = ingestion_unix_ms)
真实迁移脚本. 本测试验证:

1. dryrun=True → 不实际写 frontmatter, 仅打印
2. 已存在 verified_at 的页面 → 跳过 (幂等)
3. dryrun=False → 实际写 frontmatter, sample_migrations 含 5 个 page_id

不在 src/ 业务代码中改任何东西; 仅测试 scripts/kc_wiki_rebuild_migrate.py 的
纯函数输出 + frontmatter 修改行为.

Ref: docs/architecture/B-2_11_Gate_design.md + spec §17 D-18 + H-2 决策.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS_DIR / "kc_wiki_rebuild_migrate.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_migrate_module():
    """通过 importlib 加载 scripts/kc_wiki_rebuild_migrate.py (scripts/ 无 __init__)."""
    mod_name = "kc_wiki_rebuild_migrate"
    spec = importlib.util.spec_from_file_location(mod_name, str(SCRIPT))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_page_with_frontmatter(
    page_id: str,
    workflow_state: str = "draft",
    verified_at: int | None = None,
) -> str:
    """构造 mock markdown 含 verified_at (或不写)."""
    lines = [
        f"id: {page_id}",
        f"title: {page_id}",
        "type: concept",
        f"workflow_state: {workflow_state}",
    ]
    if verified_at is not None:
        lines.append(f"verified_at: {verified_at}")
    body = "\n".join(lines)
    return f"---\n{body}\n---\n\nbody for {page_id}\n"


def _make_project_with_frontmatter(
    root: Path,
    pages_with_state: list[tuple[str, int | None]],
) -> Path:
    """在 root 创建 wiki/concepts/ 含指定 frontmatter pages.

    pages_with_state: list of (page_id, verified_at or None).
    """
    wiki = root / "wiki" / "concepts"
    wiki.mkdir(parents=True)

    for page_id, verified_at in pages_with_state:
        (wiki / f"{page_id}.md").write_text(
            _make_page_with_frontmatter(page_id, verified_at=verified_at),
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# Test 1: dryrun=True → pages_migrated=0 (不实际写入)
# ---------------------------------------------------------------------------
def test_migrate_dryrun_does_not_write_frontmatter(tmp_path: Path) -> None:
    """dryrun=True 时, run_migration 不修改任何 frontmatter.

    注意: pages_migrated 字段在 dryrun 模式下仍然计数 (表示 *将* 迁移的页面),
    但 frontmatter 文件不被修改.

    由于 run_migration 在 dryrun=True 时仍会处理文件, pages_migrated>0;
    关键断言是 frontmatter 文件内容不变.
    """
    mod = _load_migrate_module()
    run_migration = mod.run_migration

    pages = [(f"p{i}", None) for i in range(5)]
    _make_project_with_frontmatter(tmp_path, pages)

    # 记录 mtime + 内容前
    wiki = tmp_path / "wiki" / "concepts"
    md_files = sorted(wiki.glob("*.md"))
    contents_before = {f.name: f.read_text(encoding="utf-8") for f in md_files}

    result = run_migration(
        project_root=tmp_path,
        verified_at_strategy="ingestion_unix_ms",
        dryrun=True,
        max_pages=50,
    )

    # dryrun=True 时 frontmatter 内容不变
    contents_after = {f.name: f.read_text(encoding="utf-8") for f in md_files}
    assert contents_before == contents_after, "dryrun 不应修改 frontmatter"
    # 5 个页面被"识别"为待迁移
    assert result.pages_migrated == 5
    assert result.pages_skipped == 0
    assert result.pages_failed == 0


# ---------------------------------------------------------------------------
# Test 2: 已存在 verified_at → 跳过 (幂等)
# ---------------------------------------------------------------------------
def test_migrate_skips_pages_with_existing_verified_at(tmp_path: Path) -> None:
    """3 个页面已有 verified_at → pages_migrated=0 (幂等, 不重复写入)."""
    mod = _load_migrate_module()
    run_migration = mod.run_migration

    pages = [
        ("p1", 1700000000000),
        ("p2", 1700000001000),
        ("p3", 1700000002000),
    ]
    _make_project_with_frontmatter(tmp_path, pages)

    # 记录原 verified_at
    wiki = tmp_path / "wiki" / "concepts"
    before_verified = {}
    for f in wiki.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        # 解析 verified_at 行
        for line in content.split("\n"):
            if line.startswith("verified_at:"):
                before_verified[f.name] = int(line.split(":", 1)[1].strip())
                break

    result = run_migration(
        project_root=tmp_path,
        verified_at_strategy="ingestion_unix_ms",
        dryrun=False,
        max_pages=50,
    )

    # 全部已有 verified_at → pages_migrated=0 (幂等)
    assert result.pages_migrated == 0
    assert result.pages_skipped == 3
    assert result.pages_failed == 0

    # 验证 verified_at 没变
    after_verified = {}
    for f in wiki.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        for line in content.split("\n"):
            if line.startswith("verified_at:"):
                after_verified[f.name] = int(line.split(":", 1)[1].strip())
                break
    assert before_verified == after_verified, "幂等模式不应修改已有 verified_at"


# ---------------------------------------------------------------------------
# Test 3: dryrun=False → 实际写入, sample_migrations 含 5 page_id
# ---------------------------------------------------------------------------
def test_migrate_writes_verified_at_to_frontmatter(tmp_path: Path) -> None:
    """5 个无 verified_at 页面 + dryrun=False → 实际写入 verified_at."""
    mod = _load_migrate_module()
    run_migration = mod.run_migration

    pages = [(f"p{i}", None) for i in range(5)]
    _make_project_with_frontmatter(tmp_path, pages)

    result = run_migration(
        project_root=tmp_path,
        verified_at_strategy="ingestion_unix_ms",
        dryrun=False,
        max_pages=50,
    )

    assert result.pages_migrated == 5
    assert result.pages_skipped == 0
    # sample_migrations 含 5 个 page_id + verified_at
    assert len(result.sample_migrations) == 5
    for page_id in ["p0", "p1", "p2", "p3", "p4"]:
        assert page_id in result.sample_migrations
        verified_at = result.sample_migrations[page_id]
        assert isinstance(verified_at, int)
        assert verified_at > 0  # Unix ms > 0

    # 验证 frontmatter 实际写入 verified_at
    wiki = tmp_path / "wiki" / "concepts"
    for f in wiki.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        assert "verified_at:" in content, f"{f.name} 应含 verified_at 字段"
