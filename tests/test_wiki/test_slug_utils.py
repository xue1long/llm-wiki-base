"""Phase 1.3 B-H3 tests — 统一 slug 归一函数（对账/stub/wikilink 共用）。"""
from __future__ import annotations

from src.wiki.features.slug_utils import normalize_reconcile_slug


def test_preserves_cjk_punctuation():
    """磁盘 id 保留 CJK 顿号（语言-、-动作-、-神态结合描写）时，归一不得剥掉
    顿号——这是旧 normalize_id_chars 造成假断链的根源（B-H3）。"""
    disk_id = "语言-、-动作-、-神态结合描写"
    assert normalize_reconcile_slug(disk_id) == disk_id


def test_natural_wikilink_matches_disk_id():
    """自然 wikilink [[语言、动作、神态结合描写]] 归一后应与磁盘 id
    ``语言-、-动作-、-神态结合描写`` 一致（假断链消解）。"""
    link = "语言、动作、神态结合描写"
    assert normalize_reconcile_slug(link) == "语言-、-动作-、-神态结合描写"


def test_strips_type_prefix():
    """LLM 把提示词里的类型标签抄进 target 时（concept-xxx）剥离前缀。"""
    assert normalize_reconcile_slug("concept-穿越小说角色塑造套路") == "穿越小说角色塑造套路"
    assert normalize_reconcile_slug("entity-总裁文") == "总裁文"
    assert normalize_reconcile_slug("source-补充教程") == "补充教程"


def test_strips_wikilink_bracket_and_suffix():
    assert normalize_reconcile_slug("[[佛本是道]]") == "佛本是道"
    assert normalize_reconcile_slug("[[装逼打脸|别名]]") == "装逼打脸"
    assert normalize_reconcile_slug("[[家庭烧伤处理#处理步骤]]") == "家庭烧伤处理"


def test_lowercases_ascii_only():
    assert normalize_reconcile_slug("OpenAI-写作") == "openai-写作"
    assert normalize_reconcile_slug("QiDaiGan") == "qidaigan"


def test_collapses_double_hyphens_and_strips_edges():
    assert normalize_reconcile_slug("--家庭烧伤处理--") == "家庭烧伤处理"
    assert normalize_reconcile_slug("a--b") == "a-b"


def test_idempotent():
    once = normalize_reconcile_slug("concept-语言、动作、神态结合描写")
    assert normalize_reconcile_slug(once) == once


def test_empty_and_none_safe():
    assert normalize_reconcile_slug("") == ""
    assert normalize_reconcile_slug(None) == ""
    assert normalize_reconcile_slug("   ") == ""
