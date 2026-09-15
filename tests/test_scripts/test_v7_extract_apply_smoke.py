"""Task 5 (Wave 3 final): one-source apply smoke — verify that a
single real source produces a terminal source outcome whose report,
queue, checkpoint and filesystem are mutually consistent.

Plan §4 Task 5 acceptance:
- Exit code 0
- Report status matches actual files
- Checkpoint explains the source's terminal state
- Raw file md5 unchanged across runs
- Second run skips the same source (no duplicate queue items)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.extract_full import run_full
from src.pipeline.v7_extract.llm_client import FakeLLMClient


@pytest.fixture(autouse=True)
def _scrub_d9_temp_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    """D9: pilot / smoke tests use tmp_path which lives under %TEMP% on
    Windows. Clear the temp env vars so the resolver accepts it.

    This mirrors tests/test_scripts/test_extract_full.py and tests/
    test_pipeline/test_content_filter.py — D9 path whitelist.
    """
    for var in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.delenv(var, raising=False)


SAMPLE_SOURCE = """\
# Sample Source — 写作技法测试

这是用于 V7 control plane 单文档 apply smoke 的样例源文件,
覆盖 5 个 slot 的 evidence 闭合路径,期望 page 真正写入 wiki/concepts。

## 第一段:定义
通过增加动作、环境和感官细节让句子更具体。

## 第二段:特点
扩句法不改变原意,而是让表达更生动具体。

## 第三段:例子
原句"他跑了"扩为"他冲出门,沿着湿漉漉的巷道朝地铁站狂奔,耳边的风灌进衣领"。

## 第四段:相关概念
与"曲折法""切割法"配合使用,效果更佳。

## 第五段:参考文献
经典写作教程,第 12 章。
"""


def _write_source_with_md5(root: Path, name: str, content: str) -> str:
    """Write the source file and return its md5 (the baseline the smoke
    run must NOT change — plan §4 Task 5 acceptance).

    Reads back the on-disk bytes (not the Python str) so the hash
    survives Windows CRLF normalisation. The smoke run's md5 check
    must use the SAME on-disk read so the comparison is apples-to-
    apples.
    """
    path = root / "raw" / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return hashlib.md5(path.read_bytes()).hexdigest()


def _script_full_page(fake: FakeLLMClient) -> None:
    """Script a complete Stage 5 result: all 5 slots filled with body
    and evidence so the Writer accepts the page (no Gate B/C block)."""
    fake.script("classify", '{"doc_type": "single_method", "confidence": 0.9, "rationale": "ok"}')
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "扩句法", "item_indexes": [0]}]}',
    )
    fake.script("fill_slots", (
        '{"slots": {"definition": "def", "characteristics": "c", '
        '"examples": "e", "related_concepts": "rc", "references": "ref"}, '
        '"evidence": {"definition": {"item_index": 0, "source_text_excerpt": "定义"}, '
        '"characteristics": {"item_index": 0, "source_text_excerpt": "特点"}, '
        '"examples": {"item_index": 0, "source_text_excerpt": "例子"}, '
        '"related_concepts": {"item_index": 0, "source_text_excerpt": "相关"}, '
        '"references": {"item_index": 0, "source_text_excerpt": "参考"}}}'
    ))


def test_v7_one_source_apply_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan §4 Task 5: single-source apply smoke.

    The smoke asserts:
    - raw file md5 is unchanged across runs
    - first run's report matches the filesystem (page on disk)
    - checkpoint row for the source is terminal (status=written, dry_run=False)
    - second run skips the same source via md5 (no new LLM work,
      no duplicate queue items)
    """
    # Plan §4 Task 5 O2 / test_content_filter pattern: D9 path whitelist
    # forbids temp directories unless the TEMP / TMP / TMPDIR env vars
    # are cleared. Clear them for this subprocess so the smoke can
    # resolve prompts from the temp root.
    for var in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.delenv(var, raising=False)

    md5_before = _write_source_with_md5(
        tmp_path, "complete.md", SAMPLE_SOURCE,
    )

    fake = _make_double_script()  # two runs of scripted responses
    os.environ["V7_ALLOW_APPLY"] = "1"
    try:
        # First apply run — actually writes the page.
        report1 = asyncio.run(run_full(
            tmp_path,
            batch_size=1,
            checkpoint_path=tmp_path / ".index" / "full.json",
            queue_path=tmp_path / ".index" / "reviews_queue.json",
            dry_run=False,
            llm=fake,
            json_output=tmp_path / "report.json",
            markdown_output=tmp_path / "report.md",
        ))
        # Raw file md5 must not change after apply.
        md5_after_first = hashlib.md5(
            (tmp_path / "raw" / "sources" / "complete.md").read_bytes()
        ).hexdigest()
        assert md5_after_first == md5_before, (
            "apply run must not mutate the raw source file"
        )

        # Report / filesystem consistency.
        assert report1["mode"] == "apply"
        written_count = report1["summary"]["by_status"]["written"]
        assert written_count >= 1, "expected at least one written source"
        assert list((tmp_path / "wiki" / "concepts").glob("*.md")), (
            "apply must produce at least one wiki/concepts/*.md file"
        )

        # Checkpoint explains the terminal state.
        ckpt = json.loads(
            (tmp_path / ".index" / "full.json").read_text(encoding="utf-8")
        )
        assert ckpt["version"] == 2
        assert 1 in ckpt["completed_batches"]
        source_row = ckpt["sources"]["raw/sources/complete.md"]
        assert source_row["status"] == "written"
        assert source_row["dry_run"] is False
        assert source_row["md5"] == md5_before
        assert len(source_row["written_page_ids"]) >= 1

        # Queue file lives under the project root, NOT the CWD.
        queue_path = tmp_path / ".index" / "reviews_queue.json"
        assert queue_path.exists()

        # Capture queue item count for the no-duplicate check.
        queue_items_before = json.loads(
            queue_path.read_text(encoding="utf-8")
        )["items"]
        v7_items_before = [
            i for i in queue_items_before if i.get("source") == "v7_extract"
        ]

        # Second apply run — same source md5 must skip via the v2
        # checkpoint (no new LLM calls, no duplicate queue items).
        first_calls = len(fake.calls)
        report2 = asyncio.run(run_full(
            tmp_path,
            batch_size=1,
            checkpoint_path=tmp_path / ".index" / "full.json",
            queue_path=tmp_path / ".index" / "reviews_queue.json",
            dry_run=False,
            llm=fake,
            json_output=tmp_path / "report.json",
            markdown_output=tmp_path / "report.md",
        ))
        # Raw file md5 must STILL be unchanged.
        md5_after_second = hashlib.md5(
            (tmp_path / "raw" / "sources" / "complete.md").read_bytes()
        ).hexdigest()
        assert md5_after_second == md5_before

        # No new LLM calls (md5 skip hit at source level).
        assert len(fake.calls) == first_calls, (
            "second run must skip the source via md5 (no new LLM work)"
        )

        # No duplicate v7_extract queue items.
        queue_items_after = json.loads(
            queue_path.read_text(encoding="utf-8")
        )["items"]
        v7_items_after = [
            i for i in queue_items_after if i.get("source") == "v7_extract"
        ]
        assert len(v7_items_after) == len(v7_items_before), (
            "second run must not append duplicate v7_extract queue items"
        )

        # Report state matches filesystem state.
        assert report2["summary"]["by_status"]["written"] >= 1
        assert list((tmp_path / "wiki" / "concepts").glob("*.md"))
    finally:
        os.environ.pop("V7_ALLOW_APPLY", None)


def _make_double_script() -> FakeLLMClient:
    """Return a FakeLLMClient pre-loaded with two runs of scripted
    responses (the first run consumes the first copy; the second
    run should be entirely skipped via the v2 md5 match, but we
    keep the second copy as a defensive buffer)."""
    fake = FakeLLMClient()
    for _ in range(2):
        _script_full_page(fake)
    return fake
