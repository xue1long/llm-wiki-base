"""Wiki 重建真实迁移 (B-3.5 commit 2, spec §17 D-18 + H-2 legacy 兜底).

本脚本会**修改 WikiPage frontmatter** (verified_at 字段), 比 dry-run 风险高.
- 默认 dryrun=False 模式: 需 --confirm 二次确认才写
- dryrun=True 模式 (--dryrun 或无 --confirm): 仅打印, 不写入
- 幂等: 已存在 verified_at 的页面跳过

CLI:
    # 二次确认执行 (实际写入)
    PYTHONPATH=. python scripts/kc_wiki_rebuild_migrate.py \\
        --project-root <path> --confirm --strategy ingestion_unix_ms

    # dry-run 模式 (仅打印)
    PYTHONPATH=. python scripts/kc_wiki_rebuild_migrate.py \\
        --project-root <path> --dryrun --strategy ingestion_unix_ms

策略:
- ingestion_unix_ms: 文件 mtime (H-2 决策, 机械化 backfill)
- now: 当前时间 (int(time.time() * 1000))

审计:
- .index/wiki_migration.log append-only JSONL (每次执行一条记录)

Ref: docs/architecture/B-2_11_Gate_design.md + spec §17 D-18 + H-2 决策.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass


@dataclass(frozen=True)
class WikiMigrateResult:
    """Wiki 迁移结果.

    Attributes:
        project_root:       项目根路径
        pages_migrated:      实际写入 verified_at 的页面数
        pages_skipped:       跳过的页面数 (无 frontmatter / 已 verified_at / 解析失败)
        pages_failed:        失败的页面数
        sample_migrations:   page_id → verified_at_unix_ms (前 5 个样本)
        duration_seconds:    总耗时 (秒)
        log_path:            审计日志路径 (.index/wiki_migration.log)
    """

    project_root: Path
    pages_migrated: int
    pages_skipped: int
    pages_failed: int
    sample_migrations: dict[str, int]
    duration_seconds: float
    log_path: Path


def run_migration(
    project_root: Path,
    verified_at_strategy: str = "ingestion_unix_ms",
    dryrun: bool = False,
    max_pages: int = 4892,
) -> WikiMigrateResult:
    """真实迁移 WikiPage frontmatter verified_at 字段.

    Args:
        project_root:           项目根路径 (含 wiki/ 子目录)
        verified_at_strategy:   "ingestion_unix_ms" (文件 mtime) | "now" (当前时间)
        dryrun:                 True = 仅打印不写入; False = 实际写入 (需 --confirm)
        max_pages:              扫描上限 (默认 4892 = novel-wiki 全量)

    Returns:
        WikiMigrateResult 含迁移统计 + sample_migrations + log_path

    Notes:
        - H-2 决策: legacy 兜底 = verified_at = ingestion_unix_ms (文件 mtime)
        - 幂等: 已存在 verified_at 的页面跳过 (--rerun 安全)
        - 审计: 每次执行追加 1 条 JSONL 到 .index/wiki_migration.log
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        yaml = None  # type: ignore[assignment]

    wiki_dir = project_root / "wiki"
    md_files: list[Path] = []
    if wiki_dir.is_dir():
        md_files = sorted(wiki_dir.rglob("*.md"))[:max_pages]

    start_time = time.time()
    log_path = project_root / ".index" / "wiki_migration.log"

    pages_migrated = 0
    pages_skipped = 0
    pages_failed = 0
    sample_migrations: dict[str, int] = {}

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            pages_failed += 1
            continue

        # 解析 frontmatter (必须以 --- 开头且有闭合 ---)
        if not content.startswith("---"):
            pages_skipped += 1
            continue
        end = content.find("\n---", 4)
        if end < 0:
            pages_skipped += 1
            continue

        if yaml is None:
            # 无 yaml 依赖 → 用 regex 退化解析 (只读 verified_at 字段)
            fm_text = content[4:end]
            existing_verified = None
            for line in fm_text.split("\n"):
                if line.startswith("verified_at:"):
                    val = line.split(":", 1)[1].strip()
                    try:
                        existing_verified = int(val)
                    except ValueError:
                        existing_verified = None
                    break
            fm: dict[str, Any] | None = None  # type: ignore[assignment]
        else:
            try:
                fm = yaml.safe_load(content[4:end]) or {}
            except Exception:
                pages_failed += 1
                continue
            if not isinstance(fm, dict):
                pages_failed += 1
                continue
            existing_verified = fm.get("verified_at") if "verified_at" in fm else None

        # 幂等检查
        if existing_verified is not None:
            pages_skipped += 1
            continue

        # 计算 verified_at
        if verified_at_strategy == "ingestion_unix_ms":
            try:
                verified_at = int(md_file.stat().st_mtime * 1000)
            except Exception:
                pages_failed += 1
                continue
        elif verified_at_strategy == "now":
            verified_at = int(time.time() * 1000)
        else:
            pages_failed += 1
            continue

        # 写回 frontmatter
        if not dryrun:
            if yaml is None:
                # 无 yaml 依赖时, 只在 frontmatter 末尾追加 verified_at (简化)
                # 不破坏原有内容 (无 YAML 重排)
                fm_lines = content[4:end].split("\n")
                # 找到最后一个非空行后追加
                new_fm_text = "\n".join(fm_lines) + f"\nverified_at: {verified_at}\n"
                new_content = f"---\n{new_fm_text}---\n{content[end+4:]}"
            else:
                fm["verified_at"] = verified_at  # type: ignore[index]
                new_fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
                new_content = f"---\n{new_fm_text}---\n{content[end+4:]}"
            try:
                md_file.write_text(new_content, encoding="utf-8")
            except Exception:
                pages_failed += 1
                continue

        pages_migrated += 1
        if len(sample_migrations) < 5:
            sample_migrations[md_file.stem] = verified_at

    duration = time.time() - start_time

    # 写 .index/wiki_migration.log (append-only JSONL, 仅非 dryrun 模式)
    if not dryrun:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": int(time.time() * 1000),
            "action": "wiki_migration",
            "strategy": verified_at_strategy,
            "dryrun": False,
            "pages_migrated": pages_migrated,
            "pages_skipped": pages_skipped,
            "pages_failed": pages_failed,
            "duration_seconds": duration,
        }
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # pragma: no cover
            pass

    return WikiMigrateResult(
        project_root=project_root,
        pages_migrated=pages_migrated,
        pages_skipped=pages_skipped,
        pages_failed=pages_failed,
        sample_migrations=sample_migrations,
        duration_seconds=duration,
        log_path=log_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Wiki rebuild migration (B-3.5 commit 2)")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--strategy",
        choices=["ingestion_unix_ms", "now"],
        default="ingestion_unix_ms",
        help="verified_at 字段策略 (H-2 决策: ingestion_unix_ms = 文件 mtime)",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="仅打印不写入 (默认模式, 无 --confirm 时)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="二次确认实际写入 (与 --dryrun 互斥)",
    )
    parser.add_argument("--max-pages", type=int, default=4892)
    args = parser.parse_args()

    if not args.dryrun and not args.confirm:
        print("ERROR: 需 --dryrun 或 --confirm 参数二次确认")
        print("提示: 30 天过渡期 (B-3 commit 3) 后执行 migrate")
        print("  --dryrun:  仅打印, 不写入 (推荐先用此验证)")
        print("  --confirm: 实际写入 frontmatter (修改 WikiPage, 风险较高)")
        return 1

    if args.dryrun and args.confirm:
        print("ERROR: --dryrun 与 --confirm 互斥, 二选一")
        return 1

    dryrun = not args.confirm  # --dryrun 时 dryrun=True, --confirm 时 dryrun=False

    result = run_migration(
        project_root=args.project_root,
        verified_at_strategy=args.strategy,
        dryrun=dryrun,
        max_pages=args.max_pages,
    )

    print(json.dumps({
        "pages_migrated": result.pages_migrated,
        "pages_skipped": result.pages_skipped,
        "pages_failed": result.pages_failed,
        "sample_migrations": result.sample_migrations,
        "duration_seconds": result.duration_seconds,
        "log_path": str(result.log_path),
    }, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())