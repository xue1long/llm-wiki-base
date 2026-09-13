# ADR-0009: Per-source Template Routing for Ingestion

- Status: **Proposed** (awaiting plan-audit round 1 + 2 + 人工复核)
- Date: 2026-09-06
- Owners: ruflo-kb pipeline team
- Related: `src/templates/loader.py`, `src/wiki/schema_registry.py`,
  `src/services/ingest.py`, `src/pipeline/ingest.py`,
  `src/pipeline/_pipeline_common.py`, `docs/adr/0008-v6-wiki-schema-extension-for-v2-migration.md`,
  `docs/superpowers/plans/2026-08-12-knowledge-base-scenario-templates.md`

## Context (现状与痛点)

ruflo-kb 的 wiki 摄取管线 (Collector → Analyzer → Generator) 目前**只使用项目根
`schema.md` / `purpose.md` / `taxonomy.md`** 这"全局单一"配置文件来驱动 LLM prompt
的注入与 `SchemaRegistry` 的自定义类型路由：

- `src/pipeline/_pipeline_common.py:_read_schema_text()` 永远读
  `paths.root/schema.md`；没有"按文件切换"机制。
- `src/services/ingest.enqueue_source()` 不接受任何 `template` / `schema_overrides`
  / `kind` 字段，task payload 也没有这条信息。
- `src/types.KnowledgeTask` 也只有 `project_id / folder_context / batch_id` 三个
  上下文字段，没有 template_id 字段。

`src/templates/loader.py` 已经支持 7 个 bundled 模板
（business/capture/general/novel/personal/reading/research）和 user 模板目录
（`~/.config/ruflo-kb/templates/`），但**只能在 `project init` 时选一次**，不能
在摄取时混用。

实际场景痛点（用户原始诉求）：同一项目里混杂多种素材（小说设定、学术论文、
视频转写、播客笔记、产品文档），它们对 page type 集合、`custom_type`、taxonomy
枚举、prompt 语气都有不同要求。当前要不就分开建多个项目，要不就强制统一一套
schema —— 都很别扭。

## Goal

允许**同一项目内，按 raw 来源路径 → 不同模板**摄取。具体：

1. 在项目根新增声明式路由文件 `routing.md`（类似 `schema.md` 的 markdown 表）。
2. HTTP/MCP/CLI 摄取接口可选地接受 `template` 字段，**显式覆盖**路由规则。
3. template 选择信息（`template_id` + 实际生效的 schema/purpose/taxonomy
   文本）随 task 一路传到 `run_ingest`，不再依赖运行时再读文件。
4. Analyzer/Generator 仍读各自的 schema/purpose/taxonomy，但来源可以是模板
   也可以是项目文件——以 task 上携带的为准。
5. 生成出的 wiki 页面在 frontmatter 记录 `template:` 字段，便于溯源和回放。
6. 不破坏现有"项目根 schema.md"默认路径（向后兼容）。

## Non-goals

- 不重写模板系统本体；不新增模板种类；不改 `src/templates/loader.py` 接口
  形态。
- 不做"按文件内容自动分类"（auto-detect），路由只接受**路径 glob** 或**显式
  字段**，避免 LLM 漂移。
- 不在 routing.md 里支持复杂表达式（only glob + priority + 显式字段三类输入）。
- 不为 routing 引入第三方路由库（ponytail 原则：stdlib first）。

## Design

### 1. 路由声明：`routing.md`

```markdown
# Routing Rules

按 raw 来源路径选择模板；第一行匹配的规则胜出；未匹配时回退到项目 schema.md。

| template | glob                       | priority |
|----------|----------------------------|----------|
| novel    | raw/sources/novels/**      | 10       |
| capture  | raw/sources/transcripts/** | 10       |
| research | raw/sources/papers/**      | 10       |
| general  | **                         | 0        |
```

- `template` 必须是 `templates/loader._ID_RE` 合法 id（`[a-z][a-z0-9_-]{0,63}`）。
- `glob` 用 `pathlib.PurePosixPath.match()` 兼容的 glob 语法（**是**，**?，
  `[..]`，**无 {a,b} 扩展**——stdlib 支持范围）。
- `priority` 数字大者胜；同 priority 时声明顺序靠前者胜。
- 末行兜底 `**` 强烈建议保留，否则未匹配的 raw 走项目 schema.md（仍合法）。
- 注释以 `#` 开头；空行忽略；解析失败整文件降级为"无规则"（warning log）。

新增 `src/wiki/features/template_routing.py`：

```python
@dataclass(frozen=True)
class RoutingRule:
    template: str        # "novel"
    glob: str            # "raw/sources/novels/**"
    priority: int        # 10

class TemplateRouter:
    @classmethod
    def from_project(cls, root: Path) -> "TemplateRouter": ...

    def resolve(self, raw_path: str) -> str | None:
        """Return template id, or None when no rule matches.

        raw_path 必须 project-relative, 用 POSIX 分隔符。
        """

    def iter_rules(self) -> list[RoutingRule]: ...
```

解析走纯 stdlib（`re` + 顺序遍历）；不引入第三方 glob 库。

### 2. 摄取接口签名扩展

`src/services/ingest.enqueue_source()` 新增可选参数 `template: str | None = None`，
透传到 `enqueue_task(...)` → `KnowledgeTask`。HTTP 层
`IngestRequest(BaseModel)` 同步加 `template: str | None = None`。

`KnowledgeTask` 新增可选字段 `template: Optional[str] = None`（默认 None，向后
兼容）。`enqueue` / `enqueue_batch` 两个方法的 kwarg 也加 `template`；写盘时
`JsonFileBackend` 必须能 round-trip（已有 `raw_path / note_path / knowledge_path`
等可选字段，先看后端是否丢弃 None 字段——若丢弃，必须在 `load()` 处回填）。

`generate_task_hash` 必须把 `template` 编进 hash 输入（防"同一文件 + 不同
template → 误判重复"）。原算法：

```python
data = f"{prefix}:{identifier}:{content_prefix[:1024]}:{project_id}:{round_key}"
```

改为：

```python
data = f"{prefix}:{identifier}:{content_prefix[:1024]}:{project_id}:{round_key}:{template or ''}"
```

**变更影响：** 同一 raw 在不同 template 下现在产生不同 task_hash → 不互相
dedup，符合预期。**风险：** 升级前已持久化在 `.kb-queue.json` 中的任务，其
hash 不含 template 字段，重新跑同 hash 时若新带 `template=""`，可能因算法差异
被识别为"同 hash"——验证：实际上 md5 输入末尾拼接 `""` 与原算法 bit-equivalent
（空字符串拼接是身份操作），所以 round-trip 安全。但仍要走一次
`tests/test_queue/` 回归。

### 3. Collector → Ingest 链路上 template 透传

当前 EventBus `collector:start` payload 含 `task_id / source / source_type /
project_id / folder_context`。**新增** `template` 字段（None-safe）。
`PipelineService.run_for_collector_start(payload)` 把 `payload["template"]` 传
到 `run_ingest(..., template=template)`；新增 `run_ingest` kwarg。

`src/pipeline/ingest.run_ingest(paths, source_path, source_text, provider, *,
template=None, ...)` 的优先级：

1. 若 `template is not None` 且 `templates/loader.load(template)` 成功：用模板
   的 `schema.md` / `purpose.md` 内容注入 prompt，同时把 `template` 传给
   `SchemaRegistry.from_schema_text(template_schema_md)`（不再 `from_project`）。
2. 否则若有 `routing.md` 且 `TemplateRouter.resolve(raw_path)` 命中：用命中的
   模板，走分支 1。
3. 否则走当前默认：`paths.root/schema.md`（向后兼容）。

### 4. Frontmatter 溯源

`WikiPage` 新增可选字段 `template: str = ""`，同时更新
`to_frontmatter_dict()` / `from_dict()` 的 round-trip（用 `.get(key, "")`
保留向后兼容）。`Generator` 在写 frontmatter 时把当前生效的 `template_id` 写入
（None → 空串，避免污染现有项目）。

### 5. CLI/MCP 暴露

- CLI: `python -m src.cli ingest` 已经不存在了；用户走 HTTP。**本 ADR 不新增
  CLI 命令**。
- MCP: `ruflo_kb_ingest` 工具已 deprecated（AGENTS.md）；本 ADR 不动 MCP。
- HTTP 是唯一入口；接口已述。

### 6. Template 校验

`enqueue_source(..., template="X")` 在 enqueue 之前必须先
`templates/loader.load("X")`（失败 → 400 BadRequest + 明确错误信息），避免
队列里塞进无法解析的 template_id。

## Files Touched

| 文件 | 变更 |
|---|---|
| `src/wiki/features/template_routing.py` | 新增：`RoutingRule` / `TemplateRouter` |
| `tests/test_wiki/test_template_routing.py` | 新增：parser / resolve / priority 行为 |
| `src/services/ingest.py` | 加 `template` kwarg；enqueue 前 `loader.load` 校验 |
| `src/server/routes/ingest.py` | `IngestRequest.template` 字段 |
| `src/types.py` | `KnowledgeTask.template: Optional[str]` |
| `src/queue/service.py` | `enqueue` / `enqueue_batch` 透传 template |
| `src/queue/persistence.py` | 持久化 round-trip 校验（看是否丢弃 None） |
| `src/utils/idempotency.py` | `generate_task_hash` 拼接 template |
| `src/pipeline/dispatcher.py` | payload 透传（无需改；EventBus dict 自动含新字段） |
| `src/pipeline/service.py` | `run_for_collector_start` 读 payload["template"] |
| `src/pipeline/ingest.py` | `run_ingest(..., template=None)` kwarg + 优先级解析 |
| `src/pipeline/_pipeline_common.py` | 新增 `_resolve_schema_for_ingest(paths, raw_path, template)` 内部函数 |
| `src/wiki/core/page.py` | `WikiPage.template: str = ""` + frontmatter round-trip |
| `docs/guides/wiki-spec.md` | 文档：`template:` 字段语义 |
| `AGENTS.md` / `docs/guides/*.md` | 文档：routing.md 用法 + HTTP `template` 参数 |
| `CONTEXT.md` | 术语：`TemplateRouter` / `routing.md` |

## Acceptance Evidence

- 单测 `test_template_routing.py`：`from_project` 解析、空文件、`#` 注释、
  priority 排序、glob 不匹配、显式 `None` 显式覆盖（route 不命中）。
- 单测 `test_idempotency.py`：template 编进 hash 的差异。
- 单测 `test_services_ingest.py`：非法 template_id → `ValueError`（route 层 400）。
- 集成测（手动）：在一个项目里同时放 `raw/sources/novels/x.md` 和
  `raw/sources/papers/y.pdf`，curl 两次 `/ingest` 不带 template 参数 →
  wiki/sources/ 下两个页面 frontmatter `template` 字段分别 `novel` / `research`。
- 回归测：现有 7 个 bundled 模板项目 init + 摄取 1 个文件，前置/后置页面
  对比（diff `template:` 为空，其他字段不变）。
- 队列回归：旧 `.kb-queue.json` 在升级后仍可读，pending 任务能继续派发。

## Risks & Mitigations

1. **Glob 语义分歧**：不同 stdlib 版本对 `**` 边界（如 `a/**/b.md`）的语义
   略有差异。**Mitigation**：parser 文档化"用 pathlib.PurePosixPath.match"
   ，并在测试里覆盖 `a/**` 与 `a/**/b` 两种情况。
2. **template 字段污染 frontmatter**：旧 WikiPage 反序列化时缺字段 → 用
   `.get("template", "")` 默认值；不破坏 round-trip。
3. **路由优先级误配导致页面跨模板混淆**：用户写 routing.md 但顺序/priority
   错。**Mitigation**：`TemplateRouter.resolve` 加 debug 日志（`[routing] resolved
   novel for raw/sources/novels/x.md via rule #3`）。
4. **template 不存在 / 模板文件损坏**：enqueue 前 `loader.load` 抛错；queue
   不接受该 task；HTTP 400。
5. **idempotency hash 变更破坏旧 in-memory cache**：升级后老 cache 残留
   不影响——TTL 7 天自然过期。**但** `.kb-queue.json` 持久化的 terminal-state
   任务（含旧 hash）若用户希望"换模板重摄"会需要主动删记录或等 dead-letter
   清空。文档化此行为。
6. **并发 enqueue + 同一 raw + 不同 template**：每个 template 独立 hash → 队
   列接受两个并行任务；同时写 `wiki/sources/<slug>.md` 会冲突（后写者覆盖）。
   **Mitigation**：探测同 raw 的 RUNNING/PENDING 任务**不限 template** 仍视为
   重复（`existing` 检查在 `enqueue` 中按 hash 走，已天然满足），但若两个
   template 不同则 hash 不同 → 都会入队 → race。**加固**（可选，本期可推
   迟）：在 `enqueue_source` 加"同 raw 不同 template 必须串行"的提示日志，
   并在 writer 加 file lock。本期只做到警告，不阻止。
7. **routing.md 不存在时行为**：未找到文件 → `TemplateRouter.empty()` 返
   `resolve()=None` → 回退项目 schema.md（默认路径），与现状一致。

## Open Questions (待 plan-audit 答复)

- Q1: routing.md 是否支持"按文件元数据（frontmatter 中的 category）路由"？
  当前设计只支持 path glob。若需要，扩 schema 是 v2 任务，本期不做。
- Q2: 是否需要"路由失败时报警 / dead-letter"？当前只是 warning + 回退默认。
- Q3: frontmatter `template:` 字段是否影响 `WikiPage.id` 生成？本期不影响
  （id 仍按源路径 + 时间戳生成）。若用户希望同源多模板生成不同 id，本期不
  做。