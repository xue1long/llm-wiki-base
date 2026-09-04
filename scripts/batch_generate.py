"""batch_generate.py — Phase 4 并行生成阶段（零磁盘写，产物缓存）。

与 ``batch_commit.py`` 配合，将原 ``batch_executor.py`` 的三步（generate →
gate → commit）拆为：
  1. ``batch_generate.py`` 并行生成多个批次（LLM 调用最耗时部分），把
     ``(pages, extras, meta, raw_header)`` 序列化到 ``.index/generated_cache/``
  2. ``batch_commit.py`` 串行消费缓存，执行门禁 + 写盘 + 复核 + 预算

设计动机（并行子代理方案）：
- 多批并行 LLM 生成是安全的：generate_ingest 本身零磁盘写，不触碰 wiki/
  与 .index/batch_build_state.json；
- commit 保持串行，避免 index.md 并发读改写损坏 / 门禁互相误判断链；
- 缓存 JSON 使生成与提交解耦，中断后可分别续跑。

用法::

    # 并行生成 batch 3、4、5（默认每批内 concurrency=3，批间并行）
    PYTHONPATH=. python scripts/batch_generate.py --root knowledge/novel-wiki --batches 3-5

    # 指定批内并发与批间并发
    PYTHONPATH=. python scripts/batch_generate.py --root knowledge/novel-wiki \
        --batches 3,4,5 --concurrency 3 --batch-concurrency 3

    # 测试（离线 fake 生成）
    RUFLO_EXECUTOR_FAKE_GENERATE=1 PYTHONPATH=. python scripts/batch_generate.py \
        --root <test_root> --batches 0 --concurrency 2

退出码：
  0  全部成功（或全部已有缓存）
  1  参数/缓存 IO 错误
  2  部分 raw 生成失败（缓存已落盘，可重新运行重试失败项）
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.core.types import WikiPage  # noqa: E402

DEFAULT_MANIFEST = ".index/reingest_plan.json"
DEFAULT_CACHE_DIR = ".index/generated_cache"
DEFAULT_CONCURRENCY = 3
DEFAULT_BATCH_CONCURRENCY = 3
CACHE_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Cache serialization
# ---------------------------------------------------------------------------

def _page_to_dict(page: WikiPage) -> dict:
    """WikiPage → JSON-safe dict（body 与 frontmatter 分开，from_dict 兼容）。"""
    fm = page.to_frontmatter_dict()
    # from_dict 不消费 _ko_extra，但 to_frontmatter_dict 会输出；保留无妨。
    return {"page": fm, "body": page.body or ""}


def _page_from_dict(d: dict) -> WikiPage:
    page = WikiPage.from_dict(d["page"], body=d.get("body", ""))
    ko = d.get("page", {}).get("_ko_extra")
    if ko is not None:
        page._ko_extra = ko
    return page


def _meta_to_cache(meta: dict | None) -> dict:
    """meta → JSON-safe 子集。

    commit_ingest 只需要 ``missing_slugs``；其余字段保留为可序列化快照。
    ``analysis`` 是 dataclass 不可直接 JSON，跳过。
    """
    if not meta:
        return {}
    safe = {}
    for k, v in meta.items():
        if k == "analysis":
            continue
        try:
            json.dumps(v, ensure_ascii=False)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = str(v)[:2000]
    return safe


def cache_path_for(root: Path, batch_no: int, cache_dir: str = DEFAULT_CACHE_DIR) -> Path:
    return Path(root) / cache_dir / f"batch_{batch_no}.json"


def load_cache(root: Path, batch_no: int, cache_dir: str = DEFAULT_CACHE_DIR) -> dict | None:
    p = cache_path_for(root, batch_no, cache_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _json_default(obj):
    """json.dumps fallback for V5 datetimes.

    WikiPage.to_frontmatter_dict renders created_at/updated_at as ISO
    datetime objects (V5). Serialize them to ISO strings here; on read,
    WikiPage.from_dict coerces the ISO string back to Unix ms via
    _coerce_ts_ms, so the cache round-trips cleanly.
    """
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_cache(root: Path, batch_no: int, payload: dict,
               cache_dir: str = DEFAULT_CACHE_DIR) -> None:
    p = cache_path_for(root, batch_no, cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                              default=_json_default),
                   encoding="utf-8")
    os.replace(str(tmp), str(p))


# ---------------------------------------------------------------------------
# Fake / real generation (same contract as batch_executor._generate_raw)
# ---------------------------------------------------------------------------

def _is_fake_mode() -> bool:
    return os.environ.get("RUFLO_EXECUTOR_FAKE_GENERATE") == "1"


def _fake_generate(raw_rel: str) -> tuple[list, list, dict]:
    """离线确定性生成（RUFLO_EXECUTOR_FAKE_GENERATE=1）——测试专用。

    batch_executor._fake_generate 返回 ``list[WikiPage]``；此处包装为
    generate_ingest 的 ``(pages, extras, meta)`` 契约。
    """
    from src.orchestrator.batch_runner import _fake_generate as _exec_fake
    pages = _exec_fake(raw_rel)
    return pages, [], {"fake": True}


async def _generate_one(paths, provider, raw_rel: str, batch_no: int,
                        concurrency: int) -> dict:
    """生成单个 raw，返回 cache entry dict。"""
    from src.orchestrator.batch_runner import _is_immutable_source

    entry: dict = {"raw": raw_rel, "status": "generated", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        if _is_immutable_source(paths, raw_rel):
            entry["status"] = "skipped_immutable"
            entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            return entry

        if _is_fake_mode():
            pages, extras, meta = _fake_generate(raw_rel)
        else:
            from src.pipeline.ingest import generate_ingest
            src = paths.root / raw_rel
            text = src.read_text(encoding="utf-8", errors="replace")
            task_id = f"b{batch_no}-{Path(raw_rel).stem[:30]}"
            pages, extras, meta = await generate_ingest(
                paths=paths, source_path=Path(raw_rel), source_text=text,
                provider=provider, task_id=task_id,
            )
        header = ""
        try:
            header = (paths.root / raw_rel).read_text(
                encoding="utf-8", errors="replace")[:4000]
        except OSError:
            pass
        entry.update({
            "pages": [_page_to_dict(p) for p in pages],
            "extras": [_page_to_dict(p) for p in extras],
            "meta": _meta_to_cache(meta),
            "raw_header": header,
        })
        return entry
    except Exception as exc:
        from src.pipeline.retry import PermanentFailure
        if isinstance(exc, PermanentFailure):
            entry["status"] = "permanent_failed"
        else:
            entry["status"] = "failed"
        entry["error"] = str(exc)
        print(f"  [generate-fail] {raw_rel}: {exc}", flush=True)
        return entry


async def _generate_batch(paths, provider, batch: dict, concurrency: int) -> dict:
    """生成单个批次的全部 raw，返回 cache payload dict。"""
    batch_no = batch["batch_no"]
    files = batch["files"]
    sem = asyncio.Semaphore(concurrency)

    async def _locked(raw: str) -> dict:
        async with sem:
            return await _generate_one(paths, provider, raw, batch_no, concurrency)

    entries = await asyncio.gather(*(_locked(r) for r in files))
    by_raw = {e["raw"]: e for e in entries}
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "batch": batch_no,
        "theme": batch.get("theme", "?"),
        "files": [by_raw[r] for r in files],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _resolve_paths(args) -> WikiPaths:
    if getattr(args, "root", None):
        return WikiPaths(Path(args.root))
    from src.pipeline import _resolve_wiki_paths
    return _resolve_wiki_paths(args.project)


def _resolve_provider(args):
    """真实模式 provider 解析；fake 模式不需要。"""
    from src.pipeline import _get_provider
    if _is_fake_mode():
        return None
    return _get_provider(getattr(args, "project", None))


def _parse_batches(text: str) -> list[int]:
    """'3,4,5' / '3-5' / '3' → [3,4,5]。"""
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            if a > b:
                a, b = b, a
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


async def _run_generate(args) -> int:
    paths = _resolve_paths(args)
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = paths.root / manifest
    if not manifest.exists():
        print(f"manifest missing: {manifest}", flush=True)
        return 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    batches = {b["batch_no"]: b for b in data["batches"]}
    targets = _parse_batches(args.batches)
    missing = [n for n in targets if n not in batches]
    if missing:
        print(f"batches not found: {missing}", flush=True)
        return 1

    provider = _resolve_provider(args)
    batch_concurrency = min(args.batch_concurrency, len(targets)) or 1

    async def _gen_batch_locked(batch_no: int) -> dict:
        # 已有缓存时：
        # - 全部成功/跳过 → 跳过（幂等）
        # - 有失败项 → 保留成功项，只重试 failed/permanent_failed（--force 全量重跑）
        existing = load_cache(paths.root, batch_no, args.cache_dir)
        if existing and not args.force:
            entries = existing.get("files", [])
            if entries and all(e.get("status") in ("generated", "skipped_immutable")
                               for e in entries):
                print(f"SKIP cached batch {batch_no} ({len(entries)} file(s))",
                      flush=True)
                return existing
            if entries:
                retry_raws = {
                    e["raw"] for e in entries
                    if e.get("status") in ("failed", "permanent_failed")
                }
                print(f"RERUN batch {batch_no}: {len(retry_raws)} failed raw(s) "
                      f"will be retried", flush=True)

        print(f"generate batch {batch_no} "
              f"[{batches[batch_no].get('theme', '?')}]: "
              f"{len(batches[batch_no]['files'])} file(s)", flush=True)

        # 部分重试：加载旧缓存成功项，仅重新生成缺失/失败项
        old_by_raw = {}
        if existing and not args.force:
            old_by_raw = {e["raw"]: e for e in existing.get("files", [])}

        async def _gen_merge(raw: str) -> dict:
            old = old_by_raw.get(raw)
            if old and old.get("status") in ("generated", "skipped_immutable"):
                return old
            return await _generate_one(paths, provider, raw, batch_no,
                                       args.concurrency)

        sem = asyncio.Semaphore(args.concurrency)

        async def _locked(raw: str) -> dict:
            async with sem:
                return await _gen_merge(raw)

        merged_entries = await asyncio.gather(
            *(_locked(r) for r in batches[batch_no]["files"]))
        by_raw = {e["raw"]: e for e in merged_entries}
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "batch": batch_no,
            "theme": batches[batch_no].get("theme", "?"),
            "files": [by_raw[r] for r in batches[batch_no]["files"]],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        save_cache(paths.root, batch_no, payload, args.cache_dir)
        n_ok = sum(1 for e in payload["files"] if e["status"] == "generated")
        n_fail = sum(1 for e in payload["files"] if e["status"] in ("failed", "permanent_failed"))
        n_skip = sum(1 for e in payload["files"] if e["status"] == "skipped_immutable")
        print(f"  batch {batch_no}: generated={n_ok} failed={n_fail} "
              f"skipped_immutable={n_skip}", flush=True)
        return payload

    sem = asyncio.Semaphore(batch_concurrency)

    async def _locked(batch_no: int) -> dict:
        async with sem:
            return await _gen_batch_locked(batch_no)

    results = await asyncio.gather(*(_locked(n) for n in targets))
    total_fail = sum(
        1 for p in results
        for e in (p.get("files") or [])
        if e.get("status") in ("failed", "permanent_failed")
    )
    if total_fail:
        print(f"GENERATE DONE with {total_fail} failed raw(s) — "
              f"rerun same command to retry failed entries", flush=True)
        return 2
    print(f"GENERATE DONE {len(targets)} batch(es) cached", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 4 并行生成（零磁盘写）")
    ap.add_argument("--root", default=None, help="project root")
    ap.add_argument("--project", default=None, help="project id (registry)")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--batches", required=True,
                    help="batch numbers, e.g. 3,4,5 or 3-5")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                    help="per-batch LLM concurrency (default 3)")
    ap.add_argument("--batch-concurrency", type=int,
                    default=DEFAULT_BATCH_CONCURRENCY,
                    help="parallel batch count (default 3)")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                    help="cache directory under project root")
    ap.add_argument("--force", action="store_true",
                    help="regenerate even if cache exists")
    args = ap.parse_args(argv)

    if not args.project and not args.root:
        print("ERROR: provide --project <id> or --root <path>", flush=True)
        return 1
    if args.concurrency < 1 or args.batch_concurrency < 1:
        print("ERROR: concurrency must be >= 1", flush=True)
        return 1
    if not _parse_batches(args.batches):
        print("ERROR: --batches must specify at least one batch", flush=True)
        return 1
    return asyncio.run(_run_generate(args))


if __name__ == "__main__":
    sys.exit(main())
