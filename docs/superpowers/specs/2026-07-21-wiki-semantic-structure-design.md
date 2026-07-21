# Wiki Semantic Structure (v2.0) Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ ad4fb38)
**Inspired by:** llm_wiki-main (nashsu/llm_wiki) — selective adoption, not a port

## Goal

Replace ruflo-kb's flat `Notes/<task_id>.md` output with an Obsidian-compatible, semantically-structured wiki that turns each ingested source into an interconnected set of typed pages (source summary, entities, concepts, queries, synthesis, comparisons), produced by a two-step LLM pipeline (Analyzer → Generator).

The wiki directory is human-readable as-is (Obsidian vault), machine-traversable via `[[wikilink]]` resolution, and exposes enough metadata (`sources[]` frontmatter, `index_version` counter) for downstream tools to query without re-parsing prose.

## Non-goals

- No GUI / TUI. CLI + Python API + (future) HTTP API only.
- No knowledge-graph visualization. Cross-page references are stored as `[[wikilink]]` and `sources[]`; a future spec may add graphology/Louvain analysis.
- No chat agent / tool-use loop. Out of scope; depends on Project multi-instancing (separate spec, later).
- No local LLM caching layer beyond `.index/analysis_cache/` for Analyzer re-runs.
- No automatic PDF / DOCX extraction improvements (those libraries stay as-is).
- No deletion/cascade-cleanup logic for wiki pages in this spec (deferred).

## Architecture

### Pipeline change

```
collector:start  (queue 发出)
  └─► Collector.collect          → 写 raw/sources/<task_id>.ext
       └─► COLLECTOR_DONE

COLLECTOR_DONE  →  Analyzer.analyze
  └─► 调 LLM（Step 1: Analysis prompt）
  └─► 写 .index/analysis_cache/<task_id>.json
  └─► ANALYZER_DONE

ANALYZER_DONE  →  Generator.generate
  └─► 调 LLM（Step 2: Generation prompt，传入 AnalysisResult + 现有 wiki 索引）
  └─► page_writer 写 wiki/{sources,entities,concepts,...}/<slug>.md
  └─► wikilink 二次校验：未解析的 [[link]] 创建 stub 页
  └─► indexer 追加 wiki/index.md（所有页成功落地后才追加）
  └─► logger 追加 wiki/log.md
  └─► overviewer 每 5 次 ingest 触发 wiki/overview.md 重生成
  └─► GENERATOR_DONE

GENERATOR_DONE → Orchestrator._on_generator_done
  └─► audit_hard 校验每页 frontmatter
  └─► update_task_status(APPROVED, error=<failed list> if any)  # 部分成功策略
  └─► Librarian.archive        → embed wiki 页 → 入库
       └─► LIBRARIAN_DONE
```

### Directory layout

```
<KB root>/
├── raw/sources/
│   ├── <task_id>.<ext>           # 不可变源（collector 直接落这里）
│   └── .dead-letter/             # 替代 Inbox/Error/ 的死信目录
├── wiki/                         # 原 Notes/ 改名（v1→v2 migration 物理移动）
│   ├── sources/<task_id>.md
│   ├── entities/<slug>.md
│   ├── concepts/<slug>.md
│   ├── queries/<slug>.md
│   ├── synthesis/<slug>.md
│   ├── comparisons/<slug>.md
│   ├── index.md                  # LLM 维护的目录；.index/index_version 是机器读真相
│   ├── log.md                    # 追加式操作记录
│   ├── overview.md               # 每 5 次 ingest 重生成
│   └── .obsidian/app.json        # auto-generated Obsidian 配置
├── .index/                       # LanceDB + 内部 metadata
│   ├── lancedb/
│   ├── schema_version
│   ├── index_version             # int 计数器，atomic write
│   ├── overview_counter          # int 计数器，控制 overview.md 触发
│   ├── analysis_cache/<task_id>.json
│   └── wiki_meta.json            # 项目元信息（创建时间、LLM provider、output_language、prompt_versions）
└── Templates/                    # 保留（未来 wiki 页模板起点）
```

## Components

### New modules

| Path | Responsibility |
|---|---|
| `src/pipeline/analyzer.py` | Step 1: 调 LLM 把源文本 → `AnalysisResult`，写 `.index/analysis_cache/<task_id>.json` |
| `src/pipeline/schemas.py` | `AnalysisResult`, `EntityMention`, `ConceptMention`, `PageSpec` dataclasses |
| `src/pipeline/prompts/__init__.py` |  |
| `src/pipeline/prompts/system.py` | 通用 system prompt（语言、JSON 严格性、citation 规则） |
| `src/pipeline/prompts/analyzer.py` | Step 1 prompt + `PROMPT_VERSION = "2026-07-21-v1"` |
| `src/pipeline/prompts/generator.py` | Step 2 prompt + `PROMPT_VERSION = "2026-07-21-v1"` |
| `src/wiki/__init__.py` |  |
| `src/wiki/page_writer.py` | 写 `wiki/<type>/<slug>.md`；注入 frontmatter 必填字段；sources[] 强制 |
| `src/wiki/wikilink.py` | `WikilinkResolver`：`[[id\|alias]]` ↔ 文件路径双向解析；**解析优先级：frontmatter `id` 字段 > file stem**；stub 创建 |
| `src/wiki/templates.py` | `WikiPageRenderer`：每个 render_* 是纯 Python（不调 LLM） |
| `src/wiki/indexer.py` | `WikiIndexer`：增量追加 / 全量重建；维护 `.index/index_version` |
| `src/wiki/logger.py` | `WikiLog`：追加 `wiki/log.md` |
| `src/wiki/overviewer.py` | `WikiOverviewer`：每 5 次 ingest 触发；调 LLM 重生成 `overview.md` |
| `src/wiki/obsidian.py` | 首次 init 时写 `.obsidian/app.json` 基础配置 |
| `src/schemas/migrations/__init__.py` |  |
| `src/schemas/migrations/v1_to_v2.py` | 注册 `v1.0 → v2.0` 迁移；含可逆 `down_fn`（结构可逆、内容不可逆） |
| `tests/_helpers/mock_llm.py` | `MockLLMProvider`：scripted_responses 主路径 |

### Modified modules

| Path | Change |
|---|---|
| `src/pipeline/processor.py` | 改名为概念上的 **Generator**（保留文件名）；接收 `AnalysisResult` 而非 raw content；调 LLM 生成所有页面 JSON；走 `templates.WikiPageRenderer` 渲染 |
| `src/pipeline/pipeline.py` | 插入 `ANALYZER_DONE → Generator.generate` 桥接；新增 `GENERATOR_DONE` 订阅 |
| `src/pipeline/collector.py` | 写 `raw/sources/<task_id><ext>`；失败挪到 `raw/sources/.dead-letter/`；删除 `InboxManager` 依赖 |
| `src/permissions.py` | 调整白名单：`Collector` 全域读 + 写 `raw/sources`；`Analyzer` 读 `raw/sources` + 写 `.index/`；`Generator` 读 `raw/sources` + `.index/` + `wiki/` + 写 `wiki/`；`Librarian` 读 `wiki/` + 写 `.index/`；`Searcher` 读 `wiki/` + `.index/` |
| `src/orchestrator/audit_hard.py` | 增加 wiki 页 frontmatter schema 校验（`id`/`type`/`title`/`sources[]`/`created_at`/`updated_at` 必填） |
| `src/knowledge_base.py` | `KnowledgeBasePaths` 加 `raw_sources` / `wiki` / `wiki_sources` / `wiki_entities` / ...；`ensure_knowledge_base` 创建 `raw/sources/.dead-letter/` |
| `src/cli.py` | `cmd_ingest` 报"未配置 LLM"硬错误时给友好提示 + `configure` 子命令链接；新增 `cmd_rebuild_index` 触发 `WikiIndexer.full_rebuild()` |
| `src/types.py` | `VectorChunk` 加 `page_type`/`page_id`；`KnowledgeTask` 加 `wiki_pages`/`wiki_failed`/`analysis_cache_path` |
| `src/events/events.py` | 新增 `EventName.ANALYZER_DONE` / `EventName.GENERATOR_DONE`；新增 `AnalysisResultPayload` / `GeneratorDonePayload` |
| `src/llm/base.py` | `LLMProvider` 加 `complete_json(prompt, response_schema, system=None, max_retries=1)` 抽象方法 |
| `src/llm/openai_provider.py` / `src/llm/anthropic_provider.py` | 实现 `complete_json`（OpenAI: response_format=json_schema 或 tool use；Anthropic: system + tool use 强制 JSON 输出） |
| `src/queue/queue.py` | `QUEUE_FILE = ".index/queue.json"`（从根目录 `.kb-queue.json` 迁移）；`_save_queue` 持久化新字段；`update_task_status(REJECTED, error=<failed list>)` 支持部分成功 |

### Deleted modules

| Path | Reason |
|---|---|
| `src/inbox/manager.py` | Inbox 概念消失，collector 直接写 `raw/sources/` |
| `src/inbox/__init__.py` + `tests/test_inbox.py` | 同上 |
| `src/pipeline/processor.py` 中旧 `calculate_quality_metrics` / 关键词 tag 逻辑 | 改为模板渲染；质量评估留给 audit_hard |

### Test files

```
tests/
├── test_pipeline/
│   ├── test_analyzer.py
│   ├── test_generator.py
│   └── test_pipeline_wiring.py
├── test_wiki/
│   ├── test_page_writer.py
│   ├── test_wikilink.py
│   ├── test_indexer.py
│   ├── test_logger.py
│   ├── test_overviewer.py
│   ├── test_obsidian.py
│   └── test_templates.py
├── test_schemas/
│   └── test_v1_to_v2.py
├── test_permissions/
│   └── test_new_paths.py
└── test_vector/
    └── test_page_type_filter.py
```

## Data structures

```python
# src/pipeline/schemas.py
@dataclass
class AnalysisResult:
    task_id: str
    source_path: str                          # raw/sources/<task_id>.<ext>
    summary: str                              # <= 100 字
    key_facts: list[str]                      # 3-7 条
    entities: list[EntityMention]             # confidence >= 0.6
    concepts: list[ConceptMention]
    suggested_pages: list[PageSpec]           # LLM 建议生成的页面
    links_to_existing: list[str]              # 已存在 wiki 页 id

    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, raw: str) -> "AnalysisResult": ...

@dataclass
class EntityMention:
    name: str
    slug: str                                 # kebab-case, ascii, <= 64 chars
    type: str                                 # person | org | product | place
    context: str
    confidence: float                         # 0-1

@dataclass
class ConceptMention:
    name: str
    slug: str
    context: str
    confidence: float

@dataclass
class PageSpec:
    type: str                                 # source | entity | concept | synthesis
    slug: str
    title: str
    reasoning: str
```

```python
# src/types.py (modified)
class PageType(str, Enum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    QUERY = "query"
    SYNTHESIS = "synthesis"
    COMPARISON = "comparison"

@dataclass
class WikiPage:
    id: str                                   # kebab-case，唯一
    title: str
    type: PageType
    file_path: str                            # 绝对路径
    frontmatter: dict
    body: str
    sources: list[str]                        # raw/sources/* 相对路径
    created_at: int
    updated_at: int

@dataclass
class GeneratedPages:
    task_id: str
    pages: list[WikiPage]                     # 成功写入的页
    failed: list[tuple[str, str]]             # [(slug, error), ...]
    index_version: int                        # 本次 ingest 后的 index_version
```

```python
# src/events/events.py (modified)
class EventName:
    ANALYZER_DONE = "analyzer:done"
    GENERATOR_DONE = "generator:done"

@dataclass
class AnalysisResultPayload:
    task_id: str
    analysis_path: str                        # .index/analysis_cache/<task_id>.json
    entities: list[str]
    concepts: list[str]
    suggested_pages: list[dict]

@dataclass
class GeneratorDonePayload:
    task_id: str
    pages: list[str]                          # 写入的 wiki 页绝对路径
    failed: list[str]                         # 失败 slug 列表
    index_version: int
```

## LLM protocol

### `LLMProvider.complete_json(prompt, response_schema, system=None, max_retries=1) -> dict`

- 主路径：JSON Schema 强约束
- 兜底：解析失败时正则 `\{.*\}` 提取最大 JSON 块 + system 提示"严格输出 JSON 无 fence 无解释"重试
- 两次都失败 → raise `LLMJsonError`

### Step 1: Analyzer prompt

**Input**: `<source_text>` (源全文，截断到模型 context window 80%) + `<existing_index>` (`wiki/index.md`, ~200 行) + `<existing_entities>` + `<existing_concepts>` (现有 id 列表)

**Output (strict JSON)**:
```json
{
  "summary": "<一句话源摘要，<= 100 字>",
  "key_facts": ["..."],
  "entities": [{"name", "slug", "type", "context", "confidence"}],
  "concepts": [{"name", "slug", "context", "confidence"}],
  "suggested_pages": [{"type", "slug", "title", "reasoning"}],
  "links_to_existing": ["<id>", ...]
}
```

**Constraints (硬编码进 prompt)**:
- entities/concepts 只列 confidence >= 0.6
- slug: kebab-case, ascii only, <= 64 chars
- slug 与现有 wiki/{entities,concepts}/ id 冲突 → LLM 必须重命名 + reasoning 说明
- suggested_pages 中 source 类型只能有 1 条（slug = `<task_id>`）
- key_facts 3-7 条

### Step 2: Generator prompt

**Input**: `<analysis_json>` (Step 1 完整输出) + `<existing_index>` (`wiki/index.md`) + `<template_hints>` (每类页必填字段名清单)

**Output (strict JSON)**:
```json
{
  "pages": [
    {
      "id": "<task_id>",                      # source 页 id == task_id
      "type": "source",
      "title": "...",
      "frontmatter_extra": {                  # 只填额外字段，代码补必填
        "tags": ["..."],
        "category": "..."
      },
      "body_markdown": "..."                  # 不含 frontmatter，纯 markdown 正文
    }
  ]
}
```

**关键约束**: Generator 不生成 frontmatter。LLM 只生成 `body_markdown` + `frontmatter_extra`。`id`/`type`/`title`/`sources[]`/`created_at`/`updated_at` 由 `WikiPageRenderer` 在代码里统一构造，保证 schema 严格。

### Prompt version management

- 每个 prompt 文件顶部 `PROMPT_VERSION = "2026-07-21-v1"`
- `.index/prompt_versions.json` 记录最近一次成功的 prompt 版本对
- **启动时一次性检测**：CLI / HTTP server 启动时比对新旧版本，不一致 → invalidate `.index/analysis_cache/` 下所有旧版缓存 → 下次 ingest 全部重跑 Step 1
- 运行中不检测（避免批量 ingest 半途失效）

### System prompt (src/pipeline/prompts/system.py)

- 响应语言跟 `wiki_meta.json.output_language`
- 输出必须是纯 JSON，无 ```json fence，无解释
- 引用 wiki 已有页用 `[[id]]` 语法
- 不重复 AnalysisResult 已有的字段
- 不创造 AnalysisResult 没列出的新 entity/concept（必要时在 `extra_entities` 数组说明）

## Error handling

| Stage | Error type | Strategy |
|---|---|---|
| Collector | URL 404 / PDF 损坏 / 文件超大 | `RuntimeError` → task FAILED → 1 retry（指数退避 5s） → 仍失败 → 挪 `raw/sources/.dead-letter/` + task ARCHIVED + reason 写 `log.md` |
| Analyzer | LLM 超时 / JSON 解析失败 / Schema 不符 | 2 retries（同一 prompt + "严格 JSON" 提示） → 仍失败 → task FAILED + 挪 `.dead-letter/` |
| Generator | 同 Analyzer + 单页失败 | **部分成功**：成功的页写 `wiki/`；失败的进 `task.wiki_failed`；task 最终 = APPROVED if no failure else REJECTED（task.error 列出失败清单） |
| Librarian | LanceDB 写入失败 | retry 3 次 → `circuit_breaker("lancedb").record_failure()`；连续 3 task 失败 → OPEN 60s |
| Indexer/Logger/Overviewer | 文件 I/O 失败 | warning log，不阻塞 task；下批 ingest 补齐 |

### Circuit breakers

- LLM 调用 ≥ 3 次连续超时 → `circuit_breaker("llm_provider")` OPEN 60s
- LanceDB 写入 ≥ 3 次失败 → `circuit_breaker("lancedb")` OPEN 60s

## Backwards compatibility & migration

### v1.0 → v2.0 migration (`src/schemas/migrations/v1_to_v2.py`)

`up_fn`:
1. 创建 `raw/sources/` 目录（不存在）
2. 把 `Notes/<task_id>.md` 物理移动到 `wiki/sources/<task_id>.md`
3. frontmatter schema 升级（如有 `quality_score`/`tags` 字段则保留；新增 `id: <task_id>` / `type: source` / `sources: []` / `created_at` / `updated_at`）
4. 创建 `wiki/entities/` `wiki/concepts/` `wiki/queries/` `wiki/synthesis/` `wiki/comparisons/`（空目录）
5. 初始化 `wiki/index.md` / `wiki/log.md` / `wiki/overview.md` 空模板
6. 创建 `.index/index_version = 0` / `.index/overview_counter = 0` / `.index/prompt_versions.json`
7. 删除 `Inbox/` 目录（含 `Pending`/`Processing`/`Error`）
8. 把根目录 `.kb-queue.json` 移到 `.index/queue.json`（ruflo-kb 后续所有持久化元数据归 `.index/`）
9. 更新 `.index/schema_version = "v2.0"`

`down_fn`:
1. 把 `wiki/sources/<task_id>.md` 移回 `Notes/<task_id>.md`
2. frontmatter schema 降级（移除 `id`/`type`/`sources[]`/`created_at`/`updated_at`）
3. 删除 `wiki/entities/` `wiki/concepts/` `wiki/queries/` `wiki/synthesis/` `wiki/comparisons/`
4. 把 `wiki/index.md` / `wiki/log.md` / `wiki/overview.md` 移到 `_archived_v2_content/`
5. 重建 `Inbox/{Pending,Processing,Error}/`
6. 删除 `raw/sources/`（保留 `.dead-letter/` 不删）
7. 把 `.index/queue.json` 移回根目录 `.kb-queue.json`
8. 更新 `.index/schema_version = "v1.0"`

**down_fn 不保证内容可逆**：v2.0 期间 LLM 生成的 entity/concept 等页面被移到 `_archived_v2_content/`，不参与 v1 解析。

## Testing strategy

### Unit tests (mocked LLM)

`tests/_helpers/mock_llm.py`:
```python
class MockLLMProvider:
    def __init__(self, scripted_responses: list[dict]):
        self.scripted = list(scripted_responses)
        self.calls = []

    async def complete_json(self, prompt, response_schema, system=None, max_retries=1):
        self.calls.append({"prompt": prompt, "schema": response_schema})
        if not self.scripted:
            raise RuntimeError("Mock exhausted")
        return self.scripted.pop(0)
```

`pyproject.toml` 加 `pytest` markers:
```toml
[tool.pytest.ini_options]
markers = [
    "real_llm: requires real LLM API key; opt-in via -m real_llm",
]
```

### Real LLM smoke tests (opt-in)

`tests/test_pipeline/test_analyzer.real-llm.py` — 走真实 LLM，pytest 默认跳过，`pytest -m real_llm` 启用。开发者本地手动跑一次验证 prompt 没坏。

### Coverage targets

- `src/pipeline/analyzer.py`: prompt 构造、response 解析、retry、cache 写入
- `src/pipeline/processor.py` (Generator): prompt 构造、模板渲染、wikilink 注入、sources[] 强制、stub 创建
- `src/wiki/*`: 每个 module 一个 test file
- `src/schemas/migrations/v1_to_v2.py`: up + down + 幂等性
- `src/permissions.py`: 新白名单路径测试

## Implementation order

按依赖图分 6 阶段：

1. **Foundation**: `src/pipeline/schemas.py` + `src/types.py` 更新 + `src/events/events.py` 新事件 + `src/wiki/templates.py` + tests
2. **Wiki primitives**: `src/wiki/page_writer.py` + `src/wiki/wikilink.py` + `src/wiki/indexer.py` + `src/wiki/logger.py` + `src/wiki/obsidian.py` + tests
3. **LLM JSON abstraction**: `src/llm/base.py` `complete_json` + OpenAI/Anthropic 实现 + `MockLLMProvider` + tests
4. **Pipeline integration**: `src/pipeline/analyzer.py` + `src/pipeline/prompts/*` + `src/pipeline/processor.py` 重写 + `src/pipeline/pipeline.py` 桥接 + `src/pipeline/collector.py` 改写 + tests
5. **Migration & KB init**: `src/schemas/migrations/v1_to_v2.py` + `src/knowledge_base.py` 更新 + `src/cli.py` 更新 + tests
6. **Cross-cutting**: `src/permissions.py` 新白名单 + `src/orchestrator/audit_hard.py` frontmatter 校验 + `src/queue/queue.py` 新字段持久化 + `src/wiki/overviewer.py` + tests

每阶段一提交，沿用 `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md` 的 TDD-per-task 节奏。

## Cost estimation

单源 ingest（典型论文 / 博客）：
- Step 1: ~1500 in + ~500 out = ~2000 tokens
- Step 2: ~2000 in + ~2000 out = ~4000 tokens
- 单源总计 ~6000 tokens × 2 calls
- 默认模型（gpt-4o-mini / claude-haiku-4-5）: $0.01-0.03/源

## Open questions / deferred

- Project 多实例化（依赖此 spec 完成后单开 spec）
- HTTP API + MCP（依赖 Project 多实例化）
- 两阶段 CoT 的 prompt A/B 测试框架（远期）
- Wiki 页 lint 操作（参考 llm_wiki-main 的 lint.ts；独立 spec）
- Cascade deletion（删除源时清理相关 wiki 页；独立 spec）