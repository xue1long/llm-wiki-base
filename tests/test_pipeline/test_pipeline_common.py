"""Tests for src/pipeline/_pipeline_common.py — clean_source_text and helpers."""
from src.pipeline._pipeline_common import clean_source_text, denoise_source_text


def test_clean_source_text_strips_zero_width_chars():
    """Zero-width characters (ZWSP, ZWNJ, ZWJ, BOM) are removed."""
    assert "\u200b" not in clean_source_text("hello\u200bworld")
    assert "\ufeff" not in clean_source_text("\ufeffBOM text")
    assert "hello" in clean_source_text("hello\u200bworld")
    assert "BOM text" in clean_source_text("\ufeffBOM text")


def test_clean_source_text_collapses_excessive_blank_lines():
    """3+ consecutive blank lines collapsed to 2."""
    result = clean_source_text("line 1\n\n\n\n\nline 2")
    assert "\n\n\n" not in result
    assert "line 1" in result
    assert "line 2" in result


def test_clean_source_text_preserves_two_blank_lines():
    """2 blank lines preserved (valid markdown separator)."""
    result = clean_source_text("a\n\nb")
    assert result.startswith("a\n\nb")


def test_clean_source_text_preserves_all_content():
    """All actual text content survives cleaning."""
    text = "标题\n\n正文内容\n- 列表项 1\n- 列表项 2\n\n结尾"
    result = clean_source_text(text)
    assert "标题" in result
    assert "正文内容" in result
    assert "列表项 1" in result
    assert "列表项 2" in result
    assert "结尾" in result


def test_clean_source_text_empty_input():
    """Empty or whitespace-only input returns empty string."""
    assert clean_source_text("") == ""
    assert clean_source_text("   \n  ") == ""


def test_clean_source_text_adds_trailing_newline():
    """Non-empty result always ends with a single newline."""
    result = clean_source_text("hello")
    assert result.endswith("\n")
    assert not result.endswith("\n\n")


def test_clean_source_text_handles_mixed_whitespace():
    """Blank lines with spaces/tabs collapsed correctly — 4 blank lines → 2."""
    text = "a\n \n\t\n   \nb"
    result = clean_source_text(text)
    # 3+ consecutive blank lines (each containing only spaces/tabs) collapsed to 2.
    # The text after the collapse area ("   \nb") is preserved.
    assert "a" in result
    assert "b" in result
    assert "\n\n\n" not in result  # no 3-consecutive blank lines


# ---------------------------------------------------------------------------
# denoise_source_text — rule-based platform-chrome removal (main_content fallback)
# ---------------------------------------------------------------------------


def test_denoise_strips_leading_yaml_frontmatter():
    text = "---\ntitle: 出版经验分享2\ncreated: 2026-04-09\n---\n# 标题\n正文内容"
    out = denoise_source_text(text)
    assert "title: 出版经验分享2" not in out
    assert "created:" not in out
    assert "正文内容" in out


def test_denoise_removes_flybook_metadata_and_platform_lines():
    text = (
        "# 东方玄幻_烛龙 -\n\n"
        "来源：https://www.feishu.cn/docx/SQXIdUW1oo75PNxh6SDcuuqRn1c\n\n"
        "下载时间：2026-04-14 17:27:24\n\n"
        "飞书云文档\n"
        "最新修改时间为04月13日\n\n"
        "正文内容在这里"
    )
    out = denoise_source_text(text)
    assert "feishu.cn" not in out
    assert "下载时间" not in out
    assert "飞书云文档" not in out
    assert "最新修改时间" not in out
    assert "正文内容在这里" in out


def test_denoise_removes_flybook_ui_chrome_lines():
    text = (
        "内容开始\n"
        "登录/注册\n"
        "评论（0）\n"
        "帮助中心\n"
        "效率指南\n"
        "上传日志\n"
        "联系客服\n"
        "功能更新\n"
        "内容结束"
    )
    out = denoise_source_text(text)
    for noise in ("登录/注册", "评论（0）", "帮助中心", "效率指南",
                  "上传日志", "联系客服", "功能更新"):
        assert noise not in out, f"{noise} should be removed"
    assert "内容开始" in out
    assert "内容结束" in out


def test_denoise_removes_feishu_h1_dash_artifact():
    text = "# [进阶教程]无线秘籍(1) -\n\n正文"
    out = denoise_source_text(text)
    assert "# [进阶教程]无线秘籍(1) -" not in out
    assert "正文" in out


def test_denoise_removes_transcript_footer():
    text = "正文内容\n---\n*此文档由 GPU 加速转录生成*"
    out = denoise_source_text(text)
    assert "GPU 加速转录" not in out
    assert "正文内容" in out


def test_denoise_removes_newer_flybook_export_chrome():
    text = (
        "北京圣东方国信科技有限公司\n"
        "外部\n"
        "最近修改: 昨天 23:17\n"
        "分享\n"
        "编辑\n"
        "添加图标\n"
        "添加封面\n"
        "展示文档信息\n"
        "13.作品仆街后的出路\n"
        "这是正文"
    )
    out = denoise_source_text(text)
    assert "外部" not in out
    assert "最近修改:" not in out
    assert "分享\n" not in out
    assert "添加图标" not in out
    assert "展示文档信息" not in out
    assert "13.作品仆街后的出路" in out  # content kept
    assert "这是正文" in out
    # org name is dataset-specific — the generic denoiser must NOT remove it
    # (a different feishu workspace has a different org; exact-match would
    # silently drop legitimate content if a doc were about that org).
    assert "北京圣东方国信科技有限公司" in out


def test_denoise_is_lossless_for_content_lines():
    """Content lines outside the denylist survive verbatim (not just 'in')."""
    text = (
        "START\n"
        "　烛龙\n"
        "　　中国古代神话中的神兽。\n"
        "1、列表项\n"
        "- bullet\n"
        "| 表格 | 行 |\n"
        "正文末尾"
    )
    out = denoise_source_text(text)
    for line in text.splitlines():
        assert line in out, f"content line lost: {line!r}"


def test_denoise_removes_standalone_chrome_but_keeps_word_inside_content():
    """Documented tradeoff: a bare ``编辑`` line (feishu button) is removed,
    but the word inside a longer content line is preserved."""
    text = "本章讨论编辑工作\n编辑\n继续正文"
    out = denoise_source_text(text)
    assert "编辑\n" not in out
    assert "本章讨论编辑工作" in out
    assert "继续正文" in out


def test_denoise_empty_input():
    assert denoise_source_text("") == ""
    assert denoise_source_text("   \n  ") == ""
