# tests/test_wiki/test_lint.py
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.lint import lint_wiki, LintSeverity
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.features.indexer import append_to_index


def test_lint_clean_wiki_no_issues(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Pages carry sources so they are clean under LINT-MISSING-SOURCES too.
    write_page(p, WikiPage(id="foo", title="Foo", type=PageType.ENTITY, body="Hello world", sources=["a.md"]))
    write_page(p, WikiPage(id="bar", title="Bar", type=PageType.CONCEPT, body="Other content", sources=["b.md"]))
    append_to_index(p, [("foo", PageType.ENTITY, "Foo"), ("bar", PageType.CONCEPT, "Bar")])

    report = lint_wiki(p)
    assert report.scanned_pages == 2
    assert report.issues == []


def test_lint_counts_files_with_duplicate_page_ids(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="shared", title="Entity", type=PageType.ENTITY, body="Entity body"))
    write_page(p, WikiPage(id="shared", title="Concept", type=PageType.CONCEPT, body="Concept body"))

    report = lint_wiki(p)

    assert report.scanned_pages == 2


def test_lint_detects_orphan(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Write page but don't add to index
    write_page(p, WikiPage(id="orphan", title="Orphan", type=PageType.ENTITY, body="..."))
    append_to_index(p, [])  # empty index

    report = lint_wiki(p)
    codes = [i.code for i in report.issues]
    assert "LINT-ORPHAN" in codes


def test_lint_detects_duplicate_content(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = "Identical content"
    write_page(p, WikiPage(id="dup1", title="Dup1", type=PageType.ENTITY, body=body))
    write_page(p, WikiPage(id="dup2", title="Dup2", type=PageType.ENTITY, body=body))
    append_to_index(p, [("dup1", PageType.ENTITY, "Dup1"), ("dup2", PageType.ENTITY, "Dup2")])

    report = lint_wiki(p)
    codes = [i.code for i in report.issues]
    assert "LINT-DUPLICATE" in codes


def test_lint_detects_empty_body(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="empty", title="Empty", type=PageType.ENTITY, body=""))
    append_to_index(p, [("empty", PageType.ENTITY, "Empty")])

    report = lint_wiki(p)
    empty_issues = [i for i in report.issues if i.code == "LINT-EMPTY-BODY"]
    assert len(empty_issues) == 1
    assert empty_issues[0].severity == LintSeverity.INFO


# ---------------------------------------------------------------------------
# Plan 27 (wiki v2.3 schema) — LINT-MISSING-SECTION (version-gated).
# ---------------------------------------------------------------------------


from pathlib import Path


def _write_page_with_version(paths, slug, title, page_type, body, version):
    """Write a page whose raw file declares a ``wiki-template-version``.

    Strategy: use ``write_page`` so the YAML frontmatter is well-formed
    and ``read_page`` can recover the page type. Then append the
    template-version comment to the END of the file (not the start) so
    it doesn't confuse ``read_page``'s ``text.startswith("---\n")``
    check, but the lint rule's raw-file scanner still finds it.
    """
    write_page(
        paths,
        WikiPage(
            id=slug, title=title, type=page_type, body=body,
        ),
    )
    from src.wiki.storage.page_writer import page_path_for
    md_path = page_path_for(paths, page_type, slug)
    with md_path.open("a", encoding="utf-8") as fh:
        fh.write(
            f"\n<!-- wiki-template-version: {version} -->\n"
            f"<!-- wiki-template-type: {page_type.value} -->\n"
        )


def test_lint_missing_section_warns_v2_template(tmp_path):
    """v2 template page missing required heading → LINT-MISSING-SECTION WARNING."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    # Concept page with body that has only '## 定义', missing the other
    # four required headings (主要特点 / 例子 / 相关概念 / 参考来源).
    body = (
        "## 定义\n\n"
        "只剩这一个 section，其他 required heading 全部缺失。\n"
    )
    _write_page_with_version(p, "kb-1", "示例", PageType.CONCEPT, body, "2.0.0")
    append_to_index(p, [("kb-1", PageType.CONCEPT, "示例")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SECTION"]
    assert len(missing) == 1
    assert missing[0].severity == LintSeverity.WARNING
    assert missing[0].page_id == "kb-1"
    # Message names the missing headings.
    msg = missing[0].message
    for label in ("主要特点", "例子", "相关概念", "参考来源"):
        assert label in msg, f"expected missing heading {label!r} in message: {msg}"


def test_lint_missing_section_silent_v1_template(tmp_path):
    """v1 template page is exempt from the missing-section check."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    body = "## 定义\n\nOnly one section — v1 templates don't enforce structure."
    _write_page_with_version(p, "kb-2", "旧版", PageType.CONCEPT, body, "1.0.0")
    append_to_index(p, [("kb-2", PageType.CONCEPT, "旧版")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SECTION"]
    assert missing == [], f"v1 page must not trigger MISSING-SECTION, got: {missing}"


def test_lint_full_v2_page_clean(tmp_path):
    """v2 page with all required headings → no MISSING-SECTION warning."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    body = (
        "## 定义\n\n定义内容。\n\n"
        "## 主要特点\n\n要点 A。\n\n"
        "## 例子\n\n例 1。\n\n"
        "## 相关概念\n\n[[other-slug]]\n\n"
        "## 参考来源\n\nfoo.md\n"
    )
    _write_page_with_version(p, "kb-3", "完整概念", PageType.CONCEPT, body, "2.0.0")
    append_to_index(p, [("kb-3", PageType.CONCEPT, "完整概念")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SECTION"]
    assert missing == []


def test_lint_version_with_three_components(tmp_path):
    """Version comparison handles 2.1, 2.0.1, 2.1.3 etc."""
    from src.wiki.features.lint import _parse_version
    assert _parse_version("2.0") >= (2, 0, 0)
    assert _parse_version("2.1") >= (2, 0, 0)
    assert _parse_version("1.9.9") < (2, 0, 0)
    assert _parse_version("2.1.3") >= (2, 0, 0)


# ---------------------------------------------------------------------------
# Phase 3.1 — deterministic content checks:
# LINT-RAW-PASTE / LINT-MISSING-SOURCES / LINT-UGC-CRED.
# ---------------------------------------------------------------------------


def test_lint_raw_paste_detects_long_plain_paragraph(tmp_path):
    """Concept page with a >300-char unstructured paragraph → LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    paragraph = "\n".join(
        "这是第 {} 行未经处理的原始文本，整段都是连续的长篇叙述，"
        "没有任何 markdown 标记结构。".format(i)
        for i in range(10)
    )
    assert len(paragraph) > 300  # the fixture really is a raw-paste-sized run
    write_page(
        p,
        WikiPage(
            id="raw", title="Raw", type=PageType.CONCEPT,
            body=paragraph, sources=["a.md"],
        ),
    )
    append_to_index(p, [("raw", PageType.CONCEPT, "Raw")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert len(raw) == 1
    assert raw[0].severity == LintSeverity.WARNING
    assert raw[0].page_id == "raw"


def test_lint_raw_paste_exempts_source_pages(tmp_path):
    """Source pages carry full main_content legitimately → no LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    paragraph = "\n".join(
        "这是第 {} 行未经处理的原始文本，整段都是连续的长篇叙述，"
        "没有任何 markdown 标记结构。".format(i)
        for i in range(10)
    )
    write_page(
        p,
        WikiPage(
            id="src", title="Src", type=PageType.SOURCE,
            body=paragraph, sources=["raw.md"],
        ),
    )
    append_to_index(p, [("src", PageType.SOURCE, "Src")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert raw == []


def test_lint_raw_paste_ignores_blockquotes_and_list_items(tmp_path):
    """A long body made of blockquotes / list items → no LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    lines = ["> 引用第 {} 行：这是一段很长的引用内容正文。".format(i) for i in range(20)]
    lines += ["- 列表第 {} 项：这是一段很长的列表内容正文。".format(i) for i in range(20)]
    lines += ["12. 有序列表第 {} 项：这是一段很长的有序列表内容。".format(i) for i in range(20)]
    body = "\n".join(lines)
    assert len(body) > 300
    write_page(
        p,
        WikiPage(
            id="mk", title="Mk", type=PageType.CONCEPT,
            body=body, sources=["a.md"],
        ),
    )
    append_to_index(p, [("mk", PageType.CONCEPT, "Mk")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert raw == []


def test_lint_raw_paste_ignores_code_fence(tmp_path):
    """A long verbatim block inside a ``` fence → no LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = "```\n" + "\n".join("verbatim line {}" .format(i) * 8 for i in range(20)) + "\n```"
    write_page(
        p,
        WikiPage(
            id="code", title="Code", type=PageType.CONCEPT,
            body=body, sources=["a.md"],
        ),
    )
    append_to_index(p, [("code", PageType.CONCEPT, "Code")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert raw == []


def test_lint_missing_sources_detects_empty_sources(tmp_path):
    """Page with empty sources and no derivation relation → LINT-MISSING-SOURCES."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(
        p,
        WikiPage(id="nosrc", title="NoSrc", type=PageType.CONCEPT, body="正文内容。"),
    )
    append_to_index(p, [("nosrc", PageType.CONCEPT, "NoSrc")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SOURCES"]
    assert len(missing) == 1
    assert missing[0].severity == LintSeverity.WARNING
    assert missing[0].page_id == "nosrc"


def test_lint_missing_sources_silent_when_sources_set(tmp_path):
    """Synthesis page listing its sources → no LINT-MISSING-SOURCES."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(
        p,
        WikiPage(
            id="syn", title="Syn", type=PageType.SYNTHESIS,
            body="## 综述\n\n对比内容。",
            sources=["raw/a.md", "raw/b.md"],
        ),
    )
    append_to_index(p, [("syn", PageType.SYNTHESIS, "Syn")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SOURCES"]
    assert missing == []


def test_lint_missing_sources_silent_with_derived_from_relation(tmp_path):
    """Empty sources but a derived_from relation → no LINT-MISSING-SOURCES."""
    from src.wiki.features.relations import Relation
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(
        p,
        WikiPage(
            id="der", title="Der", type=PageType.CONCEPT, body="正文内容。",
            relations=[Relation(target_id="src-a", type="derived_from")],
        ),
    )
    append_to_index(p, [("der", PageType.CONCEPT, "Der")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SOURCES"]
    assert missing == []


def test_lint_ugc_cred_detects_ugc_without_credibility(tmp_path):
    """Page tagged 素材/ugc but missing 可信度/ugc → LINT-UGC-CRED."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(
        p,
        WikiPage(
            id="ugc", title="UGC", type=PageType.CONCEPT, body="正文内容。",
            tags=["素材/ugc"], sources=["a.md"],
        ),
    )
    append_to_index(p, [("ugc", PageType.CONCEPT, "UGC")])

    report = lint_wiki(p)
    ugc = [i for i in report.issues if i.code == "LINT-UGC-CRED"]
    assert len(ugc) == 1
    assert ugc[0].severity == LintSeverity.WARNING
    assert ugc[0].page_id == "ugc"


def test_lint_ugc_cred_silent_when_credibility_tag_present(tmp_path):
    """Page tagged both 素材/ugc and 可信度/ugc → no LINT-UGC-CRED."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(
        p,
        WikiPage(
            id="ugc2", title="UGC2", type=PageType.CONCEPT, body="正文内容。",
            tags=["素材/ugc", "可信度/ugc"], sources=["a.md"],
        ),
    )
    append_to_index(p, [("ugc2", PageType.CONCEPT, "UGC2")])

    report = lint_wiki(p)
    ugc = [i for i in report.issues if i.code == "LINT-UGC-CRED"]
    assert ugc == []