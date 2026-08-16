"""统一 slug 归一函数（plan 1.3 B-H3）。

对账、stub 判定、wikilink 解析三处共用同一归一函数，消除
``generator.normalize_id_chars`` 与 ``ingest._slugify`` 的分歧导致的
假断链（实测磁盘 id ``语言-、-动作-、-神态结合描写`` 保留 CJK 顿号，
而 ``normalize_id_chars`` 会把顿号剥掉，与自然 wikilink 归一不一致）。

归一规则（reconciliation 语义，核心委托 ``utils.slugify``）：
- slugify 对 CJK↔其它字符边界插入 ``-``（``语言、动作`` → ``语言-、-动作``），
  与磁盘页 id 的生成方式一致；对已是 slugify 产物的 id 幂等。
- 剥离已知 PageType 前缀（``source-`` / ``concept-`` / ``entity-`` /
  ``synthesis-``），因为 LLM 有时把 ``- type: slug`` 提示词里的类型标签
  抄进 wikilink target。
- 去除 ``[[...]]`` / ``|alias`` / ``#section`` 残渣。
"""
from __future__ import annotations

import re

from ...utils.slugify import slugify
from ..core.types import PageType

# 已知 PageType 前缀（按 value 生成：source-/concept-/entity-/synthesis-）
_KNOWN_TYPE_PREFIXES: tuple[str, ...] = tuple(f"{pt.value}-" for pt in PageType)


def normalize_reconcile_slug(raw: str) -> str:
    """Return the canonical reconciliation form of a slug/wikilink target.

    Preserves CJK punctuation with slugify boundary rules so on-disk ids
    keep their literal form; strips type prefixes, wikilink brackets,
    ``|alias`` and ``#section``.
    """
    if not raw:
        return ""
    s = raw.strip()
    # 剥 [[ ]] 与 |alias / #section 残渣
    s = re.sub(r"^\[\[|\]\]$", "", s)
    s = s.split("|")[0].split("#")[0].strip()
    # 剥 PageType 前缀
    for pfx in _KNOWN_TYPE_PREFIXES:
        if s.startswith(pfx) and len(s) > len(pfx):
            s = s[len(pfx):]
            break
    # 核心：slugify（CJK 边界连字符 + 幂等 + ASCII 折叠）
    return slugify(s)
