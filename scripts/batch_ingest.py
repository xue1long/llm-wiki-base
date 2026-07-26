#!/usr/bin/env python3
"""
批量摄取脚本 —— 把一堆文档转进 ruflo-kb 知识库。

用法示例
--------
# 1) 整个文件夹一次投喂（最简单，推荐先试这个）
python scripts/batch_ingest.py --project-id <ID> --path /abs/path/to/docs --mode folder

# 2) 递归扫描、逐文件并发摄取（更适合几万篇、想看进度/重试）
python scripts/batch_ingest.py --project-id <ID> --path /abs/path/to/docs \
    --mode file --recursive --concurrency 4

# 3) 先只打印将要投喂哪些文件，不真正调用
python scripts/batch_ingest.py --project-id <ID> --path /abs/path/to/docs --mode file --dry-run

说明
----
- 支持的格式：pdf / docx / xlsx / html / md / txt（与 src/utils/extract 一致）
- 接口：POST /api/v1/projects/{id}/ingest  body={"source": <str|dict>}
  - 单文件：source="<绝对路径>"（非 http 开头即视为文件）
  - 整文件夹：source={"folder": "<绝对路径>"}
- 幂等：同一文件 7 天内重复投喂会被忽略（返回 reason=Duplicate）
- 需要先在另一个终端起服务：python -m src.cli serve --port 19828
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("需要 httpx：pip install httpx")

SUPPORTED_EXT = {".pdf", ".docx", ".xlsx", ".html", ".htm", ".md", ".txt"}


def discover_files(root: Path, recursive: bool) -> list[Path]:
    if recursive:
        files = [p for p in root.rglob("*") if p.is_file()]
    else:
        files = [p for p in root.iterdir() if p.is_file()]
    return sorted(f for f in files if f.suffix.lower() in SUPPORTED_EXT)


async def _post(client: httpx.AsyncClient, url: str, payload: dict) -> dict:
    try:
        resp = await client.post(url, json=payload, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": str(e)}


async def ingest_folder(client: httpx.AsyncClient, base: str, folder: Path) -> dict:
    payload = {"source": {"folder": str(folder)}, "folderContext": None}
    return await _post(client, f"{base}/ingest", payload)


async def ingest_file(client: httpx.AsyncClient, base: str, fp: Path) -> dict:
    payload = {"source": str(fp), "folderContext": None}
    return await _post(client, f"{base}/ingest", payload)


async def run(args: argparse.Namespace) -> int:
    base = f"http://{args.host}:{args.port}/api/v1/projects/{args.project_id}"
    root = Path(args.path).resolve()

    if not root.exists():
        sys.exit(f"路径不存在: {root}")

    sem = asyncio.Semaphore(args.concurrency)

    async def bounded(coro):
        async with sem:
            return await coro

    if args.mode == "folder":
        if not root.is_dir():
            sys.exit("--mode folder 要求 --path 是一个目录")
        print(f"[folder] 投喂整个目录: {root}")
        if args.dry_run:
            print("  (dry-run) 将发送: {\"source\": {\"folder\": %r}}" % str(root))
            return 0
        result = await ingest_folder_semaphore(base, root)
        print("  结果:", json.dumps(result, ensure_ascii=False))
        return 0

    # file mode
    files = discover_files(root, args.recursive)
    print(f"[file] 在 {root} 找到 {len(files)} 个可摄取文件"
          f"（recursive={args.recursive}, ext={sorted(SUPPORTED_EXT)}）")
    if args.dry_run:
        for f in files:
            print("  would ingest:", f)
        return 0

    async with httpx.AsyncClient() as client:
        tasks = [bounded(ingest_file(client, base, f)) for f in files]
        results = await asyncio.gather(*tasks)

    ok = sum(1 for r in results if r.get("status") in ("queued", "ignored"))
    err = sum(1 for r in results if r.get("status") == "error")
    print(f"\n完成: 成功/已存在 {ok} · 失败 {err} · 共 {len(files)}")
    for f, r in zip(files, results):
        if r.get("status") == "error":
            print(f"  ✗ {f.name}: {r.get('detail')}")
    # 写一份报告，方便排查
    report = str(Path.cwd() / "scripts" / "ingest_report.json")
    Path(report).write_text(json.dumps(
        [{"file": str(f), "result": r} for f, r in zip(files, results)],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入: {report}")
    return 1 if err else 0


async def ingest_folder_semaphore(base: str, folder: Path) -> dict:
    async with httpx.AsyncClient() as client:
        return await ingest_folder(client, base, folder)


def main() -> int:
    ap = argparse.ArgumentParser(description="批量摄取文档到 ruflo-kb")
    ap.add_argument("--project-id", required=True, help="项目 ID（python -m src.cli project list 查看）")
    ap.add_argument("--path", required=True, help="文档所在目录的绝对路径")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=19828)
    ap.add_argument("--mode", choices=["folder", "file"], default="folder",
                    help="folder=整个目录一次投喂；file=逐文件并发")
    ap.add_argument("--recursive", action="store_true", help="file 模式下递归子目录")
    ap.add_argument("--concurrency", type=int, default=4, help="file 模式并发数")
    ap.add_argument("--dry-run", action="store_true", help="只列出将投喂的文件，不调用")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
