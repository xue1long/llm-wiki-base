#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量构建知识库（最稳形态）—— 把 raw/ 文档转成「可检索知识库」。

设计目标：两阶段、幂等、可续、失败隔离。
  Phase 1 (ingest) : 读 raw/ 下文档 -> analyzer(MiniMax chat) -> generator(MiniMax chat) -> 写 wiki 页面
  Phase 2 (archive): 遍历 wiki/ 下生成的笔记 -> 切块 -> embo-01 embedding -> 写入 lancedb

为什么最稳
----------
* 进程内直接调用 run_ingest / archive，不依赖 serve、不碰任务队列/熔断，无网络编排噪声。
* 源文件不会被移动（绕过 collector 的「成功即移走」行为），raw/sources 始终保留原件。
* 状态文件 .index/batch_build_state.json 记录每项已完成的内容哈希；重跑只补增量，
  不重复调用 LLM / embedding，省费用也防重复落库。
* 单篇失败不中断整批，最后汇总报告；同一文件内容未变则自动跳过。

用法
----
  # 预览将要处理的文件/笔记（不花任何 API 费用）
  python scripts/batch_build.py --project-id <ID> --dry-run

  # 完整构建：先 ingest 全部 raw/sources，再 archive 全部 wiki 笔记
  python scripts/batch_build.py --project-id <ID>

  # 只跑其中一阶段（例如 ingest 已做过，只想补 embedding）
  python scripts/batch_build.py --project-id <ID> --only archive

  # 先用一个小目录试跑（验证链路，控制费用）
  python scripts/batch_build.py --project-id <ID> --raw-dir /path/to/small-dir

依赖：必须在项目根目录运行（脚本以 `src` 包方式 import 内部模块）。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

# 把项目根加入 sys.path，使 `python scripts/batch_build.py` 时 `src` 包可被 import
# （直接用 `python -m` 运行时 CWD 即根，此行无害）。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.utils.path import migrate_state_paths, normalize_source_path, safe_resolve

# 尽早加载 .env（含 MINIMAX_API_KEY 等）；src/__init__ 也会再加载一次 ~/.config/ruflo-kb/env
try:
    from dotenv import load_dotenv

    load_dotenv()
    _cfg = os.path.expanduser("~/.config/ruflo-kb/env")
    if os.path.exists(_cfg):
        with open(_cfg) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("batch_build")

# collector 实际能处理的格式（与 src/pipeline/collector.py 对齐）
SUPPORTED_EXT = {".md", ".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls"}
# wiki 下需要归档的笔记子目录（排除 wiki 根目录的 index.md/log.md 以及 archive 落地的副本）
NOTE_DIRS = ["sources", "concepts", "entities", "synthesis"]
META_FILES = {"index.md", "log.md"}


def rel_state_key(p: Path, root: Path) -> str:
    """Project-relative posix key for state files — location-independent, so
    the batch_build_state survives device moves (the old ``f.resolve().as_posix()``
    absolute keys went stale whenever the project lived at a new path)."""
    return normalize_source_path(str(p), root)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8", "ignore")).hexdigest()


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            # 状态文件可能由别的工具写入（如 phase4 只写 batch_N 键）；
            # 补齐本脚本依赖的三个分区，同时保留已有键。
            state.setdefault("ingested", {})
            state.setdefault("archived", {})
            state.setdefault("failed", {})
            return state
        except Exception:
            log.warning("状态文件损坏，已重置: %s", state_path)
    return {"ingested": {}, "archived": {}, "failed": {}}


def save_state(state_path: Path, state: dict) -> None:
    """原子写状态文件（tmp + os.replace），避免中断产生半截 JSON——与
    phase4_batch._save_state 对齐。"""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(state_path))


def resolve_root(project_id: str | None) -> Path:
    if project_id:
        try:
            from src.project.registry import GlobalRegistryStore

            entry = GlobalRegistryStore.by_id(project_id)
            if entry is not None:
                return Path(entry.path)
        except Exception as e:  # noqa: BLE001
            log.warning("无法从注册表解析项目 %s: %s", project_id, e)
    return Path.cwd()


def init_llm():
    """初始化 ingest 用的 LLM provider（默认 minimax）。"""
    from src.llm.provider_factory import create_llm_provider
    from src.llm.registry import ProviderRegistry

    cfg = ProviderRegistry.get_default()
    if cfg is None:
        raise RuntimeError(
            "未找到默认 LLM provider，请先 `python -m src.cli llm-providers set-default minimax`"
        )
    return create_llm_provider(cfg.name)


async def init_embedding():
    """初始化 archive 用的 embedding provider（默认 minimax embo-01），与 app.py 启动逻辑一致。"""
    import os

    from src.llm.embedding_runtime import set_embedding_provider
    from src.llm.provider_factory import create_embedding_provider
    from src.llm.registry import ProviderRegistry

    _env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "kimi": "KIMI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "glm": "GLM_API_KEY",
    }

    def _build(provider_type: str, api_key, endpoint, model):
        return create_embedding_provider(
            provider=provider_type,
            api_key=api_key,
            endpoint=endpoint,
            model=model,
            dimension=None,  # 由模型返回其原生维度（embo-01=1536，匹配 LanceDB）
        )

    async def _try_build_and_verify(provider_type, api_key, endpoint, model):
        """Try to build and test the provider. Returns a working provider or None."""
        try:
            provider = _build(provider_type, api_key, endpoint, model)
            # Quick smoke test: embed a single word to verify the provider actually
            # returns vectors. MiniMax embo-01 is deprecated and returns [] silently.
            result = await provider.embed(["test"])
            if not result or not result[0].embedding:
                log.warning("远程 embedding provider 返回空向量（模型可能已废弃）")
                return None
            return provider
        except Exception as e:
            log.warning("远程 embedding provider 初始化失败 (%s)", e)
            return None

    try:
        cfg = ProviderRegistry.get_default()
    except Exception:
        cfg = None

    provider = None
    if cfg is not None:
        key = cfg.api_key or (os.environ.get(_env_map.get(cfg.name, "")) if _env_map.get(cfg.name) else None)
        model = cfg.default_embedding_model or (
            "embo-01" if cfg.name == "minimax" else "text-embedding-3-small"
        )
        from src.llm.provider_factory import resolve_embedding_provider_type

        provider_type = resolve_embedding_provider_type(cfg.name, cfg.type)
        provider = await _try_build_and_verify(provider_type, key, cfg.base_url or None, model)

    if provider is None:
        # 回落：minimax + 环境变量
        provider = await _try_build_and_verify(
            "minimax",
            os.environ.get("MINIMAX_API_KEY"),
            os.environ.get("MINIMAX_BASE_URL"),
            "embo-01",
        )

    if provider is None:
        log.warning("所有远程 embedding provider 均不可用，回落至本地 sentence-transformers")
        from src.llm.local_embed import LocalEmbeddingProvider

        provider = LocalEmbeddingProvider()

    set_embedding_provider(provider)
    return provider


def extract_text(fp: Path) -> str:
    """复用项目自带提取逻辑；与 collector.collect 保持一致。"""
    ext = fp.suffix.lower()
    if ext in (".md", ".txt"):
        return fp.read_text(encoding="utf-8")
    if ext == ".pdf":
        from src.utils.extract.pdf import extract_pdf_text

        return extract_pdf_text(str(fp))
    if ext in (".docx", ".doc", ".xlsx", ".xls"):
        from src.utils.extract.office import extract_office_text

        return extract_office_text(str(fp))
    # .html/.htm 等 collector 暂不支持的格式：读取原始文本，尽量不丢内容
    log.warning("格式 %s 非标准提取路径，按纯文本读取: %s", ext, fp.name)
    return fp.read_text(encoding="utf-8", errors="ignore")


async def phase_ingest(root: Path, raw_dir: Path, state: dict, args) -> dict:
    from src.pipeline.pipeline import run_ingest
    from src.wiki.core.paths import WikiPaths

    paths = WikiPaths(root)
    llm = init_llm()

    files = sorted(p for p in raw_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXT)
    log.info("[ingest] 在 %s 找到 %d 个可摄取文件", raw_dir, len(files))

    stats = {"ok": 0, "skip": 0, "fail": 0}
    if args.dry_run:
        for f in files:
            digest = sha256_file(f)
            if rel_state_key(f, root) in state["ingested"] and state["ingested"][rel_state_key(f, root)] == digest:
                log.info("  (dry) skip (已存在且未改动): %s", f.name)
            else:
                log.info("  (dry) WOULD ingest: %s", f.name)
        return stats

    for f in files:
        fkey = rel_state_key(f, root)
        digest = sha256_file(f)
        if fkey in state["ingested"] and state["ingested"][fkey] == digest and not args.force:
            stats["skip"] += 1
            continue
        task_id = "kb-batch-" + digest[:12]
        t0 = time.time()
        try:
            text = extract_text(f)
            if not text.strip():
                raise ValueError("提取内容为空")
            await run_ingest(
                paths=paths,
                source_path=f,
                source_text=text,
                provider=llm,
                folder_context="",
                task_id=task_id,
            )
            state["ingested"][fkey] = digest
            state["failed"].pop(fkey, None)
            stats["ok"] += 1
            log.info("  ✓ ingested %s (%.1fs)", f.name, time.time() - t0)
        except Exception as e:  # noqa: BLE001
            stats["fail"] += 1
            state["failed"][fkey] = str(e)[:300]
            log.error("  ✗ ingest 失败 %s: %s", f.name, e)
    return stats


def _is_stub_note(path: Path) -> bool:
    """占位页（frontmatter ``processing_depth: stub``）不应被建向量；
    复用 read_page 作为 frontmatter 的唯一事实源。"""
    try:
        from src.wiki.storage.page_writer import read_page

        return read_page(path).processing_depth == "stub"
    except Exception:  # noqa: BLE001
        # 解析失败按普通笔记处理，由 archive 阶段报错兜底
        return False


async def phase_archive(root: Path, state: dict, args) -> dict:
    from src.pipeline.librarian import archive
    from src.vector.store import init_vector_store_for_paths
    from src.wiki.core.paths import WikiPaths

    paths = WikiPaths(root)
    init_vector_store_for_paths(paths)

    notes = []
    for sub in NOTE_DIRS:
        d = paths.wiki / sub
        if d.is_dir():
            notes.extend(sorted(p for p in d.rglob("*.md") if p.name not in META_FILES))
    # 只扫笔记子目录，不扫 wiki 根：真实生成的笔记一律在
    # sources/concepts/entities/synthesis 下；wiki 根的 index.md/log.md
    # 是索引元数据，不是待归档笔记。
    # 跳过占位页（processing_depth: stub），避免被向量化污染检索结果。
    notes = [n for n in notes if not _is_stub_note(n)]

    log.info("[archive] 找到 %d 个待归档笔记", len(notes))
    stats = {"ok": 0, "skip": 0, "fail": 0}
    if args.dry_run:
        for n in notes:
            digest = sha256_file(n)
            if rel_state_key(n, root) in state["archived"] and state["archived"][rel_state_key(n, root)] == digest:
                log.info("  (dry) skip (已归档且未改动): %s", n.name)
            else:
                log.info("  (dry) WOULD archive: %s", n.name)
        return stats

    # Reuse the same embedding provider across all notes (shared httpx client).
    embed_provider = await init_embedding()
    try:
        for n in notes:
            nkey = rel_state_key(n, root)
            digest = sha256_file(n)
            if nkey in state["archived"] and state["archived"][nkey] == digest and not args.force:
                stats["skip"] += 1
                continue
            task_id = "kb-arch-" + digest[:12]
            t0 = time.time()
            try:
                payload = await archive(task_id, str(n), paths)
                state["archived"][nkey] = digest
                state["failed"].pop(nkey, None)
                stats["ok"] += 1
                kind = type(payload).__name__
                log.info("  ✓ archived %s (%s, %.1fs)", n.name, kind, time.time() - t0)
            except Exception as e:  # noqa: BLE001
                stats["fail"] += 1
                state["failed"][nkey] = str(e)[:300]
                log.error("  ✗ archive 失败 %s: %s", n.name, e)
    finally:
        if hasattr(embed_provider, "close"):
            await embed_provider.close()
    return stats


async def run(args: argparse.Namespace) -> int:
    if args.root:
        root = safe_resolve(args.root)
    else:
        if not args.project_id:
            sys.exit("必须提供 --project-id 或 --root 之一")
        root = safe_resolve(resolve_root(args.project_id))
    raw_dir = safe_resolve(args.raw_dir) if args.raw_dir else (root / "raw" / "sources")
    state_path = root / ".index" / "batch_build_state.json"
    # 迁移历史绝对路径键 -> 项目相对键(换设备后旧绝对键会 stale)
    state = migrate_state_paths(load_state(state_path), root)

    log.info("项目根: %s", root)
    log.info("raw 目录: %s", raw_dir)

    total_fail = 0
    if args.only in (None, "ingest"):
        s = await phase_ingest(root, raw_dir, state, args)
        log.info("[ingest] 完成 -> 成功 %d · 跳过 %d · 失败 %d", s["ok"], s["skip"], s["fail"])
        total_fail += s["fail"]
        save_state(state_path, state)
    if args.only in (None, "archive"):
        s = await phase_archive(root, state, args)
        log.info("[archive] 完成 -> 成功 %d · 跳过 %d · 失败 %d", s["ok"], s["skip"], s["fail"])
        total_fail += s["fail"]
        save_state(state_path, state)

    if args.dry_run:
        log.info("dry-run 结束，未产生任何 API 调用 / 落盘。")
    else:
        # 写一份报告
        report = root / ".index" / "batch_build_report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("状态/报告: %s", report)
    return 1 if total_fail else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="批量构建 ruflo-kb 知识库（ingest + archive 两段式，幂等可续）")
    ap.add_argument("--project-id", default=None, help="项目 ID（python -m src.cli project list 查看）；与 --root 二选一")
    ap.add_argument("--root", default=None, help="直接指定项目根目录（覆盖 --project-id 解析），用于隔离测试")
    ap.add_argument("--raw-dir", default=None, help="待摄取文档目录（默认 <root>/raw/sources）")
    ap.add_argument("--only", choices=["ingest", "archive"], default=None, help="只跑某一阶段")
    ap.add_argument("--force", action="store_true", help="忽略状态文件，强制重跑全部")
    ap.add_argument("--dry-run", action="store_true", help="只列出将处理的文件/笔记，不调用 API、不落盘")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
