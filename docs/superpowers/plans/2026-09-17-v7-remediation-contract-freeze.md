# Contract Freeze — V7 Stage 1–7 + Reconciliation 整改

> **状态**：frozen（2026-09-17）
> **关联 Plan**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md`
> **生效条件**：master plan approved → Contract freeze 生效 → 进入编码阶段（ponytail full）
> **变更规则**：Contract 变更必须重新过 plan-audit（Round 1 + Round 2）+ 人工 review

---

## 0. 背景

master plan 已通过 Round 1 + Round 2 + 人工 review，达到 approved 状态。但在进入编码阶段前，必须冻结**四个最易被实施松动的核心契约**。

这四个 Contract 不是新发现——它们已经在 master plan §3.3 控制面原则、§6 Open risks、Task Acceptance 中零散出现。本文档做的是**唯一语义冻结**：消除所有可能的实施歧义。

---

## 1. Contract 1：Failure Contract

### 1.1 冻结语义

**Technical failure 不得映射成 insufficient / unresolved / conflicting。**

### 1.2 适用范围

| Stage | 失败类型枚举 | technical failure 是否映射到其他类型 |
|---|---|---|
| Stage 1 | `Classification.failed` | ❌ 不得映射到 `uncertain` |
| Stage 2 | `SegmentationStatus.FAILED` | ❌ 不得映射到 `UNCERTAIN` / `DEGRADED` |
| Stage 3 | `CompletenessStatus.TECHNICAL_FAILURE` | ❌ 不得映射到 `INCOMPLETE` / `UNCERTAIN` |
| Stage 4 | `ClusterStatus.FAILED` | ❌ 不得映射到 `UNCERTAIN` / `DEGRADED` |
| Stage 5 | `FillStatus.TECHNICAL_FAILURE` | ❌ 不得映射到 `INSUFFICIENT` / `CONFLICTING` |
| Stage 6R | `RelationRunStatus.FAILED` | ❌ 不得映射到 `READY` / `PARTIAL` |
| Stage 7 | `CommitPhase.FAILED` | ❌ 不得映射到 `COMMITTED` / `RECONCILED` |
| Reconciliation | (没有 technical failure status，但 candidate retrieval / LLM decision 失败应记 `decision=UNRESOLVED`) | ⚠️ UNRESOLVED 是合法结果，不是技术失败；技术失败应 raise exception 走到 caller 端处理 |

### 1.3 失败类型正交性

三种失败类型**严格正交**：

| 失败类型 | 含义 | 重试策略 |
|---|---|---|
| **Technical failure** | LLM timeout / parse error / schema invalid / IO error / network error | **可重试**（技术恢复后可成功）|
| **Evidence insufficient** | LLM 跑了但说"我没找到证据" / candidate 为空 / ontology 缺失 | **不可重试**（不是技术问题）→ review |
| **Semantic uncertain / conflicting** | LLM 跑了但给出 ambiguous / contradictory 答案 | **不可重试** → review（人类判断）|

### 1.4 反面案例

| 错误做法 | 后果 |
|---|---|
| Stage 3 LLM timeout → `CompletenessStatus.INCOMPLETE` | source 被永久标记 incomplete，checkpoint skip 后永不再跑 |
| Stage 5 LLM schema invalid → `FillStatus.INSUFFICIENT` | 假装证据不足，但实际是技术失败，retry 应能修复 |
| Reconciliation LLM 调用失败 → `decision=UNRESOLVED` 然后自动合并 | UNRESOLVED 是合法结果但必须由脚本判断；LLM 失败时不能直接用 UNRESOLVED 假装正常 |

### 1.5 验证（hard invariant 0）

每 stage 都必须有测试：

```python
def test_stage_X_technical_failure_never_mapped_to_insufficient_or_unresolved():
    """硬指标 0 — 技术失败绝不映射为 insufficient / unresolved / conflicting"""
    # 构造 LLM 失败的场景
    # 验证 status == TECHNICAL_FAILURE
    # 验证绝不 == INSUFFICIENT / UNCERTAIN / CONFLICTING
```

---

## 2. Contract 2：Canonical Identity Contract

### 2.1 冻结语义

**只有 SAME / ALIAS 共享 canonical；BROADER / NARROWER / OVERLAP / DISTINCT / UNRESOLVED 保持独立 canonical。**

### 2.2 ReconciliationDecision 与 canonical membership 映射

| ReconciliationDecision | 与 candidate canonical 的关系 | candidate page 是否加入 canonical membership |
|---|---|---|
| `SAME` | 等同 | ✅ 加入 |
| `ALIAS` | 等同（同义名）| ✅ 加入 + 自动注册 AliasRecord |
| `BROADER` | 候选概念更宽 | ❌ 保持独立 + 建立 `broader` relation |
| `NARROWER` | 候选概念更窄 | ❌ 保持独立 + 建立 `narrower` relation |
| `OVERLAP` | 部分语义重叠 | ❌ 保持独立 + 建立 `overlap` relation |
| `CONFLICT` | 同概念但有冲突 claims | ✅ 加入（同 canonical，conflict 在 claim 层处理）|
| `DISTINCT` | 不同概念 | ❌ 新建独立 canonical |
| `UNRESOLVED` | 证据不足 | ❌ 保持独立 + 进 review |

### 2.3 反面案例

| 错误做法 | 后果 |
|---|---|
| `OVERLAP` 决策自动合并 canonical | 丢失 overlap 信息，无法后续 reconcile |
| `BROADER` / `NARROWER` 决策合并 canonical | 父子概念消失，schema 不可恢复 |
| `UNRESOLVED` 自动合并 canonical | LLM 不确定时被强制合并，false merge 风险 |

### 2.4 验证

```python
def test_reconciliation_broader_narrower_overlap_keep_canonical_independent():
    """硬指标 0 — 仅 SAME/ALIAS/CONFLICT 共享 canonical"""
    # 构造 BROADER / NARROWER / OVERLAP 决策
    # 验证 candidate page 未加入 candidate canonical membership
    # 验证建立了对应 relation 记录
```

### 2.5 不变量

- `CanonicalConcept.member_page_ids` 仅由 SAME / ALIAS / CONFLICT 决策填充
- `CanonicalConcept.aliases` 仅由 ALIAS 决策填充
- BROADER / NARROWER / OVERLAP 决策产生 `RelationRecord`，不修改 `CanonicalConcept`

---

## 3. Contract 3：Bounded Evidence Contract

### 3.1 冻结语义

**第一批所有声称 bounded 的 LLM path 必须真的 bounded。** 尤其 Stage 2。

### 3.2 各 stage bounded evidence 硬预算（实施时必须严格遵守）

| Stage | 输入形式 | 硬预算（字节 / 字符 / 对数） | 失败检查 |
|---|---|---|---|
| Stage 1 | evidence pack | **≤ 4000 bytes** | `_build_evidence_pack` 必须断言 `len(pack.encode("utf-8")) <= MAX_EVIDENCE_BYTES` |
| Stage 2 | candidate windows | **每个 window ≤ 1500 chars**；每批 **≤ MAX_WINDOWS_PER_LLM_CALL=8** | `_segment_via_llm` 必须断言 `len(window) <= 1500` + `len(windows) <= 8` |
| Stage 3 | HEAD + TAIL + 3 mid samples + Stage 2 signals | **HEAD=2000 + TAIL=2000 + 3×500=1500 + signals** ≈ **5500 bytes** | `_build_completeness_evidence` 必须断言总字节数 |
| Stage 4 | TopicDescriptor per item | **≤ 600 bytes/item** | `_build_descriptors` 必须断言每个 descriptor 字节数 |
| Stage 5 | canonical spans | **span ≤ 1500 bytes + overlap 200 bytes** | `build_canonical_spans` 必须断言 span 大小 |
| Stage 6R | candidate pairs | **≤ 30 pairs/page** | `_retrieve_candidates` 必须 assert len ≤ MAX_CANDIDATES |
| Reconciliation | candidate retrieval | **≤ 20 canonicals/page** | `_retrieve_candidates` 必须 assert len ≤ MAX_CANDIDATES |

### 3.3 反面案例

| 错误做法 | 后果 |
|---|---|
| Stage 1 evidence pack 截断后没断言硬预算 | LLM token overflow 时悄悄发生 |
| Stage 2 `_segment_via_llm(content)` 整篇传入 | 长文 100KB 全进 LLM，context 截断 |
| Stage 3 evidence pack 没中部采样 | 仅 HEAD/TAIL 误判 |
| Stage 4 topic cluster 喂 50 篇文章全文 | token 爆炸 |
| Stage 5 canonical_span 整篇 50KB 文章作一个 span | evidence 太粗无法回指 |
| Stage 6R / Reconciliation 不限制 candidate 数量 | O(N²  全图遍历 |

### 3.4 Stage 2 重点强调

Stage 2 当前实现（`scripts/extract_pilot.py:519`）：

```python
if llm is not None and doc_type == "collection":
    boundaries = await _segment_via_llm(
        content, llm=llm, doc_type=doc_type, project_root=project_root,
    )
```

**这一行就是 bounded evidence 最危险的失败点**：

- `_segment_via_llm` 把整篇 `content` 喂给 LLM
- `article_segmenter.py:85` `content_limit: "12000"` 看似有 budget，但仅约束 prompt 渲染，不约束 content 本身
- 100KB collection → content 100KB → LLM 看不全 → 边界截断

**实施时必须强制**：`_segment_via_llm` 必须接收 **candidate window 列表**（已经 StructuralScanner 切好的小段），不接收整篇 content。

### 3.5 验证

每 stage 都必须有测试：

```python
def test_stage_X_evidence_input_within_budget():
    """硬指标 — evidence input 不超硬预算"""
    # 构造超长 source
    # 验证 Stage X 实际喂给 LLM 的内容 ≤ hard budget
```

### 3.6 不变量

- 每个 `bound_evidence` 函数结尾必须 `assert len(packed.encode("utf-8")) <= MAX_BUDGET_BYTES`
- 任何 `for x in items: ... llm.complete(...)` 的批调用必须在外层有 batch size 上限
- 任何接受 `content: str` 参数的 LLM 调用函数必须明确文档 "content 必须已分段 / 已裁剪"

---

## 4. Contract 4：Persistence Contract

### 4.1 冻结语义

冻结三个核心持久化字段的**唯一语义**：

- **revision_hash**：page rendered content 的稳定 hash，用于幂等 commit
- **page-set reconciliation**：source 更新时旧 page 的命运
- **pipeline_fingerprint**：跨 stage 的 pipeline 版本标识

### 4.2 Revision Hash

#### 4.2.1 计算口径

```python
def _compute_page_revision(page: ConceptPage) -> str:
    content = ""
    content += f"id:{page.id}\n"
    content += f"title:{page.title}\n"
    for k, v in sorted(page.slots.items()):
        content += f"slot:{k}={v}\n"
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]
```

#### 4.2.2 唯一语义

- `revision_hash` 派生 **仅基于** `id + title + sorted(slots)`
- **不包括**：`frontmatter` 中的 `committed_at / commit_id / pipeline_fingerprint`
- **不包括**：`relations` 字段（relations 在 RelationStore 独立管理）
- **不包括**：`needs_review_slots / has_evidence` 等运行时字段

**为什么**：revision_hash 用于 page commit 幂等判定。如果 revision_hash 包含运行时字段（如 `committed_at`），每次 commit 都会变化 → 永远不幂等。

#### 4.2.3 用途

- `_stable_page_id(relative, topic.id)` 不依赖 revision_hash（topic.id 才是 page_id 基础）
- `_atomic_write` 写盘后用 `_hash_file(path) == revision_hash` 校验（防 disk corruption）
- `_source_can_skip` 看 source-level checkpoint，不看 page-level revision_hash（避免双重判定）

### 4.3 Page Set Reconciliation

#### 4.3.1 唯一语义

当 source 重新 ingest（即使 md5 不变、pipeline_fingerprint 也不变，仅 Stage 4 cluster 重新聚类）：

| 情况 | 处理 |
|---|---|
| desired page 与 current page **相同 page_id** + 相同 revision_hash | 不操作（幂等）|
| desired page 与 current page **相同 page_id** + 不同 revision_hash | `update`：覆盖 page 文件 + 更新 page frontmatter |
| desired page **不在** current page | `create`：写新 page |
| current page **不在** desired page | `tombstone`：page → page.md.stale（不物理删除）|

#### 4.3.2 Tombstone 规则

- 旧 page 改为 `<page_id>.md.stale` 后缀（atomic rename）
- 记录 `.index/tombstone_log.jsonl`（含原始路径 / stale 路径 / commit_id / timestamp）
- **永不**物理删除（除非 tombstone_log 累计超过 N 天后 GC 任务删除，第四批实现）

#### 4.3.3 Ownership 检查

- 只能处理 `frontmatter.owner == "v7"` 的 page
- 其他 pipeline / 人工维护的 page 不动
- Stage 7 reconcile 时遇到 non-v7 page → skip + 警告

### 4.4 Pipeline Fingerprint

#### 4.4.1 计算口径

```python
def compute_pipeline_fingerprint(
    *,
    classifier_fp: str = "",
    segmenter_fp: str = "",
    checker_fp: str = "",
    clusterer_fp: str = "",
    generator_fp: str = "",
    template_hashes: dict[str, str] | None = None,
) -> str:
    parts = [
        classifier_fp, segmenter_fp, checker_fp, clusterer_fp, generator_fp,
    ]
    if template_hashes:
        for name in sorted(template_hashes):
            parts.append(f"{name}:{template_hashes[name]}")
    identity = "|".join(parts)
    return "pipe-" + hashlib.sha1(identity.encode()).hexdigest()[:16]
```

#### 4.4.2 唯一语义

- 每个 stage 必须暴露自己的 `*_fingerprint` 字段
- pipeline_fingerprint 是所有 stage fingerprint + template hash 的**组合 hash**
- 格式：`pipe-<16hex>`

#### 4.4.5 用途

- 写入 Wiki page frontmatter：`pipeline_fingerprint: pipe-xxxxxxxx`
- 写入 source checkpoint：`md5` + `pipeline_fingerprint` 双键
- `_source_can_skip` 升级：`if prior.pipeline_fingerprint != current_pipeline_fingerprint: return False`（pipeline 升级 → 重跑）

#### 4.4.6 升级策略

- prompt / template 任何修改 → 对应 stage fingerprint 变化 → pipeline_fingerprint 变化
- source checkpoint 双键不匹配 → 不 skip，重新跑全流程
- **不**做"fingerprint backward compatible"——升级即重跑（用户决策：不管旧 wiki）

### 4.5 三者的耦合关系

```
                ┌─────────────┐
                │ Source md5  │  (内容 hash)
                └──────┬──────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  pipeline_fingerprint         │  (算法 hash)
        │  pipe-<16hex>                  │
        │  = hash(classifier_fp | ...  | │
        │          template_hashes)      │
        └──────────────┬────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  page commit decision         │
        │  (md5 + pipeline_fp)         │
        └──────────────┬────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │  per-page commit              │
        │  revision_hash                │  (page 内容 hash)
        │  = hash(id + title + slots)   │
        └──────────────────────────────┘
```

- **md5**：决定 source 是否被处理过
- **pipeline_fingerprint**：决定 source 处理结果是否仍然有效
- **revision_hash**：决定单个 page 是否需要 update / 创建

### 4.6 反面案例

| 错误做法 | 后果 |
|---|---|
| revision_hash 包含 committed_at | 永远不幂等，page 每次 commit 都重写 |
| revision_hash 包含 relations | relations 异步更新会触发 page 重写（违反 Page 不可变原则）|
| page-set reconcile 不做 ownership 检查 | 误删人工编辑的 page |
| pipeline_fingerprint 用 md5(全部 prompt file contents) | prompt 注释改动就 fingerprint 变化（过度敏感）|
| pipeline_fingerprint 升级时 backward compatible | 旧 pipeline 永远不被重判（与 F4 决策冲突）|
| tombstone 直接物理删除 page | 错误 cluster 决策导致永久知识丢失 |

### 4.7 验证

```python
def test_revision_hash_does_not_include_temporal_fields():
    """revision_hash 仅基于 id/title/slots，不含 committed_at"""
    page_a = ConceptPage(id="x", title="T", slots={"s": "v"}, committed_at=1)
    page_b = ConceptPage(id="x", title="T", slots={"s": "v"}, committed_at=2)
    assert _compute_page_revision(page_a) == _compute_page_revision(page_b)

def test_revision_hash_changes_with_slot_content():
    """slot 内容变化 → revision_hash 变化"""
    page_a = ConceptPage(id="x", title="T", slots={"s": "v1"})
    page_b = ConceptPage(id="x", title="T", slots={"s": "v2"})
    assert _compute_page_revision(page_a) != _compute_page_revision(page_b)

def test_pipeline_fingerprint_changes_with_template_change():
    """template hash 变化 → pipeline_fingerprint 变化"""
    fp1 = compute_pipeline_fingerprint(classifier_fp="c1", template_hashes={"x": "h1"})
    fp2 = compute_pipeline_fingerprint(classifier_fp="c1", template_hashes={"x": "h2"})
    assert fp1 != fp2

def test_page_reconcile_skips_non_v7_pages():
    """page-set reconcile 仅处理 owner=v7 的 page"""
    # 构造 owner=human 的 page
    # 验证 reconcile 不修改 / 不 tombstone
```

---

## 5. Contract Freeze 边界

### 5.1 Contract 适用范围

- 所有 V7 Stage 1-7 + Reconciliation 整改代码
- 所有 v7_extract/ 模块、reconciliation/ 模块、scripts/extract_*.py
- 不影响现有 `src/wiki/` 旧代码（除非显式提到）

### 5.2 Contract 变更规则

任何 Contract 修改必须：

1. 重新过 plan-audit Round 1（漏洞审计）
2. 重新过 plan-audit Round 2（压力测试）
3. 人工 review
4. 更新 Contract Freeze 文档
5. master plan §6 Open risks 同步更新

### 5.3 Contract 与 master plan 的关系

- master plan §3.3 控制面原则描述高层契约
- **Contract Freeze 是实施级唯一解释**（本文档）
- 实施代码不遵守 Contract Freeze → 视为 bug，必须修复

### 5.4 已知 Contract 实施陷阱（提醒）

|陷阱 | 实施时容易踩的坑 |
|---|---|
| Failure Contract | LLM timeout 时 catch 异常 → 仍 return status="INCOMPLETE"（伪装的 technical failure）|
| Canonical Identity Contract | `OVERLAP` 决策自动合并 canonical（避免看起来"成功"）|
| Bounded Evidence Contract | `_build_evidence_pack` 返回 len > 预算时 silently truncate（违反 assert）|
| Persistence Contract | revision_hash 包含 timestamp 字段（看似合理，实际破坏幂幂等）|

---

## 6. Contract Freeze 实施检查清单

每 Task 完成后，对照本 Checklist：

```markdown
### Failure Contract（每 stage）
- [ ] Stage X 有 TECHNICAL_FAILURE status
- [ ] TECHNICAL_FAILURE 不映射到 INSUFFICIENT / UNCERTAIN / CONFLICTING
- [ ] 重试 unit = page / topic 级（不是 source 级）

### Canonical Identity Contract
- [ ] SAME / ALIAS 共享 canonical membership
- [ ] BROADER / NARROWER / OVERLAP 保持独立 canonical（建 relation）
- [ ] UNRESOLVED 不自动合并

### Bounded Evidence Contract（每 stage）
- [ ] Stage X 喂给 LLM 的 input ≤ hard budget bytes
- [ ] `_build_evidence_pack` 结尾 assert len
- [ ] Stage 2 candidate windows ≤ 1500 chars each + ≤ 8 per batch
- [ ] 长文 source 不直接喂整篇

### Persistence Contract
- [ ] revision_hash 仅基于 id/title/sorted(slots)
- [ ] page frontmatter 含 `owner: v7` + `pipeline_fingerprint`
- [ ] source checkpoint 双键（md5 + pipeline_fingerprint）
- [ ] page-set reconcile 处理 owner=v7 only
- [ ] tombstone 改名 + log（不物理删除）
```

---

## 7. Plan 状态更新

master plan §6 状态转换增加：

```
approved → contract-frozen → in-progress
```

新增状态：

| 状态 | 触发 |
|---|---|
| contract-frozen | 本文档已生效 |
| in-progress | ponytail full 启用，Task 1 开始 |

---

## 8. Contract Freeze 总结

| Contract | 核心规则 | 验证测试 |
|---|---|---|
| Failure | technical failure ≠ insufficient / unresolved / conflicting | `test_stage_X_technical_failure_never_mapped_to_insufficient_or_unresolved` |
| Canonical Identity | 仅 SAME/ALIAS 共享 canonical | `test_reconciliation_broader_narrower_overlap_keep_canonical_independent` |
| Bounded Evidence | 所有 LLM input ≤ hard budget（尤其 Stage 2）| `test_stage_X_evidence_input_within_budget` |
| Persistence | revision_hash / page-set / pipeline_fingerprint 唯一语义冻结 | `test_revision_hash_*` + `test_pipeline_fingerprint_*` + `test_page_reconcile_*` |

**这四个 Contract 是 V7 整改在实施层的最终防线。任何代码 PR 不遵守任一 Contract → 立即 reject。**

---

**Contract Freeze 状态：frozen（2026-09-17）**

可进入 ponytail full 编码阶段。