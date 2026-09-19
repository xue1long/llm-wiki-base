# novel-wiki-v2 摄取「音频教程/大纲写作技巧.md」实测（2026-09-18）

- 实例：`knowledge/novel-wiki-v2`（project_id `9be6839c-3a38-43e2-88cf-0fdb37fe3e1c`）
- 源文件：`raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md`（70 966 B / 约 17 280 字，UTF-8）
- 任务 ID：`kb-20260918152026-4409dd89`（HTTP 队列）
- Provider：MiniMax-M3（默认），embedding 仍无默认 MiniMax 向量（保持空）
- Wall-clock：约 71 s（1789716026 → 1789716097），1 次 retry 后 dead_letter
- 终态：`failed`（HTTP）/ `dead_letter`（队列）
- 失败原因：`[no-retry] candidate evidence quote does not match source block: evidence does not match a document block`
- 落盘：wiki **未发生变化**（仍为先前任务遗留的 2 页），仅写入 `.index/quarantine/kb-20260918152026-4409dd89/{candidate.json,candidate.judgment.json}`

## 流程行为

- HTTP `POST /api/v1/projects/<id>/ingest` 成功入队（`{"status":"queued","taskId":"kb-20260918152026-4409dd89","sourceId":"src-efbbcb8064298eb4d2740bfd4d7ae340"}`）。
- 阶段：`collector → collector(re-enter) → analyzer`；reviewer 阶段触发 `[no-retry]` 拒绝。
- queue 记录 `retry_count=1`，最终 `dead_letter`；circuit breaker `closed`、`failure_count=4`（含先前累计）。

## Reviewer 拒绝原因拆解

候选文件 `.index/quarantine/kb-20260918152026-4409dd89/candidate.json` 共生成 24 条 claim（confidence 0.78–0.95，集中在 0.85–0.92），并附带 24 段 evidence quote，全部指向同一 source。问题：

1. evidence `quote` 字段与源文件 byte 级不匹配。源文是 ASR 中文转录，存在大量同音字/简繁/错别（如「大纲」→"大高"/"大钢"/"大岗"，「架构」→"购价"/"价购"，「伏笔」→"服彼"，「灌水」→"冠水"，「悬念」→"悬彼"），LLM 抽取时将字面修正为「正确」汉字后再回引，与源块不再 byte-equal。
2. Reviewer 命中 `ReviewerStage.evidence_match` 规则，触发 `[no-retry]` short-circuit，candidate 不进入 Promoter/Generator/Writer。
3. 这是 Task 2 fail-closed slot 的预期行为：避免占位正文/错误引用落盘；与上一轮（`kb-20260918145517-6af489eb`，3 KB 短稿）根因相同，但错误信息从 `must match a unique block` 改为 `does not match a document block`，说明 Reviewer 文案在最近微调过。

## 验证结果（wiki 现有 2 页）

| 校验 | 命令 | 结果 |
| --- | --- | --- |
| `health` H1/H2/H4/H5 | `python -m src.cli health --project knowledge/novel-wiki-v2` | **HEALTHY**，0 issues；H5 报 `quarantine_items=5`（含本次 2 个 candidate 文件） |
| `lint` | `python -m src.cli lint --project 9be6839c-3a38-43e2-88cf-0fdb37fe3e1c` | `Found 0 issues` |
| `wiki-quality` strict | `python -m src.cli wiki-quality --project knowledge/novel-wiki-v2` | **HEALTHY**（H1/H2/H4/H5 全部 OK，无重复标题、无 V4 int 时间戳、无 BOM、lint_cache=1） |
| `tags validate --all` | 同前 | `OK` |
| `fields validate` × 2 页 | 逐文件 | `OK` × 2 |
| HTTP `/content-health` | API | `page_count=2`、`orphan=1`、`dangling_link=0`、`check_errors` 列出 2 页 `invalid page`（content-health 内部判定异常，详见后述） |
| HTTP `/lint` | API | 报告 `dangling=2`：`小说大纲写作技巧 → taxonomy-大纲与结构`、`→ taxonomy-写作技法`（与上一轮记录的 2 个 taxonomy gap 完全一致） |

### 残留告警

- **HTTP /lint 仍报 2 个 dangling taxonomy target**（`taxonomy-大纲与结构`、`taxonomy-写作技法`），CLI `lint` 命令和 `wiki-quality` strict gate 都通过。两者口径不一致：HTTP `/lint` 把 `taxonomy-*` 当作需要解析的 Wiki 页面目标；CLI `lint` 已接受 `taxonomy-*` 为合法分类关系，与 2026-09-18 整改方案一致。建议把 HTTP `/lint` 同步更新为「taxonomy-of 不计入 dangling」或显式提示是分类关系。
- **HTTP /content-health 的 `check_errors` 将 2 个现有页都标为 `invalid page`**。CLI 端 `fields validate` 和 `wiki-quality` 都没有这个问题。需要查 ContentHealth 的判定逻辑是否在 v3.0.0 schema 上有 bug（很可能是 `template_version=4.0.0` 与 v2.0 校验器不一致，或要求 `_ko_extra.provenance.ingestor_version` 等新增字段）。**不影响 fail-closed 摄取，但会让 WebUI 报红**。
- **book `show`** 返回 `empty`，`knowledge_units=0`，符合预期（KB 上从未编译 KC）。

## 与上一轮对比

| 维度 | 2026-09-18 14:55（3 KB 短稿） | 2026-09-18 15:20（70 KB 长稿） |
| --- | --- | --- |
| review 拒绝原因 | `must match a unique block` | `does not match a document block` |
| 终态 | failed / dead_letter | failed / dead_letter |
| wiki 落盘 | 2 页（占位正文，模板骨架） | **0 页**（被 fail-closed slot 拦截） |
| 重复标题 / 断链 | 1 组 / 18 | 0 / 0 |
| taxonomy gap | 2 | 0 新增（旧的仍 dangling） |
| wiki-quality strict | 36 issues | HEALTHY（仅看现有 2 页遗留） |

**结论：Task 2 fail-closed slots 在大文档上的表现符合预期**——错误候选不再写盘，但同时让"流程成功 ≠ 内容通过"这条原则在 70 KB 真实素材上得到了一次干净的验证。

## 待整改（建议）

1. **ASR 转录 verbatim 抽取**：MiniMax-M3 对 ASR 错字回引时倾向"纠正"。两个可行方向：
   - （A）**Collector 预处理**：用 ASR 错误词典把"大高/大钢/购价/服彼/冠水"等先规范化成标准词再喂 Analyzer，让 evidence 抽取与原文档对齐。风险：改了 raw 内容，违反 read-only 约束；应另存 `cleaned_content` 字段。
   - （B）**放宽 evidence 匹配规则**：允许 `[原文 quote, fuzz_ratio >= 0.85]` 通过，并在失败时把不一致 diff 记入 judgment，便于人工审核。短期成本：review 阈值要重测；长期收益：把"对齐失败"从 fail-closed 降级为 NEEDS_HUMAN_REVIEW。
   - （C）**Prompt 改造**：在 Analyzer prompt 明确"quote 字段必须按原文逐字符复制，不要纠正错别字/标点"。最简、最快，建议先试。
2. **修 HTTP /lint**：让 taxonomy-of 不计入 dangling（或显式标 "taxonomy relationship, not a missing page"）。
3. **修 HTTP /content-health**：调查 2 个现有页被判 `invalid page` 的具体规则——这是 v3.0.0 schema 与 v2.0 校验器之间的回归，需要补 unit test 锁定。
4. **book/quality 端到端**：本次失败任务未产出 KC，需要 1 个真正通过的源来验证 `book build` 流程。
