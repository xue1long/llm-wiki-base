"""Phase 0.2 tests — audit_blindspots.py census functions.

Exercises the deterministic B-items (B1 backlog, B3 stub refs, B5 tags,
B6 aliases, B9 taxonomy_sub, B12 broken-link classification) against a
minimal tmp wiki so Phase 4 batch planning can rely on the script.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    # 3 md raws: one tiny (<500), one normal, one long (>16000)
    (tmp_path / "raw" / "sources" / "tiny.md").write_text("短", encoding="utf-8")
    (tmp_path / "raw" / "sources" / "normal.md").write_text(
        "普通内容" * 300, encoding="utf-8")  # 900 chars
    (tmp_path / "raw" / "sources" / "long.md").write_text(
        "长内容" * 6000, encoding="utf-8")  # 18000 chars > 16000
    (tmp_path / "raw" / "sources" / "dup.md").write_text(
        "普通内容" * 300, encoding="utf-8")  # duplicate of normal.md
    (tmp_path / "raw" / "sources" / "not_md.txt").write_text("x", encoding="utf-8")

    def page(rel: str, content: str) -> None:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    page("wiki/sources/s-a.md",
         "---\nid: s-a\ntitle: SrcA\ntype: source\nsources:\n- raw/sources/normal.md\n"
         "tags:\n- 素材/ugc\n- 可信度/ugc\n---\n\n## 摘要\n\nx\n")
    page("wiki/concepts/c-stub.md",
         "---\nid: c-stub\ntitle: CStub\ntype: concept\nsources:\n- raw/sources/normal.md\n"
         "processing_depth: stub\n---\n\n## 定义\n\nstub\n")
    page("wiki/concepts/c1.md",
         "---\nid: c1\ntitle: Concept1\ntype: concept\nsources:\n- raw/sources/normal.md\n"
         "taxonomy_sub: 人物塑造\n---\n\n## 定义\n\n[[c-stub]]\n[[normal]]\n[[ghost-x]]\n"
         "[[normal-abcdef01]]\n")
    page("wiki/index.md", "# Wiki Index\n")
    return tmp_path


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_blindspots.py"),
         str(root), *extra],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
    )


def test_blindspots_census(mini_wiki: Path) -> None:
    r = _run(mini_wiki)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)

    # B1: 3 unique md (tiny + normal + long; dup.md is duplicate_of);
    # not_md.txt is unhandled.
    b1 = data["B1_backlog"]
    assert b1["total_md"] == 3
    assert b1["tiny_count"] == 1
    assert b1["long_docs_count"] == 1
    assert b1["duplicate_of_count"] == 1
    assert b1["unhandled_format_count"] == 1

    # B3: 1 stub (c-stub); c1 references it → 1 referencing page
    b3 = data["B3_stub"]
    assert b3["stub_pages"] == 1
    assert b3["pages_referencing_stubs"] == 1

    # B5: 素材/ugc + 可信度/ugc on s-a
    b5 = data["B5_tags"]
    assert b5["素材"] == {"ugc": 1}
    assert b5["可信度"] == {"ugc": 1}

    # B6: no alias file
    assert data["B6_slug_aliases"] == 0

    # B9: c1 has taxonomy_sub=人物塑造
    assert data["B9_taxonomy_sub"]["人物塑造"] == 1

    # B12: c1 links: [[c-stub]] (known → not broken), [[normal]] (raw stem →
    # unreferenced_raw), [[ghost-x]] (other), [[normal-abcdef01]] (hash → hallucinated)
    b12 = data["B12_broken_class"]
    assert b12["counts"]["unreferenced_raw"] == 1
    assert b12["counts"]["hallucinated_source_hash"] == 1
    assert b12["counts"]["other"] == 1
