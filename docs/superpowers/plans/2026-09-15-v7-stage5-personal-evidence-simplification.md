# V7 Stage 5 Personal Evidence Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 简化个人知识库场景下 Stage 5 的证据门槛，让合法来源 ID 的页面不再因 LLM 改写摘录而被阻断。

**Architecture:** Stage 5 继续由 LLM 负责语义内容，脚本负责结构化转换和来源边界校验。保留页面级 `sources`、合法 `item_id` 校验、5 槽位结构和失败重试；删除 `source_text_excerpt` 的原文匹配硬门禁，摘录只作为可选说明保存。Stage 7 的 `__other__`、内容过滤和原子写入逻辑不变。

**Tech Stack:** Python 3.11+, asyncio, TOML prompts, pytest, existing `ConceptPage` / `WikiWriter`。

**Spec:** `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`；本计划对其中“Stage 5 excerpt evidence”做个人使用范围内的最小放宽。

## Global Constraints

- 不新增依赖，不修改 CLI 参数，不改变 Stage 4 canonical `item_id` 契约。
- 保留 `CONCEPT_SLOTS` 的 5 个槽位和 `ConceptPage` 的序列化字段。
- 合法来源 ID 仍必须属于当前 `Topic.item_ids`；未知、缺失或伪造来源仍进入 `needs_review`。
- LLM 调用失败仍按 D7 重试，耗尽后返回 `None`，不把失败页面传给 Writer。
- `source_text_excerpt` 字段暂时保留，兼容现有内存对象和潜在报告读取方；只删除其阻断作用。
- Stage 5 evidence 的 `item_id` 脚本映射不在本次范围内；本次仍校验 LLM 返回值是否属于当前来源集合。

---

### Task 1: Simplify Stage 5 evidence validation

**Files:**

- Modify: `src/pipeline/v7_extract/slot_filler.py`
- Modify: `src/pipeline/v7_extract/prompts/builtin/fill_slots.toml`
- Modify: `scripts/extract_pilot.py`
- Test: `tests/test_pipeline/test_v7_extract_slot_filler.py`
- Test: `tests/test_scripts/test_extract_pilot.py`

**Interfaces:**

- Keep: `fill_slots(topic, source_text, *, llm, project_root=None, max_retries=3) -> ConceptPage | None`
- Remove the unused `item_texts` keyword from `fill_slots()` and `_payload_to_page()`.
- Keep `SlotEvidence.source_text_excerpt` as an optional stored annotation.
- Change evidence acceptance to: `item_id in sources` and non-empty slot body. A non-matching excerpt no longer changes `needs_review`.

- [ ] **Step 1: Change tests first**

Replace the current exact-match expectation with this regression test:

```python
def test_payload_to_page_allows_nonmatching_excerpt_when_item_id_valid():
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {
                "item_id": "raw-1",
                "source_text_excerpt": "LLM paraphrase, not a literal quote",
            },
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="p1",
        title="t",
        sources=["raw-1"],
        source_text="real source text here",
    )
    assert page.slot_evidence["definition"].needs_review is False
```

Add the structural guard test:

```python
def test_payload_to_page_marks_empty_slot_body_as_needs_review():
    payload = {
        "slots": {**_VALID_PAYLOAD["slots"], "definition": ""},
        "evidence": {
            "definition": {"item_id": "raw-1", "source_text_excerpt": "anything"},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="p1",
        title="t",
        sources=["raw-1"],
        source_text="real source text here",
    )
    assert "definition" in page.needs_review_slots
```

Update existing helper calls to omit `item_texts`; retain the unknown `item_id` test and the missing-evidence test unchanged in meaning.

- [ ] **Step 2: Run the focused tests and verify red**

Run:

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_slot_filler.py -q
```

Expected: FAIL because the current implementation still marks a non-matching excerpt as `needs_review` and still exposes the unused `item_texts` path.

- [ ] **Step 3: Implement the minimum code change**

In `_payload_to_page()`, replace the existing evidence decision:

```python
has_evidence = bool(item_id and item_id in sources)
needs_review = not has_evidence
if not needs_review and excerpt and not _excerpt_in_source(excerpt, source_text):
    needs_review = True
```

with:

```python
has_evidence = bool(item_id and item_id in sources)
needs_review = not has_evidence or not body
```

Then:

- Remove `_excerpt_in_source()` from `slot_filler.py`.
- Remove `item_texts` from `fill_slots()` and `_payload_to_page()` signatures and calls.
- Remove `item_texts=item_map` from the `fill_slots()` call in `scripts/extract_pilot.py`; keep `item_map` because it is still used to build `topic_text`.
- Update docstrings to say that `item_id` is validated, while `source_text_excerpt` is optional context and may be paraphrased.
- Update `fill_slots.toml` so it no longer tells the LLM to produce an “exact substring”:

```toml
For each slot, return body text + evidence. The item_id must be one of the
source IDs provided. source_text_excerpt is optional context for a human reader;
it may be a concise paraphrase and is not required to be a literal quote.
```

- [ ] **Step 4: Run the focused tests and verify green**

Run:

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_slot_filler.py tests/test_scripts/test_extract_pilot.py -q
```

Expected: all tests pass; unknown `item_id`, missing evidence, empty slot bodies and LLM failures still produce review/`None` as appropriate.

- [ ] **Step 5: Commit the self-contained slice**

```powershell
git add src/pipeline/v7_extract/slot_filler.py src/pipeline/v7_extract/prompts/builtin/fill_slots.toml scripts/extract_pilot.py tests/test_pipeline/test_v7_extract_slot_filler.py tests/test_scripts/test_extract_pilot.py
git commit -m "fix(v7-stage5): relax personal evidence excerpt gate"
```

### Task 2: Regression and one-document apply verification

**Files:**

- Modify: `.superpowers/sdd/progress.md`
- Test: `tests/test_pipeline/test_v7_extract_topic_clusterer.py`
- Test: `tests/test_pipeline/test_v7_extract_wiki_writer.py`
- Test: `tests/test_scripts/test_extract_full.py`

**Interfaces:**

- Stage 4 continues to produce canonical `Topic.item_ids`.
- Stage 5 continues to return `ConceptPage | None`.
- Stage 7 continues to block `__other__`, invalid/review pages and content-filter failures.

- [ ] **Step 1: Run the affected regression suite**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_pipeline/test_v7_extract_topic_clusterer.py tests/test_pipeline/test_v7_extract_slot_filler.py tests/test_pipeline/test_v7_extract_wiki_writer.py tests/test_scripts/test_extract_pilot.py tests/test_scripts/test_extract_full.py -q
```

Expected: all affected tests pass with no changes to Stage 4 or Writer behavior.

- [ ] **Step 2: Run compile and diff checks**

```powershell
$env:PYTHONPATH="."
python -m compileall -q src/pipeline/v7_extract scripts/extract_full.py scripts/extract_pilot.py
git diff --check
```

- [ ] **Step 3: Run a fresh one-document apply smoke**

Use a temporary root containing one real source, set `V7_ALLOW_APPLY=1` before starting Python, and pass the temporary checkpoint explicitly:

```powershell
$smokeRoot = "E:\tmp-v7-stage5-personal-smoke"
New-Item -ItemType Directory -Force -Path "$smokeRoot\raw\sources" | Out-Null
Copy-Item -LiteralPath "knowledge\novel-wiki\raw\sources\必备资料15顺眼谈文章的画面感.md" -Destination "$smokeRoot\raw\sources" -Force
$env:PYTHONPATH="."
$env:V7_ALLOW_APPLY="1"
python scripts/extract_full.py --apply --batch-size 1 `
  --checkpoint "$smokeRoot\.index\v7_full_checkpoint.json" `
  --json-out "E:\tmp-v7-stage5-personal-smoke.json" `
  --markdown-out "E:\tmp-v7-stage5-personal-smoke.md" `
  --root $smokeRoot
```

Expected:

- JSON summary has `selected=1`, `processed=1`, `errors=0`, `pages=1`.
- `wiki\concepts\` exists and contains one Markdown page if all five slots have valid source IDs and non-empty bodies.
- The page frontmatter `sources` contains the canonical `raw/sources/...` ID.
- A page blocked by an invalid source ID or empty slot is reported as blocked and is not written; this remains correct.

- [ ] **Step 4: Update the progress ledger**

Append an entry to `.superpowers/sdd/progress.md` recording the exact test command, smoke summary, whether a concept file was written, and that the excerpt match gate was removed while source-ID validation remained.

- [ ] **Step 5: Commit the verified regression evidence**

```powershell
git add .superpowers/sdd/progress.md
git commit -m "docs(v7-stage5): record personal evidence gate verification"
```

## Deliberately out of scope

- 不把 Stage 5 evidence `item_id` 改成 `item_index`；这是下一次独立的 provenance 修复，避免本次同时改变两个 LLM 契约。
- 不删除 `SlotEvidence`、`source_text_excerpt` 字段或 `needs_review_slots`；它们仍可供人工查看，删除会扩大兼容性影响。
- 不修改 Stage 7 的 `__other__`、content filter、checkpoint、原子写入和 retry 逻辑。
- 不把 5 个槽位缩减为 3 个；页面格式已经是当前 V7 合同，个人使用也需要稳定结构。

## Execution-time audit

### Round 1 — 全面漏洞审计

1. **重大隐患：**取消摘录匹配后，LLM 可能生成不存在的引文；**后果：**证据文本不再能自动审计；**处理：**保留合法 `item_id` 校验，摘录降为人工参考，个人使用接受该权衡。
2. **重大隐患：**Stage 5 evidence 的 `item_id` 仍由 LLM 返回；**后果：**多片段主题中可能再次出现短 ID；**处理：**本次保留 membership 校验并明确列为下一独立任务，不混入本次最小改动。
3. **优化疏漏：**当前 `has_evidence` 依赖 `needs_review` 间接表达；**后果：**状态语义不够直观；**处理：**本次不重构数据模型，避免影响 Writer 和已有页面。
4. **重大隐患：**LLM 可能返回空槽位；**后果：**摘录门槛放宽后空页面可能被写入；**处理：**增加 `not body` 的脚本级 review 判定和回归测试。
5. **优化疏漏：**source_text 仍只传前 12000 字；**后果：**超长主题后段信息不可见；**处理：**本次不改 token 预算，避免成本和行为变化；后续按真实漏检样本调整。
6. **优化疏漏：**保留 `source_text_excerpt` 会让调用方误以为它仍是硬证据；**后果：**使用者理解不一致；**处理：**同步改 TOML 和 docstring，明确它是可选说明。
7. **重大隐患：**删除 `item_texts` 时误删 `item_map` 会破坏 topic 文本拼接；**后果：**Stage 5 输入变空；**处理：**只删除函数参数，保留 `item_map` 和 `topic_text` 构造逻辑。
8. **优化疏漏：**现有全量 CLI 默认 checkpoint 路径可能与自定义 root 不一致；**后果：**smoke 被旧 checkpoint 跳过；**处理：**测试命令显式传临时 checkpoint，本次不扩大范围修改 CLI。

### Round 2 — 压力测试推演

- **LLM 返回未知 item_id：**membership 校验继续标记 review，Writer 不写盘，覆盖成立。
- **LLM 返回空 excerpt 但合法 item_id：**页面允许通过，这是个人模式的预期；来源仍由 page-level `sources` 追溯。
- **LLM 返回空 body：**新增 body 校验标记 review，避免写入空槽位。
- **LLM 返回 malformed JSON 或接口超时：**D7 重试仍生效，耗尽返回 `None`，不污染 batch。
- **Stage 4 返回 `__other__`：**Stage 7 原有 P4 阻断不变。
- **批处理部分成功：**`extract_full` 仍只提交无错误 batch 的 pages，checkpoint 规则不变。
- **旧调用方继续传 `item_texts`：**这是内部函数参数变更；计划同步修改仓库内唯一调用方和测试，未发现外部 CLI/API 契约。
- **smoke 复用旧状态：**显式临时 root + checkpoint，且验收同时检查报告、checkpoint、concept 文件，避免只看退出码。

**审计结论：**无致命缺陷；第 1、2、4、7、8 项是主要执行风险，均有明确边界或加固措施。方案可以进入用户确认，确认后再编码。
