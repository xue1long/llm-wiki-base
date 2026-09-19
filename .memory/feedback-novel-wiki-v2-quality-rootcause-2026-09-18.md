# novel-wiki-v2 摄取问题根因调研（架构责任 vs 提示词责任）

调研对象：70 KB 音频转录摄取任务 `kb-20260918152026-4409dd89` 中暴露的 7 个问题。
调研方法：读完整代码路径（`text_preprocessing/api.py` → `analyzer.py` → `ingest.py` → `kc/api.py` + `kc/compiler/evidence.py` + `kc/mainline.py`），不只看代码注释，按实际执行流追踪。

## 总判断

**4 个问题属架构责任，3 个属提示词责任，1 个是模型能力局限**。

架构问题都集中在 **block_id ID 空间不一致**（prompt chunked ID vs canonical ID）和 **失败模式不分类**。这两个是系统级接口契约问题，提示词改一万遍也没用——LLM 看到什么 ID 就用什么 ID，看到的是 chunked ID。提示词问题都集中在 **claim 抽取的语义范围**（是否要案例、是否要去重、粒度多细）。

## 问题逐项根因

### 问题 #1：block_id `#sub-N` 不识别（21/24 evidence 落盘失败）— **架构**

**架构层级**：契约错配（ID schema mismatch），与 LLM 无关。

**完整执行链**：

1. `preprocess_source()` 生成 **canonical blocks**（5 个），按 `\n\n` 切，ID = `sha256(doc_id, ord, content)` 形式（见 `normalize.py:54-63`）。22k 整段是 `block_ab8a09eb78aedda04cbb8a5b`。

2. `chunk_prompt_blocks(..., max_chars=16000)` 把超大 canonical block 拆成 **chunked sub-blocks**，ID = `<parent.block_id>#sub-<N>`（见 `text_preprocessing/api.py:132`）。22k 整段拆成 `block_...#sub-0` (16k) 和 `block_...#sub-1` (10k)。

3. Analyzer prompt 构造时（`analyzer.py:574-579`）走 `else` 分支，把 **chunked blocks** 序列化为 `[source_id=... block_id=block_xxx#sub-N ordinal=...]` 头部注入 source text，让 LLM 当成"identity-bearing block registry"。

4. LLM 忠实复制——22 条 evidence 全用 `block_xxx#sub-0` / `#sub-1`。

5. **`validate_evidence` (strict) 在 `ingest.py:797-802`** 跑 `for ev in candidate.evidence: validate_evidence(document, ev)`，查 `document.blocks`（canonical，无 `#sub-N`）→ 22 条命中"evidence does not match a document block" → 整体 reject。

6. 紧接着的 **`CandidateReviewer.review()` (soft) 在 `ingest.py:803-808`** 本来有软化逻辑（`mainline.py:96-108` 抓 `ValueError` 转 VALIDATED），但因为前面 hard-reject 已经 raise 出去，根本没机会执行。

**代码作者的认知**：`text_preprocessing/api.py:32-35` 写"losing the literal block_id boundary is acceptable"——他们**明确知道** chunked IDs 不会过 evidence 校验，假设 LLM 会写非 byte-equal 的 paraphrase quotes（那时 strict 校验就当 fuzzy match 处理）。但 `validate_evidence` 这条硬编码的 byte-equal 校验从来没松绑过，导致 prompt 时空 vs validate 时空 schema 永久不一致。

**架构责任评分**：**10/10 完全架构**。

---

### 问题 #2：示例/案例系统漏抽（3 案例 + 1 三段式全丢）— **提示词**

**架构层级**：prompt 没要求，导致 LLM 默认"提取抽象规则"。

**完整执行链**：

1. `analyzer.py:151` "claims: 3-10 factual claims extracted from the source"——只说 "factual"，没说要包含示例/案例/类比。
2. `analyzer.py:159` "quote: verbatim contiguous text from that exact block"——只说 quote 要 verbatim，没说要把示例作为独立 claim 抽出。
3. LLM 看到的是直播 Q&A（每段都是"嘉宾先讲规则再讲例子"），所以 LLM 把"老羊的姐姐复仇"消化为"主线一旦确定便不能随意改变"（抽象规则），把"半湖月重生"消化为"前三章必须出现明显冲突"（抽象规则）。
4. 案例的"具体性"被丢掉（书名、人物、情节），但概念被提升为通用规则。
5. 没有架构层校验"每个例子必须独立成 claim"——架构信任 LLM 抽取粒度。

**架构责任评分**：**1/10**（prompt-only）。架构没办法自动检测"LLM 漏抽了示例"，因为架构无法分辨"什么是示例"。这是 LLM 抽取任务本身的语义学问题。

---

### 问题 #3：失败信息可读性差（一行短报错）— **架构**

**架构层级**：error schema 不够结构化。

**完整执行链**：

1. `ingest.py:802` `_reject_candidate(f"candidate evidence quote does not match source block: {exc}")`——`exc` 是第一个失败的 EvidenceValidationError 的字符串。
2. 22 条 evidence 失败时，操作员只看到第 1 条的具体消息（"evidence does not match a document block"），无法知道：
   - 21 条是 block_id 不存在还是 quote 不存在
   - 哪几条是 byte-equal 但 block_id 错（架构问题）
   - 哪几条是 byte-不 equal（ASR 问题）
3. `quarantine.py:41` 把 `reason` 当成字符串存 judgment.json，**没有 per-evidence 失败明细数组**。
4. 操作员必须自己 dump `candidate.json`、自己跑 fuzz 比对——本来架构该做的事。

**架构责任评分**：**8/10**。可以要求架构记录 `{kind: 'block_id_mismatch'|'quote_mismatch'|'multi_block_match', evidence_index: N, declared_block_id: ..., actual_match_block_id: ..., max_overlap: ...}` 这样的 per-evidence 诊断。

---

### 问题 #4：claim 重复（C6≈C13、C8≡C16）— **架构**

**架构层级**：`_merge_candidate_chunks` 没有去重，但 `chunker.merge_candidates` 有去重；同一个项目里**两份并行 merge 函数**没共享去重逻辑。

**完整执行链**：

1. `chunker.py:138-156` 实现了 `_dedup_evidence` (按 quote 前 200 字符) 和 `chunker.py:159-267` `merge_candidates` (按 statement 前 80 字符去重，confidence 取 max)。
2. `ingest.py:1457-1505` 实现了**自己的一套** `_merge_candidate_chunks`——但**没有** claim 去重，只 evidence 引用 offset 调整（`ingest.py:1501-1504`）。
3. 当 chunk 数 == 1（大多数情况）时，`_merge_candidate_chunks` 走 line 1461 `if len(candidates) == 1: return candidates[0]`，直接返回单个 chunk——单 chunk 内 LLM 的重复根本不过任何去重。
4. 即使多 chunk，`_merge_candidate_chunks` 也不去重。

**架构责任评分**：**9/10**。`merge_candidates`（在 `chunker.py`）有正确的去重实现，但 `ingest.py` 复刻了一份残缺版本。这是明显的代码重复 + bug。

---

### 问题 #5：ASR 错字被"纠正"（3/24 evidence byte-equal 失败）— **混合，模型能力主导**

**架构层级**：prompt 已有强约束，但模型语义化倾向强。

**完整执行链**：

1. `analyzer.py:159` "quote: verbatim contiguous text from that exact block; never paraphrase, add ellipses, **or repair text**"——这条规则写得明确。
2. 但 MiniMax-M3 看到 ASR 转录里"三张"（"三章" 的误识别）时，会**自动语义化**——它识别出这是"三章"的概率分布较高（因为源上下文谈节奏、章节），即使 prompt 禁止也压不住。
3. 量化证据：21/24 严格 byte-equal（LLM **遵守了** 87.5%），3/24 失败（"三章" vs "三张"、"大纲" vs "大钢"等）——是 LLM 的语义修正倾向，不是 prompt 错误。
4. 架构侧 `validate_evidence` 是 binary check（substr yes/no），没有任何 fuzzy fallback。如果改成 `[quote in block.content OR fuzz_ratio(quote, best_substring) > 0.85]`，这 3 条就过。
5. `kc/api.py:74-78` 有 fuzzy-mismatch 软警告的代码路径（"continuing, no reject"），但 `validate_evidence`（strict）没有同款 fallback——同一文件里两种哲学并存。

**架构 / 提示词 / 模型 各占多少**：
- **提示词**：再加强"绝对不要修正任何字符"——可能压住 1/3
- **架构**：把 strict 改成 `substr OR fuzz > 0.85` ——能解决 3/3
- **模型能力**：根本上 LLM 是被预训练成"理解语义并修正"的，0.0 概率它不修正——只能接受 fuzzy match

**混合评分**：**架构 6/10，提示词 2/10，模型能力 2/10**。修架构性价比最高。

---

### 问题 #6：主张覆盖不均（教义 100%，案例 0%）— **提示词**

**架构层级**：架构无法判断"覆盖是否均衡"，是抽取任务的语义问题。

**完整执行链**：

1. Prompt 让 LLM 自由抽取 3–10 条 claim——LLM 倾向选最有"规则感"的内容。
2. 没有"必须覆盖每段"的指令（应该写 "for each block in registry, emit ≥1 claim or explicit nil-with-reason"）。
3. 架构侧没有"覆盖率"指标（claims per block ratio）——只能事后人工审查。

**架构责任评分**：**2/10**。架构可以加"per-block minimum coverage"门禁，但这是过度设计——典型 Q&A 文档 block 数 == 1（22k 整段被切成 1 个 block），按 block 数算覆盖率意义不大。**提示词**加 "for each concept introduced in source, emit ≥1 claim" 比架构门禁更有效。

---

### 问题 #7：置信度偏高 0.03–0.07 — **架构**

**架构层级**：没有置信度校准层。

**完整执行链**：

1. LLM 自己给出 confidence（"how certain this claim is (0.0-1.0) based on source quality"）。
2. 没有任何架构层基于"source 实际信号强度"做后置校准（Bayesian shrinkage / Platt scaling）。
3. 22 条里 18 条 confidence 在 0.85+，但实际 B/C 级比例 ~35%——LLM 偏自信 ~5–10%。

**架构责任评分**：**7/10**。可以在 candidate merge 时根据 source 噪声指标（`_quality()` 已算出 `_result.report.quality_score`）做 confidence 收缩；或在 claim 生成后基于"实际字面忠实度"做修正。但这是 nice-to-have，不是阻塞性问题。

---

## 责任分摊

| 问题 | 类型 | 修哪里 | 修法概要 | 估时 |
| --- | --- | --- | --- | --- |
| #1 block_id `#sub-N` | 架构 | `analyzer.py:574` + `ingest.py:797-802` | 选项 A：chunking 时不再造 `#sub-N`，直接把 prompt 切成小 content 复用原 ID；选项 B：`validate_evidence` 接收 chunked blocks 联合验证；选项 C：去掉 strict validate_evidence 前置，让 soft-fail 接管 | 2–4 小时 |
| #2 示例漏抽 | 提示词 | `analyzer.py:151` 加规则 | 加"每个具体案例必须作为独立 claim 抽出，附 mention 名/书名/出处" + "don't fold examples into abstract rules" | 30 分钟 |
| #3 失败信息可读性 | 架构 | `evidence.py` + `quarantine.py` + `ingest.py:802` | EvidenceValidationError 加 `evidence_index/expected_block_id/actual_match_block_id`；quarantine 存 per-evidence 失败列表 | 3 小时 |
| #4 claim 重复 | 架构 | `ingest.py:1457` 改用 `chunker.merge_candidates` | 单 chunk 也跑去重；删 `_merge_candidate_chunks` 残缺实现 | 1 小时 |
| #5 ASR 错字纠正 | 架构 + 模型 | `evidence.py:30` 加 fuzzy fallback | `quote in content OR SequenceMatcher(None, quote, content).ratio() > 0.85` | 2 小时 |
| #6 覆盖不均 | 提示词 | `analyzer.py:151` 加规则 | "for each named concept/case/work introduced in source, emit ≥1 claim" | 30 分钟 |
| #7 置信度偏高 | 架构 | 新增 `confidence_calibrator.py` | 基于 `_result.report.quality_score` 和 LLM 实际 byte-equal 率做收缩 | 4 小时 |

## 修复优先级

**P0（必须修，立刻解锁该任务成功）**：
- #1 + #5——这两个就是任务被 reject 的直接原因。#1 是 21/24 失败，#5 是 3/24 失败。修完这两条，22 条 evidence 几乎全过，整条 candidate 进入 Promoter → Generator → Writer。

**P1（必须修，否则下次换文档同样会卡）**：
- #3 + #4——下次某个任务 fail 时，操作员至少能快速定位是哪类失败、重复 claim 不会被硬生成。

**P2（建议修，提升质量）**：
- #2 + #6——案例提取质量，纯提示词投入。

**P3（可选）**：
- #7——置信度校准是 nice-to-have，不阻塞。

## 一个观察

`chunker.py:159 merge_candidates` 和 `ingest.py:1457 _merge_candidate_chunks` 是**两份并行实现**——前者带 dedup，后者不带。代码里直接搜索 `merge_candidates` 在 `ingest.py` 里 0 命中，说明 `_merge_candidate_chunks` 应该是历史遗留实现，正确的 `merge_candidates` 没人去调用。这是典型的"两份实现各干一半"的技术债。

`kc/api.py` 的 `candidate_to_payload`（soft warn + continue）和 `kc/compiler/evidence.py` 的 `validate_evidence`（strict raise）是**两种哲学并存**——前者用于软化 personal-KB 模式的 reject，后者用于硬性 evidence check。`ingest.py:797` 选了 strict 版本先跑，导致 soft 版本永远摸不到。这两条路径应该二选一，或者明确分阶段调用。

简言之：**架构问题不是"缺失"而是"重复 + 顺序错"**。修这两条性价比最高。
