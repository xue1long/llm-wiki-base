"""引用-产出对账（plan 1.3 H6/O6）——统一判定集合 + gap 采集/落盘。

对账判定集合 = 产出 ∪ 磁盘页 ∪ SlugAliasRegistry 可解析 ∪ 索引（并集，
别名优先）。所有 slug 经 ``normalize_reconcile_slug`` 归一后比对，消除
``normalize_id_chars`` vs ``_slugify`` 的分歧（B-H3）。

- ``make_missing_slugs_resolver``：给 generator 的单调用内闭环反馈用——
  输入本次产出的 raw page dicts，返回仍未解析的 slug 清单（H6）。
- ``collect_missing_slugs``：对最终 WikiPage 集合做一次完整对账，返回
  缺失 slug（供 commit 路径写 KnowledgeGapStore）。
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from ..wiki.core.paths import WikiPaths
from ..wiki.core.types import PageType
from ..wiki.features.slug_aliases import SlugAliasRegistry
from ..wiki.features.slug_utils import normalize_reconcile_slug

_logger = logging.getLogger(__name__)

# B10: 提取 body 里的 [[wikilink]] target（去 |alias 与 #section 后缀）。
_WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]")


def _extract_wikilink_targets(body: str) -> list[str]:
    out: list[str] = []
    for _raw in _WIKILINK_RE.findall(body or ""):
        _tgt = _raw.split("|")[0].split("#")[0].strip()
        if _tgt:
            out.append(_tgt)
    return out


def _collect_referenced_slugs(pages) -> list[str]:
    """Collect every referenced slug from a page collection.

    Sources: ``relations[].target_id`` and body ``[[wikilinks]]``.  Raw
    normalization is applied by the caller via :func:`normalize_reconcile_slug`
    so on-disk ids with CJK punctuation stay resolvable (B-H3).
    """
    out: list[str] = []
    for p in pages:
        for rel in (getattr(p, "relations", None) or []):
            tgt = getattr(rel, "target_id", None) or getattr(rel, "target", None)
            if tgt:
                out.append(tgt)
        for _t in _extract_wikilink_targets(getattr(p, "body", None) or ""):
            out.append(_t)
    return out


def _legacy_stub_blocklist() -> frozenset[str]:
    """Inherit the legacy exact-match stub blocklist (platform/org names).

    Plan 1.3-4: the gap ledger must keep the same quality guardrails as the
    removed auto-stub machinery — blocklist, hard cap, doc-title variants.
    This imports the (now otherwise orphaned) exact-match set from ingest.py
    so ``feishu`` / ``lark`` etc. never enter the ledger either.
    """
    try:
        from .ingest import _get_stub_blocklist
        return _get_stub_blocklist()
    except Exception:  # pragma: no cover — import guard
        return frozenset()


def _raw_is_blocklisted(raw: str) -> bool:
    """True if the RAW referenced slug must never become a gap.

    Checks both the legacy exact-match stub blocklist and the regex-based gap
    blocklist — on the raw (pre-normalization) form so type-prefixed
    hallucinated references (``source-补充教程``) are caught before the
    normalizer strips the prefix.
    """
    if raw in _legacy_stub_blocklist():
        return True
    from ..wiki.features.knowledge_gaps import is_raw_reference_blocklisted
    return is_raw_reference_blocklisted(raw)


def _resolvable_set(paths: WikiPaths, produced_slugs: set[str]) -> set[str]:
    """Build the reconciliation set: produced ∪ disk ∪ alias-resolvable ∪ index.

    All members normalized via :func:`normalize_reconcile_slug`; alias
    canonical targets are added so a wikilink to an alias also resolves.
    """
    resolvable: set[str] = {normalize_reconcile_slug(s) for s in produced_slugs if s}
    # 磁盘页（内置 typed 目录 + schema custom 目录；Task 0.4 统一枚举）
    from ..wiki.schema_registry import SchemaRegistry
    for d in SchemaRegistry.from_project(paths.root).iter_page_dirs(paths):
        if d is None or not d.exists():
            continue
        for f in d.glob("*.md"):
            resolvable.add(normalize_reconcile_slug(f.stem))
    # SlugAliasRegistry：别名本身可解析，其 canonical 目标也可解析（H6 并集）
    try:
        reg = SlugAliasRegistry(paths.root)
        for alias, canonical in reg.aliases.items():
            resolvable.add(normalize_reconcile_slug(alias))
            if canonical:
                resolvable.add(normalize_reconcile_slug(canonical))
    except Exception as exc:  # 别名注册表损坏不阻塞对账
        _logger.warning("[reconcile] SlugAliasRegistry unavailable: %s", exc)
    # 索引（index.md 条目）
    try:
        from ..wiki.features.indexer import read_index
        for entry in read_index(paths):
            if entry:
                resolvable.add(normalize_reconcile_slug(str(entry[0])))
    except Exception as exc:  # 索引缺失/损坏 → 只依赖磁盘页
        _logger.debug("[reconcile] index read skipped: %s", exc)
    return resolvable


def make_missing_slugs_resolver(
    paths: WikiPaths,
    *,
    produced_prefix: set[str] | None = None,
) -> Callable[[list[dict]], list[str]]:
    """Return a resolver for the generator's single-call closed loop (H6).

    The resolver receives the parsed raw ``pages`` list (dicts with ``id`` /
    ``relations`` / body slots) and returns the list of referenced-but-
    unresolved slugs.  ``produced_prefix`` seeds the resolvable set with
    slugs known before generation (e.g. the deterministic source-page slug).
    """
    seed = produced_prefix or set()
    resolvable_base = _resolvable_set(paths, seed)

    def resolver(pages: list[dict]) -> list[str]:
        produced = {normalize_reconcile_slug(p.get("id") or "") for p in pages}
        resolvable = resolvable_base | produced
        missing: list[str] = []
        seen: set[str] = set()
        for p in pages:
            for rel in (p.get("relations") or []):
                tgt = rel.get("target") or rel.get("target_id") or ""
                if tgt:
                    norm = normalize_reconcile_slug(tgt)
                    if (norm and norm not in resolvable and norm not in seen
                            and not _raw_is_blocklisted(tgt)):
                        seen.add(norm)
                        missing.append(tgt)
            for slot in (p.get("slots") or {}).values():
                # 槽值可能是字符串或字符串数组（LLM 常把 wikilink 数组输出为
                # ["[[a]]", "[[b]]"]）——两种形态都要扫。
                values = slot if isinstance(slot, list) else [slot]
                for v in values:
                    if isinstance(v, str):
                        for _t in _extract_wikilink_targets(v):
                            norm = normalize_reconcile_slug(_t)
                            if (norm and norm not in resolvable and norm not in seen
                                    and not _raw_is_blocklisted(_t)):
                                seen.add(norm)
                                missing.append(_t)
        return missing

    return resolver


def collect_missing_slugs(
    pages,
    paths: WikiPaths,
    *,
    produced_slugs: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Final reconciliation over WikiPage objects.

    Returns ``[(normalized_slug, referenced_by_page_id), ...]`` for every
    referenced slug that is not in 产出 ∪ 磁盘 ∪ 别名 ∪ 索引.  The caller
    (commit path) writes these to ``KnowledgeGapStore``.
    """
    produced = produced_slugs or {p.id for p in pages}
    resolvable = _resolvable_set(paths, produced)
    missing: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in pages:
        for raw in _collect_referenced_slugs([p]):
            # 先查原始（未归一）形态的 blocklist——类型前缀等幻觉引用在归一
            # 剥前缀前拦截（否则 source-补充教程 → 补充教程 绕过 blocklist）。
            if _raw_is_blocklisted(raw):
                continue
            norm = normalize_reconcile_slug(raw)
            if norm and norm not in resolvable and norm not in seen:
                seen.add(norm)
                missing.append((norm, p.id))
    return missing
