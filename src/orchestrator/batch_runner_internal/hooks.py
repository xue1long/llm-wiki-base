"""Test hooks and runtime resolution helpers for batch execution."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from src.wiki.core.paths import WikiPaths

_logger = logging.getLogger("batch_runner")


def _crash_at(stage: str) -> None:
    """kill -9 injection controlled by ``BATCH_EXECUTOR_CRASH_AT``."""
    target = os.environ.get("BATCH_EXECUTOR_CRASH_AT", "")
    if target == stage:
        _logger.warning("[crash-inject] os._exit(137) at stage %s", stage)
        if os.environ.get("RUFLO_SOFT_CRASH") == "1":
            os._exit(0)
        os._exit(137)


def _snapshot_page_hashes(paths, pages) -> dict[str, str]:
    """Record sha256 baselines for existing target pages after generation."""
    import hashlib
    from src.wiki.schema_registry import SchemaRegistry
    from src.wiki.storage.page_writer import page_path_for

    registry = SchemaRegistry.from_project(paths.root)
    out: dict[str, str] = {}
    for page in pages:
        try:
            path = page_path_for(paths, page.type, page.id)
            if path.exists():
                out[page.id] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def _fake_generate(raw_rel: str) -> list:
    """Generate deterministic gate-clean pages for offline tests."""
    from src.wiki.core.types import PageType, WikiPage

    if os.environ.get("RUFLO_FAKE_FAIL") == "1":
        raise RuntimeError("fake generate failure (RUFLO_FAKE_FAIL=1)")

    stem = Path(raw_rel).stem
    ph = " 待补充 " if os.environ.get("RUFLO_FAKE_PLACEHOLDER") == "1" else "内容"
    now = int(time.time() * 1000)
    source_body = (
        "<!-- wiki-template-version: 2.0.0 -->\n<!-- wiki-template-type: source -->\n\n"
        "## 来源元数据\n\n- 路径: `{raw}`\n\n## 摘要\n\n摘要{ph}\n\n"
        "## 关键观点\n\n- 观点\n\n## 抽取的概念\n\n- 概念"
    ).format(raw=raw_rel, ph=ph)
    concept_body = (
        "<!-- wiki-template-version: 2.0.0 -->\n<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n定义{ph}\n\n## 主要特点\n\n- 特点\n\n## 例子\n\n- 例\n\n"
        "## 相关概念\n\n[[concept-{stem}]]\n\n## 参考来源\n\n[[src-{stem}]]"
    ).format(stem=stem, ph=ph)
    return [
        WikiPage(
            id=f"src-{stem}", title=f"源{stem}", type=PageType.SOURCE,
            sources=[raw_rel], body=source_body, grade="A",
            processing_depth="source", created_at=now, updated_at=now,
        ),
        WikiPage(
            id=f"concept-{stem}", title=f"概念{stem}", type=PageType.CONCEPT,
            sources=[raw_rel], body=concept_body, grade="B",
            processing_depth="concept", created_at=now, updated_at=now,
        ),
    ]


def _is_fake_mode() -> bool:
    return os.environ.get("RUFLO_EXECUTOR_FAKE_GENERATE") == "1"


def _estimate_batch_cost(ok: int, err: int) -> float:
    """Estimate batch cost in USD using the existing fake/real formulas."""
    if _is_fake_mode():
        return float(os.environ.get("RUFLO_FAKE_COST", "0.2"))
    cost_per_call = float(os.environ.get("RUFLO_COST_PER_CALL", "0.0005"))
    return round((ok + err) * cost_per_call, 4)


def _resolve_paths(args) -> WikiPaths:
    if getattr(args, "root", None):
        return WikiPaths(Path(args.root))
    from src.pipeline import _resolve_wiki_paths
    return _resolve_wiki_paths(args.project)


def _resolve_provider(args):
    """Resolve the LLM provider for the requested project."""
    from src.pipeline import _get_provider
    project_id = getattr(args, "project", None)
    return _get_provider(project_id)
