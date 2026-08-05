"""Common prompt rules and constants for LLM calls.

This module centralizes shared prompt fragments to:
1. Reduce token usage by avoiding repetition
2. Ensure consistency across analyzer/generator prompts
3. Enable version tracking of prompt changes

Design principles:
- Rules are pure string constants (no f-strings) to avoid template conflicts
- Templates use {placeholder} syntax for runtime substitution
- Version bumps require updating PROMPT_COMMON_VERSION
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PROMPT_COMMON_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# JSON format rules (injected at the top of every LLM prompt)
# ---------------------------------------------------------------------------

JSON_FORMAT_RULES = """## CRITICAL — JSON Format
1. Output ONLY the raw JSON object — no markdown fences (```), no introductory text, no concluding remarks.
2. Your response MUST start with `{` and end with `}`.
3. Do NOT wrap the JSON in ```json ... ``` blocks.
4. All strings must be properly escaped (double quotes, not single quotes).

Do NOT output chain-of-thought, hidden reasoning, or a thinking transcript.
Reason internally and emit only the requested JSON."""

# ---------------------------------------------------------------------------
# Language rules (CJK support, slug conventions)
# ---------------------------------------------------------------------------

LANGUAGE_RULES = """## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段：title、slots[*]、relations[].context。
Slugs (id、relations[].target) 可直接使用中文 (CJK)，也可使用 ASCII kebab-case — 保留概念的自然字面，**禁止拼音转写**。专有名词/英文术语在 ASCII 段仍保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。

示例：
- 标题：`仙侠小说的叙事技巧` → slug: `仙侠小说的叙事技巧` 或 `xianxia-narrative-techniques`
- **错误**：`xian-xia-xiao-shuo`（强制拼音）"""

# ---------------------------------------------------------------------------
# Slot filling rules (for generator prompts)
# ---------------------------------------------------------------------------

SLOT_FILLING_RULES = """## Slot Rules (schema enforced)
- Every `<!-- slot:NAME -->` (no `?`) is REQUIRED and MUST have substantive content.
- Never use placeholder text: "..." / "（空）" / "TBD" / "placeholder" / "（待补充）".
- Optional slots (`<!-- slot:NAME? -->` or `<!-- if:X -->`): omit when empty, or return `[]`.
- Each slot value: ≥ 1 character after trim. Lists: ≥ 1 substantive item.
- `main_content` is NOT a SOURCE page slot — full source lives in raw/ (traced via `sources`). Use `summary` for overview."""

# ---------------------------------------------------------------------------
# Fallback values (when source truly lacks information)
# ---------------------------------------------------------------------------

FALLBACK_VALUES = """## Fallback Values (use instead of empty/placeholder)
When the source truly lacks information for a required slot, use:
- `references`          → `- [[<source-page-slug>]]`
- `source_meta`         → `"来源: [文件名]; 格式: Markdown; 下载时间: 见原始文件头部"`
- `related_concepts`    → List concept/entity slugs from THIS response
- `related`             → `- [[<source-page-slug>]]`
- `examples`            → `"来源未提供具体例子"` (invent NOTHING)
- `comparison_dimensions` → At least 2 dimensions being compared
- `overview`            → At least 1 paragraph
- ALL OTHERS            → `"来源未详述此方面"` (not empty, not placeholder)"""

# ---------------------------------------------------------------------------
# Narrative content handling (novels, stories, fiction)
# ---------------------------------------------------------------------------

NARRATIVE_CONTENT_RULES = """## Narrative/Fiction Content Handling
When the source is a NOVEL, STORY, or NARRATIVE text (not a tutorial/knowledge article):

1. **DO NOT skip** — Always extract at minimum:
   - Characters (entities): names, roles, relationships
   - Settings (entities): locations, organizations, worlds
   - Plot elements (events): key scenes, conflicts, resolutions
   - Concepts: techniques, systems, rules unique to the story world

2. **Character extraction** (entity pages):
   - name: character's full name
   - characteristics: personality traits, abilities, appearance
   - related: connections to other characters/settings
   - Use `相关/人物` tag for characters

3. **Setting extraction** (entity pages):
   - name: location/organization name
   - characteristics: description, significance in story
   - related: connected characters/events
   - Use `题材/世界观` tag for settings

4. **Source pages for fiction**:
   - summary: 2-3 sentence plot overview (NOT empty)
   - key_points: Main plot beats, NOT tutorial steps
   - extracted_concepts: Characters/settings as `[[wikilinks]]`
   - Use `题材/小说` tag for fiction sources

5. **NEVER return empty pages** — Even for pure fiction:
   - Extract SOMETHING: characters, locations, plot points
   - Use grade=C if extraction is thin
   - Empty extraction = pipeline failure"""

# ---------------------------------------------------------------------------
# Relation types (17 built-in + custom)
# ---------------------------------------------------------------------------

RELATION_TYPES = """## Relation Types (17 built-in + custom `x-*`)
Built-in: is_part_of contains references referenced_by causes caused_by
contradicts supports supported_by supersedes superseded_by depends_on
required_by analogous_to opposite_of derived_from derives

Custom: `x-<name>` for any user-registered type. Do not invent outside this set."""

# ---------------------------------------------------------------------------
# Tag namespace reference (short form for prompts)
# ---------------------------------------------------------------------------

TAG_NAMESPACE_SHORT = """## Tags (controlled namespace)
Tags use `prefix/name` format. Allowed prefixes (10):
题材/ 功能/ 角色/ 事件/ 情绪/ 实体/ 场景阶段/ 状态/ 素材/ 可信度/

Example: `题材/现言`, `功能/教程`, `状态/完结`"""

# ---------------------------------------------------------------------------
# Helper functions for building prompts
# ---------------------------------------------------------------------------

def build_prompt_header(
    include_json: bool = True,
    include_language: bool = True,
    include_slots: bool = False,
    include_fallbacks: bool = False,
) -> str:
    """Build a standard prompt header with selected rules.

    Use this to ensure consistency across different prompt types.
    """
    parts = []
    if include_json:
        parts.append(JSON_FORMAT_RULES)
    if include_language:
        parts.append(LANGUAGE_RULES)
    if include_slots:
        parts.append(SLOT_FILLING_RULES)
    if include_fallbacks:
        parts.append(FALLBACK_VALUES)
    return "\n\n".join(parts)


def build_analyzer_header() -> str:
    """Build standard header for analyzer prompts."""
    return build_prompt_header(
        include_json=True,
        include_language=True,
        include_slots=False,
        include_fallbacks=False,
    )


def build_generator_header() -> str:
    """Build standard header for generator prompts."""
    return build_prompt_header(
        include_json=True,
        include_language=True,
        include_slots=True,
        include_fallbacks=True,
    )


# ---------------------------------------------------------------------------
# Slot minimums table (for generator prompts)
# ---------------------------------------------------------------------------

SLOT_MINIMUMS_TABLE = """**Slot-specific minimums (enforced — do NOT leave these empty)**:
SLOT                  | PAGE TYPE   | MINIMUM ACCEPTABLE CONTENT
----------------------|-------------|----------------------------------------------------
`references`          | concept     | At LEAST one `[[wikilink]]` to the source page
`source_meta`         | source      | MUST include: 来源(URL/平台), 下载时间, 发布组织
`related_concepts`    | concept     | At LEAST 2 `[[wikilinks]]` to other concept/entity pages
`related`             | entity      | At LEAST 1 `[[wikilink]]` to the source page or parent entity
`key_points`          | source      | At LEAST 3 bullet points from the source text
`extracted_concepts`  | source      | At LEAST 3 `[[wikilinks]]` to concept/entity pages generated below
`comparison_dimensions`| synthesis  | At LEAST 2 dimensions being compared
`overview`            | synthesis   | At LEAST 1 paragraph summarising the comparison"""


# ---------------------------------------------------------------------------
# Few-shot examples (reduce retry rate by showing correct output format)
# ---------------------------------------------------------------------------

ANALYZER_JSON_EXAMPLE = """## Example (CORRECT output)
```json
{
  "source_id": "raw/sources/backprop-paper.pdf",
  "type": "concept",
  "title": "反向传播算法",
  "claims": [
    {"statement": "反向传播是训练神经网络的核心算法", "confidence": 0.95, "evidence_refs": [0]},
    {"statement": "它通过链式法则计算梯度", "confidence": 0.90, "evidence_refs": [0, 1]}
  ],
  "evidence": [
    {"source_path": "raw/sources/backprop-paper.pdf", "page": 3, "quote": "Backpropagation computes gradients by..."},
    {"source_path": "raw/sources/backprop-paper.pdf", "page": 5, "quote": "The chain rule is applied to..."}
  ]
}
```

## Common ERRORS to avoid:
❌ `"evidence_refs": [2]` when len(evidence)=2 → must use 0 or 1, never 2
❌ `"type": "unknown_type"` → must be one of concept|entity|event|claim|decision|procedure|synthesis|source
❌ Empty claims array → will be flagged for human review
❌ Missing source_id → will be REJECTED"""

GENERATOR_SLOT_EXAMPLE = """## Example (CORRECT slot filling)
```json
{
  "id": "反向传播算法",
  "type": "concept",
  "title": "反向传播算法",
  "slots": {
    "definition": "反向传播是训练神经网络的核心算法，通过链式法则计算损失函数对权重的梯度。",
    "characteristics": [
      "- 计算效率高，时间复杂度 O(n)",
      "- 需要可微分激活函数",
      "- 梯度消失问题需要特殊处理"
    ],
    "examples": [
      "- PyTorch: `loss.backward()` 自动计算梯度",
      "- 训练 ResNet 时每个 epoch 调用一次反向传播"
    ],
    "related_concepts": ["- [[梯度下降]]", "- [[链式法则]]", "- [[激活函数]]"],
    "references": ["- [[backprop-paper_8c363e-a1b2c3d4]]"]
  }
}
```

## Common ERRORS to avoid:
❌ `"definition": "..."` (placeholder) → must have substantive content
❌ `"examples": []` (empty) → use `"来源未提供具体例子"`
❌ `"related_concepts": ["梯度下降"]` (plain text) → use `"- [[梯度下降]]"` (wikilink)
❌ `"references": ["- backprop-paper"]` (plain text) → use `"- [[backprop-paper_8c363e-a1b2c3d4]]"` (exact slug)"""


# ---------------------------------------------------------------------------
# Quality feedback from lint cache (for regeneration prompts)
# ---------------------------------------------------------------------------

def build_quality_feedback(
    lint_cache_path: Optional[Path],
    slugs: list[str],
    max_issues: int = 5,
) -> str:
    """Build quality feedback section from lint cache for given slugs.

    This closes the quality loop: lint results → next prompt injection.

    Parameters
    ----------
    lint_cache_path:
        Path to lint cache JSON file (usually .index/lint_cache.json)
    slugs:
        List of page slugs to look up in cache
    max_issues:
        Maximum number of issues to include (prevents token bloat)

    Returns
    -------
    A formatted prompt section string, or empty string if no issues found.
    """
    if not lint_cache_path or not lint_cache_path.exists():
        return ""

    import json

    try:
        data = json.loads(lint_cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    issues_by_slug: dict[str, list[dict]] = {}
    for slug in slugs:
        # Look for entries matching this slug (file path or direct key)
        for key, entry in data.items():
            if key.endswith(f"/{slug}.md") or key == slug:
                issues = entry.get("issues", [])
                errors = [i for i in issues if i.get("severity") == "error"]
                if errors:
                    issues_by_slug[slug] = errors[:max_issues]
                break

    if not issues_by_slug:
        return ""

    lines = ["## Previous Quality Issues (FIX these)"]
    lines.append("The following pages had quality issues in the previous generation.")
    lines.append("Pay special attention to avoid repeating these errors:\n")

    for slug, issues in issues_by_slug.items():
        lines.append(f"### Page: {slug}")
        for issue in issues:
            code = issue.get("code", "unknown")
            msg = issue.get("message", "")
            lines.append(f"- [{code}] {msg}")
        lines.append("")

    return "\n".join(lines)
