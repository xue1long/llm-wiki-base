# Task 0 修复复审报告

## 结论

**部分通过，仍有 Important 未闭环。** 修复已关闭原 Critical，并补上了候选 fail-closed、空关系 `None`、悬空关系计数、三个默认候选、merge/cancel 以及 hard/soft 依赖字段/门控。但最小学习闭环仍只是弱存在性检查，关键回归测试也没有实际加入；因此不能判定 Task 0 整体通过，后续任务不应把当前 `closed` 当作完整的前置—产出学习链证明。

审查范围：原简报、原实施报告、`task-0-fix-review-package.md` 所示 `267cd6c3..d940adab` 修复 diff；只检查修复 diff 的新行为和回归。未修改实现，未派生子代理，未调用远程 LLM。

## 原 finding 逐项判定

### Critical

1. **数据门 fail-open：ADDRESSED。**

   `evaluate_series_gate` 现在以 `not any(candidate.decision == "proceed" ...)` 参与 `blocked` 判定；所有候选均被否决时追加 `no_retained_candidate`，返回 `status="blocked"` 与 `generation_mode="rule_only"`。弱候选自身仍不能得到 `proceed`，因此修复了原先治理字段齐全即可放行的路径。

### Important

2. **最小学习闭环过于宽松：NOT ADDRESSED（部分改进）。**

   修复增加了候选内任意关系边和 `min_reader_tasks` 检查，但 `has_learning_edge` 只要求任意目标属于候选页面；没有验证边的方向/关系类型是否构成“前置页面 → 出口产物”，也没有章节概念或“连续两章无可验证出口产物”的检查。自环、出口指回前置、或任意无关页面边都能满足这一条件。代码仍不能证明原规格要求的前置—产出链。

3. **关系解析率不是实际指标：ADDRESSED（按修复包承诺的空值/悬空语义）。**

   无关系时 `relation_parse_rate is None`；有关系时按总结构化关系数减悬空目标数计算，并公开 `relation_unresolved_count`。命名空间目标以 `taxonomy` 前缀排除在悬空计数外。限制是 scanner 对格式错误关系仍整体 fail-closed，所以无法统计被拒快照内部的原始声明/解析失败分母；这是已知边界，不能解释为完整的原始解析率。

4. **三个候选及 merge/cancel：ADDRESSED。**

   `_candidate_pages` 将 `ReaderProfile.candidate_taxonomies` 与实际分组取并集，因此默认始终输出 `book-a`、`book-b`、`book-c`；空候选为 `cancel`，存在跨候选页面目标且候选不满足门槛时为 `merge`，合格候选才为 `proceed`。实现仍允许 profile 自定义候选数量，这是已有配置能力，不构成修复回归。

5. **治理依赖未进入结果/未门控：ADDRESSED。**

   `SeriesGateResult` 和 `CandidateDecision` 现在输出 hard/soft 依赖；缺失 hard 依赖追加 `hard_reference_dependencies` 并阻断，soft 缺失仅记录。依赖匹配的是候选 taxonomy ID；若后续调用方传入 page ID 或 manifest book ID，则不会被识别为已满足，接口语义仍需后续契约统一，但当前修复已实现其声明的候选级门控。

6. **测试没有覆盖关键门槛：NOT ADDRESSED。**

   修复 diff 只修改原 4 个测试，未新增实际测试用例来覆盖报告所称的 fail-closed、6 个 reader task、出口关系、悬空/`None`、三候选 merge/cancel、hard/soft 依赖或 provider 不调用。现有弱候选测试只断言 `decision != proceed`，不能验证整体 `status/generation_mode`；闭环 ready 测试还通过把 `min_reader_tasks` 降为 2 来放宽门槛。实施报告声称“新增回归覆盖”与 diff 不符。

### Minor

7. **重复率分母未冻结/记录：NOT ADDRESSED。**

   `_duplicate_rate` 仍以全部页面数为分母，而分子只统计有 `content_sha256` 的重复页；空 hash 会稀释重复率。修复 diff 未改变实现、未记录分母约定，也未增加空 hash 测试。

8. **范围外预先加入章节分块：NOT ADDRESSED（本修复未恶化）。**

   `partition_pages`/`build_chapter_chunks` 仍存在且不属于 Task 0 门禁；修复 diff 未移除它们，也未新增测试。该项是原始范围判断，不能算修复后的回归，但仍未被处理。

## 修复 diff 新回归

### Important

1. **治理完整但没有合格候选时确实阻断。** 未发现原 Critical 的新回归。

2. **默认候选引入空候选是契约变化。** 这是本次需求所需变化；调用方若以“`candidates` 非空即有可编译书”为条件，必须改用 `status`/`decision`。当前 `SeriesGateResult.status` 已能区分，未发现本 diff 内部调用方误用。

### Minor

1. **`target.startswith("taxonomy")` 过宽。** 它把诸如 `taxonomyfoo` 也视为命名空间目标；scanner 当前生成的是 `taxonomy/` 或 `taxonomy-`，所以这是输入模型边界上的小风险，不影响标准合法目标。

## 验证

直接运行 bundled Python 的定向命令：`tests/test_kc/test_book_series_baseline.py tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q`，结果为 **4 passed, 17 errors**。4 个 baseline 测试通过；其余测试因 pytest `tmp_path` 无法创建 `C:\Users\HP\AppData\Local\Temp\pytest-of-HP`（`PermissionError: [WinError 5]`）而未执行到断言，属于当前测试环境权限问题。原报告的“21 passed”无法由当前修复 diff 中的测试内容复现。

## 最终判定

原 1 Critical：**ADDRESSED**；原 6 Important：**4 ADDRESSED、2 NOT ADDRESSED**（其中关系率按修复包承诺的空值/悬空边界判定）；原 1 Minor：**NOT ADDRESSED**；原第 8 条范围项仍未处理。由于闭环语义和测试覆盖两个 Important 未闭环，Task 0 复审结论为 **FAIL / 需继续修复**。
