"""Phase 1.7 tests — write_page is_immutable guard (F8)."""
from __future__ import annotations

import pytest

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page, read_page
from src.wiki.features.indexer import append_to_index


def _make(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="imm", title="不可变", type=PageType.CONCEPT,
                           body="## 定义\n\n内容\n"))
    append_to_index(p, [("imm", PageType.CONCEPT, "不可变")])
    # Mark immutable by rewriting frontmatter directly.
    path = p.wiki_concepts / "imm.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("is_immutable: false", "is_immutable: true")
    path.write_text(text, encoding="utf-8")
    return p, path


def test_overwrite_immutable_rejected(tmp_path):
    p, path = _make(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        write_page(p, WikiPage(id="imm", title="不可变", type=PageType.CONCEPT,
                               body="## 定义\n\n新内容\n"))
    # Original content preserved
    assert "新内容" not in path.read_text(encoding="utf-8")


def test_overwrite_normal_page_allowed(tmp_path):
    p, path = _make(tmp_path)
    # reset immutability
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("is_immutable: true", "is_immutable: false"),
                    encoding="utf-8")
    write_page(p, WikiPage(id="imm", title="不可变", type=PageType.CONCEPT,
                           body="## 定义\n\n新内容\n"))
    assert "新内容" in read_page(path).body


def test_immutable_flag_roundtrip(tmp_path):
    p, path = _make(tmp_path)
    assert read_page(path).is_immutable is True
