# Wiki Semantic Structure (v2.0) Design Spec

**Date:** 2026-07-21 (rev 2 — A1-A7 features integrated)
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ ad4fb38)
**Inspired by:** llm_wiki-main (nashsu/llm_wiki) — selective adoption, not a port

## Goal

Replace ruflo-kb's flat `Notes/<task_id>.md` output with an Obsidian-compatible, semantically-structured wiki that turns each ingested source into an interconnected set of typed pages (source summary, entities, concepts, queries, synthesis, comparisons), produced by a two-step LLM pipeline (Analyzer → Generator).

The v2.0 release also brings **seven lifecycle features** borrowed from llm_wiki-main: cascade deletion on source removal, folder-aware ingest with classification hints, async review items for human judgment, lint operation for wiki health, schema routing validation, ZIP export/import for project migration, and LLM-driven duplicate-entity merge.

The wiki directory is human-readable as-is (Obsidian vault), machine-traversable via `[[wikilink]]` resolution, and exposes enough metadata (`sources[]` frontmatter, `index_version` counter) for downstream tools to query without re-parsing prose.

## Non-goals

- No GUI / TUI. CLI + Python API + (future) HTTP API only.
- No knowledge-graph visualization (no sigma.js, no Louvain UI). Cross-page references are stored as `[[wikilink]]` and `sources[]`; a future spec may add graphology/Louvain analysis.
- No chat agent / tool-use loop. Out of scope; depends on Project multi-instancing (separate spec, later).
- No local LLM caching layer beyond `.index/analysis_cache/` for Analyzer re-runs.
- No automatic PDF / DOCX extraction improvements (those libraries stay as-is).
- No image extraction / captioning (vision LLM + storage not in scope).
- No Chrome extension / web clipper.
- No i18n UI strings (CLI-only).
- No KaTeX / Mermaid rendering (no UI).
- No web search / Deep Research integration (depends on HTTP API spec).
- Graph relevance scoring (4-signal model) is **deferred to v2.1** — see Open Questions.

## Architecture

### Pipeline change

```
collector:start  (queue 发出)
  └─► Collector.collect          → 写 raw/sources/<task_id>.<ext>
       │   (folder_context 传给 Analyzer: "papers > energy")
       └─► COLLECTOR_DONE

COLLECTOR_DONE  →  Analyzer.analyze
  └─► 调 LLM（Step 1: Analysis prompt；含 folder_context + existing wiki 索引）
  └─► 写 .index/analysis_cache/<task_id>.json
  └─► 抽取 review_items 写 .index/reviews.json（追加，去重按 normalized_title）
  └─► ANALYZER_DONE

ANALYZER_DONE  →  Generator.generate
  └─► 调 LLM（Step 2: Generation prompt，传入 AnalysisResult + 现有 wiki 索引）
  └─► page_writer 写 wiki/{sources,entities,concepts,...}/<slug>.md
  └─► wikilink 二次校验：未解析的 [[link]] 创建 stub 页（frontmatter.stub: true）
  └─► indexer 追加 wiki/index.md（所有页成功落地后才追加）
  └─► logger 追加 wiki/log.md
  └─► overviewer 每 5 次 ingest 触发 wiki/overview.md 重生成
  └─► GENERATOR_DONE

GENERATOR_DONE → Orchestrator._on_generator_done
  └─► audit_hard 校验每页 frontmatter + schema routing（type → dir 一致性）
  └─► update_task_status(APPROVED, error=<failed list> if any)  # 部分成功策略
  └─► Librarian.archive        → embed wiki 页 → 入库
       └─► LIBRARIAN_DONE
```

### Lifecycle CLI commands (separate from ingest pipeline)

```
python -m src.cli delete <task_id>
  └─► cascade_delete.run(project, task_id)
       │   1. 找到所有 sources: [raw/sources/<task_id>.*] 的 wiki 页
       │   2. source 页整页删除；entity/concept 页从 sources[] 移除该 source
       │   3. 若 entity/concept 页 sources[] 变空 → 删除该页
       │   4. 重写所有 [[wikilink]] 引用（指向被删的 page → 指向 stub 或删除）
       │   5. 重建 wiki/index.md（删条目）+ .index/index_version += 1
       │   6. 删 raw/sources/<task_id>.<ext>
       └─► emit CASCADE_DELETE_COMPLETED

python -m src.cli review [--list | --resolve <id> | --dismiss <id>]
  └─► review_manager.list/resolve/dismiss
       │   读 .index/reviews.json（normalized_title 去重）
       └─► 写入 .index/reviews_resolved.json（已处理归档）

python -m src.cli lint [--fix] [--json]
  └─► lint_runner.run(project, fix=False)
       │   5 类问题：orphan / broken-link / no-outlinks / semantic / duplicate
       │   semantic 类调 LLM 分析（可选，跳过用 --no-llm）
       └─► 输出报告；--fix 时自动修复 broken-link + orphan 提示

python -m src.cli export <output.zip>
  └─► export_runner.run(project, output)
       │   打 zip：raw/sources/ + wiki/ + .index/wiki_meta.json + schema.md
       │   不打 .index/lancedb/（太大；可在目标机器 ingest 时重建）
       └─► 写入 output.zip

python -m src.cli import <archive.zip> [--target <dir>]
  └─► import_runner.run(archive, target)
       │   解压 → 检查 schema_version → 兼容迁移（如 v1→v2）→ 写 .index/wiki_meta.json
       │   提示用户运行 ingest --rescan 重建向量库
       └─► emit IMPORT_COMPLETED

python -m src.cli dedup [--auto] [--threshold 0.7]
  └─► dedup_runner.run(project)
       │   Stage 1: extract_entity_summaries() — 扫 wiki/entities + concepts
       │   Stage 2: detect_duplicate_groups() — 调 LLM 找同义组
       │   Stage 3: 用户确认 → merge_duplicate_group() — 合并页 + 重写 wikilink + index
       └─► emit PAGES_MERGED

python -m src.cli ingest --folder <dir>
  └─► Collector.collect_folder(folder_path)
       │   递归扫描 dir；每个文件 enqueue_task(folder_context=folder path)
       └─► 走标准 ingest pipeline
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
│   ├── log.md                    # 追加式操作记录（含 source_delete 条目）
│   ├── overview.md               # 每 5 次 ingest 重生成
│   ├── schema.md                 # ⭐ A5: schema routing 规则（auto-generated）
│   └── .obsidian/app.json        # auto-generated Obsidian 配置
├── .index/                       # LanceDB + 内部 metadata
│   ├── lancedb/
│   ├── schema_version
│   ├── index_version             # int 计数器，atomic write
│   ├── overview_counter          # int 计数器，控制 overview.md 触发
│   ├── analysis_cache/<task_id>.json
│   ├── reviews.json              # ⭐ A3: 待人工裁决的 review items
│   ├── reviews_resolved.json     # ⭐ A3: 已处理归档
│   ├── lint_history/             # ⭐ A4: 历史 lint 报告
│   │   └── YYYY-MM-DD-HHMMSS.json
│   ├── wiki_meta.json            # 项目元信息 + schema routing schema_md 路径
│   └── prompt_versions.json
└── Templates/                    # 保留
```

## Components

### New modules

| Path | Responsibility |
|---|---|
| `src/pipeline/analyzer.py` | Step 1: 调 LLM 把源文本 → `AnalysisResult`；写 `.index/analysis_cache/<task_id>.json`；抽 review_items 写 `.index/reviews.json` |
| `src/pipeline/schemas.py` | `AnalysisResult`, `EntityMention`, `ConceptMention`, `PageSpec`, `ReviewItem`, `FolderContext` dataclasses |
| `src/pipeline/prompts/__init__.py` |  |
| `src/pipeline/prompts/system.py` | 通用 system prompt（语言、JSON 严格性、citation 规则） |
| `src/pipeline/prompts/analyzer.py` | Step 1 prompt + `PROMPT_VERSION = "2026-07-21-v1"` |
| `src/pipeline/prompts/generator.py` | Step 2 prompt + `PROMPT_VERSION = "2026-07-21-v1"` |
| `src/pipeline/prompts/lint_semantic.py` | ⭐ A4: lint semantic analysis prompt |
| `src/pipeline/prompts/dedup_detect.py` | ⭐ A7: dedup 同义组检测 prompt |
| `src/wiki/__init__.py` |  |
| `src/wiki/page_writer.py` | 写 `wiki/<type>/<slug>.md`；注入 frontmatter 必填字段；sources[] 强制 |
| `src/wiki/wikilink.py` | `WikilinkResolver`：`[[id\|alias]]` ↔ 文件路径双向解析；**解析优先级：frontmatter `id` 字段 > file stem**；stub 创建 |
| `src/wiki/templates.py` | `WikiPageRenderer`：每个 render_* 是纯 Python（不调 LLM） |
| `src/wiki/indexer.py` | `WikiIndexer`：增量追加 / 全量重建；维护 `.index/index_version` |
| `src/wiki/logger.py` | `WikiLog`：追加 `wiki/log.md`（ingest、source_delete、dedup、lint_fix 条目） |
| `src/wiki/overviewer.py` | `WikiOverviewer`：每 5 次 ingest 触发；调 LLM 重生成 `overview.md` |
| `src/wiki/obsidian.py` | 首次 init 时写 `.obsidian/app.json` 基础配置 |
| `src/wiki/schema_routing.py` | ⭐ A5: 读 `wiki/schema.md` 解析 `type → dir` 路由；`validate_page_routing(relative_path, frontmatter)` |
| `src/wiki/cascade_delete.py` | ⭐ A1: `CascadeDeleter.run(task_id)` 删除源 + 级联清理 wiki 页 + 重写 wikilink + 重建 index |
| `src/wiki/lint.py` | ⭐ A4: `LintRunner.run(fix=False)` 5 类问题扫描 + 自动修复 |
| `src/wiki/review.py` | ⭐ A3: `ReviewManager` 读 `.index/reviews.json`；list/resolve/dismiss；按 `normalize_review_title` 去重 |
| `src/wiki/dedup.py` | ⭐ A7: 3 阶段 dedup：`extract_entity_summaries()` → `detect_duplicate_groups()` → `merge_duplicate_group()` |
| `src/schemas/migrations/__init__.py` |  |
| `src/schemas/migrations/v1_to_v2.py` | 注册 `v1.0 → v2.0` 迁移；含可逆 `down_fn`（结构可逆、内容不可逆） |
| `src/export/__init__.py` | ⭐ A6: `export_project(project, output_zip)` |
| `src/export/importer.py` | ⭐ A6: `import_project(archive_zip, target_dir)` + schema 兼容性检查 |
| `src/cli_ext/__init__.py` | ⭐ 新增 CLI 子命令分发层（避免 src/cli.py 变成 god-file） |
| `src/cli_ext/delete.py` | ⭐ A1: `cmd_delete` |
| `src/cli_ext/review.py` | ⭐ A3: `cmd_review` |
| `src/cli_ext/lint.py` | ⭐ A4: `cmd_lint` |
| `src/cli_ext/dedup.py` | ⭐ A7: `cmd_dedup` |
| `src/cli_ext/export_import.py` | ⭐ A6: `cmd_export` + `cmd_import` |
| `tests/_helpers/mock_llm.py` | `MockLLMProvider`：scripted_responses 主路径 |

### Modified modules

| Path | Change |
|---|---|
| `src/pipeline/processor.py` | 改名为概念上的 **Generator**（保留文件名）；接收 `AnalysisResult` + `folder_context` 而非 raw content；调 LLM 生成所有页面 JSON；走 `templates.WikiPageRenderer` 渲染 |
| `src/pipeline/pipeline.py` | 插入 `ANALYZER_DONE → Generator.generate` 桥接；新增 `GENERATOR_DONE` 订阅；启动时检查 `.index/prompt_versions.json` 不一致则清空 `.index/analysis_cache/` |
| `src/pipeline/collector.py` | 新增 `collect_folder(folder_path)`；单文件走 `collect(source_path, folder_context="")`；写 `raw/sources/<task_id><ext>`；失败挪到 `raw/sources/.dead-letter/`；删除 `InboxManager` 依赖 |
| `src/permissions.py` | 调整白名单：`Collector` 全域读 + 写 `raw/sources`；`Analyzer` 读 `raw/sources` + 写 `.index/`；`Generator` 读 `raw/sources` + `.index/` + `wiki/` + 写 `wiki/`；`Librarian` 读 `wiki/` + 写 `.index/`；`Searcher` 读 `wiki/` + `.index/`；新 agent `CascadeDeleter` 读 `wiki/` + 写 `wiki/` + `.index/`；新 agent `LintRunner` 读 `wiki/` + 写 `wiki/` + `.index/lint_history/`；新 agent `DedupRunner` 读 `wiki/` + 写 `wiki/` |
| `src/orchestrator/audit_hard.py` | 增加 wiki 页 frontmatter schema 校验（`id`/`type`/`title`/`sources[]`/`created_at`/`updated_at` 必填）+ `schema_routing.validate_page_routing` 调用 |
| `src/knowledge_base.py` | `KnowledgeBasePaths` 加 `raw_sources` / `wiki` / `wiki_sources` / `wiki_entities` / ...；`ensure_knowledge_base` 创建 `raw/sources/.dead-letter/` + 首次生成 `wiki/schema.md` 默认模板 + `.index/reviews.json` 空数组 |
| `src/cli.py` | `cmd_ingest` 支持 `--folder`；报"未配置 LLM"硬错误时给友好提示 + `configure` 子命令链接；新增 `cmd_rebuild_index` 触发 `WikiIndexer.full_rebuild()`；分发到 `src/cli_ext/*` 子命令 |
| `src/types.py` | `VectorChunk` 加 `page_type`/`page_id`；`KnowledgeTask` 加 `wiki_pages`/`wiki_failed`/`analysis_cache_path`/`folder_context` |
| `src/events/events.py` | 新增 `EventName.ANALYZER_DONE` / `GENERATOR_DONE` / `CASCADE_DELETE_COMPLETED` / `IMPORT_COMPLETED` / `PAGES_MERGED`；新增 payload `AnalysisResultPayload` / `GeneratorDonePayload` / `CascadeDeletePayload` / `ImportCompletedPayload` / `PagesMergedPayload` |
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
│   ├── test_templates.py
│   ├── test_schema_routing.py         # ⭐ A5
│   ├── test_cascade_delete.py         # ⭐ A1
│   ├── test_lint.py                   # ⭐ A4
│   ├── test_review.py                 # ⭐ A3
│   └── test_dedup.py                  # ⭐ A7
├── test_export/
│   ├── test_export.py                 # ⭐ A6
│   └── test_import.py                 # ⭐ A6
├── test_cli_ext/
│   ├── test_cmd_delete.py             # ⭐ A1
│   ├── test_cmd_review.py             # ⭐ A3
│   ├── test_cmd_lint.py               # ⭐ A4
│   ├── test_cmd_dedup.py              # ⭐ A7
│   └── test_cmd_export_import.py      # ⭐ A6
├── test_schemas/
│   └── test_v1_to_v2.py
├── test_permissions/
│   └── test_new_paths.py
└── test_vector/
    └── test_page_type_filter.py
```

## Data structures

### Core (unchanged from v1 design)

```python
# src/pipeline/schemas.py
@dataclass
class AnalysisResult:
    task_id: str
    source_path: str
    summary: str
    key_facts: list[str]
    entities: list[EntityMention]
    concepts: list[ConceptMention]
    suggested_pages: list[PageSpec]
    links_to_existing: list[str]
    folder_context: str                  # ⭐ A2: 来自 Collector 的 folder path
    review_items: list[ReviewItem]       # ⭐ A3: Analyzer Step 1 顺手抽出

@dataclass
class EntityMention:
    name: str
    slug: str
    type: str
    context: str
    confidence: float

@dataclass
class ConceptMention:
    name: str
    slug: str
    context: str
    confidence: float

@dataclass
class PageSpec:
    type: str
    slug: str
    title: str
    reasoning: str
```

```python
# src/types.py
class PageType(str, Enum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    QUERY = "query"
    SYNTHESIS = "synthesis"
    COMPARISON = "comparison"
    STUB = "stub"                        # ⭐ wikilink 未解析时的占位页

@dataclass
class WikiPage:
    id: str
    title: str
    type: PageType
    file_path: str
    frontmatter: dict
    body: str
    sources: list[str]
    created_at: int
    updated_at: int

@dataclass
class GeneratedPages:
    task_id: str
    pages: list[WikiPage]
    failed: list[tuple[str, str]]
    index_version: int

@dataclass
class KnowledgeTask:
    # ... existing fields ...
    wiki_pages: list[str] = field(default_factory=list)
    wiki_failed: list[str] = field(default_factory=list)
    analysis_cache_path: str | None = None
    folder_context: str = ""             # ⭐ A2
```

### A1: Cascade Deletion

```python
# src/wiki/cascade_delete.py
@dataclass
class CascadeDeleteResult:
    task_id: str
    deleted_source_path: str             # raw/sources/<task_id>.<ext>
    deleted_wiki_pages: list[str]        # 整页删除的 wiki 页路径
    rewritten_wiki_pages: list[str]      # 只移除 sources[] 的页路径
    rewritten_wikilinks: int             # 重写的 [[link]] 引用数
    index_version: int
```

### A2: Folder Context

```python
# src/pipeline/schemas.py
@dataclass
class FolderContext:
    raw_path: str                        # 原始文件夹路径（用户传入）
    relative_path: str                   # 相对 KB 根的路径，如 "papers/energy"
    depth: int                           # 文件夹深度
    name: str                            # 最后一段文件夹名
    
    def to_hint(self) -> str:
        """生成 LLM 分类提示字符串"""
        return f"Folder context: {self.relative_path}"
```

### A3: Review Items

```python
# src/pipeline/schemas.py
@dataclass
class ReviewItem:
    id: str                              # uuid
    type: str                            # "missing-page" | "duplicate-page" | "uncertain-claim" | "needs-verification"
    title: str                           # 人类可读标题（如 "Missing page: Foo Bar"）
    normalized_title: str                # ⭐ 用于去重：剥前缀 + lower + collapse whitespace
    detail: str                          # 详细说明
    page_path: str | None                # 相关 wiki 页路径
    confidence: float                    # LLM 置信度 0-1
    search_queries: list[str]            # ⭐ 预生成的 Deep Research 检索问题（v2.0 不消费，v2.1+ 用）
    created_at: int
    source_task_id: str | None           # 哪个 ingest 触发的
    status: str = "open"                 # "open" | "resolved" | "dismissed"
    resolved_at: int | None = None
    resolved_action: str | None = None   # "create-page" | "deep-research" | "skip" | "merge"
```

`.index/reviews.json` 存储格式：
```json
{
  "version": 1,
  "items": [
    {"id": "...", "type": "...", "title": "...", "normalized_title": "...", ...}
  ]
}
```

去重规则（同 llm_wiki-main `normalizeReviewTitle`）：剥前缀 `missing-page:` / `缺失页面:` / `重复页面:` 等 + 折叠空白 + lowercase。同 `(type, normalized_title)` 视为同一项，只保留先到的。

### A4: Lint

```python
# src/wiki/lint.py
@dataclass
class LintIssue:
    type: str                            # "orphan" | "broken-link" | "no-outlinks" | "semantic" | "duplicate"
    severity: str                        # "warning" | "info"
    page: str                            # 短文件名（"foo.md"）
    detail: str
    affected_pages: list[str] | None = None    # 仅 duplicate 类型
    broken_target: str | None = None           # 仅 broken-link 类型
    suggested_target: str | None = None
    auto_fixable: bool = False

@dataclass
class LintReport:
    project_path: str
    scanned_at: int
    total_pages: int
    issues: list[LintIssue]
    auto_fixed: list[str] = field(default_factory=list)    # 自动修复的页路径

# 5 类问题定义（对齐 llm_wiki-main lint.ts）：
# - orphan: 没有 [[wikilink]] 指向它的页（不含 index.md/log.md/overview.md）
# - broken-link: 解析失败的 [[link]]
# - no-outlinks: 没有 [[wikilink]] 指出去的页
# - semantic: LLM 语义分析发现 contradiction / stale / missing-page / suggestion
# - duplicate: 同 normalized_title 出现多次（与 review_items.duplicate-page 重叠但更轻量）
```

### A5: Schema Routing

`wiki/schema.md` 默认模板（首次 `ensure_knowledge_base` 时生成）：

```markdown
# Wiki Schema Routing

## Page Types

| type | directory |
|------|-----------|
| source | wiki/sources |
| entity | wiki/entities |
| concept | wiki/concepts |
| query | wiki/queries |
| synthesis | wiki/synthesis |
| comparison | wiki/comparisons |
| stub | wiki/_stubs |

## Conventions

- All wiki pages MUST have frontmatter `id`, `type`, `title`, `sources[]`, `created_at`, `updated_at`.
- `id` is kebab-case, unique across the entire wiki.
- `sources[]` is relative paths to `raw/sources/<task_id>.<ext>`.
```

```python
# src/wiki/schema_routing.py
@dataclass
class WikiSchemaRouting:
    type_dirs: dict[str, str]            # {"entity": "wiki/entities", ...}

def parse_schema_routing(markdown: str) -> WikiSchemaRouting: ...
def validate_page_routing(relative_path: str, frontmatter: dict, routing: WikiSchemaRouting) -> str | None:
    """返回错误消息字符串，None 表示通过"""
```

### A6: Project Export / Import

```python
# src/export/__init__.py
@dataclass
class ProjectArchive:
    name: str                            # 项目名（KB 根目录名）
    schema_version: str                  # "v2.0"
    exported_at: int
    wiki_meta: dict                      # .index/wiki_meta.json 内容
    schema_md: str                       # wiki/schema.md 内容
    raw_sources: list[ArchiveEntry]
    wiki_files: list[ArchiveEntry]

@dataclass
class ArchiveEntry:
    relative_path: str                   # 相对 KB 根
    content: bytes                       # 文件内容（zip 内）
    size: int
    sha256: str                          # 校验用

# 不打包：
# - .index/lancedb/（太大；在目标机器跑 `python -m src.cli ingest --rescan` 重建）
# - .index/analysis_cache/（可重建）
# - .index/lint_history/（可清理）
# - .obsidian/（自动生成）
```

```python
# src/export/importer.py
@dataclass
class ImportResult:
    archive_path: str
    target_dir: str
    schema_version_before: str
    schema_version_after: str
    migration_applied: str | None        # "v1_to_v2" 等
    files_imported: int
    warnings: list[str]
```

### A7: Dedup (3-stage)

```python
# src/wiki/dedup.py
@dataclass
class EntitySummary:
    slug: str
    path: str                            # 相对 KB 根，如 "wiki/entities/foo.md"
    type: str
    title: str
    description: str | None              # 优先 frontmatter.description，否则正文首段（截 200 字）
    tags: list[str]

@dataclass
class DuplicateGroup:
    slugs: list[str]
    reason: str                          # LLM 给的同义理由
    confidence: str                      # "high" | "medium" | "low"

@dataclass
class MergeRequest:
    group: list[dict]                    # [{"slug", "path", "content"}, ...]
    canonical_slug: str                  # 保留哪个 slug（用户或 LLM 选）
    other_wiki_pages: list[dict]         # 用于重写 wikilink

@dataclass
class MergeResult:
    canonical_path: str
    deleted_paths: list[str]
    rewritten_wikilinks: int
    rewritten_index_entries: int
    new_content: str                     # LLM 合并后的页内容
```

### Events

```python
# src/events/events.py
class EventName:
    ANALYZER_DONE = "analyzer:done"
    GENERATOR_DONE = "generator:done"
    CASCADE_DELETE_COMPLETED = "cascade_delete:completed"     # ⭐ A1
    IMPORT_COMPLETED = "import:completed"                       # ⭐ A6
    PAGES_MERGED = "pages:merged"                               # ⭐ A7

@dataclass
class AnalysisResultPayload:
    task_id: str
    analysis_path: str
    entities: list[str]
    concepts: list[str]
    suggested_pages: list[dict]
    review_items: list[str]                                    # ⭐ A3: ReviewItem.id 列表

@dataclass
class GeneratorDonePayload:
    task_id: str
    pages: list[str]
    failed: list[str]
    index_version: int

@dataclass
class CascadeDeletePayload:                                     # ⭐ A1
    task_id: str
    deleted_wiki_pages: list[str]
    rewritten_wiki_pages: list[str]
    rewritten_wikilinks: int
    index_version: int

@dataclass
class ImportCompletedPayload:                                   # ⭐ A6
    target_dir: str
    files_imported: int
    migration_applied: str | None
    warnings: list[str]

@dataclass
class PagesMergedPayload:                                       # ⭐ A7
    canonical_path: str
    deleted_paths: list[str]
    rewritten_wikilinks: int
```

## LLM protocol

### `LLMProvider.complete_json(prompt, response_schema, system=None, max_retries=1) -> dict`

- 主路径：JSON Schema 强约束
- 兜底：解析失败时正则 `\{.*\}` 提取最大 JSON 块 + system 提示"严格输出 JSON 无 fence 无解释"重试
- 两次都失败 → raise `LLMJsonError`

### Step 1: Analyzer prompt

**Input**: `<source_text>` (源全文，截断到模型 context window 80%) + `<folder_context>` (A2: "Folder context: papers > energy") + `<existing_index>` (`wiki/index.md`, ~200 行) + `<existing_entities>` + `<existing_concepts>`

**Output (strict JSON)**:
```json
{
  "summary": "<一句话源摘要，<= 100 字>",
  "key_facts": ["..."],
  "entities": [{"name", "slug", "type", "context", "confidence"}],
  "concepts": [{"name", "slug", "context", "confidence"}],
  "suggested_pages": [{"type", "slug", "title", "reasoning"}],
  "links_to_existing": ["<id>", ...],
  "review_items": [                       // ⭐ A3
    {
      "type": "missing-page" | "duplicate-page" | "uncertain-claim" | "needs-verification",
      "title": "<Missing page: Foo Bar>",
      "detail": "<详细说明>",
      "confidence": 0.0-1.0,
      "search_queries": ["<query1>", "<query2>"]
    }
  ]
}
```

**Constraints (硬编码进 prompt)**:
- entities/concepts 只列 confidence >= 0.6
- slug: kebab-case, ascii only, <= 64 chars
- slug 与现有 wiki/{entities,concepts}/ id 冲突 → LLM 必须重命名 + reasoning 说明
- suggested_pages 中 source 类型只能有 1 条（slug = `<task_id>`）
- key_facts 3-7 条
- review_items 最多 5 条；每条 confidence >= 0.7（避免噪音）
- review_items 类型必须从 4 个固定值里选（防止 LLM 创造新类型）
- review_items.search_queries 0-3 条

### Step 2: Generator prompt

（不变，v1 设计的延续）

### Step 3: Lint Semantic Analysis prompt (⭐ A4)

**Input**: `<wiki_pages_summary>` 每个页 frontmatter + 前 500 字正文（截断到 context window 80%）

**Output (strict JSON)**:
```json
{
  "findings": [
    {
      "type": "contradiction" | "stale" | "missing-page" | "suggestion",
      "severity": "warning" | "info",
      "title": "<短标题>",
      "detail": "<详细说明>",
      "page": "<相关页 id 或 None>"
    }
  ]
}
```

**Constraints**:
- 最多 20 条 findings
- missing-page 的 title 必须**精确等于**现有页 basename 或 frontmatter id（`normalize_for_existence` 比对），否则丢弃
- type 必须是 4 个固定值之一

### Step 4: Dedup Detect prompt (⭐ A7)

**Input**: `<entity_summaries>` list of `{slug, title, description, tags}`（≤ 50 个，超出分批）

**Output (strict JSON)**:
```json
{
  "groups": [
    {
      "slugs": ["paos", "polyphosphate-accumulating-organisms"],
      "reason": "<同义理由>",
      "confidence": "high" | "medium" | "low"
    }
  ]
}
```

**Constraints**:
- 每个 group 至少 2 个 slug
- confidence = "low" 时该组会被 UI 标注"需人工确认"
- 不返回单 slug 组（无意义）

### Prompt version management

- 每个 prompt 文件顶部 `PROMPT_VERSION = "2026-07-21-v1"`
- `.index/prompt_versions.json` 记录最近一次成功的 prompt 版本对
- **启动时一次性检测**：CLI / HTTP server 启动时比对新旧版本，不一致 → invalidate `.index/analysis_cache/` 下所有旧版缓存 → 下次 ingest 全部重跑 Step 1
- 运行中不检测

### System prompt

- 响应语言跟 `wiki_meta.json.output_language`
- 输出必须是纯 JSON，无 ```json fence，无解释
- 引用 wiki 已有页用 `[[id]]` 语法

## Error handling

| Stage | Error type | Strategy |
|---|---|---|
| Collector | URL 404 / PDF 损坏 / 文件超大 | `RuntimeError` → task FAILED → 1 retry（指数退避 5s） → 仍失败 → 挪 `raw/sources/.dead-letter/` + task ARCHIVED + reason 写 `log.md` |
| Collector.folder | 路径不存在 / 不可读 | 硬错误退出，不入队 |
| Analyzer | LLM 超时 / JSON 解析失败 / Schema 不符 | 2 retries（同一 prompt + "严格 JSON" 提示） → 仍失败 → task FAILED + 挪 `.dead-letter/`；review_items 缺失不阻塞（fallback = []） |
| Generator | 同 Analyzer + 单页失败 | **部分成功**：成功的页写 `wiki/`；失败的进 `task.wiki_failed`；task 最终 = APPROVED if no failure else REJECTED（task.error 列出失败清单） |
| Librarian | LanceDB 写入失败 | retry 3 次 → `circuit_breaker("lancedb").record_failure()`；连续 3 task 失败 → OPEN 60s |
| Indexer/Logger/Overviewer | 文件 I/O 失败 | warning log，不阻塞 task；下批 ingest 补齐 |
| CascadeDeleter (⭐ A1) | wikilink 重写冲突（两个 stub 同名） | warning log，继续；report 列出冲突 |
| CascadeDeleter | source 文件不存在 | warning + 继续（用户可能先手动删了） |
| LintRunner (⭐ A4) | LLM semantic 调用失败 | 跳过 semantic 类，仅输出 orphan/broken-link/no-outlinks/duplicate 四类 |
| LintRunner --fix | 自动修复产生新冲突 | 回滚本次 fix，写 fix 失败清单到 report |
| ReviewManager (⭐ A3) | reviews.json 损坏 | 备份为 `.bak` + 重新初始化为空数组 + warning |
| Export (⭐ A6) | 文件读取失败 / 磁盘空间不足 | 整个 export 失败，回滚临时 zip |
| Import (⭐ A6) | schema_version 不兼容 | 列出需要的手动迁移步骤，询问用户 `--force` 才继续 |
| Import | archive zip 损坏 / 校验和不匹配 | 整个 import 失败，回滚已解压文件 |
| DedupRunner (⭐ A7) | LLM detect 失败 | 退回纯 slug 匹配（同 normalized_title） |
| DedupRunner merge | wikilink 重写冲突 | warning log；report 列出 |
| LLMProvider | 连续超时 / 5xx | `circuit_breaker("llm_provider")` OPEN 60s |

## Backwards compatibility & migration

### v1.0 → v2.0 migration (`src/schemas/migrations/v1_to_v2.py`)

`up_fn`:
1. 创建 `raw/sources/` 目录（不存在）
2. 把 `Notes/<task_id>.md` 物理移动到 `wiki/sources/<task_id>.md`
3. frontmatter schema 升级（如有 `quality_score`/`tags` 字段则保留；新增 `id: <task_id>` / `type: source` / `sources: []` / `created_at` / `updated_at`）
4. 创建 `wiki/entities/` `wiki/concepts/` `wiki/queries/` `wiki/synthesis/` `wiki/comparisons/` `wiki/_stubs/`（空目录）
5. 初始化 `wiki/index.md` / `wiki/log.md` / `wiki/overview.md` 空模板
6. 创建 `wiki/schema.md` 默认模板（A5）
7. 创建 `.index/index_version = 0` / `.index/overview_counter = 0` / `.index/prompt_versions.json` / `.index/reviews.json`（空数组）
8. 删除 `Inbox/` 目录（含 `Pending`/`Processing`/`Error`）
9. 把根目录 `.kb-queue.json` 移到 `.index/queue.json`
10. 更新 `.index/schema_version = "v2.0"`

`down_fn`:
1. 把 `wiki/sources/<task_id>.md` 移回 `Notes/<task_id>.md`
2. frontmatter schema 降级（移除 `id`/`type`/`sources[]`/`created_at`/`updated_at`）
3. 删除 `wiki/entities/` `wiki/concepts/` `wiki/queries/` `wiki/synthesis/` `wiki/comparisons/` `wiki/_stubs/`
4. 把 `wiki/index.md` / `wiki/log.md` / `wiki/overview.md` / `wiki/schema.md` 移到 `_archived_v2_content/`
5. 把 `.index/reviews.json` / `.index/lint_history/` 也移到 `_archived_v2_content/`
6. 重建 `Inbox/{Pending,Processing,Error}/`
7. 删除 `raw/sources/`（保留 `.dead-letter/` 不删）
8. 把 `.index/queue.json` 移回根目录 `.kb-queue.json`
9. 更新 `.index/schema_version = "v1.0"`

**down_fn 不保证内容可逆**：v2.0 期间 LLM 生成的 entity/concept 等页面被移到 `_archived_v2_content/`，不参与 v1 解析。

### Import compatibility (⭐ A6)

`import_project()` 流程：
1. 解压 zip 到临时目录
2. 读 `archive.wiki_meta.schema_version`
3. 与目标机器 `.index/schema_version` 比对：
   - 相同 → 直接拷贝到 target_dir
   - v1 → 目标 v2 → 自动调用 v1_to_v2.up_fn
   - v2 → 目标 v1 → 报错（要求用户先升级目标）
   - 其他组合 → 报错 + 列出已知迁移路径
4. 写 `.index/wiki_meta.json`
5. 写 `wiki/schema.md`
6. 提示用户运行 `python -m src.cli ingest --rescan` 重建向量库（因为 .index/lancedb/ 没打包）

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

### Coverage targets

| Module | Test focus |
|---|---|
| `src/pipeline/analyzer.py` | prompt 构造、response 解析、retry、cache 写入、review_items 抽取 + 去重 |
| `src/pipeline/processor.py` (Generator) | prompt 构造、模板渲染、wikilink 注入、sources[] 强制、stub 创建、folder_context 注入 |
| `src/pipeline/collector.py` | 单文件 + folder 两种入口；dead-letter 行为 |
| `src/wiki/page_writer.py` | 文件写入、frontmatter 注入、sources[] 强制、stub 标记 |
| `src/wiki/wikilink.py` | 双向解析、stub 创建、slug 冲突 |
| `src/wiki/indexer.py` | 增量追加、全量重建、version 同步 |
| `src/wiki/logger.py` | log.md 追加格式（ingest + source_delete + dedup + lint_fix） |
| `src/wiki/overviewer.py` | 5 次触发、LLM 集成（real-llm test 可选） |
| `src/wiki/obsidian.py` | `.obsidian/app.json` 生成 |
| `src/wiki/schema_routing.py` (⭐ A5) | 解析 schema.md、validate_page_routing |
| `src/wiki/cascade_delete.py` (⭐ A1) | 完整链路：source 页删 / entity 页改 sources[] / 空 sources[] 删 / wikilink 重写 / index 重建 |
| `src/wiki/lint.py` (⭐ A4) | 5 类问题检测；--fix 自动修复；LLM 失败降级 |
| `src/wiki/review.py` (⭐ A3) | 读 .index/reviews.json、normalize 去重、resolve/dismiss 状态机 |
| `src/wiki/dedup.py` (⭐ A7) | 3 阶段全链路 |
| `src/export/__init__.py` (⭐ A6) | 打包正确性、sha256 校验 |
| `src/export/importer.py` (⭐ A6) | 兼容矩阵、迁移调用、回滚 |
| `src/schemas/migrations/v1_to_v2.py` | up + down + 幂等性 |
| `src/permissions.py` | 新白名单路径 + 新 agent (CascadeDeleter/LintRunner/DedupRunner) |

### Real LLM smoke tests (opt-in)

`tests/test_pipeline/test_analyzer.real-llm.py` — 走真实 LLM，pytest 默认跳过，`pytest -m real_llm` 启用。

## Implementation order

按依赖图分 8 阶段：

1. **Foundation**: `src/pipeline/schemas.py` + `src/types.py` + `src/events/events.py` + `src/wiki/templates.py` + tests
2. **Wiki primitives**: `src/wiki/page_writer.py` + `src/wiki/wikilink.py` + `src/wiki/indexer.py` + `src/wiki/logger.py` + `src/wiki/obsidian.py` + `src/wiki/schema_routing.py` (A5) + tests
3. **LLM JSON abstraction**: `src/llm/base.py` `complete_json` + OpenAI/Anthropic 实现 + `MockLLMProvider` + tests
4. **Prompts module**: `src/pipeline/prompts/{system,analyzer,generator,lint_semantic,dedup_detect}.py`
5. **Pipeline integration**: `src/pipeline/analyzer.py` + `src/pipeline/processor.py` 重写 + `src/pipeline/pipeline.py` 桥接 + `src/pipeline/collector.py` 改写 + tests
6. **Lifecycle modules**: `src/wiki/cascade_delete.py` (A1) + `src/wiki/review.py` (A3) + `src/wiki/lint.py` (A4) + `src/wiki/dedup.py` (A7) + `src/export/{__init__,importer}.py` (A6) + tests
7. **CLI + migration**: `src/cli_ext/*` + `src/schemas/migrations/v1_to_v2.py` + `src/knowledge_base.py` 更新 + `src/cli.py` 更新 + tests
8. **Cross-cutting**: `src/permissions.py` 新白名单 + `src/orchestrator/audit_hard.py` frontmatter + schema routing 校验 + `src/queue/queue.py` 新字段持久化 + integration test

每阶段一提交，沿用 `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md` 的 TDD-per-task 节奏。

## Cost estimation

单源 ingest（典型论文 / 博客）：
- Step 1: ~1500 in + ~500 out = ~2000 tokens
- Step 2: ~2000 in + ~2000 out = ~4000 tokens
- 单源总计 ~6000 tokens × 2 calls
- 默认模型（gpt-4o-mini / claude-haiku-4-5）: $0.01-0.03/源

按需命令成本（不计入 ingest）：
- `lint`（含 semantic）: ~5000 in + ~1000 out = $0.005-0.015/wiki
- `dedup`（50 entities 一次性）: ~3000 in + ~500 out = $0.003-0.01/run

## Open questions / deferred (v2.1+)

- **Graph relevance scoring (4-signal model)** — Direct link ×3.0, source overlap ×4.0, Adamic-Adar ×1.5, type affinity ×1.0. 接入 searcher 后端排序。无需 UI，纯算法。
- **Louvain community detection** — 自动知识聚类；结果写到 `.index/communities.json`，给 searcher 当 rerank 信号。
- **Multi-provider LLM** — 加 Google Gemini、Ollama（local）。OpenAI/Anthropic 已实现，新增 provider 是 boilerplate。
- **Configurable LLM timeout per provider** — 默认 60s，本地慢模型不够；改成 provider config 里 `timeout_seconds`。
- **Project multi-instancing** — 多个 KB 项目独立运行；为 HTTP API / MCP 铺路。
- **HTTP API + MCP server** — `127.0.0.1:<port>` JSON API + bundled MCP server；让 Claude Code / Codex 等 agent 直接调用。
- **Deep Research** — web search (Tavily/SerpApi/SearXNG) + review_items.search_queries 消费 + auto-ingest 闭环。
- **Chat agent + skills + tool use** — tool-using runtime + SKILL.md scanning + workspace 文件生成。
- **Image extraction + caption** — vision LLM + 图片管理。
- **EPUB/MOBI support** — 文档解析扩展。
- **Cascade deletion 的"软删除"模式** — 当前是硬删除；如果未来要做"撤销"，需要保留 `.trash/` 暂存。
- **`wiki/_stubs/` 自动实体化** — 当前 stub 永远 stub；v2.1 可以让任何引用 stub 的 ingest 自动触发 stub → 实体页的转换（"按需实体化"）。
- **Lint semantic 调用频率** — v2.0 默认每次 lint 都调 LLM；v2.1 可以加 `--cache-ttl 24h` 选项缓存结果。
- **Dedup 的"自动合并 vs 用户确认"** — 当前 v2.0 必须用户确认；v2.1 可以加 `--auto --threshold 0.9` 选项。