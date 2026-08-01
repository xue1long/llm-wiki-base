# 新文档门禁 NDG + 摄取优化 — 实施计划（2026-08-01）

> **依据**：
> - 2026-08-01 第三方审计（隐含假设树 / 门禁 V1-V12 对抗验证）——审计结论见会话记录；
> - `2026-08-01-novel-wiki-ingest-execution.md` Phase 3.1 / Phase 4.2（本计划**修正其中两条过时假设**）；
> - `docs/guides/novel-wiki-ingest-spec.md`（规范 v2，验收目标 §十）。
>
> **修正声明**（相对既有执行计划）：
> 1. 执行计划 Phase 3.1 称"LINT-RAW-PASTE 必须豁免 source 页（main_content 槽本就是完整正文）"——**已过时**。6e1348d/4edda47 后 source 模板无 main_content 槽，source 页正文应为蒸馏形态。本计划将 RAW-PASTE 改为 **source 页同样检查**（全文段标题 + 长 run），并保留对"长摘要"的容错（阈值标定）。
> 2. 执行计划 Phase 4.2 称门禁 = `lint + tags validate + fields validate`——升级为**新文档门禁 NDG**（P1-P7，写盘前拦截）。
>
> **再校验修正（2026-08-01 第二遍）**：
> 1. **V13【致命】**：原「generate 全部 → NDG → commit 全部」破坏批内可见性（`_collect_existing_wiki` 扫磁盘，file B 看不到 file A 未提交页 → 批内交叉引用 stub 爆炸 + 同 slug 静默覆盖）。→ 新增**批级 reconcile** 步骤（见 Phase 4.2），并用 V13 原则修订 Phase 4/5。
> 2. **V14【重大】**：Phase 1.5 标定原依赖"临时 staging 空 wiki" → 语境失真（`Existing wiki index=(empty)`）。→ Phase 0 移到 Phase 1 之后，用 `generate_ingest(真实 paths, dry)` 标定。
> 3. **V15【重大】**：P6 只 flag 不 resolve 跨文件同 slug 重复实体 → 批级 reconcile 规则②（保留 grade 高者 + 合并 relations + merged 报告）。
> 4. **V16【中】**：P4b 的 UGC 判定需 raw 文件头 → phase4_batch 读 raw 头传 `is_ugc_source` 标志；无标记 UGC 文件文档化为已知残留。
> 5. **V17【中】**：并发(5.2) × 批内可见性 → 并发 generate + 批级 reconcile 吸收（reconcile 确定性、顺序无关）。
> 6. **V18【小】**：Phase 2 后存量 7 个带转录/长摘要 source 页被新开检标记 → `cli lint` 计数上升，提交信息注明为预期行为。
>
> 遵守 CLAUDE.md：TDD-per-task + 一次一 commit + 每任务 reviewer。**本计划立项时不写代码。**

## 决策记录

### D1 — UGC 源判定 = 选项 A（细化版）
- **规则**：输入 raw 文件头部（前 4000 字符）命中 UGC 载体标记
  `feishu.cn | mp.weixin.qq.com | 飞书云文档 | 公众号 | 论坛 | 知乎 | 豆瓣 | 简书 | QQ群`
  → 该文件派生的**所有页**必须同时携带 `素材/ugc` + `可信度/ugc`。
- **理由**：novel-wiki 语料源几乎全为飞书托管的公众号/论坛 UGC 内容；判定为确定性（读文件头），不依赖 LLM 输出；覆盖 pilot 实测的 `ugc_tags=0` 失败形态（此前 LINT-UGC-CRED 只查一致性、抓不到"完全没打标"）。
- **白名单扩展**：未来引入书籍/官方源时，检测器加豁免——源含 `book/官方/出版社` 标记 → 要求 `素材/book` + `可信度/book`（本期不实现，仅预留）。
- **默认行为**：本语料下 ≈ 全部新页被强制要求双 UGC 标（与语料真实属性一致）。

### D2 — 门禁时机 = 先校验后写盘（generate/commit 分离）
- 修复审计 V1（写后校验，污染已入库）。架构见 Phase 1。

### D3 — 阈值不硬编码，由 Phase 0 标定
- 修复审计 V4。`T_source` / `T_non` 由新文档 dry-run 分布决定，写死后仅能经标定流程修订。

### D4 — 门禁收窄为批级结构检查（P5-P7），页级质量归 lint（2026-08-01 落地）
- **决策**：`run_ndg_gate` 只强制 P5（输入↔source 配对）、P6（slug 跨 type 冲突）、P7（extra_pages 覆盖保护）三项**批级结构检查**；P1（可读性）、P2（RAW-PASTE）、P3（缺 sources）、P4（UGC 缺标）**从门禁移除**，由 `cli lint`（`lint_wiki`）发现后修复。
- **理由**：页级质量问题是"内容质量"而非"写盘安全"。向量化是独立 archive 阶段（`batch_build --only archive`，手动触发、不随摄取自动跑），坏页在 lint 修复前不会被向量化——只要遵守"archive 在 lint 修复后执行"的顺序约束，向量库零污染。
- **实现**：P1/P3/P4 判定已收敛到 lint 单一事实源（`_readability_violation`/`_missing_sources`/`_missing_ugc_cred`），P2 复用 lint 的 `_long_raw_text_run`/`_has_fulltext_section`。`check_page` 保留为 P1-P4 的独立 API；`run_ndg_gate` 不再调用它。phase4_batch / batch_gate_check 均走 reconcile → run_ndg_gate。
- **影响**：门禁 FAIL 不再保证"坏页零写盘"——只保证"结构性冲突零写盘"。页级质量问题由 lint 事后清理。

---

## 验收总目标（NDG 生效后）

- 每批 NDG PASS 才写盘；FAIL 时磁盘**零写入**（可验证：FAIL 后 wiki 目录 mtime 无变化）。
- 新页：全文段标题 0 命中、`_long_raw_text_run ≤ T` 100%、P5 输入↔source 配对 100%、P6 slug 零冲突。
- 全部 NDG 判定逻辑收敛到 `src/wiki/features/lint.py` 单一事实源（gate 只消费导出符号）。
- backlog：829 可摄取 / 46 批（已重写生成器落地）。

---

## 执行顺序（依赖硬约束）

```
Phase 1   run_ingest 拆 generate/commit（前置①：门禁"写前"窗口；标定也依赖它）
Phase 1.5 NDG 标定预演（依赖 Phase 1 generate_ingest，真实语境 dry-run → 锁阈值）
Phase 2   lint.py 单一事实源（_has_fulltext_section / 阈值导出）
Phase 3  NDG 实现（batch_gate_check 重写，P1-P7 + P4b）
Phase 4  phase4_batch 接入 generate→reconcile→NDG→commit + batch_build_state
Phase 5  UGC(A) + B5 并发 + B6 覆盖保护
Phase 6  批 1-46 放行
```

> **V13 修订后的批执行流**（Phase 4/5 统一采用）：
> `generate 全部（可并发）→ 批级 reconcile → NDG P1-P7 → PASS 才 commit 全部`
> reconcile 在 gate 前、commit 前，见 Phase 4.2。

---

## Phase 1.5 — NDG 标定预演（纯测量，无生产写盘）

> **V14 修订**：本 Phase 硬依赖 Phase 1 的 `generate_ingest`（**必须做完 Phase 1 才能跑**）。若在 Phase 1 之前执行会标定在空 wiki 语境下（`Existing wiki index=(empty)`），阈值失真。

### 0.1 新文档采样生成
- **Files**：`scripts/ndg_calibrate.py`（新建；种子可复现）
- **Implementation guidance**：
  1. 从新 manifest `.index/reingest_backlog.json` 的 `ingestible` 抽 25 文件（`--seed` 默认固定）；
  2. 每文件 `generate_ingest(paths=真实, dry)` ——读真实 existing-wiki index 进提示词、**不写盘**（依赖 Phase 1）；若 Phase 1 尚未拆分，退路为写临时 staging `WikiPaths`（接受语境近似，标定报告中注明）；
  3. 收集每页：type、body chars、`_long_raw_text_run`、全文段标题命中、`sources` 非空、tags、slug。
- **验收**：输出 `_long_raw_text_run` 直方图 + 各 type 的 p90/p95/p99 + Top-10 最长 run 预览。

### 0.2 阈值标定 + 检查项验证
- **Implementation guidance**：
  1. 人工过目 Top-10 长 run：判「合法长摘要」（放行）还是「污染」（拦截）；
  2. `T_source` / `T_non` = 合法页 p99（取整到 50 的倍数），写入 `.index/quality_settings.json`（`raw_paste: {source_threshold, non_source_threshold}`）；
  3. 验证 P5 配对 100%、P6 零冲突、P2 样本 0 误伤、全文段标题 0 命中。
- **验收**：标定报告存档（`scripts/_ndg_calibrate_report.txt`）；阈值有据可查、非拍脑袋。

---

## Phase 1 — run_ingest 拆 generate/commit

### 1.1 generate_ingest / commit_ingest 拆分
- **Files**：`src/pipeline/ingest.py`
- **Tests**：`tests/test_pipeline/`（新增/扩展拆分后语义不变的单测）
- **Implementation guidance**：
  1. `generate_ingest(paths, source_path, source_text, provider, folder_context, task_id) -> (pages, extra_pages, meta)`：现有 `run_ingest` 中 sanitize → unified/two-step → stubs → reverse relations（**只读**既有页）→ quality_gate 过滤的全部逻辑，**不含任何写盘**；
  2. `commit_ingest(paths, source_path, pages, extra_pages, task_id)`：write_page × N + append_to_index + log_event（现有 AtomicContext 块）；
  3. `run_ingest = generate_ingest + commit_ingest`（对外签名、行为不变，旧调用方/生产/测试不受影响）。
- **验收**：`tests/test_pipeline/` 全绿；`run_ingest` 行为与拆分前一致（对比一次摄取前后 wiki mtime）。
- **Commit**：`refactor(pipeline): run_ingest 拆 generate/commit，门禁前置的前提`

---

## Phase 2 — lint.py 单一事实源

### 2.1 全文段检测器 + 阈值导出
- **Files**：`src/wiki/features/lint.py`、`tests/test_wiki/test_lint.py`
- **Implementation guidance**：
  1. `_FULLTEXT_SECTION_RE`（`^#{1,6}\s*(正文内容|转录内容|原文|全文|完整文本)`）+ `_has_fulltext_section(body)`——**围栏感知**（复用 `_long_raw_text_run` 的 `in_fence` 状态，避免代码块内标题误报）；
  2. `T_source` / `T_non` 从 `.index/quality_settings.json` 读取（Phase 0 写入），缺省回落常量；
  3. **LINT-RAW-PASTE 改为 source 同样检查**（修正旧假设）：source 页命中全文段标题 **或** run > T_source → 违规；非 source run > T_non → 违规。
- **验收**：`test_lint.py` 更新旧"source 豁免"断言为"source 带全文段 → 违规 / source 蒸馏 → 放行"；新增围栏、变体标题用例。
- **V18 注**：本 Phase 后存量 7 个带转录/长摘要 source 页会被 `cli lint` 新标记为 RAW-PASTE——**预期行为**（遗留债挂账不动），提交信息注明，避免被误判为回归。
- **Commit**：`feat(lint): RAW-PASTE 覆盖 source 页（全文段标题 + 阈值），单一事实源`

## Phase 3 — NDG 实现

### 3.1 batch_gate_check 重写为 NDG 消费者
- **Files**：`scripts/batch_gate_check.py`（重写）、`scripts/ndg_calibrate.py`（Phase 0 复用其 check 函数）
- **Tests**：新增 `tests/test_wiki/test_ndg_gate.py`（合成样本断言 P1-P7 各违规）
- **Implementation guidance**：`check_page` 只消费 lint 导出符号（`_has_fulltext_section`、`_long_raw_text_run`、阈值），不各自实现：
  - P1 READABILITY；P2 RAW-PASTE（source/非source 双阈值）；P3 MISSING-SOURCES；P4 UGC-CRED；
  - P4b（D1，**V16 修订**）：**phase4_batch 读输入 raw 文件头（前 4000 字符）**，命中 UGC 载体标记（feishu.cn / mp.weixin.qq.com / 飞书云文档 / 公众号 / 论坛 / 知乎 / 豆瓣 / 简书 / QQ群）→ 该文件派生页强制双 UGC 标；`is_ugc_source` 标志由 batch runner 传入 NDG（gate 不自己读 raw）。**已知残留**：未命中载体标记的真实 UGC 文件会漏标——文档化，不伪装覆盖。
  - 批级 P5 输入↔source 配对、P6 slug 唯一（跨 type 冲突 → 拒批）、P7 extra_pages 轻查。
- **验收**：合成样本各违规命中；真样本（Phase 0 的 25 文件）0 假阳性。
- **Commit**：`feat(scripts): NDG 门禁 P1-P7 + UGC(A) 强制打标`

## Phase 4 — 批执行接入

### 4.1 phase4_batch 改 generate→reconcile→NDG→commit
- **Files**：`scripts/phase4_batch.py`
- **Implementation guidance**（**V13 修订**）：批流改为
  `generate 全部（可并发）→ 批级 reconcile（4.2）→ NDG 全批校验 → PASS 才 commit 全部 → 记录 batch_build_state`；
  FAIL 整批拒写（回滚粒度=批，天然由"未写盘"实现）；文件级失败单列 `retry_batch`，重试 1 次后再 FAIL 即批次拦截并告警。
- **验收**：① 制造一个必 FAIL 的输入（含 `## 转录内容` 的假源）→ 批 FAIL 且 wiki mtime 无变化；② 构造批内 A 引用 B 将产出的实体 → reconcile 后无 stub、无同 slug 双页（**V13 回归测试**）。
- **Commit**：`feat(scripts): phase4_batch 接入 generate→reconcile→NDG→commit，FAIL 零写盘`

### 4.2 批级 reconcile（新增，V13/V15/V17 核心）
- **Files**：`src/wiki/features/batch_reconcile.py`（新建；纯确定性，无 LLM）
- **Implementation guidance**——在 gate 前、commit 前，对批内全部 `pages ∪ extra` 执行：
  1. **stub 压制**：`processing_depth=stub` 且 slug 命中批内非 stub 页 → 丢弃 stub（防批内交叉引用的 stub 爆炸）；
  2. **同 slug 同 type 合并**（**V15**）：批内两个文件提取同一实体 → 保留 `grade` 高者（同 grade 保留先到者），把另一页的 `relations`/反向边合并进保留页，删除被合并页，记入 merged 报告（确定性规则，不调 LLM）；
  3. **同 slug 跨 type**：P6 判定 → 拒批（不自动选边）。
  reconcile 产物是 gate 与 commit 的唯一输入。
- **验收**：构造同实体两文件批 → reconcile 后单页、relations 合并、merged 报告记录；跨 type 冲突 → P6 拒批。
- **Commit**：`feat(wiki): 批级 reconcile——stub 压制 + 同 slug 实体合并（V13/V15）`

## Phase 5 — UGC(A) + 并发 + 覆盖保护

### 5.1 UGC(A) 载体判定落地
- **Files**：`src/wiki/features/lint.py`（P4b 判定函数，供 NDG 消费）
- **Implementation guidance**：见 D1。book 类豁免留 TODO（本期不实现）。
- **验收**：对含 feishu URL 头的输入，派生页缺 UGC 标 → P4b 命中。

### 5.2 并发 + 断点续跑（B5，V17 修订）
- **Files**：`scripts/phase4_batch.py`
- **Implementation guidance**：generate 阶段并发 3（LLM 密集 + 只读，安全）；**并发下 A/B 互相看不到批内页 → 由批级 reconcile（4.2）吸收**（reconcile 确定性、与并发完成顺序无关）；commit 阶段串行；批前读/批后写 `.index/batch_build_state.json`，支持中断续跑。
- **验收**：中断批 N → 重跑跳过已完成文件；并发批的 reconcile 结果与串行批一致（V17 回归测试）。

### 5.3 覆盖保护（B6）
- **Files**：`scripts/phase4_batch.py`
- **Implementation guidance**：commit 前将批内 `(slug,type)` 与既有 wiki 求交集：命中非 stub 页 → 告警 + 需 `--allow-overwrite`；命中 stub 页 → 放行（Fix E 的 stub→实页升级是设计行为）。
- **验收**：同 slug 冲突页被拦截/告警，stub 升级不受阻。

## Phase 6 — 批 1-46 放行

- 前置：Phase 0-5 全绿；`tests/test_pipeline/`、`tests/test_wiki/`、`tests/test_lib/` 全过。
- 逐批 `phase4_batch.py --batch N`；每批 NDG PASS 才落盘；成本护栏：单批 >60min 告警、累计超预算即停。
- **验收**：46 批全部 NDG PASS；tap rate 达标；漂移基线（`_baseline.py`）重跑新增页漂移=0。

---

## 遗留（不进本计划范围，挂账）

- 旧 wiki 数据：7 个含转录/长摘要 source 页、36 个 synthesis 长文页、59 个漂移 source 页——独立 cleanup 任务，**不动**。
- UGC 白名单 book 豁免（D1 预留）。
