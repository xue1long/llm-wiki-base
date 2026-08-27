"""Book 重建真实迁移 (B-3.6 commit 2, spec §17 D-18 + H-2 legacy 兜底).

本脚本会**修改 Book Chapter frontmatter** (verified_at 字段), 比 dry-run 风险高.
- 默认 dryrun=True 模式: 仅打印, 不写入
- dryrun=False 模式: 实际写入 (需 --confirm 二次确认)
- 幂等: 已存在 verified_at 的章节跳过

CLI:
    # 二次确认执行 (实际写入)
    PYTHONPATH=. python scripts/kc_book_rebuild_migrate.py \\
        --project-root <path> --confirm --strategy ingestion_unix_ms

    # dry-run 模式 (仅打印, 默认)
    PYTHONPATH=. python scripts/kc_book_rebuild_migrate.py \\
        --project-root <path> --dryrun --strategy ingestion_unix_ms

策略:
- ingestion_unix_ms: 文件 mtime (H-2 决策, 机械化 backfill)
- now: 当前时间 (int(time.time() * 1000))

审计:
- .index/book_migration.log append-only JSONL (每次实际执行一条记录)

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
class BookMigrateResult:
    """Book 迁移结果.

    Attributes:
        project_root:        项目根路径
        books_migrated:      实际写入 verified_at 的 Book 数
        chapters_migrated:   实际写入 verified_at 的章节数
        chapters_skipped:    跳过的章节数 (无 frontmatter / 已 verified_at / 解析失败)
        chapters_failed:     失败的章节数
        sample_migrations:   chapter_path → verified_at_unix_ms (前 5 个样本)
        duration_seconds:    总耗时 (秒)
        log_path:            审计日志路径 (.index/book_migration.log)
    """

    project_root: Path
    books_migrated: int
    chapters_migrated: int
    chapters_skipped: int
    chapters_failed: int
    sample_migrations: dict[str, int]
    duration_seconds: float
    log_path: Path


def run_migration(
    project_root: Path,
    verified_at_strategy: str = "ingestion_unix_ms",
    dryrun: bool = False,
    max_books: int = 5,
) -> BookMigrateResult:
    """真实迁移 Book Chapter frontmatter verified_at 字段.

    Args:
        project_root:           项目根路径 (含 knowledge/books/ 或 books/ 子目录)
        verified_at_strategy:   "ingestion_unix_ms" (文件 mtime) | "now" (当前时间)
        dryrun:                 True = 仅打印不写入; False = 实际写入 (需 --confirm)
        max_books:              扫描 Book 数上限 (避免大数据集超时)

    Returns:
        BookMigrateResult 含迁移统计 + sample_migrations + log_path

    Notes:
        - H-2 决策: legacy 兜底 = verified_at = ingestion_unix_ms (文件 mtime)
        - 幂等: 已存在 verified_at 的章节跳过 (--rerun 安全)
        - 审计: 每次实际执行追加 1 条 JSONL 到 .index/book_migration.log
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        yaml = None  # type: ignore[assignment]

    # 扫描 Book 目录 (尝试多个可能位置)
    book_dirs = [
        project_root / "knowledge" / "books",
        project_root / "books",
        project_root / "book",
    ]
    book_dir = None
    for candidate in book_dirs:
        if candidate.exists():
            book_dir = candidate
            break

    if book_dir is None:
        return BookMigrateResult(
            project_root=project_root,
            books_migrated=0,
            chapters_migrated=0,
            chapters_skipped=0,
            chapters_failed=0,
            sample_migrations={},
            duration_seconds=0.0,
            log_path=project_root / ".index" / "book_migration.log",
        )

    start_time = time.time()
    log_path = project_root / ".index" / "book_migration.log"

    books_migrated = 0
    chapters_migrated = 0
    chapters_skipped = 0
    chapters_failed = 0
    sample_migrations: dict[str, int] = {}
    book_set: set[str] = set()

    md_files = sorted(book_dir.rglob("*.md"))[:max_books * 50]  # 上限避免超时

    for md_file in md_files:
        book_set.add(md_file.parent.name)

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            chapters_failed += 1
            continue

        # 解析 frontmatter (必须以 --- 开头且有闭合 ---)
        if not content.startswith("---"):
            chapters_skipped += 1
            continue
        end = content.find("\n---", 4)
        if end < 0:
            chapters_skipped += 1
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
                chapters_failed += 1
                continue
            if not isinstance(fm, dict):
                chapters_failed += 1
                continue
            existing_verified = fm.get("verified_at") if "verified_at" in fm else None

        # 幂等检查
        if existing_verified is not None:
            chapters_skipped += 1
            continue

        # 计算 verified_at
        if verified_at_strategy == "ingestion_unix_ms":
            try:
                verified_at = int(md_file.stat().st_mtime * 1000)
            except Exception:
                chapters_failed += 1
                continue
        elif verified_at_strategy == "now":
            verified_at = int(time.time() * 1000)
        else:
            chapters_failed += 1
            continue

        # 写回 frontmatter
        if not dryrun:
            if yaml is None:
                # 无 yaml 依赖时, 只在 frontmatter 末尾追加 verified_at (简化)
                fm_lines = content[4:end].split("\n")
                new_fm_text = "\n".join(fm_lines) + f"\nverified_at: {verified_at}\n"
                new_content = f"---\n{new_fm_text}---\n{content[end+4:]}"
            else:
                fm["verified_at"] = verified_at  # type: ignore[index]
                new_fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
                new_content = f"---\n{new_fm_text}---\n{content[end+4:]}"
            try:
                md_file.write_text(new_content, encoding="utf-8")
            except Exception:
                chapters_failed += 1
                continue

        chapters_migrated += 1
        if len(sample_migrations) < 5:
            sample_migrations[str(md_file)] = verified_at

    # 实际写入时, books_migrated = 含已迁移章节的 Book 数
    books_migrated = len(book_set) if chapters_migrated > 0 else 0
    duration = time.time() - start_time

    # 写 .index/book_migration.log (append-only JSONL, 仅非 dryrun 模式)
    if not dryrun:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": int(time.time() * 1000),
            "action": "book_migration",
            "strategy": verified_at_strategy,
            "dryrun": False,
            "books_migrated": books_migrated,
            "chapters_migrated": chapters_migrated,
            "chapters_skipped": chapters_skipped,
            "chapters_failed": chapters_failed,
            "duration_seconds": duration,
        }
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # pragma: no cover
            pass

    return BookMigrateResult(
        project_root=project_root,
        books_migrated=books_migrated,
        chapters_migrated=chapters_migrated,
        chapters_skipped=chapters_skipped,
        chapters_failed=chapters_failed,
        sample_migrations=sample_migrations,
        duration_seconds=duration,
        log_path=log_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Book rebuild migration (B-3.6 commit 2)")
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
    parser.add_argument("--max-books", type=int, default=5)
    args = parser.parse_args()

    if not args.dryrun and not args.confirm:
        print("ERROR: 需 --dryrun 或 --confirm 参数二次确认")
        print("提示: 30 天过渡期 (B-3 commit 3) 后执行 migrate")
        print("  --dryrun:  仅打印, 不写入 (推荐先用此验证)")
        print("  --confirm: 实际写入 frontmatter (修改 Book Chapter, 风险较高)")
        return 1

    if args.dryrun and args.confirm:
        print("ERROR: --dryrun 与 --confirm 互斥, 二选一")
        return 1

    dryrun = not args.confirm  # --dryrun 时 dryrun=True, --confirm 时 dryrun=False

    result = run_migration(
        project_root=args.project_root,
        verified_at_strategy=args.strategy,
        dryrun=dryrun,
        max_books=args.max_books,
    )

    print(json.dumps({
        "books_migrated": result.books_migrated,
        "chapters_migrated": result.chapters_migrated,
        "chapters_skipped": result.chapters_skipped,
        "chapters_failed": result.chapters_failed,
        "sample_migrations": result.sample_migrations,
        "duration_seconds": result.duration_seconds,
        "log_path": str(result.log_path),
    }, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())