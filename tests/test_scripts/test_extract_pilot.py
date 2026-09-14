from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.extract_pilot import run_pilot


def _write_source(root: Path, name: str, content: str) -> None:
    path = root / "raw" / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_run_pilot_selects_deterministic_sources_and_never_writes_wiki(
    tmp_path: Path,
) -> None:
    for index in range(4):
        _write_source(
            tmp_path,
            f"source-{index}.md",
            f"# 主题 {index}\n\n这是一个足够长的来源正文。" * 120,
        )

    report = run_pilot(tmp_path, count=3, seed=7)

    assert report["mode"] == "dry-run"
    assert report["summary"]["selected"] == 3
    assert len(report["sources"]) == 3
    assert report["sources"] == run_pilot(tmp_path, count=3, seed=7)["sources"]
    assert not (tmp_path / "wiki").exists()
    assert not (tmp_path / ".index").exists()


def test_run_pilot_reports_classification_completeness_and_pages(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "complete.md",
        "# 扩句法\n\n定义：通过增加动作、环境和感官细节让句子更具体。\n\n"
        + "正文内容。" * 200,
    )
    _write_source(tmp_path, "short.md", "# 只有标题\n\n简介")

    report = run_pilot(tmp_path, count=10, seed=1)
    by_name = {item["source"]: item for item in report["results"]}

    assert by_name["raw/sources/complete.md"]["complete"] is True
    assert by_name["raw/sources/complete.md"]["pages"]
    assert by_name["raw/sources/short.md"]["doc_type"] == "incomplete"
    assert by_name["raw/sources/short.md"]["pages"] == []
    assert report["summary"]["pages"] >= 1


def test_write_report_emits_json_and_markdown_without_wiki_writes(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    report = run_pilot(
        tmp_path,
        count=1,
        seed=1,
        json_output=json_path,
        markdown_output=markdown_path,
    )

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# V7 Extract Pilot Report" in markdown
    assert "dry-run" in markdown
    assert not (tmp_path / "wiki").exists()


def test_direct_script_entrypoint_bootstraps_repo_imports(tmp_path: Path) -> None:
    _write_source(tmp_path, "one.md", "# 标题\n\n" + "正文。" * 300)
    json_path = tmp_path / "direct.json"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[2] / "scripts" / "extract_pilot.py"),
            "--root",
            str(tmp_path),
            "--count",
            "1",
            "--json-out",
            str(json_path),
            "--markdown-out",
            str(tmp_path / "direct.md"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json_path.exists()
