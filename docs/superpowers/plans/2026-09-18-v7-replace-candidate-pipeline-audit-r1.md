# V7 替换候选管线 plan-audit 第一轮：全面漏洞审计

## 审计者立场

独立第三方审计专家。抛弃方案正向思路。**这份方案风险在于"删错文件"和"接口契约漏掉一个调用方"**。下文按 9 个维度找漏洞。

---

## ① 致命缺陷（方案无法落地）

### F1. bridge.py 用 `result.fill_status == FILLED` 判成功，但 `fill_slots` 返回 `ConceptPage | None`，**没有 FillResult 对象**

**位置**: 方案 Task 3 bridge 实现代码
```python
if use_fill_slots_v2:
    result = await fill_slots_v2(topic, ..., llm=llm, project_root=paths.root)
else:
    result = await fill_slots(topic, ..., llm=llm, project_root=paths.root)
if result.fill_status == FILLED:  # ❌ fill_slots 返回 None 时崩溃
    pages.append(result.page)
```

**事实**: `slot_filler.py:184` `fill_slots(...) -> ConceptPage | None`；`fill_slots_v2` 才返回 `FillResult`。两套签名完全不同：
- `fill_slots(topic, source_text, *, llm, item_texts, project_root, max_retries)` — D7 不抛错，None = 失败
- `fill_slots_v2(topic, *, spans_per_slot, topic_items, source_bytes, llm, project_root, topic_label, max_retries)` — 返回 FillResult，None = technical failure

**后果**: 用户选了 v2 路径 → 第一个 topic 失败 → AttributeError on None → 整批 failed → 整个 ingest 死锁

**整改**: 方案必须明确：
- v2 路径：`if page is None: continue`（参见 `extract_pilot.py:488`）
- v3 路径：检查 `result.status == FillStatus.FILLED`（**不是 `result.fill_status`**；field name 错）

**严重性**: ① 致命

---

### F2. bridge 跳过 Stage 2 确定性切分，直接调 `cluster_topics(items=...)`，**但 `items` 来自哪里？**

**位置**: 方案 Task 3 实现伪代码

**事实**:
- `cluster_topics(items: list[dict], *, llm, ...)` 第一参数是 `list[dict]`，**不是 source_text**
- `extract_pilot.py:792 _extract_items(content, relative)` 是确定性的——基于作者署名/标题/编号切分，**无 LLM**
- `extract_pilot.py:262 _wrap_items_as_segmentation_result(items, content, ...)` 把 dict 转成 `SegmentationResult`
- `extract_pilot.py:629 _build_structural_summary(...)` 把 SegmentationResult 转成 dict 喂给 Stage 3
- 没有这些预处理，`cluster_topics` 拿不到 items

**后果**: bridge 实现里如果直接 `cluster_topics(content)` 或 `cluster_topics([{"id": source_path, "text": source_text}])`，会让 Stage 4 LLM 看到全文本作为单一 item，**绕过了 Stage 2 契约**，cluster 质量断崖式下降。

**整改**:
1. 把 `_extract_items` + `_wrap_items_as_segmentation_result` + `_build_structural_summary` 从 `scripts/extract_pilot.py` 抽到 `src/pipeline/v7_extract/segmentation.py`（已存在的模块）
2. 或在 bridge.py 内联实现（接受 import scripts 路径——耦合，**不推荐**）

**严重性**: ① 致命（导致整批 V7 产出质量回归到 v2 之下）

---

### F3. `build_source_stub_page` 的 source 页路径不对——V7 `WikiWriter` 只写 `wiki/concepts/`，不走 `page_path_for`

**位置**: 方案 Task 2 page_adapter.py

**事实**:
- `wiki_writer.py:113`: `self.pages_dir = self.root / "wiki" / "concepts"` （硬编码）
- `page_writer.py:50 page_path_for(type_, slug)` 按 type 分发到 `wiki_sources/wiki_entities/wiki_concepts/wiki_synthesis`
- V7 WikiWriter **完全没调** `page_path_for`，只写 `wiki/concepts/<id>.md`
- 我的 bridge 方案让 `commit_ingest` 接管写盘——如果 source stub 的 `page.type = PageType.SOURCE`，`commit_ingest` 会调用 `write_page` 走 `page_path_for(SOURCE, ...)` → 写到 `wiki/sources/`。**这是对的**。

但我的 plan 里 `build_source_stub_page` 描述"复用 `WikiPage` 构造器，body 填 frontmatter + 摘要 stub" — 如果 WikiPage type=SOURCE 且交给 commit_ingest 写盘，路径 OK；但如果让 V7 WikiWriter 写（这不可能因为 V7 WikiWriter 不接受 source 页），会写到 `wiki/concepts/`，**和 source page 错位**。

**整改**: 方案必须明确 source stub **不走 V7 WikiWriter**，**走 commit_ingest**。bridge 返回的 `pages` 列表里 source stub 在前面（或最后），`commit_ingest` 用 `page.type` 路由。

**严重性**: ① 致命（如果走错，source 页错位导致 lint H2 断链）

---

## ② 重大隐患（容易失败）

### H1. `commit_ingest` 接受 3-tuple `(pages, extras, meta)` 但 bridge 的 meta 与候选路径的 meta schema 不一致

**位置**: Task 3 bridge 实现 vs 现有 `commit_ingest` 签名

**事实**:
- `commit_ingest(paths, source_path, pages, extra_pages, task_id, triage_result, missing_slugs, event, expected_page_hashes, kc_bundle_key, readiness_audit)` — 11 个参数
- 候选路径从 meta 中提取 `triage_result` / `missing_slugs` / `kc_bundle_key` / `readiness_audit`
- V7 bridge 不会产生这些字段

**后果**: commit_ingest 不会崩（字段都允许 None），但 `_meta["triage"]` / `_meta["readiness_audit"]` 等关键审计信息**丢失**。后续 `audit_logger.py` / `readiness_audit.py` 的 record 路径失效。

**整改**: bridge 必须仍产生 `triage_result`（用 V7 自己的 triage）和 `readiness_audit`（用 V7 的 Stage 7 闸门报告）。看 `extract_pilot.py:240-300` 怎么产生 `ExtractionResult.metadata`，照搬。

**严重性**: ② 重大

---

### H2. fill_slots_v2 默认路径成本爆炸（**用户已知**但 plan 未量化）

**位置**: Task 3 `use_fill_slots_v2: bool = True` 默认

**事实**:
- 用户问"默认 fill_slots_v2 (v3 完整路径)" = 选 fill_slots_v2
- `.memory/feedback-v7-agl-design-tree-2026-09-18.md:175-177` 已记录：v2 路径 1 次 LLM call，v3 路径 8+1 次 per-slot
- 70 KB 文档 = 1 chunk > 16k → 拆 2 chunk → Stage 4 产多个 topic → 每 topic 9 次 LLM
- 实测 mini 实数：smoke 单源 37.69s 1 次 v2 call；如果是 v3 + 2 topics，37.69s × 18 = **678s (11 min) per source**
- 4918 文件 = 4918 × 11 min = **单 CPU 串行 38 天**，并行 6 槽 = **6 天**

**后果**: 用户说"默认 v3 路径"是 v3 完整能力选择。但 plan 没说默认 v3 的财务/时间成本，没说怎么 fallback。当用户在 22k 文档 + 3 topics 上跑 v3，预计 270s/源；如果 LLM 限速 3 req/min（MiniMax），可能 30 min/源；运行批量时用户会觉得 hang。

**整改**: 
- 方案加 cost budget 兜底：`RUFLO_V7_BUDGET_USD` 环境变量，超预算 fallback v2
- 或保留默认 v2（更稳），让用户显式 opt-in v3

**严重性**: ② 重大

---

### H3. 删除 `unified_generate` 会触发 4 个 `test_unified_generate_*` 测试 import 错误；方案说"删除测试"但没说在哪个 commit

**位置**: Task 6

**事实**:
- `tests/test_pipeline/test_pipeline.py:262, 298, 321, 360` 4 个 `test_unified_generate_*`
- `tests/test_pipeline/test_ingest_generate_commit_split.py:923, 937, 940` legacy monkey-patch
- `tests/test_pipeline/test_ingest_kc_mainline.py:78, 79` candidate monkey-patch
- `tests/test_e2e/test_ingest_happy_path.py:102-104, 70` legacy e2e
- `tests/test_pipeline/test_chunked_analysis.py:8, 66, 81, 97, 104` 5 个 _merge_analysis_results 测试

**后果**: 直接 `git commit` Task 5 → `pytest tests/` 9+ 个测试 import 失败。CI 红。不会"悄悄通过"。但 Task 6 计划覆盖了，**但顺序错了**：Task 5 删代码 + Task 6 改测试，**中间会有失败 commit**。应该 Task 5 和 Task 6 合并到同一 commit，或者明确"中间 commit 不要求测试全绿"。

**整改**: Task 5 和 Task 6 合并为 Task 5a（删代码 + 改测试同步完成，单一 commit）

**严重性**: ② 重大

---

### H4. ingest.py 候选路径里 `from src.kc.compiler.evidence import validate_evidence` 的 KC 集成，被 V7 替换后 KC 审计路径不写

**位置**: ingest.py:797-861

**事实**:
- 候选路径在 reject 路径把 candidate 写到 `.index/quarantine/kb-*/candidate.json` + `candidate.judgment.json`
- V7 失败走 `.index/reviews_queue.json`（enqueue_failure）——**完全不同路径**
- V7 没有 quarantine 概念
- 现有 web UI / CLI 可能假设 `.index/quarantine/` 有 rejected candidate 用于复审

**后果**:
1. 重跑 `kb-20260918152026-4409dd89` 70KB 任务时，V7 失败 → 写 reviews_queue，**不写 quarantine**
2. 任何期望看到 quarantine 文件的工具会看不到
3. `QuarantineStore` 模块整个变成 dead code

**整改**: 明确"quarantine 路径消失"是设计的 vs bug。建议在 bridge 失败时**同时**写到 reviews_queue 和 quarantine（向后兼容）；或文档说明这是 breaking change。

**严重性**: ② 重大

---

### H5. ingest.py:1316+ `reconcile.collect_missing_slugs` 接收的 `pages` 列表里有"旧 candidate 写入的 source 页"——V7 bridge 不写 source 页，reconcile 数据源变形

**位置**: ingest.py:1292-1300

**事实**:
- 候选路径会同时产出 1 个 source 页 + N 个 concept 页
- V7 bridge 也产 source stub + N concept 页
- `collect_missing_slugs` 扫 pages 找 `[[wikilink]]` → 算反向引用
- source stub 我设计成"无 wikilink"，但概念页（V7 写的）会用 `[[other-page]]` → reconcile 工作正常
- **风险**：如果 source stub 设计成"指向第一个 concept 页"（用 `[[concept-id]]`），需要确保该 ID 存在

**后果**: reconcile 漏报 / 误报。`wiki-quality` lint 看不到缺失反向边。

**整改**: source stub 不写 wikilinks，只写来源元数据 + 摘要 + 关键观点（空数组）。Bridge 在 `meta["source_page_id"]` 返回 stub ID 让前端引用。

**严重性**: ② 重大

---

### H6. `commit_ingest` 的 `commit_ingest(..., readiness_audit=None)` 默认行为未知——V7 不生产 readiness_audit dict，可能导致 readiness 审计字段缺失

**位置**: ingest.py:1632-1648

**事实**:
- `commit_ingest` 接受 `readiness_audit: dict | None = None`，None 时跳过 `write_readiness_record`
- 候选路径总是通过 `_pilot_audit` dict 传 audit
- V7 没有 readiness gate（它的 4-gate 是 stage7 的闸门，不是 readiness）

**后果**: V7 ingest 后 readiness_audit.json 不写。Web UI / CLI `health --project` H5 检查可能受影响。

**整改**: bridge 也构造 readiness_audit dict（用 V7 Stage 7 report 转译）

**严重性**: ② 重大

---

### H7. `_page_path(page_id)` 是 V7 私有的——直接传 source stub 进 V7 `commit_and_index` 会失败

**位置**: wiki_writer.py:688-698

**事实**:
- V7 `_page_path(page_id)` 检查 page_id 不能含 `/` `\\` `..`
- 我的 `build_source_stub_page` 的 slug 需要符合规范
- 但 source slug 在 ingest.py 现有路径里是 `f"{_norm_stem_for_slug}-{_path_hash_for_slug}"`，可能含中文 + 8 字符 hash
- V7 的 page_id 来自 ConceptPage.id，**V7 自己的 stable_page_id 逻辑**：`_stable_page_id(relative, topic.id)`

**后果**: source stub slug 用 ingest.py 自己的格式，但 V7 不接受这种 slug 通过 `commit_and_index`。V7 用 `commit_and_index` 写 concept，但 source stub 由 commit_ingest 写盘——**两边 slug 生成逻辑不同** → link 不到。

**整改**: bridge 不调用 V7 `commit_and_index` 写 source stub。**Source stub 完全走 commit_ingest 写盘链路**。Bridge 只把 V7 ConceptPage（concept）通过 V7 WikiWriter 写。Source stub 在 commit_ingest 阶段追加。

**严重性**: ② 重大

---

### H8. `extract_pilot.py` 的 `_extract_items` 是脚本级私有函数，没有正式成为 `v7_extract.segmentation` 公共 API；bridge 调用它会破坏 `scripts/` 模块边界

**位置**: Task 3 + scripts/extract_pilot.py:792

**事实**:
- `_extract_items` 是 `_` 开头（私有）
- 在 scripts/ 下，**不能被 src/ 下的代码 import**（违反分层）
- v7_extract/segmentation.py 已有 `SegmentationResult` dataclass，但没有对应的 deterministic splitter 实现

**后果**: bridge 引入对 scripts 的依赖 → 循环依赖 → ImportError

**整改**: 把 `_extract_items` / `_wrap_items_as_segmentation_result` / `_build_structural_summary` 从 `scripts/extract_pilot.py` 抽出，移到 `src/pipeline/v7_extract/segmentation.py`（**新增 80 行 deterministic splitter**）。`scripts/extract_pilot.py` 改为 import 这些函数（向后兼容）。

**严重性**: ② 重大

---

### H9. `_analyze` / `_analyze_chunked` 在 `analyzer.py` 中保留作为 public exports，但 ingest.py 不再调它们——dead code 残留

**位置**: Task 5

**事实**:
- 候选路径删除后 `_analyze` / `_analyze_chunked` 无调用方
- `analyzer.py:analyze` 也成 dead code（唯一调用方是候选路径）
- AGL 训练用 `BaseURLLLMClient` 不走 `analyzer.analyze`
- `page_synthesizer.py:fill_slots_v2` 不依赖 `analyzer.analyze`

**后果**: 删不删都行，**但 Task 5 没说要删 `analyze`**。残留死代码让下一步重构更混乱。

**整改**: Task 5 加一行："删除 `src/pipeline/analyzer.py` 整文件（除 `analyze` 顶层函数）。`analyze` 实际未被任何生产路径调用。"

**严重性**: ② 重大（如果保留，3 个月后还得回来处理）

---

## ③ 优化疏漏

### O1. `from src.pipeline.ingest import _merge_candidate_chunks` 在 test 文件直接 import（test_ingest_kc_mainline.py:10）——删后会立即 ImportError

**位置**: tests/test_pipeline/test_ingest_kc_mainline.py:10

**整改**: 测试 import 改成 `from src.pipeline.ingest import run_ingest`，但仍需要 `FakeLLMClient`-style stub 把 bridge 替换掉。

### O2. `from src.pipeline.ingest import _merge_analysis_results` 在 test_pipeline/test_chunked_analysis.py:8

**整改**: 整测试文件删除（`_merge_analysis_results` 是 chunked 路径私有，删函数时一并删测试）。

### O3. `tests/test_pipeline/test_ingest_generate_commit_split.py:39` 设 `RUFLO_PIPELINE_MODE=legacy`，但 plan 删除 legacy

**整改**: 删这行；保留 commit_ingest 测试块（line 833, 881 candidate 设的也删，因为 candidate mode 不存在）。

### O4. bridge 返回 3-tuple `(pages, extras, meta)`，但 plan 没明说 `extras` 该是什么

**事实**: `commit_ingest` 把 `extra_pages` 当作"反向边写入"使用。V7 阶段没有 extras 概念。

**整改**: bridge 返回 `(pages, [], meta)` —— `extras` 始终为空。Document this.

### O5. V7 WikiWriter 的 `commit_and_index` 写盘到 `wiki/concepts/<id>.md`——但 candidate 路径的 concept 写到 `wiki/concepts/<id>.md`（同样）。混合格局时 V7 页和候选页共存，**没有冲突**

**事实**: V7 WikiWriter 不验证 `id` 是否已存在——重复 id 会**覆盖**。如果同一个 source 在不同次运行中产出了同一个 topic id（md5 一致），第二次会覆盖第一次，**但 revision_hash 不同**会让 lint 误报？

**整改**: 验证 V7 WikiWriter 的 idempotency smoke report 是否覆盖此情形（`.memory/feedback-v7-control-plane-real-provider-smoke-2026-09-15.md:41` 已经测了 apply2 = skipped，OK）。

### O6. `_split_source_chunks` 是 chunked legacy 路径私有，被 `_analyze_chunked` 调用，被 test 直接 import

**事实**: ingest.py:1507-1536 是 `_split_source_chunks`，test_ingest_kc_mainline 不直接 import 但 test_chunked_analysis 通过 `_merge_analysis_results` 间接用。

**整改**: Task 5 同步删除 `_split_source_chunks`。

### O7. plan 没说 ADR-0014 该引用哪些前序决策（ADR-0007 candidate ownership，plan 2026-09-15 control plane）

**事实**: `docs/adr/0007-knowledge-candidate-ownership.md` 已存在 `KnowledgeCandidate` 概念。V7 替换后 `KnowledgeCandidate` 仍是 V7 内部的 ReviewResult 投影对象。

**整改**: ADR-0014 在 "前序决策" 引用 ADR-0007 + plan 2026-09-15。

### O8. `README.md` 没说在哪里，但 plan 提到"更新"

**事实**: AGENTS.md / CLAUDE.md / README.md 都有"ingest 流程"段；plan 只说 README.md。

**整改**: plan 加 AGENTS.md + CLAUDE.md 的同步更新。

### O9. plan 没列回归测试范围——只说"V7 已通过 30 个测试"。但 V7 测试用的 `extract_pilot.py` 路径，不是 `bridge.py` 路径

**事实**: 30 个 `test_v7_extract_*.py` 测 Stage 1-7 单步；不测 Stage 1→7 串联（除 gold_corpus）。

**整改**: Task 3 测试要测**串联**（bridge 端到端）+ `tests/test_pipeline/test_v7_extract_bridge.py` 新增。

### O10. plan 没明说 `_extracted_text` / `_result.canonical_text` 等 sanitized input 怎么来

**事实**: ingest.py:610-619 `_result = preprocess_source(...)` 包含 sanitization（chrome lines / Feishu H1 / meta lines 过滤）。

**整改**: bridge 必须调 `preprocess_source` 然后用 `_result.prompt_text` 或 `_result.canonical_text` 喂 V7 stages（不要用 raw source_text，否则 sanitizer 输出被忽略）。

---

## 信息盲区（需要查清才能落地）

### B1. `commit_ingest` 是否在写盘后**做 reconciliation / lineage / audit 日志**？V7 是否能保留？

**事实**: 读 commit_ingest 1742 行有 `_prepare_lineage` + `_lineage.prepare_wiki_commits`，**lineage 总是走 commit_ingest 链路**。V7 替代 candidate 不影响 lineage。✓

### B2. V7 WikiWriter 是否处理 page.id 的 `card_<13hex>_<8hex>_<slug>` 命名？

**事实**: V7 自己生成 stable page_id（`_stable_page_id`）。commit_ingest 接受的 page.id 是 WikiPage 的 id，没有格式约束。

**整改**: 让 bridge 用 V7 生成的 id，不强制 ingest.py 命名规则。**冲突**：ingest.py line 707 `_source_slug_for_map = f"{_norm_stem_for_slug}-{_path_hash_for_slug}"` 用于 `_source_slug_map` 喂 Generator，V7 bridge 不需要这个。

### B3. `KcReview` / `CandidatePromoter` 删除后，`.index/kc/bundles/` 还有谁写？

**事实**: `kc/compiler/compile.py:compile_claim` 调 `validate_evidence`，候选路径专用。删除 candidate 后 kc/compiler 不再被调用——`book build` 链路的 KC 数据源枯竭。

**整改**: book build 不在本次 plan 范围。但应在 ADR-0014 明确"V7 bridge 不写 KC bundles；book build 路径 deprecated 直到 V7 写 KC"。

### B4. `quarantine.py` 整个文件是否还有调用方？

**事实**: `quarantine.py:25 put_candidate` 只在 ingest.py:778-783 调用。删除 candidate 后 quarantine 整文件 dead code。

**整改**: Task 5 同步删除 `src/quality/quarantine.py`（除了被 review queue 复用的部分——检查）。

### B5. V7 的 `commit_and_index` 写盘是否走 `commit_ingest` 的 `safe_write`？

**事实**: V7 `_atomic_write(path, content)` (line 700-705) 写本地文件，`safe_write` 在 `commit_ingest` 链路用。**两套写盘逻辑并存**——V7 WikiWriter 直接 `path.write_text` 然后 `path.replace`，不走 `AtomicContext`。

**后果**: V7 写盘不参与 commit_ingest 的 AtomicContext 批写——中途崩溃可能产生 partial wiki。

**整改**: 这是 V7 已知设计。方案不修 V7 写盘逻辑，但应在 bridge 里把 V7 写盘也包在 `AtomicContext` 里（在 `commit_ingest` 之前 commit）。

### B6. `test_v7_extract_*` 30 个测试用的 FakeLLMClient 是不是能被 bridge 复用？

**事实**: bridge 需要 FakeLLMClient 测试，但当前 `extract_pilot.py:146` 用 `FakeLLMClient` 注入。bridge 应该接受一个 `llm: LLMClient` 参数（与 stages 一致），让测试容易。

**整改**: bridge 签名 `run_v7_ingest(..., llm: LLMClient, ...)` 暴露给测试。

---

## 缺陷分级汇总

| 等级 | 数量 | 编号 |
| --- | --- | --- |
| ① 致命 | 3 | F1, F2, F3 |
| ② 重大 | 9 | H1, H2, H3, H4, H5, H6, H7, H8, H9 |
| ③ 优化 | 10 | O1-O10 |
| 信息盲区 | 6 | B1-B6 |

**致命+重大共 12 项**，方案需要全部整改。
