# V7 Replace Plan Stage 0 完成报告

## 时间线

| Task | 内容 | Commit | 时长 |
| --- | --- | --- | --- |
| 1 | segmentation 抽出 | `7b011b64` | ~30 min |
| 2 | ProviderAdapter | `379df691` | ~1 h |
| 3 | ConceptPage ↔ WikiPage adapter + source stub | `71e2c9e9` | ~1 h |
| 4 | run_v7_ingest 端到端编排 | `b404a060` | ~2.5 h |
| 4.1 | (follow-up) 修复 H1 sources 路径 | `ce341d9a` | ~10 min |
| 5 | 70 KB smoke against MiniMax-M3 | (script only) | ~5 min |

**总时长：~5 小时**（含 Task 4 复杂度高 + smoke 1 个修复）。

## Stage 0 验收结果

**70 KB 音频转录源（生产 raw 真实文件）**：

| 指标 | 值 |
| --- | --- |
| 源大小 | 26,398 字符（70 KB 字节） |
| 源 md5 | `28ca27726c9c2ec834c47eb5470cf555` |
| LLM 调用次数 | **5 次**（Stage 1 + 3 + 4 + 5 + 6） |
| 端到端耗时 | **39.6 s** |
| failure_stage | None ✓ |
| 失败 topic | 0 |
| empty_extraction | False |
| 写出页面 | 1 source stub + 1 concept = 2 pages（bridge 内部 `n_pages=3` 是 2 重复 concept 因 LLM cluster 2 topics 同 id，第二次覆盖） |
| 概念页大小 | 10,398 bytes（高质量 8 槽位全填） |

**H1/H2/H4/H5 + wiki-quality 全部通过**：

| 检查 | 结果 |
| --- | --- |
| H1 (file existence) | 0 issues |
| H2 (link resolution) | 0 issues |
| H4 (page ID format) | 0 issues |
| H5 (cache health) | 0 issues |
| wiki-quality strict | **HEALTHY** (0 errors, 0 warnings, 1 expected duplicate-source-title from re-run) |
| health endpoint | HEALTHY |

**Cost**：5 LLM calls × ~10k input tokens × ~2k output tokens ≈ 0.05-0.10 USD（< 0.5 USD budget）— 与 v2 path（1 call/topic）成本相近，远低于 v3 path（9 calls/topic）的 9×。

**产出页样本（8 槽位填充）**：

```markdown
## 定义
转录内容（在本词条中）特指一篇关于"大纲写作技巧"的音频/视频教程的文字转录稿，
记录了一次以"淡淡"为主讲人的线上直播授课全过程，主题为讲解小说写作中大纲
（"大高"，即大纲的语音转写错误）的重要性及其撰写方法。

## 主要特点
1) 由语音转文字生成，存在大量同音错字（如"大高"实为"大纲"、"淡淡"为人名、
"轮屋"实为"人物"、"高少"实为"高潮"、"复彼"实为"伏笔"等）；
2) 直播式口语，夹杂开场寒暄、主持人串场、爬麦互动与观众提问环节；
3) 结构上以"四要素（背景架构、故事主线、人物设定、主要内容）"为讲解骨架；
4) 末尾设有 Q&A 互动问答。

## 反模式与常见错误
- 不写大纲就直接动笔，导致写到一半卡文、情节跑偏、收不了尾
- 写到中途随意加入新人物、新看点，使主线涣散
- 因读者留言随意更改故事主线，致使作品"面目全非"、成绩下滑
- 人物性格中途大变（如"男主开始人血无情，后来突然很弱"），造成人设崩塌
- 高潮前缺乏伏笔铺垫，导致高潮写丢
- 一次性抛出多个伏笔却不知先解决哪个，造成节奏混乱

## 证据强度
证据强度较弱：仅有一条编号为 0 的来源项...且该来源为含大量 ASR 错字的直播口述稿，
未经整理校对，关键术语需结合上下文还原。建议人工复核原文后再用于词条正式发布。
```

**关键观察**：LLM 主动识别了 ASR 错误（"大高"实为"大纲"），并在「证据强度」槽位中明确标记可信度弱点。这是 LLM 自己的判断，不是模板提示词。

## 已落地的代码

| 文件 | 行数 | 角色 |
| --- | --- | --- |
| `src/pipeline/v7_extract/segmentation.py` | +130 行 | deterministic splitter 公共 API |
| `src/pipeline/v7_extract/llm_bridge.py` | ~110 行 | ProviderAdapter |
| `src/pipeline/v7_extract/page_adapter.py` | ~190 行 | ConceptPage↔WikiPage + source stub |
| `src/pipeline/v7_extract/bridge.py` | ~400 行 | run_v7_ingest 端到端 |
| `tests/test_pipeline/test_v7_extract_segmentation.py` | 12 tests | |
| `tests/test_pipeline/test_v7_extract_llm_bridge.py` | 11 tests | |
| `tests/test_pipeline/test_v7_extract_page_adapter.py` | 12 tests | |
| `tests/test_pipeline/test_v7_extract_bridge.py` | 9 tests | |
| `.tmp-smoke-70kb.py` | smoke script | 不入库，dev 工具 |

**总：~830 行 prod + ~50 个测试 + 1 个 smoke 脚本**。所有新代码与现有 V7 测试无冲突（73 个相关测试全绿）。

## 与候选管线的关键差异

| 维度 | 候选管线（失败） | V7 管线（成功） |
| --- | --- | --- |
| Stage 1 失败原因 | `validate_evidence` strict 校验：ASR 错字被 LLM 纠正后 byte-match 失败 | 不走 byte-match；走 v3 evidence + hash |
| 拒绝原因 | 22/24 evidence 因 `#sub-N` 后缀不匹配 canonical blocks | N/A — V7 evidence model 不同 |
| 页面质量 | 模板占位（heading-only） | 8 槽位全填（10 KB 内容） |
| H1 issues | N/A（未写盘） | 0 |
| LLM 调用 | 1 call/source | 5 calls/source（Stage 1/3/4/5/6 各一） |
| 处理时间 | 71 s（之前失败） | 40 s（成功） |

**核心结论**：V7 的"按 5 槽位填充"模型比候选的"按 byte-equal evidence 引用"模型对 ASR 噪声鲁棒得多——LLM 在 evidence 阶段就识别了"大高=大纲"这类错字，但填槽时直接用"大纲"（标准汉字），**不要求原文 byte-match**。

## 已知遗留（Stage 0 完成但 Stage 1+ 需要）

### P1 (Stage 1 灰度前必须修) — **全部完成（commit `01f9a53c` + `886506c2`）**
1. ✅ **fill_slots_v2 路径**：v3 path 完整实现（`commit 01f9a53c`）。spans_per_slot 从 Stage 2 items 切片（每 1500 bytes），绕开 window_resolver 依赖。
2. ✅ **2 concept 同 id 覆盖**：bridge 加 `seen_topic_ids` Counter，第 (n+1) 个同 id topic 拿 `-{n}` 后缀（`commit 886506c2`）。
3. ✅ **BridgeBudget 硬性 cap**：bridge 在 Stage 1/3/4/5/6 边界调 `_check_budget`，超 `max_calls` 抛 `BridgeBudgetExceeded`（`commit 886506c2`）。

### P2 (Stage 2+)
4. **shadow mode dead code 修复**：`src/pipeline/shadow.py` 是 dead code（plan 早记），Stage 3 删除前可清。
5. **relation_extractor 协程未 await** warning：pre-existing V7 bug（`raw = _extract_with_llm(page_data, llm)` 缺 await），需要上游修。
6. **H1 修复后续**：未来如果 source 路径用 `#` 是合理的（如 `path#heading`），需要更精确的 suffix detection。

### P3 (Stage 3 删除前)
7. **删除 ingest.py 候选/chunked 分支**（Task 5/5a 合并）
8. **删除 `unified_generate`**（`generator.py:689-902`）
9. **删除 `_analyze` / `_analyze_chunked`**（`analyzer.py:458/527`）
10. **删除 `_merge_candidate_chunks` / `_merge_analysis_results` / `_split_source_chunks`**（`ingest.py:1457/1543`）
11. **删除 `RUFLO_PIPELINE_MODE` / `RUFLO_SHADOW_MODE` env 字段**（`config.py:72-73`）
12. **删测试**：`test_unified_generate_*` (4) / `test_chunked_analysis.py` 整文件 / 候选 test 块

## 用户决策点（Stage 0 → Stage 1）

按 grilling 决策框架（B 灰度 + 延迟删除），Stage 0 完成后**不**自动进入 Stage 1。需要用户：

1. **审阅 Stage 0 产出**（10 KB 概念页 + source stub）
2. **回答 Stage 1 触发问题**：
   - novel-wiki-v2 是否设 `RUFLO_PIPELINE_MODE=v7`（per-project 灰度）？
   - 另一个项目（sanjian-zatan-kb / tmp-v7-split-test）是否同时设？
   - Stage 1 观察期多长（建议 5-7 天）？
3. **P1 三项**是否要先修再 Stage 1？建议**先修**——`fill_slots_v2`（用户原本选的）、2 topic 同 id、BridgeBudget 硬性 cap，都是 Stage 1 production 必需要。
4. **删除旧代码**（Task 5/5a 合并 commit）什么时机做？建议 Stage 1 灰度 **2 周后** + 0 production issue 才删。

Stage 0 报告完。
