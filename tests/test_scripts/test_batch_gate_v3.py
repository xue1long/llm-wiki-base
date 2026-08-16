"""Phase 1.5 tests — batch_gate_v3 post-ingest gate (plan 1.5 / spec §5.3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    # Project-level v3.0.0 templates so the gate checks the v3 slot set
    # (bundled 2.0.0 would demand extracted_concepts on source pages).
    tpl_dir = tmp_path / ".wiki-templates"
    tpl_dir.mkdir(parents=True)
    src_tpl = REPO_ROOT / "knowledge" / "novel-wiki" / ".wiki-templates"
    for name in ("source.md", "concept.md", "entity.md", "synthesis.md"):
        (tpl_dir / name).write_text(
            (src_tpl / name).read_text(encoding="utf-8"), encoding="utf-8")

    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "a.md").write_text("内容 A", encoding="utf-8")
    (tmp_path / "raw" / "sources" / "b.md").write_text("内容 B", encoding="utf-8")

    def page(rel: str, content: str) -> None:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    page("wiki/sources/s-a.md",
         "---\nid: s-a\ntitle: 源A\ntype: source\nsources:\n- raw/sources/a.md\n---\n\n"
         "<!-- wiki-template-version: 3.0.0 -->\n<!-- wiki-template-type: source -->\n\n"
         "## 来源元数据\n\nm\n\n## 转录质量\n\n人工整理\n\n## 摘要\n\ns\n\n"
         "## 关键观点\n\n- k\n\n## 可信度声明\n\nc\n")
    # clean concept with all v3.0.0 required sections
    page("wiki/concepts/c1.md",
         "---\nid: c1\ntitle: 概念一\ntype: concept\nsources:\n- raw/sources/a.md\n"
         "tags:\n- 读者群/男频\n- 素材/ugc\n- 可信度/ugc\n---\n\n"
         "<!-- wiki-template-version: 3.0.0 -->\n<!-- wiki-template-type: concept -->\n\n"
         "## 定义\n\ndef\n\n## 主要特点\n\nc\n\n## 适用场景\n\nctx\n\n"
         "## 反模式与常见错误\n\nap\n\n## 证据强度\n\nev\n\n## 例子\n\nex\n\n"
         "## 相关概念\n\n[[c2]]\n\n## 参考来源\n\n[[s-a]]\n")
    page("wiki/concepts/c2.md",
         "---\nid: c2\ntitle: 概念二\ntype: concept\nsources:\n- raw/sources/b.md\n"
         "tags:\n- 素材/ugc\n- 可信度/ugc\n---\n\n"
         "<!-- wiki-template-version: 3.0.0 -->\n<!-- wiki-template-type: concept -->\n\n"
         "## 定义\n\ndef\n\n## 主要特点\n\nc\n\n## 适用场景\n\nctx\n\n"
         "## 反模式与常见错误\n\nap\n\n## 证据强度\n\nev\n\n## 例子\n\nex\n\n"
         "## 相关概念\n\n[[ghost-x]]\n\n## 参考来源\n\n[[s-a]]\n")  # ghost link
    page("wiki/concepts/c3.md",
         "---\nid: c3\ntitle: 概念三\ntype: concept\nsources:\n- raw/sources/a.md\n"
         "tags:\n- 素材/ugc\n- 可信度/ugc\n---\n\n"
         "<!-- wiki-template-version: 3.0.0 -->\n<!-- wiki-template-type: concept -->\n\n"
         "## 定义\n\n见下游概念页\n\n## 主要特点\n\nc\n\n## 适用场景\n\nctx\n\n"
         "## 反模式与常见错误\n\nap\n\n## 证据强度\n\nev\n\n## 例子\n\nex\n\n"
         "## 相关概念\n\n[[c1]]\n\n## 参考来源\n\n[[s-a]]\n")  # placeholder
    return tmp_path


def _run(root: Path, report: str, pages: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "batch_gate_v3.py"),
         str(root), "--report", report, "--pages", pages],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
    )


def test_gate_clean_batch_passes(mini_wiki: Path) -> None:
    r = _run(mini_wiki, "batch_ok", "s-a,c1")
    assert r.returncode == 0, r.stderr
    data = json.loads((mini_wiki / ".index" / "batch_reports" / "batch_ok.json")
                      .read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["metrics"]["M4_placeholders"] == 0


def test_gate_broken_link_blocks(mini_wiki: Path) -> None:
    r = _run(mini_wiki, "batch_broken", "c2")
    assert r.returncode == 1
    data = json.loads((mini_wiki / ".index" / "batch_reports" / "batch_broken.json")
                      .read_text(encoding="utf-8"))
    assert data["passed"] is False
    codes = {i["code"] for i in data["issues"]}
    assert "BROKEN-LINK" in codes


def test_gate_placeholder_blocks(mini_wiki: Path) -> None:
    r = _run(mini_wiki, "batch_ph", "c3")
    assert r.returncode == 1
    data = json.loads((mini_wiki / ".index" / "batch_reports" / "batch_ph.json")
                      .read_text(encoding="utf-8"))
    assert data["passed"] is False
    assert any(i["code"] == "LINT-PLACEHOLDER" for i in data["issues"])


def test_gate_tag_enum_blocks(mini_wiki: Path) -> None:
    # c1 has valid 读者群/男频; add a page with an invalid tag value
    p = mini_wiki / "wiki" / "concepts"
    (p / "c4.md").write_text(
        "---\nid: c4\ntitle: 概念四\ntype: concept\nsources:\n- raw/sources/a.md\n"
        "tags:\n- 读者群/其它\n- 素材/ugc\n- 可信度/ugc\n---\n\n"
        "<!-- wiki-template-version: 3.0.0 -->\n<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\ndef\n\n## 主要特点\n\nc\n\n## 适用场景\n\nctx\n\n"
        "## 反模式与常见错误\n\nap\n\n## 证据强度\n\nev\n\n## 例子\n\nex\n\n"
        "## 相关概念\n\n[[c1]]\n\n## 参考来源\n\n[[s-a]]\n", encoding="utf-8")
    r = _run(mini_wiki, "batch_tag", "c4")
    assert r.returncode == 1
    data = json.loads((mini_wiki / ".index" / "batch_reports" / "batch_tag.json")
                      .read_text(encoding="utf-8"))
    assert any(i["code"] == "TAG-ENUM" for i in data["issues"])
