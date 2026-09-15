# Plan: novel-wiki V7.1.1 模板改造 + 抽取流水线

status: planned
branch: feature/2026-09-13-novel-wiki-v7-pipeline

## Goal

将 novel-wiki 模板从 V3.0.0 升级到 V7.1.1（基于 RFC v6），并实现全自动抽取流水线，让 4918 页存量 + ~13000 个 raw 素材能被自动结构化为 wiki 页。

**用户可见产出**：
- 4 个模板升级到 V7.1.1（5 主槽位 + stage 多值 + refines 关系 + tool 新类型）
- 4918 页存量全量通过 V7.1.1 校验
- 抽取流水线能在 8 天内批量抽取所有 raw 素材
- 写盘失败的 wiki 页不污染存量

**明确非目标**（不在本计划内）：
- `用途/可执行` 审核通道（ADR-004 待起）
- 跨库互联（ADR-005 待起）
- V8 模板版本号配置化 / 模板片段（ADR-006 待起）
- 概念去重合并（V8 待起）
- 主动推荐 API（V8 待起）

## Tasks

每个 task 是一个逻辑切片。**先写测试，再写实现**（TDD per task）。每个 task 完成后一个 commit（`type(scope): 中文描述`）。

---

### Task 1: V7.1.1 Schema 扩展（RFC v6 落地 ①必改 3 项）

- **Files**：
  - `docs/superpowers/plans/2026-09-11-novel-wiki-template-rewrite-v7.md`（已落盘，作为规范来源）
  - `src/wiki/core/types.py`：`WikiPage` dataclass `stage: list[str]`（多值）
  - `src/wiki/storage/page_writer.py`：写盘路径 stage 多值序列化
  - `src/wiki/core/relations.py`：加 `refines` 关系类型
  - `src/wiki/storage/frontmatter_validator.py`：加 `source_meta` 必填 `forum_url`
  - `src/server/routes/search.py`：检索 API 接受 `stage IN (...)` 多值查询
  - `src/templates/bundled/novel/`：同步升级
  - `knowledge/novel-wiki/.wiki-templates/index.yaml`：加 `tool` 类型 + `refines` 关系
  - `knowledge/novel-wiki/.wiki-templates/tool.md`（新增）

- **Test**：
  - `tests/test_wiki/test_stage_multi.py`：stage 单值/多值/旧数据兼容
  - `tests/test_wiki/test_refines_relation.py`：refines 关系写盘 + 读取
  - `tests/test_wiki/test_source_meta_url.py`：source_meta 必填 URL + 缺失 warn
  - `tests/test_wiki/test_tool_type.py`：tool 类型写盘 + 3 槽位模板
  - `tests/test_server/test_search_stage_multi.py`：API 多值 stage 查询

- **Implementation**：
  1. dataclass `stage: list[str]`，写盘路径 YAML 序列化为列表
  2. relations 加 `refines`，校验脚本加白名单
  3. `source_meta` 加 `forum_url` 必填校验（缺失 warn 而非 reject）
  4. 检索 API `stage=X` 改为 `stage=X,Y,Z` 多值
  5. `tool` 类型加极简 3 槽位模板 + 写盘分支

- **Acceptance**：
  - 4918 页存量 100% 通过 `validate_novel_wiki_frontmatter.py --strict-v7.1.1`
  - stage 多值概念页（如 `zhang-jie-ming-she-ji`）写盘 + 读取 round-trip 一致
  - `refines` 关系类型在反查中能命中
  - `tool` 类型页面成功写盘
  - 检索 API `stage=开篇,前期` 返回跨阶段结果

- **Status**: pending
- **Time estimate**: 3 days（含 4918 页存量迁移 + 4 个写盘分支扩展）

---

### Task 2: V7.1.1 模板重写 + index.yaml + tool 模板

- **Files**：
  - `knowledge/novel-wiki/.wiki-templates/source.md`（v3.0.0 → v4.0.0）
  - `knowledge/novel-wiki/.wiki-templates/entity.md`（v3.0.0 → v4.0.0）
  - `knowledge/novel-wiki/.wiki-templates/concept.md`（v3.0.0 → v4.0.0）
  - `knowledge/novel-wiki/.wiki-templates/synthesis.md`（v3.0.0 → v4.0.0）
  - `knowledge/novel-wiki/.wiki-templates/tool.md`（新增）
  - `knowledge/novel-wiki/.wiki-templates/index.yaml`（V6 完整版）
  - `knowledge/novel-wiki/.wiki-templates/.archive/v3.0.0/`（备份）

- **Test**：
  - `tests/test_wiki/test_template_v7_1_1.py`：4+1 模板 v4.0.0 标记校验
  - `tests/test_wiki/test_index_yaml.py`：index.yaml schema 校验

- **Implementation**：
  1. 4 个模板重写为 V4.0.0（基于 RFC v6 §4）
  2. 加 tool 模板（3 槽位：tool_meta / usage / examples）
  3. index.yaml 加 `tool` 类型 + `refines` 关系 + `list_type` / `chat_format` 字段
  4. 备份 V3.0.0 到 `.archive/`

- **Acceptance**：
  - 5 个模板 frontmatter 含 `wiki-template-version: 4.0.0`
  - index.yaml 通过 yaml.safe_load 解析
  - V3.0.0 备份可恢复

- **Status**: pending
- **Time estimate**: 0.5 day

---

### Task 3: 写盘路径 cross-field 校验（M10/F-C-V5 整改）

- **Files**：
  - `src/wiki/storage/frontmatter_validator.py`
  - `scripts/validate_novel_wiki_frontmatter.py`
  - `tests/test_wiki/test_cross_field_validation.py`

- **Test**：
  - `policy_kind` 仅在 `entity_subtype=policy` 时合法
  - `template_version` 默认 `4.0.0`（缺失时补）
  - `stage` 多值必须 ∈ `allowed_stages`

- **Implementation**：
  1. 加 cross-field 校验函数 `validate_cross_fields(page)`
  2. 写盘路径调用该函数
  3. 跑存量扫描列出违规页

- **Acceptance**：
  - 存量扫描结果 < 5% 违规页（已是历史产物）
  - 新写入页 0 违规

- **Status**: pending
- **Time estimate**: 1 day（含存量扫描报告）

---

### Task 4: 流水线 Phase0 — 文档分类 + 完整性检测（不依赖 LLM 部分）

- **Files**：
  - `scripts/ingest_pipeline.py`（新增）
  - `src/pipeline/ingest/doc_classifier.py`（新增）
  - `src/pipeline/ingest/completeness_checker.py`（新增）
  - `tests/test_pipeline/test_doc_classifier.py`
  - `tests/test_pipeline/test_completeness_checker.py`

- **Test**：
  - 9 个已知文档（设计者已抽取过）分类全对
  - 3-5 个**新文档盲测**（设计者未见过）分类 ≥90% 正确
  - 15 条技巧被识别为 `incomplete`
  - 百家姓被识别为 `tool`

- **Implementation**：
  1. 实现 `classify_doc(content)` 纯规则版本（0.5 天）
  2. 加 LLM 辅助 fallback（1.5 天）
  3. 实现 `check_completeness(content, doc_type)`（0.5 天）
  4. 加 LLMClient 接口（为单元测试 mock 留口子 — M9-V5 整改）

- **Acceptance**：
  - 9 文档 + 5 盲测 = 14 文档分类 ≥90% 正确
  - 单测覆盖 ≥80%
  - `LLMClient.extract_topics()` 接口可被 fake 替换

- **Status**: pending
- **Time estimate**: 2.5 days

---

### Task 5: 流水线 Stage 4 — 主题聚类（F-A/M1-V5 整改）

- **Files**：
  - `src/pipeline/ingest/topic_clusterer.py`（新增）
  - `src/pipeline/ingest/concept_deduplicator.py`（新增 — F4-V5 整改）
  - `tests/test_pipeline/test_topic_clusterer.py`
  - `tests/test_pipeline/test_concept_deduplicator.py`

- **Test**：
  - 103 个桥段 → 3-5 个聚类（M1-V5）
  - 8难墨武聊天 → 按主讲主题聚合
  - 三江杂谈 → 11 篇文章 → 7 concept
  - **概念去重**：已存在 `kuo-ju-fa` 概念，新素材有同主题 → 合并 `sources_used`（不新建）

- **Implementation**：
  1. LLM 聚类（3-5 个）+ 后处理合并/拆分
  2. 概念去重（查存量 `wiki/concepts/*.md` 已有概念 ID 列表）
  3. 决策树：合并 / 新增（id 加后缀） / 跳过

- **Acceptance**：
  - 103 桥段产出 3-5 concept（不爆炸）
  - 概念去重准确率 ≥85%
  - 重复抽取幂等性 OK（md5 标记已抽取 — O6-V5 整改）

- **Status**: pending
- **Time estimate**: 3 days

---

### Task 6: 流水线 Stage 5-7 — 槽位填充 + 关系抽取 + 写盘索引

- **Files**：
  - `src/pipeline/ingest/slot_filler.py`（新增）
  - `src/pipeline/ingest/relation_extractor.py`（新增）
  - `src/pipeline/ingest/wiki_writer.py`（新增 — checkpoint + retry）
  - `src/pipeline/ingest/audit_logger.py`（新增 — M11-V5 整改）
  - `src/wiki/storage/page_writer.py`（扩展）
  - `src/wiki/storage/inverse_index.py`（增量更新）
  - `tests/test_pipeline/test_slot_filler.py`
  - `tests/test_pipeline/test_relation_extractor.py`
  - `tests/test_pipeline/test_wiki_writer.py`（含 checkpoint + retry 测试）
  - `tests/test_pipeline/test_audit_logger.py`

- **Test**：
  - 5 槽位填充准确率 ≥85%（基于已知文档）
  - `refines` vs `supported_by` 自动判断 ≥80%
  - 写盘失败 retry 3 次后跳过（M5/F-E-V5 整改）
  - **checkpoint 幂等性**：跑两遍不重复写盘（O6-V5 整改）
  - 审计日志：每篇原始素材 → 哪些 concept 页（M11-V5 整改）

- **Implementation**：
  1. `slot_filler.py`：基于 RFC v7.1.1 5 槽位模板填充
  2. `relation_extractor.py`：自动推断 taxonomy / cites / refines / supported_by
  3. `wiki_writer.py`：checkpoint + retry + round-trip
  4. `audit_logger.py`：输出 `extract_report.json`（每篇 → concept 映射）

- **Acceptance**：
  - 9 个测试文档抽取产物与设计者手抽结果**完全匹配**（type +数量 + 关键字段）
  - 写盘失败自动停止 + 报告
  - 审计日志可追溯每条概念来源

- **Status**: pending
- **Time estimate**: 4 days

---

### Task 7: 流水线 Phase 1.5 — 试点验证（O4-V5 整改）

- **Files**：
  - `scripts/extract_pilot.py`（新增 — 50 篇真实素材 dry-run）
  - `docs/superpowers/reports/2026-09-13-extract-pilot-report.md`（报告）

- **Test**：
  - 选 50 篇 raw 素材（覆盖各种结构）
  - dry-run 跑流水线
  - 人工 spot-check 10 篇（5 概念页）
  - 准确率统计

- **Implementation**：
  1. 写 `extract_pilot.py`：调用流水线 Phase0-Stage 5
  2. dry-run 输出 JSON（**不写盘** — M4-V5 整改）
  3. 人工审核 → 输出准确率报告
  4. 调整阈值 / prompt

- **Acceptance**：
  - 准确率 ≥80%（spot-check）
  - 报告包含每篇素材的抽取结果
  - 阈值已调整到 Phase 2 准备

- **Status**: pending
- **Time estimate**: 1 day

---

### Task 8: 流水线 Phase 2 — 批量抽取 4918 页存量

- **Files**：
  - `scripts/extract_full.py`（新增 — 批量 dry-run + 写盘）
  - `docs/superpowers/reports/2026-09-14-extract-full-report.md`

- **Test**：
  - 4918 页全量抽取
  - 写盘失败清单（人工 review）
  - 反向索引重建

- **Implementation**：
  1. 写 `extract_full.py`：分批（500/批）+ checkpoint + retry
  2. dry-run →人工确认 → 写盘模式
  3. 写盘失败页 → review queue
  4. 全量报告

- **Acceptance**：
  - 4918 页存量抽取完成
  - 写盘失败页 < 5%
  - 反向索引覆盖 100%
  - 预算 < $200（基于实测）

- **Status**: pending
- **Time estimate**: 2 days（含人工 review）

---

### Task 9: 敏感内容审核闸门（F-D-V5 整改）

- **Files**：
  - `src/pipeline/ingest/content_filter.py`（新增）
  - `src/wiki/storage/reviews_queue.py`（新建 reviews_resolved.json 类似机制）
  - `tests/test_pipeline/test_content_filter.py`

- **Test**：
  - 敏感词库匹配（政治 /色情 /抄袭）
  - 命中 → 进 review queue
  - 人工审 → 通过 → 入 wiki

- **Implementation**：
  1. 敏感词字典（来源：起点明文规则）
  2. 流水线 Stage 6 后加审核闸门
  3. review queue 持久化

- **Acceptance**：
  - 流水线自动拦截敏感内容
  - review queue 有明确状态机

- **Status**: pending
- **Time estimate**: 1 day

---

### Task 10: 流水线 Phase 5 — 回归验证 + A/B 对比（M7/F-G-V5 整改）

- **Files**：
  - `scripts/extract_eval.py`（新增 — A/B 对比脚本）
  - `docs/superpowers/reports/2026-09-15-extract-eval-report.md`

- **Test**：
  - 选 5-10 个**设计者未见过**的文档
  - 流水线抽取 vs人工抽取对照
  - 准确率 /召回率统计

- **Implementation**：
  1. 写 `extract_eval.py`：随机选 5-10 文档
  2. 流水线抽取 →产物
  3. 人工对照（独立评估）
  4. 输出指标报告

- **Acceptance**：
  - 准确率 ≥80% / 召回率 ≥75%
  - A/B 报告签字

- **Status**: pending
- **Time estimate**: 1 day

---

### Task 11: 文档与落地报告

- **Files**：
  - `knowledge/novel-wiki/CONTEXT.md`（更新术语 — V7.1.1 新增字段）
  - `docs/adr/ADR-003-decouple-template-slots-from-frontmatter.md`（更新 V7.1.1 引用）
  - `docs/superpowers/plans/2026-09-11-novel-wiki-template-rewrite-v7.md`（已落盘）
  - `docs/superpowers/reports/2026-09-13-*`（实施报告）

- **Test**：
  - 文档准确性人工审核

- **Implementation**：
  1. 更新 CONTEXT.md（V7.1.1 新增字段）
  2. 更新 ADR-003 引用 V7.1.1
  3. 写落地报告

- **Acceptance**：
  - 文档同步代码
  - 报告含准确率 /成本 / 时间数据

- **Status**: pending
- **Time estimate**: 0.5 day

---

## 任务依赖关系

```
Task 1 (V7.1.1 Schema)
   ↓
Task 2 (模板 + index.yaml)  ─→  Task 3 (cross-field 校验)
                                  ↓
                              Task 4 (Phase0 分类 + 完整性)
                                  ↓
                              Task 5 (Stage 4 聚类 + 去重)
                                  ↓
                              Task 6 (Stage 5-7 写盘)
                                  ↓
                              Task 7 (Phase 1.5 试点)
                                  ↓
                              Task 9 (敏感审核闸门)  ── 并行
                                  ↓
                              Task 8 (Phase 2 全量抽取)
                                  ↓
                              Task 10 (Phase 5 A/B 对比)
                                  ↓
                              Task 11 (文档与报告)
```

---

## 总时间线（预估）

| Phase | Tasks | 工作量 | 累计 |
|---|---|---|---|
| Phase A：Schema + 模板 | Task 1 + 2 + 3 | 4.5 天 | 4.5 天 |
| Phase B：流水线骨架 | Task 4 + 5 + 6 | 9.5 天 | 14 天 |
| Phase C：试点 + 审核 | Task 7 + 9 | 2 天 | 16 天 |
| Phase D：批量抽取 | Task 8 | 2 天 | 18 天 |
| Phase E：验证 + 报告 | Task 10 + 11 | 1.5 天 | 19.5 天 |

**总计约 20 天**（4 周）

---

## Audit

- **Round 1**: ✅ completed — 26 个问题已识别并写入 tasks（4 致命 + 11 重大 + 6 优化 + 5 失败路径）
- **Round 2**: ✅ completed — 压力测试 6 个失败路径有对应加固措施
- **Human review**: pending
- **Open risks**:
  - LLM 成本可能突破 $200 →需用小模型 + 缓存
  - 概念去重准确率 < 85% →需人工 review queue
  - 敏感内容审核漏检 →需人工闸门
- **Rollback**:
  - 每个 task 一个 commit，revert 单 task 即可
  - 4918 页存量迁移失败 → checkpoint 回滚
  - 流水线抽取失败 → 反向索引不重建

---

## Completion evidence

- **Final commit**: TBD
- **Tests**:
  - `tests/test_wiki/test_stage_multi.py`
  - `tests/test_wiki/test_refines_relation.py`
  - `tests/test_wiki/test_source_meta_url.py`
  - `tests/test_wiki/test_tool_type.py`
  - `tests/test_wiki/test_cross_field_validation.py`
  - `tests/test_pipeline/test_doc_classifier.py`
  - `tests/test_pipeline/test_completeness_checker.py`
  - `tests/test_pipeline/test_topic_clusterer.py`
  - `tests/test_pipeline/test_concept_deduplicator.py`
  - `tests/test_pipeline/test_slot_filler.py`
  - `tests/test_pipeline/test_relation_extractor.py`
  - `tests/test_pipeline/test_wiki_writer.py`
  - `tests/test_pipeline/test_audit_logger.py`
  - `tests/test_pipeline/test_content_filter.py`
  - `tests/test_server/test_search_stage_multi.py`
  - `tests/test_wiki/test_template_v7_1_1.py`
  - `tests/test_wiki/test_index_yaml.py`

- **Static checks**:
  - `python scripts/validate_novel_wiki_frontmatter.py --strict-v7.1.1`
  - `python scripts/validate_novel_wiki_template_slots.py --check-spec`
  - `python scripts/extract_eval.py`（A/B 对比）

- **Documentation updated**:
  - `knowledge/novel-wiki/CONTEXT.md`（V7.1.1 新增字段）
  - `docs/adr/ADR-003-decouple-template-slots-from-frontmatter.md`（更新 V7.1.1 引用）
  - `docs/superpowers/reports/2026-09-13-extract-pilot-report.md`（试点）
  - `docs/superpowers/reports/2026-09-14-extract-full-report.md`（全量）
  - `docs/superpowers/reports/2026-09-15-extract-eval-report.md`（A/B 评估）

- **Progress ledger updated**: yes/no