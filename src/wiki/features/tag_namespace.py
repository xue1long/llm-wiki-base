"""Validate and normalize wiki page tags.

Prefixes are defined in TAG_PREFIXES. For high-frequency prefixes,
TAG_VALUES constrains the allowed suffix values (None = free-form).
MANDATORY_PAIRS lists prefix:value pairs that may be required by policy.

The public ``normalize_tags`` function is the single normalization
boundary used by ingestion, commit, cleanup and Gate code.
"""

from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------------------
# Prefix registry
# ---------------------------------------------------------------------------

TAG_PREFIXES: dict[str, str] = {
    "题材": "题材类型",
    "功能": "功能类型",
    "角色": "角色类型",
    "事件": "事件类型",
    "情绪": "情绪氛围",
    "实体": "是什么 (What)",
    "场景阶段": "何时用 (When)",
    "状态": "生命周期",
    "素材": "素材品类",
    "可信度": "可信度",
    "读者群": "读者群类型（Phase 1.4/Q13 新增）",
    "平台": "发布平台（Phase 1.4/Q13 新增）",
}

# ---------------------------------------------------------------------------
# Value domain constraints (None = free-form, any value allowed)
# ---------------------------------------------------------------------------

@dataclass
class TagNormalizationResult:
    tags: list[str]
    mapped: dict[str, str] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mandatory_added: list[str] = field(default_factory=list)


LEGACY_PREFIX_MAP: dict[str, str] = {
    "genre": "题材",
    "func": "功能",
    "char": "角色",
    "event": "事件",
    "mood": "情绪",
    "entity": "实体",
    "scene_phase": "场景阶段",
    "status": "状态",
}


TAG_VALUES: dict[str, set[str] | None] = {
    "题材": {"现言", "古言", "玄幻", "仙侠", "科幻", "悬疑", "都市", "校园", "职场", "历史", "武侠", "军事",
            "写作", "写作理论", "网络小说", "网文", "小说类型", "写作技巧", "通用", "现代"},
    "功能": {"教程", "方法论", "案例", "模板", "参考", "工具", "规范", "FAQ",
            "技巧", "写作技巧", "设定", "写作素材", "法则", "写作手法", "技法", "主题",
            "写作教学", "结构", "理论", "桥段", "写作方法", "套路"},
    "角色": None,
    "事件": None,
    # 情绪/场景阶段: spec §4.4 收紧枚举 ∪ 存量旧值（H4 并集过渡；Phase 4 后清理旧值）
    "情绪": {"爽", "虐", "甜", "燃", "悬疑", "惊悚", "治愈", "热血", "轻松", "沉重",
            "甜宠", "虐文", "爽文", "正剧", "暗黑",
            "沉浸感", "新鲜感", "虐心", "紧张"},
    "实体": None,
    "场景阶段": {"开篇", "发展", "高潮", "结局", "日常", "战斗", "情感", "悬疑",
               "转折", "铺垫", "过渡", "冲突", "收束",
               "结构设计", "全篇", "情节设计", "大纲阶段", "大纲设计", "人物构建",
               "策划", "设定", "中后期"},
    "状态": {"完结", "连载中", "弃坑", "暂停", "大纲", "待发布"},
    "素材": {"ugc", "official", "转载", "原创", "投稿"},
    "可信度": {"book", "web", "expert", "user", "ai", "unknown", "ugc", "mixed"},
    "读者群": {"男频", "女频", "全年龄", "青少年", "中老年"},
    "平台": {"起点", "番茄", "晋江", "纵横", "飞卢", "QQ阅读", "掌阅"},
}

# ---------------------------------------------------------------------------
# Mandatory pairs — tags that MUST exist in every valid tag set
# ---------------------------------------------------------------------------

MANDATORY_PAIRS: list[tuple[str, str]] = [
    ("素材", "ugc"),
    ("可信度", "ugc"),
]

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def is_valid(tag: str) -> bool:
    """True if tag uses one of the controlled prefixes."""
    return any(tag.startswith(prefix + "/") for prefix in TAG_PREFIXES)


def parse(tag: str) -> tuple[str, str] | None:
    """Returns (prefix, name) or None if invalid."""
    if "/" not in tag:
        return None
    prefix, _, name = tag.partition("/")
    if prefix in TAG_PREFIXES:
        return prefix, name
    return None


def is_valid_value(tag: str) -> bool:
    """True if tag has a valid prefix AND its value is in the allowed set (if constrained)."""
    parsed = parse(tag)
    if parsed is None:
        return False
    prefix, name = parsed
    allowed = TAG_VALUES.get(prefix)
    if allowed is None:
        return True  # free-form prefix
    return name in allowed


def allowed_values_for(prefix: str) -> set[str] | None:
    """Return the allowed value set for *prefix*, or None if free-form."""
    return TAG_VALUES.get(prefix)


def validate_tags(tags: Iterable[str]) -> list[str]:
    """Return list of invalid tags (must be empty for valid tag set)."""
    return [t for t in tags if not is_valid(t)]


def validate_tag_values(tags: Iterable[str]) -> list[str]:
    """Return list of tags whose value is outside the allowed domain.

    Only checks prefixes with constrained TAG_VALUES.
    """
    invalid: list[str] = []
    for t in tags:
        parsed = parse(t)
        if parsed is None:
            invalid.append(t)
            continue
        prefix, name = parsed
        allowed = TAG_VALUES.get(prefix)
        if allowed is not None and name not in allowed:
            invalid.append(t)
    return invalid


def missing_mandatory_tags(tags: Iterable[str]) -> list[str]:
    """Return MANDATORY_PAIRS not present in *tags*."""
    tag_set = set(tags)
    missing: list[str] = []
    for prefix, value in MANDATORY_PAIRS:
        tag = f"{prefix}/{value}"
        if tag not in tag_set:
            missing.append(tag)
    return missing


def normalize_tags(
    tags: Iterable[str] | None,
    *,
    source_kind: str | None = None,
    source_path: str | None = None,
) -> TagNormalizationResult:
    """Normalize tags at a deterministic pipeline boundary.

    Legacy prefixes are mapped when the mapping is unambiguous. Unknown
    prefixes and invalid values are removed with warnings. For backwards
    compatibility with the current project Gate, configured mandatory pairs
    are added whenever at least one valid tag remains. ``source_kind`` is
    retained for the planned source-aware policy transition.
    """
    mapped: dict[str, str] = {}
    removed: list[str] = []
    warnings: list[str] = []
    result: list[str] = []
    for raw in tags or []:
        if not isinstance(raw, str) or not raw.strip():
            if raw not in (None, ""):
                removed.append(str(raw))
            continue
        tag = raw.strip()
        parsed = tag.split("/", 1)
        candidate = tag
        if len(parsed) == 2 and parsed[0] in LEGACY_PREFIX_MAP:
            candidate = f"{LEGACY_PREFIX_MAP[parsed[0]]}/{parsed[1]}"
            mapped[tag] = candidate
        if not is_valid_value(candidate):
            removed.append(tag)
            warnings.append(f"removed invalid tag: {tag}")
            continue
        if candidate not in result:
            result.append(candidate)
    mandatory_added: list[str] = []
    if result:
        for prefix, value in MANDATORY_PAIRS:
            mandatory = f"{prefix}/{value}"
            if mandatory not in result:
                result.append(mandatory)
                mandatory_added.append(mandatory)
    if source_path and warnings:
        warnings = [f"{source_path}: {item}" for item in warnings]
    return TagNormalizationResult(
        tags=result,
        mapped=mapped,
        removed=removed,
        warnings=warnings,
        mandatory_added=mandatory_added,
    )


# ---------------------------------------------------------------------------
# LLM prompt helpers
# ---------------------------------------------------------------------------


class TagValidationError(ValueError):
    """Raised when tags fail value-domain or mandatory-pair validation."""

    def __init__(self, message: str, invalid_values: list[str] | None = None,
                 missing_pairs: list[str] | None = None):
        super().__init__(message)
        self.invalid_values = invalid_values or []
        self.missing_pairs = missing_pairs or []


def validate_tag_compliance(tags: list[str]) -> None:
    """Validate tags against value domain + mandatory pairs. Raises on failure.

    Value-domain validation always applies. Mandatory-pair validation is
    skipped when *tags* is empty (page hasn't been tagged yet). Once a page
    carries at least one tag the full mandatory set must be present.
    """
    reasons: list[str] = []
    invalid_vals = validate_tag_values(tags)
    if invalid_vals:
        reasons.append(f"invalid tag values: {invalid_vals}")
    if tags:  # only enforce mandatory pairs when page has been tagged
        missing = missing_mandatory_tags(tags)
        if missing:
            reasons.append(f"missing mandatory tags: {missing}")
    if reasons:
        raise TagValidationError(
            "; ".join(reasons),
            invalid_values=invalid_vals,
            missing_pairs=missing if tags else [],
        )


def build_tag_prompt_section() -> str:
    """Build a prompt snippet describing allowed tags and value domains.

    Injected into generator prompts so the LLM knows which values are
    valid for each constrained prefix.
    """
    lines: list[str] = [
        "## Tag namespace rules",
        "Tags MUST use the format `prefix/value`. Valid prefixes:",
    ]
    for prefix, desc in TAG_PREFIXES.items():
        allowed = TAG_VALUES.get(prefix)
        if allowed is not None:
            values_str = ", ".join(sorted(allowed))
            lines.append(f"- `{prefix}/` ({desc}): {values_str}")
        else:
            lines.append(f"- `{prefix}/` ({desc}): free-form, any value")
    if MANDATORY_PAIRS:
        mandatory = [f"`{p}/{v}`" for p, v in MANDATORY_PAIRS]
        lines.append(f"\nMandatory tags (must be present): {', '.join(mandatory)}")
    lines.append(
        "\nLegacy English prefixes (genre/, func/, char/, event/, mood/, "
        "entity/, scene_phase/, status/) are FORBIDDEN — never emit them."
    )
    return "\n".join(lines)
