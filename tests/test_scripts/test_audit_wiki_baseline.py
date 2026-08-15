"""Phase 0.1 tests — audit_wiki_baseline.py against a minimal wiki.

Verifies the spec §6 metric calculations (M1/M2/M6/M7 via the shared
metrics core), the audit counts (stub / legacy tags / illegal relations),
and the --json baseline output. Uses a tmp wiki fixture so the test is
self-contained (no dependency on the real novel-wiki data).
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
    """Project root with raw files + a small typed wiki."""
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    for name in ("a.md", "b.md", "c.md"):
        (tmp_path / "raw" / "sources" / name).write_text(
            f"raw {name} content", encoding="utf-8")

    def page(rel: str, content: str) -> None:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    page("wiki/sources/s-a.md",
         "---\nid: s-a\ntitle: SrcA\ntype: source\nsources:\n- raw/sources/a.md\n"
         "relations:\n- target: c1\n  type: references\n---\n\n## 来源元数据\n\nx\n"
         "\n## 正文内容\n\n全文粘贴污染\n")  # M7 pollution on purpose
    page("wiki/concepts/c1.md",
         "---\nid: c1\ntitle: Concept1\ntype: concept\nsources:\n- raw/sources/a.md\n"
         "relations:\n- target: ghost-slug\n  type: references\n---\n\n## 定义\n\n[[s-a]]\n"
         "## 适用场景\n\n见下游概念页\n")  # placeholder substring + ghost relation target
    page("wiki/concepts/c2.md",
         "---\nid: c2\ntitle: Concept2\ntype: concept\nsources:\n- raw/sources/b.md\n"
         "grade: C\nprocessing_depth: stub\ntags:\n- func/旧前缀\n---\n\n## 定义\n\nb\n")  # stub + legacy tag
    page("wiki/entities/e1.md",
         "---\nid: e1\ntitle: Ent1\ntype: entity\nsources:\n- raw/sources/a.md\n"
         "relations:\n- target: c1\n  type: related_to\n---\n\n## 简介\n\n[[c1]]\n")  # illegal relation type
    page("wiki/synthesis/syn1.md",
         "---\nid: syn1\ntitle: Syn1\ntype: synthesis\nsources:\n- raw/sources/a.md\n"
         "- raw/sources/c.md\n---\n\n## 议题\n\n## 各方观点\n\n- [[c1]]\n")
    page("wiki/index.md", "# Wiki Index\n\n- **c1** (concept) — C1\n- **c2** (concept) — C2\n")
    return tmp_path


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_wiki_baseline.py"),
         str(root), *extra],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
    )


def test_baseline_counts(mini_wiki: Path) -> None:
    r = _run(mini_wiki)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "raw_md               3" in out
    assert "wiki_pages_total     5" in out
    assert "stub_pages           1" in out
    assert "legacy_tag_pages     1" in out
    assert "illegal_relation_pages 1" in out
    # M7: s-a has 正文内容 → 1
    assert "M7_source_fulltext   1" in out
    # M6: 1 synthesis page
    assert "M6_synthesis_pages   1" in out
    # M1: c1 relation target ghost-slug not on disk → broken; s-a→c1 known;
    # e1→c1 known; c1 body [[s-a]] known. ghost-slug is the only broken link.
    assert "M1_broken_links      1" in out
    # M2: deep refs = a (syn1) + c (syn1); b only via self-produced c2 → not deep.
    assert "M2_deep_ref_rate_pct 66.7" in out


def test_baseline_json(mini_wiki: Path) -> None:
    out_json = mini_wiki / ".index" / "baseline_test.json"
    r = _run(mini_wiki, "--json", str(out_json))
    assert r.returncode == 0, r.stderr
    data = json.loads(out_json.read_text(encoding="utf-8"))
    m = data["metrics"]
    assert m["M1_broken_links"] == 1
    assert m["M2_total_raw"] == 3
    assert m["M7_source_fulltext"] == 1
    assert m["M8_legacy_tag_pages"] == 1
    assert m["M9_illegal_relation_pages"] == 1
    assert data["counts"]["stub_pages"] == 1
    assert data["counts"]["index_entries"] == 2
