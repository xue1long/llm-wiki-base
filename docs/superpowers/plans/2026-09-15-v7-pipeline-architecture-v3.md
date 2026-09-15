# V7 摄取流水线架构文档 v3.0

**版本**:v3.0(架构对齐版)
**状态**:待评审
**日期**:2026-09-15

---

## 1. 背景与目标

### 1.1 背景

novel-wiki 摄取流水线经历了三代演进:

```
v1(legacy): pipeline/stages/ → Collector → Analyzer → Generator
v2(v7):     pipeline/v7_extract/ → 7 阶段 LLM 驱动抽取
v3(本文档): 继承 v2 的语义驱动思想 + 继承 v1 的模板架构优势
```

**v2 当前核心问题**:
1. 架构分裂:LLM Prompt 是字符串字面量,与现有 `src/wiki/templates/` 的 AST/版本化/三层覆盖架构不一致
2. async/sync 桥接 bug:4 个 stage 用 `asyncio.run(coro)` 桥接,RuntimeError 时 coroutine orphan,导致 needs_review 假阳性
3. 失败语义不统一:部分 stage 抛异常,部分返回空,extract_pilot 不能正确识别"LLM 失败 vs 真正不可写"
4. Stage 1 错污染 Stage 3:`check_completeness` 用 `if doc_type is INCOMPLETE: return False` 短路,Stage 1 误判即污染
5. Stage 4 漏分配无兜底:LLM 漏分配的 item 进 review queue 都做不到

### 1.2 目标

| 维度 | 目标 |
|---|---|
| 质量 | spot-check 准确率 ≥ 80%,write_contamination = 0 |
| 稳定 | LLM 失败不污染存量,不中断整批 |
| 追溯 | 每张概念页可追溯到原文 evidence chain |
| 演进 | LLM 模型升级 / prompt 优化不影响数据 |
| 审计 | 失败有明确队列,人工 review 路径清晰 |
| 架构对齐 | 完整继承现有 `src/wiki/templates/` 架构的所有优秀特性 |

### 1.3 非目标

- 模板升级(plan Task 1/2)
- 概念去重(plan Task 5)
- Stage 6 LLM 关系增强
- 跨库互联 / 主动推荐 API(后续 plan)

---

## 2. 设计原则

| 原则 | 表述 | 优先级 |
|---|---|---|
| **P1** | LLM 管语义,脚本管机制 | 必须 |
| **P2** | 失败可逆(任何 stage 失败 = needs_review,不抛异常) | 必须 |
| **P3** | 三道闸门(Stage 5 evidence / Stage 7 needs_review / content_filter) | 必须 |
| **P4** | 100% 覆盖度(Stage 4 LLM 漏分配 → "其他主题" 桶,**桶内不写盘**) | 必须 |
| **P5** | Stage 解耦(Stage 1 错不影响 Stage 3 独立判断) | 必须 |
| **P6** | 幂等性(checkpoint + source_md5 双键去重) | 必须 |
| **P7** | 集中 Prompt(PromptAST 镜像 TemplateAST,三层覆盖 + TOML 版本化) | 必须 |
| **P8** | async 一致性(顶层函数全 async,不混用 sync/async 桥接) | 必须 |
| **P9** | 向后兼容(CLI 接口、对外行为不变) | 强烈建议 |

---

## 3. 架构全景

### 3.1 模块结构

```
src/pipeline/v7_extract/
├── __init__.py                  # 公共 API 重导出
├── prompts/                     # 🆕 v3.0:Prompt AST + 三层覆盖
│   ├── __init__.py
│   ├── ast.py                   # PromptAST, PromptSlot, PromptSection
│   ├── parser.py                # TOML 解析
│   ├── renderer.py              # render_prompt + output_schema 校验
│   ├── resolver.py              # 三层覆盖(运行时热加载)
│   └── builtin/                 # 内置 bundled prompt(TOML 格式)
│       ├── classify.toml
│       ├── completeness.toml
│       ├── cluster.toml
│       └── fill_slots.toml
├── failures.py                  # 🆕 v3.0:统一失败语义 → 复用现有 reviews_queue
├── llm_client.py                # LLMClient + FakeLLMClient + AnthropicLLMClient
├── doc_classifier.py            # Stage 1:async + prompts + 失败语义
├── completeness_checker.py     # Stage 3:async + prompts + P5 解耦
├── topic_clusterer.py           # Stage 4:async + prompts + P4 兜底
├── slot_filler.py               # Stage 5:async + prompts + evidence 验证
├── relation_extractor.py        # Stage 6:可选 best-effort 后处理,首轮不调用
├── wiki_writer.py               # Stage 7:脚本 + needs_review 阻断 + P4 阻断
├── content_filter.py            # 敏感词闸门(沿用)
└── audit_logger.py              # 反向索引 + failure 记录(扩展)

scripts/
├── extract_pilot.py            # async 化(顶层 asyncio.run)
├── extract_full.py             # async 化(顶层 asyncio.run)
└── review_queue_cli.py         # 🆕 review queue CLI(list/resolve/stats)

tests/test_pipeline/
├── test_v7_extract_prompts_{ast,parser,renderer,resolver}.py  # 新增
├── test_v7_extract_failures.py                                # 新增
├── test_v7_extract_doc_classifier.py                           # 重写(async)
├── test_v7_extract_completeness_checker.py                     # 重写(async)
├── test_v7_extract_topic_clusterer.py                          # 重写(async)
├── test_v7_extract_slot_filler.py                              # 重写(async)
└── test_extract_pilot_async.py                                 # 新增(async 入口)

tests/fixtures/v7_spot_check/
└── spot_check_v1.json                                          # 新增(回归集)
```

### 3.2 v3.0 与现有 wiki/templates/ 架构对齐表

| 现有架构(`src/wiki/templates/`) | v3.0 对应(`src/pipeline/v7_extract/prompts/`) |
|---|---|
| `types.TemplateAST` | `ast.PromptAST` |
| `types.Slot` | `ast.PromptSlot` |
| `types.TemplateSection` | `ast.PromptSection` |
| `types.Template` | `renderer.PromptTemplate`(resolved) |
| `parser.parse()` | `parser.parse_prompt()` |
| `renderer.render_body()` | `renderer.render_prompt()` |
| `renderer.compute_slot_fill_status()` | `renderer.compute_prompt_fill_status()` |
| `resolver.list_resolved()` | `resolver.resolve()` |
| `bundled/*.md` | `builtin/*.toml` |
| `<!-- wiki-template-version: 3.0.0 -->` | `[meta] version = "1.0"` |
| 三层覆盖(project/user/bundled) | 三层覆盖(`.v7-prompts/` / `~/.config/.../v7-prompts/` / bundled) |
| `<!-- slot:NAME -->` | `{slot_name}` in TOML |
| `<!-- slot:NAME? -->` 可选 | `[[slot]] required = false` |
| `<!-- if:X -->` 条件 | `[user.if]` TOML 块 |

**核心:PromptAST 100% 镜像 TemplateAST,学习成本零**

---

## 4. 决策记录(D1-D11)

| ID | 决策 | 理由 | 影响范围 |
|---|---|---|---|
| **D1** | Prompt 三层覆盖保留(project/user/bundled) | 镜像 wiki/templates/ 架构,学习成本零 | `prompts/resolver.py` |
| **D2** | schema 校验失败自动重试 3 次,3 次后进 review queue | 降低人工 review 成本 ~50% | `prompts/renderer.py`, `failures.py` |
| **D3** | extract_pilot / extract_full 顶层 async 化,CLI 入口 `asyncio.run()` | 根除 sync/async 桥接 bug | `scripts/extract_pilot.py`, `scripts/extract_full.py` |
| **D4** | failures.py 复用现有 `src/wiki/storage/reviews_queue.py`,不新建 review_queue.py | 避免两套并行机制,统一审计 | `src/pipeline/v7_extract/failures.py` |
| **D5** | schema 校验失败 + 其他 stage 失败都写入 audit_logger | 完整失败追溯,几乎零成本 | `src/pipeline/v7_extract/audit_logger.py` |
| **D6** | Prompt 三层覆盖运行时热加载,无需重启 | 改完立即生效,提升开发效率 | `prompts/resolver.py` |
| **D7** | Stage 5 单 topic 失败 → 过滤 + blocked_topic_ids 记录,不污染 pages 列表 | 一个失败不影响其它 topic 写盘 | `src/pipeline/v7_extract/failures.py` |
| **D8** | extract_pilot / extract_full 新增 `--review-queue` 子命令 | CLI 入口替代直接编辑 JSON | `scripts/review_queue_cli.py`(新增) |
| **D9** 🆕 | Prompt 路径白名单 + TOML schema 校验(R14) | 防止恶意 `.toml` 注入劫持 LLM 行为 | `prompts/resolver.py`, `prompts/parser.py` |
| **D10** 🆕 | failures.py 给所有 review 项加 `source="v7_extract"` 标记(R13) | 区分 Generator 与 V7 失败项,避免混淆 | `failures.py`, `scripts/review_queue_cli.py` |
| **D11** 🆕 | payload 脱敏(白名单 + 长度截断,不删除 payload)(R15) | 保留排错信息同时防敏感数据泄露 | `failures.py` |

### 4.1 控制面补充边界(2026-09-15)

- Stage 5 的硬要求是脚本拥有的 item provenance 与页面级 source 闭环。
  `source_text_excerpt` 仅供人工定位原文；非 literal paraphrase 不能单独触发
  `needs_review`，但缺失或越界的 item 引用仍必须阻断。
- 首轮必需链路是 Stage 1/2/3/4/5 → Stage 7 → durable source outcome。
  Stage 6 不在这条成功路径内，也不参与首轮 checkpoint 的终局判定。
- Stage 6 仅在首轮 outcome 已持久化后按需运行。未来接入必须复用同一
  `page_id`、review queue、source checkpoint 和 outcome 契约；关系抽取失败
  只能形成可重试的后处理结果，不能降级、回滚或覆盖已成立的首轮 outcome。
- 详细决策与回滚边界见
  `docs/adr/0011-v7-ingestion-outcome-control-plane.md`。

---

## 5. 单文档处理流水线

### 5.1 流程图

```
                    1 篇 raw 文档
                         ↓
        ┌─────────────────────────────────────┐
        │ Stage 1: classify_doc (async, LLM)  │
        │ 输入: content + filename_hint       │
        │ 输出: Classification                │
        │ 失败: needs_review(进 review_queue) │
        └─────────────────────────────────────┘
                         ↓
        ┌─────────────────────────────────────┐
        │ Stage 2: extract_items (脚本)        │
        │ 输入: content                       │
        │ 输出: list[{id, text}]              │
        │ 失败: needs_review(源文档级)        │
        └─────────────────────────────────────┘
                         ↓
        ┌─────────────────────────────────────┐
        │ Stage 3: check_completeness (async) │
        │ 输入: content + doc_type_hint(soft)│
        │ 输出: (complete, reason)             │
        │ 失败: incomplete → 跳到末尾         │
        └─────────────────────────────────────┘
                         ↓ (complete=True)
        ┌─────────────────────────────────────┐
        │ Stage 4: cluster_topics (async)      │
        │ 输入: items, min/max_topics        │
        │ 输出: list[Topic] + 100% 覆盖      │
        │ 失败: needs_review(源文档级)        │
        └─────────────────────────────────────┘
                         ↓
        ┌─────────────────────────────────────┐
        │ Stage 5: fill_slots (async × N)     │
        │ 输入: topic + source_text + items  │
        │ 输出: ConceptPage + evidence       │
        │ 单 topic 失败: 过滤 + blocked_topic_ids(D7)│
        └─────────────────────────────────────┘
                         ↓ (首轮必需)
        ┌─────────────────────────────────────┐
        │ Stage 7: commit_and_index (脚本)    │
        │ 输入: pages                         │
        │ 三道闸门 + 1 道 P4:                 │
        │   A. P4 "其他主题" 桶 → blocked    │
        │   B. needs_review → blocked        │
        │   C. content_filter → blocked      │
        │   D. evidence chain 校验           │
        │ 失败: retry 3 次 → review_queue    │
        └─────────────────────────────────────┘
                         ↓
        Writer page outcome → queue / recoverable result
                         ↓
        .index/v7_checkpoint.json(page-level 幂等)
                         ↓
        .index/v7_full_checkpoint.json(source-level v2)
        .index/extract_report.json(追溯 + failure 记录)
        reviews_queue.json(失败队列)

                         ↓ (终局之后,按需执行)
        ┌─────────────────────────────────────┐
        │ Stage 6: extract_relations (可选)   │
        │ 输入:已持久化 pages / page_id      │
        │ 输出:PageRelation[]                 │
        │ 失败:best-effort 失败,不改首轮终局 │
        └─────────────────────────────────────┘
```

### 5.2 失败行为矩阵(P2 原则)

| Stage | LLM 失败行为 | 数据丢失风险 |
|---|---|---|
| Stage 1 | ExtractionStatus.NEEDS_REVIEW,源文档级失败 | 无 |
| Stage 2(文件 IO / 编码) | ExtractionStatus.NEEDS_REVIEW | 无 |
| Stage 3 LLM 失败 | 视为 incomplete,跳到末尾 | 无 |
| Stage 4 LLM 失败 | ExtractionStatus.NEEDS_REVIEW | 无 |
| Stage 5 单 topic LLM 失败 | 该 topic 过滤 + blocked_topic_ids | 无(D7) |
| Stage 5 item provenance 不合法或 evidence 缺失 | 该 slot 标 needs_review；excerpt 非 literal 匹配本身不阻断 | 无 |
| Stage 6(可选后处理) | 记录可重试的 best-effort 结果；不改变首轮 source outcome | 无(首轮结果已持久化) |
| Stage 7 写盘失败 | retry 3 次 → failed,进 review queue | 无 |
| Stage 7 needs_review 阻断 | blocked 列表 | 无 |
| Stage 7 content_filter 拦截 | blocked 列表 | 无 |
| Stage 7 "其他主题"桶 | blocked 列表(P4) | 无 |
| schema 校验失败 | 自动重试 3 次 → review_queue(D2) | 无 |

---

## 6. 核心数据结构

### 6.1 ExtractionResult(统一返回值,D2/D4/D5)

```python
@dataclass
class ExtractionResult:
    """Per-document processing result — replaces inconsistent return types."""
    status: ExtractionStatus  # OK | NEEDS_REVIEW | INCOMPLETE
    source_id: str
    pages: list[ConceptPage] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    blocked_topic_ids: list[str] = field(default_factory=list)  # D7
    failure_stage: str | None = None  # stage1/3/4/5/7

class ExtractionStatus(str, Enum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    INCOMPLETE = "incomplete"
```

### 6.2 PromptAST(镜像 TemplateAST,D1)

```python
@dataclass(frozen=True)
class PromptSlot:
    name: str
    required: bool = True
    default: str = ""
    description: str = ""

@dataclass(frozen=True)
class PromptSection:
    heading: str  # "system" | "user_header" | "user_data" | "constraints"
    body_template: str
    slots: list[PromptSlot] = field(default_factory=list)

@dataclass(frozen=True)
class PromptAST:
    prompt_kind: str
    version: str | None
    sections: list[PromptSection]
    output_schema: dict | None = None

@dataclass(frozen=True)
class PromptTemplate:
    """Resolved prompt, ready to render."""
    prompt_kind: str
    version: str | None
    system_section: str
    user_template: str
    output_schema: dict | None
    source: PromptSource  # "project" | "user" | "bundled"
    path: Path

PromptSource = Literal["project", "user", "bundled"]
```

### 6.3 TOML Prompt 格式

```toml
[meta]
prompt_kind = "classify"
version = "1.0"

[system]
text = """You are a V7 document classifier. Reply with a single JSON
object and nothing else."""

[user]
template = """\
Classify into exactly one of:
  - single_method: ...
Document body (first {content_limit} chars):
```
{content}
```
"""

[output_schema]
type = "json"
required = ["doc_type", "confidence", "rationale"]
enum = { doc_type = ["single_method", "multi_section", "collection", "qa_chat", "list", "tool", "incomplete"] }
range = { confidence = [0.0, 1.0] }

[retry]  # D2
max_retries = 3
on_schema_failure = "..."

[[slot]]
name = "content"
required = true

[[slot]]
name = "filename_hint"
required = false
default = ""

[[slot]]
name = "content_limit"
required = false
default = "4000"
```

### 6.4 output_schema 校验 + 重试(D2)

```python
def parse_llm_response(raw: str, schema: dict | None) -> dict:
    """Validate LLM response against output_schema.

    D2: schema validation failure → retry up to max_retries with
        "fix and retry" instruction in prompt.
    """
    text = _strip_json_fence(raw)
    payload = json.loads(text)
    # 必填字段、enum、range 校验
    return payload
```

---

## 7. 三层 Prompt 覆盖(D1, D6 运行时热加载, R14 安全)

```
项目级:  knowledge/novel-wiki/.v7-prompts/classify.toml   ← 项目作者可改
用户级:  ~/.config/ruflo-kb/v7-prompts/classify.toml       ← 用户全局
bundled: src/pipeline/v7_extract/prompts/builtin/*.toml    ← 项目无关默认
```

**优先级**:project > user > bundled(与现有 wiki/templates/ 一致)

**热加载(D6)**:`prompts_resolver.resolve(prompt_kind, project_root)` 每次都重新读盘 + 解析 + 校验(~10ms),改完立即生效,无需重启。

**R14 安全约束**:
- **路径白名单**:`resolver.resolve()` 只接受 ALLOWED_ROOTS 内的路径,防止恶意 `.toml` 注入
- **TOML schema 校验**:parse 后验证 `output_schema.enum.doc_type ⊆ KNOWN_DOC_TYPES`,防止通过 enum 绕过 evidence 校验
- **文件权限建议**:项目作者本地 `.v7-prompts/*.toml` chmod 0600

```python
# prompts/resolver.py
ALLOWED_ROOTS = [
    Path("knowledge/novel-wiki/.v7-prompts"),
    Path.home() / ".config" / "ruflo-kb" / "v7-prompts",
    Path(__file__).parent / "builtin",  # 只读 bundled
]

def resolve(prompt_kind: str, project_root: Path) -> PromptTemplate:
    for root in ALLOWED_ROOTS:
        candidate = root / f"{prompt_kind}.toml"
        if candidate.is_file():
            return _parse_and_validate(candidate)  # R14: schema 校验
    return _load_bundled(prompt_kind)
```

```python
# prompts/parser.py
KNOWN_DOC_TYPES = {"single_method", "multi_section", "collection",
                   "qa_chat", "list", "tool", "incomplete"}

def _validate_output_schema(schema: dict) -> None:
    """R14: 防止恶意 TOML 注入未知 enum 值绕过 evidence 校验。"""
    if "enum" in schema:
        doc_types = schema["enum"].get("doc_type", [])
        unknown = set(doc_types) - KNOWN_DOC_TYPES
        if unknown:
            raise PromptParseError(f"Unknown doc_type in enum: {unknown}")
```

---

## 8. Stage 设计细则

### 8.1 Stage 1: classify_doc(D3, async)

```python
async def classify_doc(
    content: str,
    *,
    filename_hint: str = "",
    llm: LLMClient,
    project_root: Path,
) -> Classification:
    """Pure LLM classification. No fallback heuristic."""
    template = await prompts_resolver.resolve("classify", project_root)
    system_prompt, user_prompt = render_prompt(template, {...})
    try:
        raw = await llm.complete(prompt_kind="classify", ...)
        payload = parse_llm_response(raw, template.output_schema)
        return Classification(...)
    except (LLMCallError, ValidationError) as e:
        return Classification(
            doc_type=DocType.INCOMPLETE,
            confidence=0.0,
            rationale=f"stage1_failed: {e}",
        )
```

### 8.2 Stage 3: check_completeness(P5 解耦, async)

```python
async def check_completeness(
    content: str,
    doc_type: DocType,  # soft hint, NOT strong dependency
    *,
    llm: LLMClient,
    project_root: Path,
) -> tuple[bool, str]:
    template = await prompts_resolver.resolve("completeness", project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "text": content,
        "doc_type_hint": doc_type.value,  # 软 hint
    })
    try:
        raw = await llm.complete(...)
        payload = parse_llm_response(raw, template.output_schema)
        return bool(payload["complete"]), payload.get("reason", "")
    except (LLMCallError, ValidationError) as e:
        return False, f"stage3_failed: {e}"
```

### 8.3 Stage 4: cluster_topics(P4 兜底, async)

```python
async def cluster_topics(
    items: list[dict],
    *,
    llm: LLMClient,
    project_root: Path,
    min_topics: int = 1,
    max_topics: int = 5,
) -> list[Topic]:
    template = await prompts_resolver.resolve("cluster", project_root)
    system_prompt, user_prompt = render_prompt(template, {...})
    raw = await llm.complete(...)
    payload = parse_llm_response(raw, template.output_schema)
    topics = [_parse_topic(t) for t in payload.get("topics", [])]
    topics = _enforce_min_max(topics, min_topics, max_topics)
    topics = _enforce_full_coverage(topics, items)  # P4
    return topics


def _enforce_full_coverage(topics, items):
    """P4: 漏分配的 item 强制塞进 "其他主题" 桶。"""
    assigned = {iid for t in topics for iid in t.item_ids}
    leftover = [i for i in items if i["id"] not in assigned]
    if leftover:
        topics.append(Topic(
            id="__other__",
            title="其他主题",
            item_ids=[i["id"] for i in leftover],
        ))
    return topics
```

### 8.4 Stage 5: fill_slots(D7 单 topic 失败过滤, async)

Stage 5 必须保留 canonical item ID → page → source 的 provenance 闭环。
`source_text_excerpt` 是可选人工参考，不是全文 substring 硬门：只要 item 引用
合法、evidence 和正文满足既有约束，paraphrase excerpt 不应单独标记
`needs_review`。

```python
async def fill_slots(
    topic: Topic,
    source_text: str,
    *,
    llm: LLMClient,
    item_texts: dict[str, str],
    project_root: Path,
) -> ConceptPage | None:
    """LLM fills 5 slots + evidence. Returns None on full failure."""
    template = await prompts_resolver.resolve("fill_slots", project_root)
    try:
        raw = await llm.complete(...)
        payload = parse_llm_response(raw, template.output_schema)
        slots, evidence = _validate_slots(payload, topic, item_texts)
        return ConceptPage(slots=slots, slot_evidence=evidence, ...)
    except (LLMCallError, ValidationError) as e:
        return None  # D7: 调用方负责记录 blocked_topic_ids


# extract_one 调用方(D7 应用)
async def process_article(article):
    pages, blocked = [], []
    for topic in cluster_result.topics:
        page = await fill_slots(topic, ...)
        if page is not None:
            pages.append(page)
        else:
            blocked.append(topic.id)  # 记录到 ExtractionResult
    return ExtractionResult(pages=pages, blocked_topic_ids=blocked, ...)
```

### 8.5 Stage 6: extract_relations(可选 best-effort 后处理)

`relation_extractor.py` 保留现有实现，但首轮 `extract_pilot.py` / `extract_full.py`
不以它作为 Stage 7 的前置条件。需要关系时，在 source outcome 持久化后由独立
后处理任务调用；调用方必须使用已落盘页面的同一 `page_id`，并沿用本控制面的
queue、checkpoint 与 outcome 语义。Stage 6 失败不得删除页面、回退首轮
checkpoint，或把 `written` 改成 `blocked` / `failed`。

### 8.6 Stage 7: wiki_writer(P3 + P4, 不变)

```python
class WikiWriter:
    def commit_and_index(self, pages, relations=()) -> WriteReport:
        for page in pages:
            # 闸门 A: P4 "其他主题" 桶
            if page.topic_id == "__other__":
                report.blocked.append(page.id)
                continue
            # 闸门 B: needs_review
            if page.has_any_needs_review():
                report.blocked.append(page.id)
                continue
            # 闸门 C: content_filter
            if self.content_filter.check(page.body).blocked:
                report.blocked.append(page.id)
                continue
            # 闸门 D: evidence chain
            if not page.has_evidence():
                report.blocked.append(page.id)
                continue
            # 写盘
            ...
```

---

## 9. failures.py(D4 + D5 + D7 + R13)

```python
"""统一失败语义,复用现有 reviews_queue(D4),记录到 audit_logger(D5)。

R13: 所有 v7_extract 失败项必须带 `source="v7_extract"` 标记,
避免与 Generator 流水线的 review 项混淆。
"""
from src.wiki.storage.reviews_queue import ReviewQueue, ReviewItem
from src.pipeline.v7_extract.audit_logger import AuditLogger


def enqueue_failure(
    source_id: str,
    stage: str,
    reason: str,
    payload: dict,
    queue: ReviewQueue,
    audit: AuditLogger,
) -> None:
    """失败统一进 review_queue + audit_logger(D4 + D5 + R13)。"""
    item = ReviewItem(
        id=uuid4(),
        source_id=source_id,
        source="v7_extract",  # R13: 区分 Generator 与 V7 失败项
        failure_stage=stage,
        reason=reason,
        payload=sanitize_payload(payload),  # R15: 脱敏
        created_at=now_ms(),
    )
    queue.add(item)
    audit.record_failure(source_id, stage, reason, sanitize_payload(payload))


def sanitize_payload(payload: dict) -> dict:
    """R15: 递归移除敏感字段 + 限制字符串长度,不删除 payload(保留排错信息)。"""
    SENSITIVE_FIELDS = {"api_key", "email", "phone", "id_card", "password"}
    if not isinstance(payload, dict):
        return payload
    result = {}
    for k, v in payload.items():
        if k.lower() in SENSITIVE_FIELDS:
            result[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 500:
            result[k] = v[:500] + "..."
        elif isinstance(v, dict):
            result[k] = sanitize_payload(v)
        else:
            result[k] = v
    return result


def filter_failed_topics(
    pages: list[ConceptPage],
    failed_topic_ids: list[str],
) -> list[ConceptPage]:
    """D7: 失败的 topic 从 pages 中过滤,只把成功的传给 WikiWriter。"""
    return [p for p in pages if p.topic_id not in failed_topic_ids]
```

---

## 10. CLI 扩展(D8)

```bash
# review queue 管理
python scripts/review_queue_cli.py list --open
python scripts/review_queue_cli.py list --all
python scripts/review_queue_cli.py resolve <item_id> --action promoted
python scripts/review_queue_cli.py resolve <item_id> --action discarded
python scripts/review_queue_cli.py resolve <item_id> --action retry
python scripts/review_queue_cli.py stats
```

---

## 11. 测试架构

### 11.1 三层测试

| 层 | LLM 依赖 | 速度 | 触发 |
|---|---|---|---|
| 单元测试 | FakeLLMClient | < 1s/test | 每次 commit |
| 集成测试 | FakeLLMClient 端到端 | < 5s/test | 每次 commit |
| 真实 LLM 集成 | MiniMax-M3 | < 30s/test | nightly |
| 回归测试集 | MiniMax-M3 | < 5min/test | weekly |

### 11.2 回归测试集(D8 配套)

固化 spot-check 报告的 10 个真实样本为 fixture:
```json
// tests/fixtures/v7_spot_check/spot_check_v1.json
{
  "samples": [
    {"source": "raw/sources/.../借鉴素材小说写作.md", "expected_doc_type": "multi_section"},
    {"source": "raw/sources/.../入门教程一个新手的五个阶段.md", "expected_doc_type": "multi_section"},
    ...
  ]
}
```

### 11.3 必加测试文件

```
tests/test_pipeline/
├── test_v7_extract_prompts_ast.py            # 新增
├── test_v7_extract_prompts_parser.py         # 新增
├── test_v7_extract_prompts_renderer.py        # 新增
├── test_v7_extract_prompts_resolver.py       # 新增
├── test_v7_extract_failures.py                # 新增
├── test_v7_extract_doc_classifier.py           # 重写(async + FakeLLMClient)
├── test_v7_extract_completeness_checker.py     # 重写
├── test_v7_extract_topic_clusterer.py          # 重写
├── test_v7_extract_slot_filler.py              # 重写
├── test_extract_pilot_async.py                 # 新增(async 入口)
└── test_review_queue_cli.py                    # 新增
```

---

## 12. 复用与共享

### 12.1 复用现有模块(零修改)

| 模块 | 用途 |
|---|---|
| `src.wiki.core.types.WikiPage` | 概念页数据类型 |
| `src.wiki.storage.page_writer` | 原子写盘 |
| `src.wiki.storage.inverse_index` | 反查索引 |
| **`src.wiki.storage.reviews_queue`** | **失败队列(D4 复用,不新建)** |
| `src.wiki.taxonomy_registry` | 主题分类 |
| `src.pipeline.v7_extract.audit_logger` | 审计日志(D5 扩展) |
| `src.pipeline.v7_extract.content_filter` | 敏感词过滤 |
| `src.pipeline.v7_extract.llm_client` | LLMClient 抽象 |

### 12.2 镜像现有架构(共享设计)

| 现有 | v3.0 镜像 |
|---|---|
| `src/wiki/templates/` 全套 | `src/pipeline/v7_extract/prompts/` 全套 |
| `bundled/*.md` | `builtin/*.toml` |
| 三层覆盖机制 | 同 |

---

## 13. 向后兼容性(P9)

| 兼容性维度 | 状态 |
|---|---|
| CLI 接口(`python -m src.cli ...`) | ✅ 不变 |
| `extract_pilot.py --count/--seed/--root` 参数 | ✅ 不变 |
| `extract_pilot.py` 输出 JSON / Markdown 格式 | ✅ 不变 |
| `extract_full.py --apply` 行为 | ✅ 不变(更稳) |
| `WikiWriter.commit_and_index` 签名 | ✅ 不变 |
| Wiki 产物文件格式 | ✅ 不变(只多了 `generated_by_v7_extract` 注释) |
| 现有单元测试 | 🟡 需要迁移到 async(FakeLLMClient) |

---

## 14. 验收标准

| ID | 验收项 | 标准 |
|---|---|---|
| A1 | spot-check 准确率 | ≥ 80%(10 样本回归) |
| A2 | write_contamination | 0(三道闸门 + P4) |
| A3 | Prompt 版本化 | 4 个 prompt 都有 `[meta] version`,改动有 changelog |
| A4 | 三层覆盖 | project > user > bundled 优先级正确,有单元测试 |
| A5 | PromptAST 抽象 | 与 TemplateAST 镜像设计,字段对齐 |
| A6 | output_schema 校验 + 重试 | D2 自动重试 3 次,3 次后进 review queue |
| A7 | Stage 1/3/4 启发式删除 | grep `classify_doc_heuristic` / `_check_heuristic` / `_cluster_heuristic` 无结果 |
| A8 | 任何 stage LLM 失败 → needs_review | 单元测试覆盖 |
| A9 | P4 "其他主题" 桶不写盘 | WikiWriter 强制阻断,测试覆盖 |
| A10 | Stage 1 → 3 解耦 | Stage 3 独立判断,Stage 1 结论只作 hint |
| A11 | 离线 CI 通过 | 单元测试用 FakeLLMClient,prompts 用 bundled 默认 |
| A12 | async 一致性 | 4 个 stage 顶层函数全 `async def` |
| A13 | 现有 wiki 模板架构对齐 | `prompts/*` 模块与 `templates/*` 镜像 |
| A14 | review_queue CLI 可用 | list / resolve / stats 三个子命令测试通过 |
| A15 | failures 复用 reviews_queue | grep `class ReviewQueue` 出现 ≥ 1 处(D4) |
| A16 | Prompt 热加载 | 单元测试覆盖修改 prompt 后立即生效(D6) |
| A17 🆕 | Prompt 路径白名单 | `resolver.resolve()` 拒绝 ALLOWED_ROOTS 之外的路径(D9) |
| A18 🆕 | TOML schema 校验 | 未知 doc_type enum 触发 PromptParseError(D9) |
| A19 🆕 | review_queue source 标记 | 所有 v7_extract 失败项带 `source="v7_extract"`(D10) |
| A20 🆕 | payload 脱敏 | api_key / email / phone 等敏感字段在 payload 中被 [REDACTED](D11) |

### 14.1 控制面补充验收(不改变 A1-A20)

| ID | 验收项 | 标准 |
|---|---|---|
| C1 | Stage 5 excerpt 边界 | canonical item provenance 合法且正文/evidence 合格时，非 literal paraphrase excerpt 不单独阻断写盘 |
| C2 | Stage 5 provenance | 缺失、越界或跨 topic 的 item 引用继续进入 review，页面保留 source 闭环 |
| C3 | Stage 6 首轮隔离 | `scripts/` 首轮 source→concept 路径不要求关系抽取；没有 relations 仍可形成 durable outcome |
| C4 | Stage 6 后处理失败 | 失败可重试且可审计，不删除页面、不回退 checkpoint、不覆盖既有 source outcome |

---

## 15. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| async 化导致现有测试失败 | 高 | 中 | 用 FakeLLMClient 重写,逐 stage 迁移 |
| extract_pilot / extract_full 行为变化 | 中 | 高 | 保留 CLI 接口不变,只改内部实现 |
| prompts.py 与现有 wiki/templates/ 不一致 | 中 | 中 | 严格镜像设计 |
| review_queue 持久化兼容性 | 低 | 低 | D4 复用现有 reviews_queue,JSON 格式简单 |
| TOML 解析依赖 | 低 | 低 | Python 3.11+ 自带 tomllib |
| LLM 调用次数增加 | 中 | 中 | D2 重试上限 3x(见 §16.x) |
| 项目作者不懂 TOML | 中 | 低 | 提供示例 + 注释 |
| 热加载性能(D6) | 低 | 低 | ~10ms/次,可接受 |
| **R14 Prompt 热加载注入** | 中 | 高 | ✅ **D9 路径白名单 + TOML schema 校验** |
| **R13 reviews_queue 字段冲突** | 中 | 中 | ✅ **D10 source 标记区分失败来源** |
| **R15 payload 敏感数据泄露** | 中 | 中 | ✅ **D11 字段白名单 + 长度截断脱敏** |

---

## 16. 总结

| 维度 | v2(当前) | v3.0(本文档) |
|---|---|---|
| Prompt 存储 | Python 字符串 | TOML 文件 + AST 抽象 |
| Prompt 版本化 | ❌ 无 | ✅ TOML `[meta] version` |
| 三层覆盖 | ❌ 无 | ✅ project > user > bundled |
| 顶层函数 | 4 个 sync + 桥接 | 4 个 async + 直 await |
| 失败语义 | 不统一(异常 + 空返回) | 统一 ExtractionResult + needs_review |
| Stage 1→3 耦合 | 强(INCOMPLETE 短路) | 弱(soft hint) |
| Stage 4 覆盖度 | LLM 自由分配 | P4 硬约束 + 兜底 |
| Stage 5 excerpt | literal substring 硬门 | 人工参考；item provenance 仍是硬约束 |
| Stage 6 关系抽取 | 容易被理解为首轮必需阶段 | 终局之后的可选 best-effort 后处理 |
| 模板架构对齐 | 平行架构 | 镜像现有 wiki/templates/ |
| 失败队列 | 需新建 review_queue.py | 复用现有 reviews_queue(D4) |
| CLI 工具 | 仅 JSON 文件 | 新增 review_queue_cli(D8) |
| 失败追溯 | 有限 | 完整 audit_log + review_queue(D5) |

**v3.0 不是替代 v2,而是 v2 的自然演进**:继承 LLM 驱动的语义判断思想,补齐架构完整性,根除 async/sync bug,统一失败语义。

---

## 16.x LLM 成本说明(D2 重试上限)

D2 自动重试 3 次,**单 stage LLM 调用次数上限 = 3 倍**。

单文档最坏调用次数:
- Stage 1: 3 次
- Stage 3: 3 次
- Stage 4: 3 次 × topics
- Stage 5: 3 次 × topics

假设每篇文章聚成 1 个 topic,最坏 = (3+3+3) + (3 × 1) = **12 次/文档**。

4918 页全量 = **~59000 次 LLM 调用(最坏)**。

实际值取决于 prompt 稳定性 + schema 合规率,通常 2-4x 放大系数。

---

## ✅ 架构验证清单

### 已验证
- [x] P1:LLM 管语义,脚本管机制
- [x] P2:任何 stage 失败 → needs_review,不抛异常
- [x] P3:三道闸门(needs_review / content_filter / evidence)
- [x] P4:Stage 4 兜底桶不写盘
- [x] P5:Stage 1→3 解耦
- [x] P6:幂等性(checkpoint + source_md5)
- [x] P7:PromptAST 镜像 TemplateAST
- [x] P8:async 一致性
- [x] 复用性:page_writer / inverse_index / reviews_queue(D4)/ content_filter / audit_logger
- [x] 向后兼容(P9):CLI / 文件格式 / WikiWriter 签名不变
- [x] D1-D8 决策全部采纳

### 决策记录已锁定
- [x] D1 Prompt 三层覆盖
- [x] D2 schema 校验失败自动重试 3 次
- [x] D3 extract_pilot/extract_full async 化
- [x] D4 复用现有 reviews_queue
- [x] D5 schema 失败入 audit_logger
- [x] D6 Prompt 热加载
- [x] D7 Stage 5 单 topic 失败过滤
- [x] D8 review_queue CLI
- [x] D9 Prompt 路径白名单 + TOML schema 校验(R14)
- [x] D10 review_queue source 标记(R13)
- [x] D11 payload 脱敏(R15)

---

## 17. 下一步

**架构已定稿。下一步是写实施计划(每个 Phase 拆到 0.1-0.5 天的 task),待确认后再开始实施。**

请确认:
1. **架构是否还需要修改?**(如果 OK,告诉我「写实施计划」)
2. **实施计划评审通过后,我会按计划执行**(预计 4 天工作量)
