# tests/test_wiki/test_lint.py
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.lint import lint_wiki, LintSeverity, _is_ugc_carrier
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.features.indexer import append_to_index


# ---------------------------------------------------------------------------
# Phase 1.2 new rules (plan 1.2: placeholder / illegal relation /
# synthesis gate / RAW-PASTE severity)
# ---------------------------------------------------------------------------

def _make_page(paths, slug, page_type, body, *, sources=None, relations=None):
    page = WikiPage(id=slug, title=slug, type=page_type, body=body,
                    sources=sources or [], relations=relations or [])
    write_page(paths, page)
    from src.wiki.storage.page_writer import page_path_for
    md_path = page_path_for(paths, page_type, slug)
    with md_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n<!-- wiki-template-version: 3.0.0 -->\n"
                 f"<!-- wiki-template-type: {page_type.value} -->\n")
    return md_path


def test_lint_page_subset_scope(tmp_path):
    """plan 1.8: lint_wiki(page_ids=...) only scans the given pages.

    A dirty legacy page outside the batch must not produce issues when the
    batch scope excludes it; an in-scope page still gets flagged.
    """
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "bad-1", PageType.CONCEPT,
               "## 定义\n\n见下游概念页\n",
               sources=["raw/sources/a.md"])
    _make_page(p, "good-1", PageType.CONCEPT,
               "## 定义\n\ndef\n\n## 主要特点\n\nc\n\n## 例子\n\ne\n\n"
               "## 相关概念\n\n[[x]]\n\n## 参考来源\n\ns\n",
               sources=["raw/sources/a.md"])
    # Whole library: bad-1 flagged
    report = lint_wiki(p)
    assert any(i.code == "LINT-PLACEHOLDER" and i.page_id == "bad-1"
               for i in report.issues)
    # Batch scope = only good-1 → no placeholder issue, scanned == 1
    scoped = lint_wiki(p, page_ids={"good-1"})
    assert scoped.scanned_pages == 1
    assert not [i for i in scoped.issues if i.code == "LINT-PLACEHOLDER"]


def test_lint_placeholder_rule(tmp_path):
    """Placeholder substring in body → LINT-PLACEHOLDER ERROR."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "ph-1", PageType.CONCEPT,
               "## 定义\n\n见下游概念页\n",
               sources=["raw/sources/a.md"])
    report = lint_wiki(p)
    hits = [i for i in report.issues if i.code == "LINT-PLACEHOLDER"]
    assert len(hits) == 1
    assert hits[0].severity == LintSeverity.ERROR


def test_lint_placeholder_clean(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "ph-ok", PageType.CONCEPT,
               "## 定义\n\n正常内容\n",
               sources=["raw/sources/a.md"])
    report = lint_wiki(p)
    assert not [i for i in report.issues if i.code == "LINT-PLACEHOLDER"]


def test_lint_illegal_relation(tmp_path):
    """relations[].type outside 17 built-ins + x-* → LINT-ILLEGAL-RELATION."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    from src.wiki.features.relations import Relation
    rel = Relation(target_id="x", type="related_to", weight=0.5)
    _make_page(p, "rel-1", PageType.CONCEPT,
               "## 定义\n\n内容\n",
               sources=["raw/sources/a.md"], relations=[rel])
    report = lint_wiki(p)
    hits = [i for i in report.issues if i.code == "LINT-ILLEGAL-RELATION"]
    assert len(hits) == 1
    assert hits[0].severity == LintSeverity.ERROR
    # x-* is allowed
    rel2 = Relation(target_id="x", type="x-致敬", weight=0.5)
    _make_page(p, "rel-2", PageType.CONCEPT,
               "## 定义\n\n内容\n",
               sources=["raw/sources/a.md"], relations=[rel2])
    report2 = lint_wiki(p)
    assert not [i for i in report2.issues
                if i.code == "LINT-ILLEGAL-RELATION" and i.page_id == "rel-2"]


def test_lint_synthesis_gate(tmp_path):
    """v3.0.0 synthesis page with <2 viewpoint wikilinks → ERROR."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Sources page so the synthesis can link it.
    _make_page(p, "s-a", PageType.SOURCE, "## 摘要\n\nx\n",
               sources=["raw/sources/a.md"])
    _make_page(p, "syn-bad", PageType.SYNTHESIS,
               "## 议题\n\n话题\n\n## 各方观点\n\n- 观点一\n\n"
               "## 共识\n\nc\n\n## 证据对比\n\ne\n\n## 待定与结论\n\nz\n",
               sources=["raw/sources/a.md", "raw/sources/b.md"])
    report = lint_wiki(p)
    hits = [i for i in report.issues if i.code == "LINT-SYNTHESIS-GATE"]
    assert len(hits) == 1
    assert hits[0].severity == LintSeverity.ERROR
    assert hits[0].page_id == "syn-bad"
    # two wikilinks pass (check only the new page — syn-bad stays flagged)
    _make_page(p, "syn-ok", PageType.SYNTHESIS,
               "## 议题\n\n话题\n\n## 各方观点\n\n- [[s-a]] 观点一\n- [[s-a]] 观点二\n\n"
               "## 共识\n\nc\n\n## 证据对比\n\ne\n\n## 待定与结论\n\nz\n",
               sources=["raw/sources/a.md", "raw/sources/b.md"])
    report2 = lint_wiki(p)
    assert not [i for i in report2.issues
                if i.code == "LINT-SYNTHESIS-GATE" and i.page_id == "syn-ok"]


def test_lint_raw_paste_source_fulltext_is_error(tmp_path):
    """Source page with 正文内容 section → RAW-PASTE ERROR (was WARNING)."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "src-1", PageType.SOURCE,
               "## 来源元数据\n\nm\n\n## 摘要\n\ns\n\n## 正文内容\n\n全文\n",
               sources=["raw/sources/a.md"])
    report = lint_wiki(p)
    hits = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert hits and hits[0].severity == LintSeverity.ERROR


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
    """v2 template page missing required heading → LINT-MISSING-SECTION ERROR.

    Severity upgraded from WARNING to ERROR in plan 1.2 (H2) so the gate
    can enforce M4; the test name is kept for continuity.
    """
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
    assert missing[0].severity == LintSeverity.ERROR
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


def test_lint_v2_page_clean_under_project_v3_template(tmp_path):
    """Phase 3 实测回归：项目级 v3.0.0 模板存在时，2.0.0 存量页按 2.0.0
    槽检查，不得被要求填 v3.0.0 新增槽（适用场景/反模式/证据强度）。

    novel-wiki 首批实测暴露：lint MISSING-SECTION 用项目解析模板（v3.0.0）
    的必填槽集检查所有页，导致声明 2.0.0 的存量页被误报缺失
    v3.0.0 槽（H3 版本门语义 = 存量 2.0.0 页仍按 ≥2.0.0 检查）。
    """
    from src.wiki.templates.types import PROJECT_TEMPLATE_DIRNAME

    p = ensure_knowledge_base(tmp_path)
    # 项目级 v3.0.0 concept 模板（含 v3.0.0 新增槽）
    tpl_dir = tmp_path / PROJECT_TEMPLATE_DIRNAME
    tpl_dir.mkdir(parents=True, exist_ok=True)
    (tpl_dir / "concept.md").write_text(
        "<!-- wiki-template-version: 3.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n\n"
        "## 主要特点\n\n<!-- slot:characteristics -->\n\n"
        "## 适用场景\n\n<!-- slot:context -->\n\n"
        "## 反模式与常见错误\n\n<!-- slot:anti_patterns -->\n\n"
        "## 证据强度\n\n<!-- slot:evidence -->\n\n"
        "## 例子\n\n<!-- slot:examples -->\n\n"
        "## 相关概念\n\n<!-- slot:related_concepts -->\n\n"
        "## 参考来源\n\n<!-- slot:references -->\n",
        encoding="utf-8",
    )

    # 2.0.0 存量页：只有 bundled 2.0.0 的 5 个槽
    body = (
        "## 定义\n\n定义内容。\n\n"
        "## 主要特点\n\n要点 A。\n\n"
        "## 例子\n\n例 1。\n\n"
        "## 相关概念\n\n[[other-slug]]\n\n"
        "## 参考来源\n\nfoo.md\n"
    )
    _write_page_with_version(p, "kb-20", "旧概念", PageType.CONCEPT, body, "2.0.0")
    append_to_index(p, [("kb-20", PageType.CONCEPT, "旧概念")])

    report = lint_wiki(p)
    missing = [i for i in report.issues if i.code == "LINT-MISSING-SECTION"]
    assert missing == [], (
        f"2.0.0 存量页不得被要求 v3.0.0 新增槽，got: {[m.message for m in missing]}"
    )


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


def test_lint_raw_paste_flags_source_page_with_fulltext_heading(tmp_path):
    """NDG Phase 2: source page with full-text section heading → LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = "## 来源\n\nsome meta\n\n## 正文内容\n\n" + ("全文文本内容。" * 50)
    write_page(
        p,
        WikiPage(
            id="src-full", title="SrcFull", type=PageType.SOURCE,
            body=body, sources=["raw.md"],
        ),
    )
    append_to_index(p, [("src-full", PageType.SOURCE, "SrcFull")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert len(raw) == 1, f"source page with 正文内容 heading must be flagged, got {raw}"
    assert raw[0].page_id == "src-full"
    assert "full-text" in raw[0].message.lower() or "正文内容" in raw[0].message


def test_lint_raw_paste_flags_source_page_with_transcript_heading(tmp_path):
    """NDG Phase 2: source page with 转录内容 heading → LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = "## 转录内容\n\n" + ("会议记录文本。" * 20)
    write_page(
        p,
        WikiPage(
            id="src-trans", title="SrcTrans", type=PageType.SOURCE,
            body=body, sources=["raw.md"],
        ),
    )
    append_to_index(p, [("src-trans", PageType.SOURCE, "SrcTrans")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert len(raw) == 1
    assert raw[0].page_id == "src-trans"


def test_lint_raw_paste_ignores_fulltext_heading_inside_code_fence(tmp_path):
    """NDG Phase 2: fulltext heading inside a ``` fence → no false positive."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = (
        "## 摘要\n\nA short summary.\n\n"
        "```markdown\n"
        "## 正文内容\n"
        "这个是代码示例中的标题，不是真实 section。\n"
        "```\n"
    )
    write_page(
        p,
        WikiPage(
            id="src-code", title="SrcCode", type=PageType.SOURCE,
            body=body, sources=["raw.md"],
        ),
    )
    append_to_index(p, [("src-code", PageType.SOURCE, "SrcCode")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert raw == [], f"fulltext heading inside code fence must not flag, got {raw}"


def test_lint_raw_paste_source_page_with_short_distilled_body(tmp_path):
    """NDG Phase 2: source page with short summary, no fulltext heading → clean."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = "## 摘要\n\n这是一段简短的蒸馏摘要，大约一百字左右。描述了文档的主要内容和关键发现。\n\n## 关键观点\n\n- 观点一\n- 观点二\n"
    write_page(
        p,
        WikiPage(
            id="src-ok", title="SrcOk", type=PageType.SOURCE,
            body=body, sources=["raw.md"],
        ),
    )
    append_to_index(p, [("src-ok", PageType.SOURCE, "SrcOk")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert raw == [], f"short distilled source page must be clean, got {raw}"


def test_lint_raw_paste_flags_source_page_with_long_raw_run(tmp_path):
    """NDG Phase 2: source page with >T_source raw run → LINT-RAW-PASTE."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Build a body just over _DEFAULT_T_SOURCE (2000) with no fulltext heading.
    paragraph = "\n".join(
        "这是第 {} 行未经处理的原始文本，整段都是连续的长篇叙述，没有任何 markdown 结构。".format(i)
        for i in range(60)
    )
    assert len(paragraph) > 2000
    body = "## 摘要\n\n" + paragraph
    write_page(
        p,
        WikiPage(
            id="src-long", title="SrcLong", type=PageType.SOURCE,
            body=body, sources=["raw.md"],
        ),
    )
    append_to_index(p, [("src-long", PageType.SOURCE, "SrcLong")])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert len(raw) == 1
    assert raw[0].page_id == "src-long"
    assert "Source page" in raw[0].message


def test_lint_raw_paste_flags_source_page_with_variant_fulltext_heading(tmp_path):
    """NDG Phase 2: 原文 / 全文 / 完整文本 headings also flag."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    for heading in ("原文", "全文", "完整文本"):
        write_page(
            p,
            WikiPage(
                id=f"src-{heading}", title=heading, type=PageType.SOURCE,
                body=f"## {heading}\n\n" + ("内容。" * 30), sources=["raw.md"],
            ),
        )
        append_to_index(p, [(f"src-{heading}", PageType.SOURCE, heading)])

    report = lint_wiki(p)
    raw = [i for i in report.issues if i.code == "LINT-RAW-PASTE"]
    assert len(raw) == 3, f"all three fulltext-heading variants must flag, got {len(raw)}"


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
    """Page tagged 素材/ugc but missing 可信度/ugc → LINT-UGC-CRED.

    Since write_page now enforces tag compliance, we write the invalid page
    directly to disk to simulate a pre-existing page from before the validation.
    """
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    from src.wiki.storage.page_writer import page_path_for
    page = WikiPage(
        id="ugc", title="UGC", type=PageType.CONCEPT, body="正文内容。",
        tags=["素材/ugc"], sources=["a.md"],
    )
    path = page_path_for(p, PageType.CONCEPT, "ugc")
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    fm = yaml.dump(page.to_frontmatter_dict(), allow_unicode=True, sort_keys=False,
                   default_flow_style=False)
    path.write_text(f"---\n{fm}---\n\n{page.body}", encoding="utf-8")
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


# ---------------------------------------------------------------------------
# R3-1 · _is_ugc_carrier — UGC carrier detection (D5 single source of truth).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("header", [
    "https://www.feishu.cn/docx/abc123",
    "https://mp.weixin.qq.com/s/xyz789",
    "来源：飞书云文档",
    "本文转载自公众号 写作技法",
    "整理自某小说论坛精华帖",
    "知乎高赞回答，作者匿名",
    "豆瓣书评摘录",
    "简书热门文章转载",
    "加QQ群 123456 领取资料",
])
def test_is_ugc_carrier_hits_known_platforms(header):
    assert _is_ugc_carrier(header), f"{header!r} should be a UGC carrier"


def test_is_ugc_carrier_case_insensitive():
    assert _is_ugc_carrier("FEISHU.CN 文档")
    assert _is_ugc_carrier("MP.WEIXIN.QQ.COM/s/abc")


def test_is_ugc_carrier_whitespace_tolerant():
    assert _is_ugc_carrier("  飞 书 云 文 档  ")
    assert _is_ugc_carrier("mp.weixin.qq. com 正文内容")
    assert _is_ugc_carrier("来源：公 众 号 整理")


def test_is_ugc_carrier_misses_normal_text():
    assert not _is_ugc_carrier("")
    assert not _is_ugc_carrier("普通文本，无任何 UGC 平台。")
    assert not _is_ugc_carrier("https://example.com/article/123")
    assert not _is_ugc_carrier("书籍《写作指南》第一章")
