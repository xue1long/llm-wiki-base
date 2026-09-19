# V7 Stage 1 整改方案评估与最小修复落点

> 本文档是对用户提交的《Stage 1 整改方案（修订版）》的评估，并把它收敛为
> **可立即落地的「最高杠杆最小改动」三步走法**。所有代码事实均已逐行核实，
> 列在 §2 作为权威锚点。设计决策的裁判仍以 `docs/adr/0011-v7-ingestion-outcome-control-plane.md`
> 与 `docs/guides/v7-ingestion-pipeline.md` 为准。

---

## 1. 整体评估结论

**方案成立，且是「治本」而非「打补丁」。**

核心反转——**「脚本完整看见文档，LLM 只解释语义，Stage 1 不再有阻止确定性处理的权力」**——
正是对此前发现的 7 条最高优先级风险（长文截断、单标签混合、级联误判、`incomplete` 混模、
缺 provenance/验收契约）的正确解法。修订版还补上了第一版缺失的三块：
provenance（fingerprint）、checkpoint invalidation、gold-set 验收，并用 4 批次做了诚实的范围切分。

**但对照真实代码，方案有两点关键遗漏 + 若干落地精度问题（§4、§5）。**
其中最关键的是：**方案修好了 Stage 1 的 4000 截断，却没碰 Stage 2 自身的 12000 截断，
而后者正是「合集分段」这条最危险路径上的真实瓶颈。**

---

## 2. 代码事实锚点（已逐行核实）

| 文件:行 | 事实 | 与方案的关系 |
|---|---|---|
| `doc_classifier.py:90` | `Classification.__slots__ = ("doc_type","confidence","rationale")` | 现状仅 3 字段，无 `failed`/provenance |
| `doc_classifier.py:47-54` | `_VALID_DOC_TYPES` frozenset 含 `"incomplete"` | `incomplete` 与文档形态混在同一枚举 |
| `doc_classifier.py:77` | `DocType.INCOMPLETE = "incomplete"`（enum 已废弃但仍在 import） | 第三处真相源，漂移隐患 |
| `doc_classifier.py:149` | `render_prompt(..., "content_limit": "4000", ...)` | Stage 1 仅喂前 4000 字 → 合集尾部多作者署名不可见 |
| `doc_classifier.py:184-186` | 重试耗尽 → `return Classification(doc_type="incomplete", confidence=0.0, ...)` | 技术失败伪装成「残稿」状态 |
| `classify.toml:94-96` | user template 用 `first {content_limit} chars` | 截断契约写死在 prompt |
| `extract_pilot.py:192` | 注释 `v3: P5-decoupled (doc_type is soft hint)` | 与下方 :229/:241 自相矛盾 |
| `extract_pilot.py:229` | `_extract_items_async(..., doc_type=classification.doc_type, ...)` | Stage 1 真权力：驱动 Stage 2 分段 |
| `extract_pilot.py:241` | `cluster_topics(..., doc_type=classification.doc_type, ...)` | Stage 1 真权力：驱动 Stage 4 聚类 |
| `extract_pilot.py:519` | `if llm is not None and doc_type == "collection":` | **级联断点精确位置** |
| `extract_pilot.py:433-434` | `_COLLECTION_HEADER_RE = re.compile(r"更新时间\d{4}...\s+字数：\d+")` | 只认时间戳表头，作者署名合集不命中 |
| `extract_pilot.py:438` | `def _extract_items_by_metadata_header(...)` | 确定性切分器 #1（仅时间戳表头） |
| `extract_pilot.py:481` | `async def _segment_via_llm(...)` | LLM 兜底分段 |
| `article_segmenter.py:85` | `render_prompt(..., "content_limit": "12000", ...)` | **Stage 2 LLM 兜底仍被 12KB 截断** |
| `topic_clusterer.py:95` | `doc_type_header = f"\nDocument type: {doc_type}\n" if doc_type else ""` | Stage 4 靠 `doc_type` 门控聚类规则 |
| grep 全库 | 无 `invalidate`/`reclassify`；`confidence` 仅在 :206 落盘、零消费 | 无 invalidation，confidence 是死字段 |

---

## 3. 方案比第一版多补上的（确认正确）

| 第一版缺口 | 修订版是否解决 | 证据 |
|---|---|---|
| 「第 2 点其实落在 Stage 2」 | ✅ 第十节显式改为 Stage 2 责任 | `extract_pilot.py:519` 确是分段门控 |
| 缺 provenance | ✅ 第十五节 fingerprint | `__slots__` 现仅 3 字段 |
| 缺 invalidation | ✅ 第十六节 checkpoint 双键 | 现状 skip 仅 `source_md5+status` |
| 缺 gold set | ✅ 第十九节 16 类样本 + 专项指标 | 现状无任何 eval 设施 |
| 单标签表达力 | ✅ 第八节 `mixed` + `traits` | 现状强制单枚举 |

---

## 4. 两个关键遗漏（代码事实）

### G1 · Stage 2 自己还有一道 12000 截断——方案完全没提

`article_segmenter.py:85` 写死 `content_limit: "12000"`，`_segment_via_llm`（LLM 分段兜底）
只把前 12KB 喂给 LLM。修订版第十节说「发现 12 个稳定 header 就直接按 12 篇切」——
**这只对带 `更新时间+字数` 表头的合集成立**（那种走确定性正则 `:438`，根本不调 LLM）。

对于**用「作者 XXX」署名、但没有时间戳表头**的合集：
- 确定性正则 `_COLLECTION_HEADER_RE`（`:433` 仅匹配三江杂谈式时间戳）匹配失败 → 落到 LLM 兜底；
- LLM 兜底仍被 12KB 截断 → 尾部作者署名看不见 → **19 篇仍可能切成 1 篇**。

> 结论：方案把 Stage 1 的 4000 截断修好了，但**合集分段最危险路径上的 Stage 2 截断纹丝未动**。

### G2 · 真正的级联断点只有一个，方案没点名

`_extract_items_async`（`:495-534`）的真实顺序是：
1. **确定性 metadata-header 正则（永远执行）** `:513-516`
2. **LLM 分段兜底——仅当 `llm is not None and doc_type == "collection"`（:519）**
3. v2 heading/numbered 正则兜底 `:534`

所以「Stage 1 错一次 → 后面整篇没拆」的断点**精确到 :519 的 `doc_type == "collection"`**。
方案第十节说「确定性扫描永远执行」——第 1 步**其实已经永远执行了**；
真正被 `doc_type` 卡住的只有第 2 步的 LLM 兜底。因此方案第十节的改动量被高估了：
**关键修复就是改 :519 的门控条件**，从 `doc_type=="collection"` 换成结构信号
（如 `author_marker_count >= 2 or metadata_header_count >= 2`）。

**更优根治法**（顺带消掉 G1）：新增 `_extract_items_by_author_byline`
（与 `:438` 的 metadata-header 切分器平级），用作者署名做确定性切分，
让大多数合集**根本不进 LLM 兜底**——这样 Stage 2 的 12000 截断也绕开了。

---

## 5. 其余落地精度问题

| # | 问题 | 代码定位 | 建议 |
|---|---|---|---|
| G3 | Stage 4 的 collection 特殊规则也是硬门控，方案未点名 | `topic_clusterer.py:95` | 第十一节落地时需把 `traits:[possible_collection]` 也带进 header，否则 Stage 4 仍会因 `doc_type≠collection` 关掉拆分规则 |
| G4 | `confidence` 现状是死字段 | grep 确认仅落盘、零消费 | 方案第十二节算 `effective_confidence` 很好，但必须明文写「仅作元数据，不门控任何分支」，否则重蹈死字段/误门控覆辙 |
| G5 | `structural_corruption` 落点未定义 | 新字段，下游无对应分支 | 需明确：corruption 是「继续但标旗」还是「block」。若 block，必须补下游闸门 |
| G6 | 批次 1 第 1 项（删 incomplete）与 `failed` 字段耦合 | 失败路径 `doc_classifier.py:184-186` 返回 `incomplete` | 删 incomplete 前必须先有 `failed` 字段承接失败路径，否则失败无处可去。建议批次 1 与第十八节 `failed` 合并实施 |
| G7 | boilerplate 抑制（第七节）「不改性 source」原则对，但要防误删 | 仅生成 analysis view | 模板化教程里 legitimately 重复的块会被当重复块压制，需保留白名单 |

---

## 6. 最高杠杆最小改动（三步走，blast radius 极小）

> 与其按 4 批次平推，建议优先做真正止血的三处。做完这 3 步，R1（截断失明）、
> R2（失败可审计）、R3（无降级）的**级联根因**就闭合了；`traits/mixed/confidence/
> fingerprint/checkpoint/gold-set` 作为第二批往后排完全合理。

### Step 1 · 删 `incomplete` + 加 `failed` 契约（承接失败路径）

**文件：`src/pipeline/v7_extract/doc_classifier.py`**

```python
# 1) __slots__ 扩展（:90）—— 失败可审计 + provenance 占位
__slots__ = (
    "doc_type", "confidence", "rationale",
    "failed", "error",          # 技术失败标记（R2 闭环）
    "uncertain",                # 语义不确定，非失败（第十八节）
    "traits",                   # 结构特征，取代单标签（第八节）
    "evidence_summary",         # 分类输入覆盖度（第五/十五节）
    "classifier_fingerprint",   # 分类规则指纹（第十五节）
)

# 2) 构造函数增加默认参数
def __init__(self, doc_type, confidence, rationale,
             failed=False, error=None, uncertain=False,
             traits=None, evidence_summary=None, classifier_fingerprint=None):
    ...
    self.failed = failed
    self.error = error
    self.uncertain = uncertain
    self.traits = traits or []
    self.evidence_summary = evidence_summary
    self.classifier_fingerprint = classifier_fingerprint

# 3) _VALID_DOC_TYPES（:47-54）删除 "incomplete"；DocType enum（:77）删 INCOMPLETE
_VALID_DOC_TYPES = frozenset({
    "single_method", "multi_section", "collection",
    "qa_chat", "list", "tool", "mixed",
})

# 4) 失败路径（:184-186）改为显式失败，不再伪装成 incomplete
return Classification(
    doc_type="unknown", confidence=0.0,
    rationale=f"stage1_failed_after_{max_retries}_retries: {last_error}",
    failed=True, error=str(last_error),
)
```

**调度处落点：`scripts/extract_pilot.py` `_extract_one`（:188 之后）补失败入队分支**

```python
classification = await classify_doc(...)
if classification.failed:                       # 新增：失败可审计（R2）
    enqueue_review(source=relative, stage="stage1",
                   reason=classification.error)   # 复用现有 reviews_queue（D4）
    return ExtractionResult(status="failed", source=relative, ...)
# 否则继续 Stage 2...
```

> 注：`enqueue_review` 复用 `src/wiki/storage/reviews_queue.py`（D4），不新建设施。

### Step 2 · 改 `:519` 门控 + 补 byline 确定性切分器（消灭级联 + 绕过 G1）

**文件：`scripts/extract_pilot.py`**

```python
# A) 新增：作者署名确定性切分器（与 :438 平级）
_AUTHOR_BYLINE_RE = re.compile(r"^\s*作者\s*[:：]\s*(\S{1,20})\s*$", re.M)

def _extract_items_by_author_byline(content: str, relative: str) -> list[dict] | None:
    """合集按作者署名确定性切分；无署名或仅 1 位作者返回 None。"""
    spans = [(m.start(), m.group(1)) for m in _AUTHOR_BYLINE_RE.finditer(content)]
    if len({name for _, name in spans}) < 2:
        return None
    boundaries = [0] + [pos for pos, _ in spans[1:]] + [len(content)]
    out = []
    for i in range(len(boundaries) - 1):
        text = content[boundaries[i]:boundaries[i+1]].strip()
        if text:
            out.append({
                "id": f"{relative}#article-{i+1}",
                "text": text,
                "title": spans[i][1],
            })
    return out or None

# B) 改 _extract_items_async（:513-534）顺序 —— 确定性永远先跑
async def _extract_items_async(content, relative, *, llm=None,
                               doc_type=None, project_root=None):
    # 1. 时间戳表头确定性切分（已有）
    by_header = _extract_items_by_metadata_header(content, relative)
    if by_header:
        return by_header
    # 2. 作者署名确定性切分（新增 —— 直接读全量 content，绕过 12KB 截断 G1）
    by_byline = _extract_items_by_author_byline(content, relative)
    if by_byline:
        return by_byline
    # 3. LLM 兜底 —— 门控从 doc_type=="collection" 改为结构信号（:519 修复）
    if llm is not None and _looks_like_collection(content):
        boundaries = await _segment_via_llm(content, llm=llm,
                                            doc_type=doc_type,
                                            project_root=project_root)
        if len(boundaries) > 1 or (boundaries and boundaries[0].title):
            return [...]
    # 4. v2 heading/numbered 正则兜底
    return _extract_items(content, relative)

def _looks_like_collection(content: str) -> bool:
    """脚本侧结构信号，取代 LLM 标签作为分段门控（P1 脚本管机制）。"""
    ts_headers = len(_COLLECTION_HEADER_RE.findall(content))
    authors = {m.group(1) for m in _AUTHOR_BYLINE_RE.finditer(content)}
    return ts_headers >= 2 or len(authors) >= 2
```

> **效果**：即使 Stage 1 把合集误判成 `single_method`，`:519` 仍会因结构信号触发分段；
> 且作者署名合集走 `by_byline`（全量读取），**根本不碰 12KB 截断的 LLM 兜底** → G1 一并解决。

**联动 Step 1 收口**：Stage 1 改 `mixed`/`traits` 后，`doc_type` 仍可传，但 :519 已不再依赖它。
Stage 4（`topic_clusterer.py:95`）同步把 `traits:[possible_collection]` 带进 `doc_type_header`（G3）。

### Step 3 · Stage 1 改 bounded evidence pack（修 4000 截断 + 中部决定性结构漏看）

**文件：`src/pipeline/v7_extract/doc_classifier.py`**

```python
MAX_EVIDENCE_BYTES = 4000
MAX_EVENT_SAMPLES = 12
MAX_FIXED_SAMPLES = 6
MAX_SAMPLE_CHARS = 400

def _build_evidence_pack(content: str) -> tuple[str, dict]:
    """脚本完整扫描后构造有硬预算的 evidence pack。
    返回 (pack_text, evidence_summary)。不依赖 provider 是否吞下整篇原文。"""
    import re
    h2 = len(re.findall(r"(?m)^##\s+", content))
    authors = len(re.findall(r"^\s*作者\s*[:：]", content, re.M))
    qa = len(re.findall(r"(?m)^(Q|A)[:：]|问[:：]|答[:：]", content))
    bytes_total = len(content.encode("utf-8"))

    # 分布式采样：0/20/40/60/80/100% 附近小窗 + 事件驱动采样
    n = len(content)
    fixed = [content[int(n * r):int(n * r) + MAX_SAMPLE_CHARS]
             for r in (0, .2, .4, .6, .8, 1.0)]
    pack = "\n---\n".join(s.strip() for s in fixed if s.strip())

    # 硬预算封顶：超预算确定性抽样，绝不交给 LLM 删
    if len(pack.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        pack = pack[:MAX_EVIDENCE_BYTES]

    summary = {
        "document_bytes": bytes_total,
        "sampled_bytes": len(pack.encode("utf-8")),
        "h2_count": h2, "author_marker_count": authors, "qa_marker_count": qa,
    }
    return pack, summary

# classify_doc 渲染处改两行（:149 附近）
system_prompt, user_prompt = render_prompt(template, {
    "content": _build_evidence_pack(content)[0],   # 原: content[:4000]
    "structural_hint": _structural_hint(content),   # 新增（见下）
    ...
})
```

> 可叠加一个纯函数 `_structural_hint`（脚本侧信号，零成本）注入 prompt，正是 P1「脚本管机制」的写法。

**三步走完后契约收敛为：**

```
Raw source
  ↓  Script full structural scan（读全量，不受 context 限制）
  ↓  Bounded evidence pack（硬预算，可记录 coverage）
  ↓  LLM semantic classifier（primary_type + traits + uncertain + confidence）
  ↓  仅作为 soft semantic hint
  ↓  Stage 2/4 永远先跑确定性结构路径（不再被 doc_type 卡）
```

---

## 7. 验证口径（gold set，修订版第十九节认可）

建立覆盖以下 16 类的样本（不需要大，但要卡住最危险混淆）：

1. 正常短文　2. 50KB 单篇长文　3. 100KB 合集　4. >20 篇合集
5. 无标题长文　6. 多 H2 文档　7. QA+教程混合　8. 合集+工具混合
9. 文件名误导（如 `001.md` 实为合集）　10. 中部才出现决定性结构
11. HTML boilerplate 很重　12. 重复 footer ×100　13. 代码块内大量 `Q:`/`1.`
14. 含 prompt injection　15. 段落乱序/重复　16. 完全无法判断类型

**头号验收指标（高于 overall accuracy）：**
> 真正的 collection **不要** 被判成普通单篇（collection→multi_section 误判会直接改写 Stage 2 行为）。

建议 gold set 第一条就用「无 metadata-header、纯作者署名合集」——正好卡住 §4 的 G1/G2 断点。
配套指标：collection recall、mixed detection recall、false collection rate、uncertain precision、
long-document stability、same-input repeatability。

---

## 8. 残留风险与未覆盖项

| 项 | 状态 | 说明 |
|---|---|---|
| R4 confidence 无阈值 | 本次未修 | 方案第十二节要求，但须明文「仅元数据、不门控」 |
| R6 prompt injection 未隔离 | 本次未修 | 方案第十三节要求 `UNTRUSTED_DOCUMENT_DATA` 包裹 |
| G5 corruption 落点 | 待定 | 需先定义「继续标旗 vs block」再写下游闸门 |
| G7 boilerplate 误删 | 待定 | 需白名单保护 legitimately 重复块 |
| provenance / checkpoint invalidation | 第二批 | 方案第十五/十六节，依赖 `classifier_fingerprint` 字段（Step 1 已占位） |
| 历史页回滚 | 不存在 | grep 全库无 invalidation；prompt 升级后旧页不会回滚，需第二批补 |

---

## 9. 实施顺序建议

| 顺序 | 改动 | 文件 | 闭合的风险 |
|---|---|---|---|
| 1 | `Classification` 加 `failed`/`error`/`uncertain`/`traits`/`evidence_summary`/`classifier_fingerprint`；删 `incomplete` | `doc_classifier.py` | R2 + G6 + provenance 占位 |
| 2 | 失败入队分支（`:188` 后） | `extract_pilot.py` `_extract_one` | R2 闭环 |
| 3 | `_extract_items_by_author_byline` + 改 `:519` 门控为结构信号 | `extract_pilot.py` | G2 级联 + G1 截断 |
| 4 | bounded evidence pack + structural hint | `doc_classifier.py` + `classify.toml` | R1 截断失明 |
| 5 | Stage 4 `doc_type_header` 带 `traits` | `topic_clusterer.py:95` | G3 |
| — | traits/mixed/fingerprint/checkpoint/gold-set | 第二批 | 全面收口 |

> 改完跑 `tests/test_v7*`（当前 298 passed, 1 skipped）验证不破坏现有行为。
> `dry-run` 用确定性抽样（`--count 50 --seed 42`）先验证不碰 `wiki/`。
