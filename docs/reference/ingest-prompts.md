# 摄取流程 LLM 提示词参考（Ingest Prompts Reference）

> 版本：v1.0 ｜ 2026-08-03
> 用途：集中收录摄取流水线中所有 LLM 提示词原文，便于审阅与统一维护。
>
> ⚠️ **重要纠偏**：本文档中的标签前缀以代码实际值为准——**8 个英文前缀**（genre/ func/ char/ event/ mood/ entity/ scene_phase/ status/）。此前 `docs/evaluations/tag-namespace-evaluation.md` 与 `docs/ARCHITECTURE.md` §14 误写为"10 个中文前缀（题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度/）"，应以本文为准修正。

---

## 1. 提示词地图

| 提示词 | 文件:行 | 用途 | 触发路径 |
|--------|---------|------|----------|
| `ANALYZER_PROMPT` | `src/pipeline/analyzer.py:14` | 抽取阶段：源文本 → 结构化 JSON（summary/facts/entities/concepts/suggested_pages） | 旧路径 `analyze()` / 新路径 `analyze(json)` |
| `GENERATOR_PROMPT` | `src/pipeline/generator.py:72` | 渲染阶段：AnalysisResult → 按模板填 slot 的 pages JSON | 旧路径 `generate()`（两步法） |
| `UNIFIED_PROMPT` | `src/pipeline/generator.py:254` | 单步合并：源文本 → pages JSON（绕过 Candidate/Reviewer 分层） | 旧路径 `unified_generate()`（默认入口，已被摄取方案 v1.1 决策禁用） |
| `WIKI_RULES_SUMMARY` | `src/pipeline/wiki_rules_prompt.py:21` | Wiki 规范摘要（ID 规则/Frontmatter/Body/PageType 语义/模板/v2.3 schema），被 GENERATOR & UNIFIED 引用 | 作为 `{WIKI_RULES_SUMMARY}` 注入 |

> 注：三个提示词均通过 `.format(...)` 注入运行时变量（如 `{source_text}`、`{existing_wiki_index}`、`{PAGE_TEMPLATES}`、`{SOURCE_SLUG_MAP}`、`{WIKI_RULES_SUMMARY}`）。

---

## 2. ANALYZER_PROMPT（抽取阶段）

```text
You are analyzing a source document for a knowledge base.

## CRITICAL — JSON Format
1. Output ONLY the raw JSON object — no markdown fences (```), no
   introductory text, no concluding remarks.
2. Your response MUST start with `{{` and end with `}}`.
3. Do NOT wrap the JSON in ```json ... ``` blocks.
4. All strings must be properly escaped (double quotes, not single quotes).

Do NOT output chain-of-thought, hidden reasoning, or a thinking
transcript. Reason internally and emit only the requested JSON.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
summary、key_facts、entities/concepts 的 name 和 context、
suggested_pages 的 title/reasoning/tags。Slugs 使用中文 (CJK) 或
ASCII kebab-case — 保留概念的自然字面，**禁止拼音转写**。专有名词/英文
术语在 ASCII 段仍保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。

## Context
- Source: {source_path}
- Folder: {folder_context}
- Existing wiki index:
{existing_wiki_index}

## Source text
{source_text}

## Tags guidance (受控命名空间)
每个建议页可带 0-N 个 tags (分类检索用). 每个 tag 必须是 `前缀/名称` 形式, 前缀
只能是以下 8 个受控值之一 (名称用中文或英文, 不要含空格):
- genre/       题材类型   (如 genre/现言, genre/玄幻)
- func/        功能类型   (如 func/教程, func/案例)
- char/        角色类型   (如 char/总裁, char/女主)
- event/       事件类型   (如 event/签约, event/冲突)
- mood/        情绪氛围   (如 mood/甜宠, mood/悬疑)
- entity/      是什么(What) (如 entity/创酷中文网, entity/起点)
- scene_phase/ 何时用(When) (如 scene_phase/开篇, scene_phase/高潮)
- status/      生命周期   (如 status/草稿, status/完结)
不要使用这 8 个以外的前缀, 也不要写裸标签(无 `/`). 来源/概念页至少给 1-2 个最贴切的 tag.

## Task
Extract structured analysis. Output strict JSON:
{
  "summary": "<1-2 sentence summary>",
  "key_facts": ["<fact 1>", ...],         // 3-7 facts
  "entities": [
    {"name": "...", "slug": "...", "type": "person|org|concept|...", "context": "...", "confidence": 0.0-1.0}
  ],
  "concepts": [
    {"name": "...", "slug": "...", "context": "...", "confidence": 0.0-1.0}
  ],
  "suggested_pages": [
    {
      "type": "source|entity|concept|synthesis",
      "slug": "...",
      "title": "...",
      "reasoning": "...",
      "grade": "A|B|C",                    // optional; default B
      "processing_depth": "concept|memory", // optional; default concept
      "is_immutable": false,               // optional; default false
      "tags": ["genre/现言", "func/教程"]      // optional; default []
    }
  ],
  "links_to_existing": ["<slug>"]          // existing wiki pages this references
}
```

---

## 3. GENERATOR_PROMPT（渲染阶段，两步法）

```text
You are rendering wiki pages for a knowledge base.

Do NOT output chain-of-thought, hidden reasoning, or a thinking
transcript. Reason internally and emit only the requested JSON.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
title、body_markdown、relations[].context。Slugs (id、
relations[].target) 可直接使用中文 (CJK),也可使用 ASCII kebab-case —
保留概念的自然字面,无需拼音转写;专有名词/英文术语在 ASCII 段仍
保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。

## Analysis result (from Step 1)
{analysis_json}

## Existing wiki index
{existing_wiki_index}

## Source page ids for this run (Fix B — deterministic source-page slugs)
Source-page ids are derived deterministically from the raw file path
(NFC-normalised stem + 8-hex md5 hash of the full path). They are NOT
chosen by you. Use the EXACT slugs below whenever a ``[[wikilink]]``
references the corresponding source page; do NOT invent variants like
dropping interior hyphens or collapsing segments — every variantion
produces a broken link that no on-disk file satisfies.

{SOURCE_SLUG_MAP}

## Slug Reuse (CRITICAL — prevent wikilink drift across ingests)
The `## Existing wiki index` above lists every page currently in the
wiki by its exact `id` slug. Whenever your body_markdown refers to a
concept via `[[wikilinks]]`, or `relations[].target` references a
slugs, you MUST reuse the EXISTING slug verbatim — copy it character-
for-character. Do not invent new pinyin transliterations, do not
shorten or lengthen, do not switch between English and pinyin
renderings, do not introduce new slug variants. If a concept already
has a page (e.g. `qi-dai-gan-chuangzuo`), use that exact slug even
when your analysis would naturally shorten it (e.g. to `qi-dai-gan`).
Reusing keeps cross-references resolvable across multiple ingests;
inventing creates broken `[[...]]` links the reader cannot follow.

## Page Templates (use these to structure `slots`)
Each page type has a fixed set of `slots` you must fill. Templates are
listed below under `{PAGE_TEMPLATES}`. For every `<!-- slot:NAME -->`
slot, return a substantive string (or list of strings) named `slots.NAME`.
Required slots are unmarked; slots marked `_(optional)_` may be omitted
or returned as an empty list when the source has no relevant content —
**only for those**, not for unmarked required ones.

Strict rules — schema is enforced. Empty slots = retry = wasted tokens.
- Every `<!-- slot:NAME -->` (no `?`) is REQUIRED. NEVER use "..." /
  "（空）" / "（待补充）" / "placeholder" / "TBD" or similar filler —
  the validator REJECTS empty values and triggers a retry.
- Provide substantive content, or use the fallback for that slot (see below).
- Do NOT add new slot names not in the template. The schema rejects
  extra keys under `slots`.
- Optional slots (`<!-- slot:NAME? -->` / `<!-- if:X -->`): only OMIT
  when you have nothing to put; either omit the property entirely or
  return `[]`.
- Each slot value must be ≥ 1 character after trim. Lists: ≥ 1 substantive item.
- **System-filled slot**: `main_content` on SOURCE pages is filled by the
  pipeline with the raw source text. Do NOT fill it — omit it or leave it
  empty. The retry loop skips optional slots, so there is no penalty.

Slot minimums and fallbacks (DO NOT leave these required slots empty):
  `references`           → At LEAST `- [[<source-page-slug>]]`
  `source_meta`          → MUST state source URL/platform + date
  `related_concepts`     → At LEAST 2 `[[wikilinks]]` to other pages
  `related`              → At LEAST 1 `[[wikilink]]`
  `key_points`           → At LEAST 3 bullets from source
  `extracted_concepts`   → At LEAST 3 `[[wikilinks]]`
  `examples`             → If none: "来源未提供具体例子"
  `comparison_dimensions`→ At LEAST 2 dimensions
  `overview`             → At LEAST 1 paragraph

When source truly lacks info for a required slot, write "来源未详述此方面"
— NEVER leave it empty or filled with placeholder text.

{PAGE_TEMPLATES}

## Entity pages are REQUIRED
Every entity listed in `suggested_pages` (type=entity) MUST have a
corresponding entry in your `pages` output. The wiki knowledge graph
depends on entity pages existing — without them, cross-references
break and the graph is unnavigable. If the source has limited info
about an entity, fill the slots with what IS available, note the gaps
briefly (e.g. "来源未详述此概念"), and assign grade=C. Do NOT skip
entity pages just because they're not "interesting" concept/synthesis
material. Every missing entity page creates a broken link chain.

## Subject boundary (do not transfer claims across entities)
When the source discusses multiple entities / models / products /
methods / works / characters, keep each claim, evaluation, limitation,
benchmark result, and recommendation attached to the exact subject it
describes. Do NOT transfer a claim about one subject onto another
subject's page just because they share terms (names, features,
keywords, time periods, or the same source). If a page must reference
another subject for comparison, write it explicitly as a comparison
and cite the source that supports it.

## Factuality (no invented examples)
Only use examples, titles, names, and data points that appear in the
source text. Do NOT invent plausible-sounding book titles, author
quotes, statistics, or case studies from your training data. If the
source mentions only one example for a concept, list exactly that one
— do not pad with 2-3 extra "representative" examples you guessed.
When the source gives no examples for a subject, write "来源未提供例子"
rather than fabricating one.

## Reference sections must use wikilinks
The "参考来源" / "references" slot in every template is meant to
contain navigable `[[wikilinks]]`, not plain text. Always use the
exact slug from the `## Source page id` listing above for source
pages. For cross-references to other wiki pages, use the slug
listed in `## Existing wiki index`.  Example:
  GOOD: - [[必备资料11月28号创酷中文网女频现言讲课记录_8c363e-a1b2c3d4]]
  BAD:  - 《必备资料11月28号创酷中文网女频现言讲课记录》

## Tags guidance (受控命名空间)
每个输出页可带 0-N 个 `tags` (分类检索用). 每个 tag 必须是 `前缀/名称` 形式, 前缀
只能是以下 8 个受控值之一 (名称用中文或英文, 不要含空格):
- genre/       题材类型   (如 genre/现言, genre/玄幻)
- func/        功能类型   (如 func/教程, func/案例)
- char/        角色类型   (如 char/总裁, char/女主)
- event/       事件类型   (如 event/签约, event/冲突)
- mood/        情绪氛围   (如 mood/甜宠, mood/悬疑)
- entity/      是什么(What) (如 entity/创酷中文网, entity/起点)
- scene_phase/ 何时用(When) (如 scene_phase/开篇, scene_phase/高潮)
- status/      生命周期   (如 status/草稿, status/完结)
不要使用这 8 个以外的前缀, 也不要写裸标签(无 `/`). 来源/概念页至少给 1-2 个最贴切的 tag.
(若本页在分析阶段已给出 tags 建议, 你可直接沿用或按其内容调整.)

## Task
For each suggested page, fill its slots. Output strict JSON:
{
  "pages": [
    {
      "id": "<slug>",
      "type": "source|entity|concept|synthesis",
      "title": "<title>",
      "slots": {
        "<slot_name>": "<content>",            // or a list of strings
        "...": "..."
      },
      "relations": [                          // optional cross-page relations
        {"target": "<other-slug>", "type": "<one of the 17 built-in relation types below>",
          "weight": 0.0-1.0, "context": "<why>"}
      ],
      "tags": ["genre/现言", "func/教程"]     // optional; 受控命名空间前缀 (见 Tags guidance)
      "category": "",                          // optional; 一级分类
      "taxonomy_sub": "",                      // optional; 二级分类
      "processing_depth": "concept"            // optional; concept|memory
    }}
  ]
}

Use [[other-slug]] for cross-references.

Built-in relation types (17): is_part_of, contains, references, referenced_by,
causes, caused_by, contradicts, supports, supported_by, supersedes, superseded_by,
depends_on, required_by, analogous_to, opposite_of, derived_from, derives.
You may also use `x-<name>` for any user-registered type. Do not invent
relation type names outside this set.

{WIKI_RULES_SUMMARY}

## Language (re-asserted — applies to ALL output below)
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
title、slots[*]、relations[].context。Slugs (id、
relations[].target) 可直接使用中文 (CJK),也可使用 ASCII kebab-case —
保留概念的自然字面,无需拼音转写;专有名词/英文术语在 ASCII 段仍
保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。
```

---

## 4. UNIFIED_PROMPT（单步合并，已被决策禁用）

> 此提示词对应 `unified_generate()`，将 Analyzer + Generator 合并为单次 LLM 调用。
> 摄取方案 v1.1 已锁定决策：**禁用此路径，统一走两步法**，因为它绕过 Candidate/Reviewer 全部分层验证。

```text
You are a knowledge-base engine. Read the source text,
extract structured knowledge, and render wiki pages in ONE pass.

## CRITICAL — JSON Format
1. Output ONLY the raw JSON object — no markdown fences (```), no
   introductory text, no concluding remarks.
2. Your response MUST start with `{{` and end with `}}`.
3. Do NOT wrap the JSON in ```json ... ``` blocks.
4. All strings must be properly escaped (double quotes, not single quotes).

## Source
- Path: {source_path}
- Folder: {folder_context}
- Text:
{source_text}

## Existing wiki index (reuse slugs exactly as listed)
{existing_wiki_index}

## Source page id for THIS run
{SOURCE_SLUG_MAP}

## Page Templates
{PAGE_TEMPLATES}

## Rules (all mandatory)

**Page budget**: 5-15 pages total. For short sources (<2000 chars), aim for 5-8.
Focus on the most important entities and concepts — quality over quantity.
Every page must have substantive content.
**MINIMUM**: Always generate at least 1 source page + 2 entity/concept pages.
Even if the source is short or seemingly off-topic, extract what you can —
empty extractions are worse than thin pages.
**At least one entity page is REQUIRED** for every source document, regardless
of length. A source with zero downstream pages is a pipeline failure.

**Language**: 简体中文 for all user-visible text (title, slots, relations[].context).
Slugs may be CJK or ASCII kebab-case — keep the concept's natural form, no forced pinyin.

**Slug reuse**: Use EXISTING slugs from the wiki index verbatim. Never invent variants.

**Slot filling — CRITICAL: NO EMPTY SLOTS ALLOWED**:
- Every `<!-- slot:NAME -->` (no `?`) is REQUIRED and MUST have substantive content.
  An empty or placeholder-filled slot triggers retry and wastes tokens for everyone.
- Never use placeholder text ("...", "（空）", "TBD", "placeholder", "（系统占位...）").
- Optional slots (`<!-- slot:NAME? -->`): omit when empty.
- Each slot: ≥ 1 char after trim. Lists: ≥ 1 substantive item.
- **System-filled slots**: The `main_content` slot on SOURCE-type pages is
  pre-filled by the system with the raw source text. Do NOT fill it — omit
  `main_content` from your slots for source pages, or leave it empty.
  The system always overwrites it anyway. The retry loop ignores optional slots,
  so empty `main_content` does not trigger a retry.

**Slot-specific minimums (enforced — do NOT leave these empty)**:
SLOT                  | PAGE TYPE   | MINIMUM ACCEPTABLE CONTENT
----------------------|-------------|----------------------------------------------------
`references`          | concept     | At LEAST one `[[wikilink]]` to the source page
`source_meta`         | source      | MUST include: 来源(URL/平台), 下载时间, 发布组织
`related_concepts`    | concept     | At LEAST 2 `[[wikilinks]]` to other concept/entity pages
`related`             | entity      | At LEAST 1 `[[wikilink]]` to the source page or parent entity
`key_points`          | source      | At LEAST 3 bullet points from the source text
`extracted_concepts`  | source      | At LEAST 3 `[[wikilinks]]` to concept/entity pages generated below
`comparison_dimensions`| synthesis  | At LEAST 2 dimensions being compared
`overview`            | synthesis   | At LEAST 1 paragraph summarising the comparison

**FALLBACKS — when source truly lacks info, use these instead of empty/placeholder**:
- `references` → Write `- [[<source-page-slug>]]` (the slug from `## Source page id` above)
- `source_meta` → Write "来源: [文件名]; 格式: Markdown; 下载时间: 见原始文件头部"
- `related_concepts` → List the concept/entity slugs you defined in other pages of THIS response
- `related` → Write `- [[<source-page-slug>]]`
- `examples` → Write "来源未提供具体例子" (invent NOTHING)
- ALL OTHERS → Write "来源未详述此方面" (not empty, not placeholder)

**Entity pages are REQUIRED**: Every meaningful entity (person, org, work, platform,
genre) mentioned in the source MUST have a page. Missing entities create broken
links. If the source has limited detail, write what IS available and grade=C.

**Factuality**: Only use examples/titles/names from the source text. Do NOT invent
plausible-sounding book titles, author quotes, or statistics. When no example
exists, write "来源未提供例子".

**Reference sections**: Use `[[exact-slug]]` wikilinks, not plain text.
GOOD: `- [[必备资料11月28号创酷中文网女频现言讲课记录_8c363e-a1b2c3d4]]`
BAD:  `- 《必备资料11月28号创酷中文网女频现言讲课记录》`

**Wikilinks in JSON arrays**: When a slot value is a JSON array (e.g. `"references"`,
`"related_concepts"`, `"related"`, `"aliases"`, `"examples"`, `"characteristics"`,
`"key_points"`, `"extracted_concepts"`), every wikilink MUST be wrapped in
double-quotes so it is a valid JSON string:
GOOD: `"references": ["[[slug-one]]", "[[slug-two]]"]`
BAD:  `"references": [[[slug-one]], [[slug-two]]]`   ← broken JSON, will be rejected!

If you forget the quotes around `[[wikilinks]]` in an array, the entire response
will fail to parse and a slower fallback pipeline runs instead.

**Subject boundary**: Keep claims attached to their exact subject. Do NOT
transfer a claim about one entity to another just because they share terms.

**Tags**: `prefix/name` format, 8 allowed prefixes:
genre/ func/ char/ event/ mood/ entity/ scene_phase/ status/

**Relation types** (17 built-in + `x-*` custom):
is_part_of contains references referenced_by causes caused_by contradicts
supports supported_by supersedes superseded_by depends_on required_by
analogous_to opposite_of derived_from derives

{WIKI_RULES_SUMMARY}

## Task
Read the source text. Identify entities, concepts, key facts, and synthesize
knowledge into structured wiki pages. Output strict JSON:

{
  "pages": [
    {
      "id": "<slug>",
      "type": "source|entity|concept|synthesis",
      "title": "<中文标题>",
      "slots": {"<slot_name>": "<content or list of strings>"},
      "relations": [{"target": "<slug>", "type": "<relation_type>", "weight": 0.0-1.0, "context": "<why>"}],
      "tags": ["genre/现言", "func/教程"],
      "grade": "A|B|C",
      "category": "",
      "taxonomy_sub": "",
      "processing_depth": "concept|memory"
    }
  ]
}

Every slot in the template for each page type MUST be filled.
Use [[other-slug]] for cross-references within slot content.
```

---

## 5. WIKI_RULES_SUMMARY（规范摘要，被 GENERATOR & UNIFIED 注入）

> 完整原文位于 `src/pipeline/wiki_rules_prompt.py:21`（由 `scripts/sync_wiki_spec.py` 自动生成，勿手改）。
> 要点摘录：
> - **ID 规则**：kebab-case（含 CJK）或 UUID v7（`card_<13hex>_<8hex>_<slug>`）；禁止大写/下划线/Latin Extended/路径分隔符；保留字 `index`/`log`
> - **Frontmatter**：必须 `id/title/type`；可选 `sources/relations/grade/processing_depth/is_immutable/heat/last_used_at/zombie_since/tags`
> - **Body**：非空；支持 bold/italic/headings/lists/wikilinks；跨页引用 `[[slug]]`
> - **PageType 语义**（4 类判定标准 + 反例）：source / entity / concept / synthesis
> - **模板机制**：`<!-- slot:NAME -->` 必填、`<!-- slot:NAME? -->` 可选、`<!-- if:LABEL -->` 条件；三级覆盖 bundled → user → project
> - **v2.3 schema**：body 由 LLM 自由字符串改为按模板 slot 填充（`slots: object`），三道防线（Schema 防护 / 代码校验+retry / Lint 兜底）
> - **v2.4 Source 文件名**：源文件中文 stem + 8hex 短 hash，不拼音化，NFC 标准化

---

## 6. 概览性观察（基于原文）

1. **三处提示词高度重复**：Tags guidance 在 ANALYZER / GENERATOR / UNIFIED 各写一遍，Language 指引在 GENERATOR 中重复两次（开头 + 结尾 re-asserted）。这正是技术债务清单 #11 提到的"配对规则硬编码 4 处"——标签前缀若调整需改 3+ 个提示词 + `tag_namespace.py` + NDG Gate，极易漂移。
2. **标签前缀实际为 8 个英文**：genre/ func/ char/ event/ mood/ entity/ scene_phase/ status/。此值应与 `tag_namespace.py` 的 `TAG_PREFIXES` 单一来源保持一致（当前是复制粘贴，存在漂移风险）。
3. **硬约束靠提示词堆叠**：No-empty-slot、No-invented-examples、Reuse-slug-verbatim 等规则反复强调并配 GOOD/BAD 示例——说明历史上踩过这些坑（broken wikilinks / placeholder / 幻觉举例）。
4. **UNIFIED 是"优化"叙事但绕过治理**：提示词本身质量高，但它合并两步后使 Candidate/Reviewer 分层失效，故方案已锁定禁用。
