"""统一 Target Resolver（计划 2026-08-18 Task 1）。

单一引用解析器：body ``[[wikilink]]`` 与 ``relations[].target`` 共享同一
解析上下文与结果，杜绝不同 Generator 入口各自 slugify/猜名导致 canonical
目标漂移。解析优先级固定为：

    exact（现有 canonical ID）
    → source（当前 raw 的确定性 source slug）
    → alias（已登记且 canonical 真实存在）
    → title（标题索引唯一候选）
    → legacy_hash（带 8 位 hex 后缀且唯一匹配当前 raw stem 的历史漂移）
    → unresolved / ambiguous

安全门：绝不按模糊相似度自动重连普通概念页；多候选一律 ``ambiguous``；
无法安全解析返回 ``unresolved`` 并交由 Gate 阻断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .slug_utils import normalize_reconcile_slug

_LEGACY_HASH_SUFFIX = re.compile(r"-[0-9a-f]{8}$")


@dataclass(frozen=True)
class TargetResolution:
    """一次解析结果。``canonical_target`` 为 None 表示未解析（Gate 阻断）。"""

    raw_target: str
    canonical_target: str | None
    kind: str  # exact|source|alias|title|legacy_hash|ambiguous|unresolved
    changed: bool
    candidates: tuple[str, ...] = ()
    warning: str | None = None


@dataclass(frozen=True)
class ResolutionContext:
    """一次生成操作冻结的解析上下文（不可变快照）。

    ``source_candidates``: ``(canonical_raw_key, source_slug, stem)`` 元组，
    每次摄入至多一个，但保留多 source 未来扩展；legacy_hash 只允许唯一匹配。
    ``existing_index``: 磁盘页 canonical slug 的归一化集合。
    ``title_index``: 归一化标题 → slug 候选列表（多候选必须 ambiguous）。
    ``aliases``: 已校验（canonical 存在）的 alias → canonical 映射。
    """

    source_candidates: tuple[tuple[str, str, str], ...] = ()
    existing_index: frozenset[str] = frozenset()
    title_index: Mapping[str, Sequence[str]] = field(default_factory=dict)
    aliases: Mapping[str, str] = field(default_factory=dict)
    resolver_version: str = "v1"


def _clean_target(raw: str) -> str:
    """去 ``[[ ]]``、``|alias``、``#fragment`` 残渣。"""
    s = raw.strip()
    s = re.sub(r"^\[\[|\]\]$", "", s)
    return s.split("|")[0].split("#")[0].strip()


def resolve_wiki_target(
    raw_target: str,
    *,
    context: ResolutionContext,
) -> TargetResolution:
    """按固定优先级解析 *raw_target*，见模块 docstring。"""
    target = _clean_target(raw_target)
    if not target:
        return TargetResolution(raw_target=raw_target, canonical_target=None,
                                kind="unresolved", changed=False,
                                warning="empty target")
    norm = normalize_reconcile_slug(target)

    # 1. exact —— 现有 canonical ID
    if norm and norm in context.existing_index:
        return TargetResolution(raw_target=raw_target, canonical_target=target,
                                kind="exact", changed=False)

    # 2. source —— 当前 raw 的确定性 source slug
    for _key, slug, _stem in context.source_candidates:
        if norm == normalize_reconcile_slug(slug):
            return TargetResolution(raw_target=raw_target, canonical_target=slug,
                                    kind="source", changed=norm != target)

    # 3. alias —— canonical 已存在
    canonical = context.aliases.get(target) or context.aliases.get(norm)
    if canonical and normalize_reconcile_slug(canonical) in context.existing_index:
        return TargetResolution(raw_target=raw_target, canonical_target=canonical,
                                kind="alias", changed=norm != target)

    # 4. title —— 唯一候选才可复用
    title_hits = context.title_index.get(norm) or ()
    if title_hits:
        if len(title_hits) == 1:
            return TargetResolution(
                raw_target=raw_target, canonical_target=title_hits[0],
                kind="title", changed=True, candidates=tuple(title_hits))
        return TargetResolution(
            raw_target=raw_target, canonical_target=None, kind="ambiguous",
            changed=False, candidates=tuple(title_hits),
            warning=f"ambiguous title match: {title_hits}")

    # 5. legacy_hash —— 带 8 位 hex 后缀且唯一匹配当前 raw stem。
    #    仅此场景允许轻微标题漂移（如丢词）：hash 后缀证明它曾是 source
    #    链接，唯一候选证明无歧义；普通概念页无 hash 后缀绝不进入此分支。
    base = _LEGACY_HASH_SUFFIX.sub("", target)
    if base != target and context.source_candidates:
        base_norm = normalize_reconcile_slug(base)
        matches: list[str] = []
        for _key, slug, stem in context.source_candidates:
            stem_norm = normalize_reconcile_slug(stem)
            if stem_norm == base_norm:
                matches.append(slug)
                continue
            if base_norm and stem_norm:
                ratio = _similarity(base_norm, stem_norm)
                if ratio >= 0.88:
                    matches.append(slug)
        if len(matches) == 1:
            return TargetResolution(
                raw_target=raw_target, canonical_target=matches[0],
                kind="legacy_hash", changed=True, candidates=tuple(matches))
        if len(matches) > 1:
            return TargetResolution(
                raw_target=raw_target, canonical_target=None, kind="ambiguous",
                changed=False, candidates=tuple(matches),
                warning="ambiguous legacy-hash source match")

    return TargetResolution(raw_target=raw_target, canonical_target=None,
                            kind="unresolved", changed=False)


def _similarity(a: str, b: str) -> float:
    """轻量字符串相似度（仅用于 legacy_hash 安全门内）。"""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()
