# Plan 5 — V7 Stage 4 collection-split rule (2026-09-16)

**Status:** superseded by `2026-09-17-v7-stage-remediation-master-plan.md` (Task 11)
**Branch:** feature/2026-09-16-v7-collection-split

> **Superseded 2026-09-17.** Plan 5 proposed gating Stage 4 collection splitting on
> `doc_type == "collection"` (single-source, hard rule in `cluster.toml` v1.1).
> Master plan Task 11 explicitly removed this gate: `doc_type` is a **soft hint**
> carried via `classification_hint`, and Stage 2's `SegmentationResult.structural_signals`
> plus the author-byline splitter are the structural authority. Implementing Plan 5
> as written would re-introduce the H8/L1 risk (Stage 1 misclassification cascades
> into Stage 4). The 3 tests added under this plan that asserted the gate / version
> bump were removed in commit (see progress ledger); only the `doc_type` kwarg
> shape and header-omission guards remain, repurposed to assert soft-hint behaviour.

## Goal

Stage 4 cluster 遇到 `collection` 类型文档时，按文章标题拆多 topic（每篇文章 1 topic），而不是把整篇合成 1 个 umbrella topic。让 Stage 5 fill_slots 对每篇文章产出独立 wiki 页面，保留每篇文章的具体内容（书名原则 / 字数控制等），解决 wiki 信息密度损失 97% 的问题。

## Non-goals

- 不改 Stage 1 classify（collection 分类正确，问题在 Stage 4 聚类）
- 不改 Stage 5 fill_slots / Stage 7 WikiWriter
- 不动 collection 以外 doc_type 的聚类行为（single_method / multi_section / list / qa_chat / tool / incomplete）
- 不改 D9 schema（D10 P4 兜底 + D11 仍生效）
- 不改 v2 legacy ingest 路径
- 不加 Stage 4.5 独立模块
- 不动 WikiWriter atomic write（plan-audit 范围外，单次 apply 19 张 wiki 在 WikiWriter 当前架构下行为已稳定）

## Architecture

### 当前行为（bad）

Stage 4 cluster 把 53 KB collection 文档聚成 1 个 topic（"三江杂谈"）。Stage 5 跑 1 次 fill_slots → 1 张 wiki 概念页 → 1321 B（原文 53428 字符，**压缩率 2.5%**）。9 个具体条目（书名原则 / 笔名原则 / 字数控制等）全部丢失。

### 目标行为

Stage 4 cluster 把 collection 文档按文章标题拆成 N 个 topic（N = 文章数）。Stage 5 跑 N 次 fill_slots → N 张 wiki 概念页。每张 wiki 含单篇文章的具体内容。

### 改动范围（2 个文件 + 3 个测试）

| 文件 | 改动 |
|---|---|
| `src/pipeline/v7_extract/prompts/builtin/cluster.toml` | 改 user template（加 collection-split 规则 + article 定义） + bump version 1.0 → 1.1 |
| `src/pipeline/v7_extract/topic_clusterer.py` | `cluster_topics()` 新增 `doc_type` keyword 参数 + max_topics 默认 5 → 20 |
| `src/pipeline/v7_extract/prompts/builtin/cluster.toml` (system 部分) | 加 "Document type: ..." 一行（仅当 doc_type 已知时） |
| `scripts/extract_pilot.py` | 把 `classification.doc_type` 透传给 `cluster_topics()` |
| `scripts/extract_full.py` (extract_pilot._extract_one 调用) | 同上 |
| `tests/test_pipeline/test_v7_extract_topic_clusterer.py` | +3 测试 |
| `.superpowers/sdd/progress.md` | Plan 5 条目 |
| `.memory/feedback-v7-collection-split-2026-09-16.md` | new |
| `.memory/MEMORY.md` | index 追加 |

### 关键设计选择

1. **改 prompt 而非加 Stage**：奥卡姆 剃刀——5 行规则解决 80% 问题
2. **doc_type 显式传入 prompt**：解决 Round 1 致命缺陷 H8/L1（LLM 之前只能从 items_text 推断 "multi-author"，不可靠）
3. **max_topics 默认 5 → 20**：collection 通常 ≥ 5 篇；20 够覆盖大部分 roundup；超 20 走 P4 `__other__` 兜底
4. **规则嵌入 user template**：不动 system text + output_schema（D9 防注入不变）
5. **仅 collection 触发**：prompt 明确 "ONLY when document type is collection"——避免误触发其他 doc_type
6. **Stage 5 / 7 零改动**：现有 fill_slots 接受任意数量 topic；WikiWriter 一次写多个 page（已有逻辑）

## Global Constraints

- 不引入新依赖
- 不改 Stage 1/3/5/7 任何代码（除了 extract_pilot.py 透传 doc_type 这一个调用点）
- D9 schema 仍生效
- D10 P4 兜底仍生效（item 未分配 → `__other__` bucket）
- 现有 17 个 test_v7_extract_topic_clusterer.py 测试零回归（用 `doc_type=None` 默认值兼容现有调用）
- 现有 299+ 测试零回归

---

### Task 1: cluster_topics() 接 doc_type 参数 + max_topics 默认提升

**Files:**

- Modify: `src/pipeline/v7_extract/topic_clusterer.py`

**改动**：

```python
async def cluster_topics(
    items: list[dict],
    *,
    llm: LLMClient,
    project_root: Path | str | None = None,
    doc_type: str | None = None,         # NEW: passed into prompt
    min_topics: int = 1,
    max_topics: int = 20,                  # CHANGED: 5 → 20 for collection docs
    max_retries: int = 3,
) -> list[Topic]:
```

**改动 `_render_user_prompt` 部分**：

```python
items_text = "\n".join(
    f"{index}: {str(item.get('text', ''))[:200]}"
    for index, item in enumerate(items)
)
# NEW: prepend document-type header so LLM knows if collection rule applies
doc_type_header = (
    f"\nDocument type: {doc_type}\n"
    if doc_type else ""
)
system_prompt, user_prompt = render_prompt(template, {
    "min_topics": min_topics,
    "max_topics": max_topics,
    "items_text": items_text,
    "doc_type_header": doc_type_header,  # NEW
})
```

**改动 builtin/cluster.toml `[[slot]]`** 加一个 slot：

```toml
[[slot]]
name = "doc_type_header"
required = false
default = ""
description = "Optional 'Document type: X' header line prepended to items"
```

**Acceptance**:

- 现有 17 个 cluster 测试零回归（doc_type 默认 None，行为不变）
- 新 keyword 参数向后兼容

---

### Task 2: cluster.toml 改 prompt + bump version

**Files:**

- Modify: `src/pipeline/v7_extract/prompts/builtin/cluster.toml`

**新 user template**：

```toml
[user]
template = """\
Cluster the source items below into {min_topics}-{max_topics} topics.
{doc_type_header}
Rules:
  - Prefer using existing section headings or document titles as topic titles
  - Do NOT split a single document into multiple "综合主题" topics
  - Use only the zero-based integer indexes shown below
  - Each item index must belong to exactly one topic in your output
  - Do not output item_id values or rewrite source paths; the script fills canonical IDs
  - Topic IDs must be stable slugs (lowercase, hyphens, no spaces)
  - Collection splitting (apply ONLY when document type is "collection"):
    When the document is a multi-author or multi-article roundup, split by
    article — each article boundary becomes its own topic. An "article boundary"
    is one of:
      (a) a level-2 heading `## Title` followed by substantial body content, OR
      (b) an explicit author byline (e.g. "作者 314" / "by 314") followed by
          substantial body content.
    Do NOT collapse multiple articles into a single umbrella topic (e.g.
    "三江杂谈"); the umbrella column is the source's job, not Stage 4's. Each
    topic should correspond to one article.

Items (zero-based index: first 200 chars of text):
{items_text}

Respond with JSON:
{{"topics":[{{"id":"stable-slug","title":"主题","item_indexes":[0, 2]}}, ...]}}"""
```

**Version bump**：`[meta].version` 从 `"1.0"` → `"1.1"`。

**Acceptance**:

- TOML 合法（`tomllib.loads` 不抛）
- D9 schema 校验仍通过
- 现有 17 个 cluster 测试零回归（FakeLLMClient 注入响应）

---

### Task 3: extract_pilot.py 透传 doc_type

**Files:**

- Modify: `scripts/extract_pilot.py`

**改动 line 227 附近**：

```python
# v3: cluster_topics is async; returns [] if LLM missing
topics = await cluster_topics(
    items,
    llm=llm,
    project_root=root,
    doc_type=classification.doc_type,  # NEW: pass Stage 1 hint to Stage 4
)
```

**Acceptance**:

- 透传后 cluster_topics() 内部能拿到 doc_type
- 其他调用点不变

---

### Task 4: 加 3 个新测试

**Files:**

- Modify: `tests/test_pipeline/test_v7_extract_topic_clusterer.py`

**测试 1：`test_cluster_topic_signature_accepts_doc_type_kwarg`**

```python
@pytest.mark.asyncio
async def test_cluster_topic_signature_accepts_doc_type_kwarg():
    """Plan 5: cluster_topics accepts a doc_type keyword that propagates into
    the prompt so LLM knows if collection-split rule applies."""
    from src.pipeline.v7_extract.topic_clusterer import cluster_topics
    fake = FakeLLMClient()
    fake.script("cluster", '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}')

    items = _items("a")
    topics = await cluster_topics(items, llm=fake, project_root=None, doc_type="collection")
    assert len(topics) == 1
    # Verify the prompt contained "Document type: collection"
    last_call = fake.calls[-1]
    assert "Document type: collection" in last_call["user_prompt"]
```

**测试 2：`test_cluster_collection_splitting_rule_in_prompt`**

```python
def test_cluster_collection_splitting_rule_in_prompt():
    """Plan 5: cluster.toml must contain the collection-splitting rule
    with article-boundary definition."""
    from src.pipeline.v7_extract.prompts.resolver import resolve
    template = resolve("cluster", project_root=None)
    user = template.user_template
    assert "Collection splitting" in user, "Plan 5 rule missing from cluster.toml"
    assert "level-2 heading" in user, "Article boundary definition missing"
    assert "author byline" in user, "Author byline boundary missing"
    assert "ONLY when document type is \"collection\"" in user, "Rule scope not constrained"
```

**测试 3：`test_cluster_version_bumped_to_1_1`**

```python
def test_cluster_version_bumped_to_1_1():
    """Plan 5: cluster.toml version must be 1.1 to reflect collection-split behavior."""
    import tomllib
    from pathlib import Path
    path = Path("src/pipeline/v7_extract/prompts/builtin/cluster.toml")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["meta"]["version"] == "1.1", (
        f"cluster.toml version is {data['meta']['version']!r}, expected '1.1'"
    )
```

**Acceptance**:

- 3 个新测试通过
- 现有 17 个 cluster 测试零回归
- V7 全套 ≥ 322 passed

---

### Task 5: Real Provider smoke — 验证 collection 拆分生效

**Files:**

- Manual: temp root under `E:\tmp-v7-split-test\`

**步骤 1: 准备 KB + fixture**

```powershell
if (Test-Path "E:\tmp-v7-split-test") { Remove-Item -Recurse -Force "E:\tmp-v7-split-test" }
python -m src.cli project init "E:\tmp-v7-split-test"
Copy-Item "C:\Users\HP\OneDrive\100 - 备份\飞书文档\01_新手入门\入门教程_三江杂谈.md" "E:\tmp-v7-split-test\raw\sources\"
```

**步骤 2: dry-run pilot**

```powershell
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
$env:PYTHONPATH = "."
python scripts/extract_pilot.py --root "E:\tmp-v7-split-test" --count 1 --seed 42 `
  --sources "E:\tmp-v7-split-test\sources.json" `
  --json-out "E:\tmp-v7-split-test\pilot.json" `
  --provider minimax
```

**步骤 3: 验证 cluster 输出**

读 `pilot.json` 的 `results[0].topics`：
- 期望：**topics.length ≥ 2**（split 生效）
- 期望：每个 topic 的 `id` 是单篇文章的 slug（如 `ruhe-biaoti`、`jianjie-xiezuo`），不是 `sanjian-zatan` umbrella
- 期望：每个 topic 的 `title` 与原文 H2 / 作者署名匹配

**Acceptance**:

- topics.length ≥ 2（split 生效）
- topic.title 与原文 H2 匹配

**步骤 4: apply run 落盘**

```powershell
$env:V7_ALLOW_APPLY = "1"
python scripts/extract_full.py --root "E:\tmp-v7-split-test" --batch-size 5 `
  --json-out "E:\tmp-v7-split-test\apply.json" `
  --markdown-out "E:\tmp-v7-split-test\apply.md" `
  --provider minimax --apply
```

**Acceptance**:

- `apply.json` summary `generated_pages >= 2`
- `wiki/concepts/` 下出现 ≥ 2 个 `.md` 文件
- 每张概念页的 5 槽含单篇文章的具体内容（书名原则 / 字数控制等）

**步骤 5: 清理**

```powershell
Remove-Item -Recurse -Force "E:\tmp-v7-split-test"
```

---

### Task 6: Documentation sync

**Files:**

- Modify: `.superpowers/sdd/progress.md`（Plan 5 条目）
- New: `.memory/feedback-v7-collection-split-2026-09-16.md`
- Modify: `.memory/MEMORY.md`（index 追加）

**Acceptance**: progress.md 主账本 + memory feedback + MEMORY.md index 三处同步。

---

## Audit

- Round 1: done — 1 fatal (H8/L1: cluster prompt 没拿到 doc_type), 3 major (E1, E4, B1), 8 minor. All addressed via F1-F4.
- Round 2: done — 10 stress scenarios + 4 boundary points. All addressed (F1 doc_type 透传, F2 max_topics 20 保护, F3 规则限定, F4 article 定义).
- Human review: cluster_topics() 当前确实**不**接受 doc_type 参数（topic_clusterer.py:51-59 已确认）。Plan F1 是必须的架构级修改，不是单纯改 prompt。
- Open risks:
  - **成本线性增加**：N 篇 → N × 4 LLM calls。53 KB / ~19 篇估算 ~0.4 USD（vs 当前 0.02 USD）。Plan 4 cost observability 已暴露，operator 自行判断。
  - **page_id 唯一性**：同 source 多 topic，page_id 由 `(source, topic_id) → sha` 生成，topic_id unique 即 page_id unique。`_page_id.py` 已 dedupe（实测）。
  - **未知文章数**：原文"~19"是 LLM 推断；实际可能 4-30 篇。Plan 不假设数字。
- Rollback: revert cluster.toml version 1.1 → 1.0 + 删 doc_type 透传。FakeLLMClient 测试不受影响。

## Completion evidence

- Final commit: (filled on close)
- Tests: 17 existing + 3 new = 20 cluster tests; full V7 suite ≥ 322 passed
- Static checks: `python -m compileall -q src/pipeline/v7_extract/ scripts/extract_pilot.py` exit 0
- Documentation updated: progress.md Plan 5 + memory feedback + MEMORY.md index
- Real Provider verification: collection type doc produces ≥ 2 wiki pages, each with article-specific content
