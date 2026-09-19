"""V7 摄取桥接端到端冒烟（真实 LLM，会写盘）。

对单个真实源文档跑完整的 V7 链路 —— `run_v7_ingest`（classify_doc →
segment_articles → check_completeness → cluster_topics → fill_slots →
extract_relations）→ `commit_ingest`（写页面 + index + log），然后调用
`health` 与 `wiki-quality --strict` 做验收判定。

这不是单元测试：它会打真实 LLM 端点并写盘，用于
- Stage 0 验收门（V7 桥接是否可用）
- 灰度观察期（Stage 1）的单源复现与回归对比

默认参数对应 V7 替换工作的标准靶子：70 KB 音频转录稿
（`大纲写作技巧.md`，26,398 字 / 70,966 字节），即旧 candidate 路径
曾经失败的 worst-case 源。

用法（在仓库根目录执行）::

    # 只跑桥接，不写盘（最快，约 30 秒）
    python -X utf8 scripts/smoke_v7_bridge.py --no-commit

    # 完整跑：写盘 + health + wiki-quality
    python -X utf8 scripts/smoke_v7_bridge.py

    # 换项目 / 换源 / 换 provider
    python -X utf8 scripts/smoke_v7_bridge.py \\
        --project-root knowledge/novel-wiki-v2 \\
        --source "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md" \\
        --provider minimax

预算可用 `--max-usd` / `--max-calls` / `--stage-timeout-sec` 覆盖，
默认放宽到 1.0 USD / 30 calls / 180 s（单源冒烟足够）。

退出码：0 = 桥接成功且（写盘模式下）health/wiki-quality 均通过；1 = 失败。
报告写到 `--report`（默认 `.tmp-smoke-v7-report.json`），
日志同时打印到 stdout 并追加到 `--log`（默认 `.tmp-smoke-v7.log`）。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 本脚本在 scripts/ 下运行，sys.path[0] 是 scripts/ 而非仓库根；
# 显式注入仓库根，使其可从任意 cwd 直接调用（无需 PYTHONPATH=.）。
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PROJECT_ROOT = "knowledge/novel-wiki-v2"
DEFAULT_SOURCE = "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md"
DEFAULT_PROVIDER = "minimax"


class _Logger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")

    def __call__(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """用当前解释器调 src.cli 子命令（不依赖 .venv/Scripts/python.exe）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "src.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", default=DEFAULT_PROJECT_ROOT,
                        help=f"项目根目录，相对仓库根（默认 {DEFAULT_PROJECT_ROOT}）")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="源文档，相对项目根（默认 70KB 音频转录稿）")
    parser.add_argument("--provider", default=os.environ.get("RUFLO_LLM_PROVIDER") or DEFAULT_PROVIDER,
                        help=f"LLM provider 注册名（默认 {DEFAULT_PROVIDER}）")
    parser.add_argument("--task-id", default="kb-smoke-v7-bridge")
    parser.add_argument("--no-commit", action="store_true",
                        help="只跑桥接不写盘（不调 commit_ingest，不跑 health/wiki-quality）")
    parser.add_argument("--v3", action="store_true",
                        help="走 fill_slots_v2（v3）路径；默认 v2，调用数约 9 倍")
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--max-calls", type=int, default=30)
    parser.add_argument("--stage-timeout-sec", type=int, default=180,
                        help="单阶段超时秒数（整数——BridgeBudget.from_env 用 int() 解析）")
    parser.add_argument("--report", default=".tmp-smoke-v7-report.json")
    parser.add_argument("--log", default=".tmp-smoke-v7.log")
    opts = parser.parse_args(argv)

    log = _Logger(REPO_ROOT / opts.log)
    report_path = REPO_ROOT / opts.report

    project_root = (REPO_ROOT / opts.project_root).resolve()
    source_abs = project_root / opts.source

    log("=" * 78)
    log("V7 摄取桥接冒烟")
    log("=" * 78)

    if not project_root.exists():
        log(f"ERROR: 项目根不存在: {project_root}")
        return 1
    if not source_abs.exists():
        log(f"ERROR: 源文档不存在: {source_abs}")
        return 1

    source_text = source_abs.read_text(encoding="utf-8")
    source_md5 = hashlib.md5(source_text.encode("utf-8")).hexdigest()
    log(f"project: {project_root.relative_to(REPO_ROOT)}")
    log(f"source:  {opts.source}")
    log(f"chars:   {len(source_text):,}")
    log(f"md5:     {source_md5}")

    os.environ["RUFLO_LLM_PROVIDER"] = opts.provider
    os.environ["RUFLO_V7_MAX_USD"] = str(opts.max_usd)
    os.environ["RUFLO_V7_MAX_CALLS"] = str(opts.max_calls)
    os.environ["RUFLO_V7_STAGE_TIMEOUT_SEC"] = str(opts.stage_timeout_sec)

    log("---")
    log(f"解析 provider: {opts.provider}")
    from src.llm.provider_factory import create_llm_provider
    from src.pipeline.v7_extract.llm_bridge import ProviderAdapter

    provider = create_llm_provider(opts.provider)
    llm = ProviderAdapter(provider)
    log(f"provider ready: name={llm.provider_name} "
        f"model={getattr(provider, 'model', 'n/a')}")

    from src.wiki.core.paths import WikiPaths

    paths = WikiPaths(project_root)
    log(f"wiki_paths ready: root={paths.root} index={paths.index}")

    log("---")
    log(f"run_v7_ingest（use_fill_slots_v2={opts.v3}）...")
    from src.pipeline.v7_extract.bridge import run_v7_ingest

    t0 = time.time()
    result = await run_v7_ingest(
        paths=paths,
        source_path=Path(opts.source),
        source_text=source_text,
        provider=llm,
        task_id=opts.task_id,
        use_fill_slots_v2=opts.v3,
    )
    elapsed = time.time() - t0
    log(f"桥接耗时 {elapsed:.1f}s")
    log(f"  failure_stage:   {result.failure_stage}")
    log(f"  failure_reason:  {result.failure_reason}")
    log(f"  pages:           {len(result.pages)}")
    log(f"  llm_calls:       {llm.calls_count}")
    log(f"  failed_topics:   {result.meta.get('failed_topics', [])}")
    log(f"  empty_extraction:{result.meta.get('empty_extraction', False)}")

    report: dict[str, object] = {
        "task": "smoke_v7_bridge",
        "project_root": opts.project_root,
        "source": opts.source,
        "source_md5": source_md5,
        "source_chars": len(source_text),
        "provider": opts.provider,
        "use_fill_slots_v2": opts.v3,
        "committed": not opts.no_commit,
        "elapsed_sec": round(elapsed, 1),
        "llm_calls": llm.calls_count,
    }

    if result.failure_stage is not None:
        log("桥接失败 —— 中止冒烟")
        report |= {
            "status": "bridge_failed",
            "failure_stage": result.failure_stage,
            "failure_reason": result.failure_reason,
            "traceback": result.meta.get("traceback", ""),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"REPORT: {report_path}")
        return 1

    report |= {
        "n_pages": len(result.pages),
        "concept_page_ids": result.meta.get("concept_page_ids", []),
        "failed_topics": result.meta.get("failed_topics", []),
        "empty_extraction": result.meta.get("empty_extraction", False),
    }

    if opts.no_commit:
        log("---")
        log("--no-commit：跳过 commit_ingest / health / wiki-quality")
        report |= {"status": "bridge_only_ok"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"REPORT: {report_path}")
        return 0

    log("---")
    log("commit_ingest 写盘...")
    from src.pipeline.ingest import commit_ingest

    await commit_ingest(
        paths=paths,
        source_path=Path(opts.source),
        pages=result.pages,
        extra_pages=[],
        task_id=opts.task_id,
    )
    log(f"commit_ingest 写入 {len(result.pages)} 页")

    log("---")
    log("health...")
    health = _run_cli(["health", "--project", str(project_root)])
    log(f"health exit={health.returncode}")
    for line in (health.stdout or "").splitlines()[-20:]:
        log(f"  {line}")
    if health.returncode != 0 and health.stderr:
        log(f"  stderr: {health.stderr[:800]}")

    log("---")
    log("wiki-quality --strict...")
    quality = _run_cli(["wiki-quality", "--project", str(project_root), "--strict"])
    log(f"wiki-quality exit={quality.returncode}")
    for line in (quality.stdout or "").splitlines()[-30:]:
        log(f"  {line}")
    if quality.returncode != 0 and quality.stderr:
        log(f"  stderr: {quality.stderr[:800]}")

    log("---")
    log("落盘产物：")
    for p in sorted(paths.wiki_concepts.glob("*.md")):
        log(f"  concept: {p.name} ({p.stat().st_size} bytes)")
    for p in sorted(paths.wiki_sources.glob("*.md")):
        log(f"  source:  {p.name} ({p.stat().st_size} bytes)")

    ok = health.returncode == 0 and quality.returncode == 0
    report |= {
        "status": "succeeded" if ok else "gate_failed",
        "health_exit": health.returncode,
        "wiki_quality_exit": quality.returncode,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log("---")
    log(f"REPORT: {report_path}")
    log(f"LOG:    {log.log_path}")
    log("结果: PASS" if ok else "结果: FAIL")
    return 0 if ok else 1


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
