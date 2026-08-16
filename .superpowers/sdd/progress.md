# progress — novel-wiki v3 写作知识库方案（执行账本）

> 方案：`docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md`
> 计划：`docs/superpowers/plans/2026-08-15-novel-wiki-writing-template.md`
> 续接：`.memory/handoff-novel-wiki-phase1-2026-08-15.md`

## 状态总览

| Phase | 状态 | 说明 |
|---|---|---|
| Phase 0 基线+盲区+index | ✅ | 见 handoff（0.1/0.2/0.3） |
| Phase 1 平台改造 | ✅ 10/10 | 见 handoff（1.1–1.9 + 1.3 对账 + 1.9 备注） |
| **Phase 2 场景模板落地** | ✅ 2/2 | 2.1 + 2.2 已完成（2026-08-16） |
| Phase 3 实测首轮 | ⚠️ 部分达标 | 链路跑通 + 4 缺陷修复；M1/M4 残留 → **回 Phase 1 修**（见下） |
| Phase 4 全量分批重摄入 | ⬜ | 未开始（等 Phase 1 follow-up） |
| Phase 4.5 synthesis 聚合 | ⬜ | 未开始 |
| Phase 5 终验 | ⬜ | 未开始 |

## Phase 2 任务记录（2026-08-16）

### 2.1 schema/purpose/taxonomy 落盘 — ✅ commit `7c25c625`

- **产出**：
  - `knowledge/novel-wiki/schema.md`（spec §4.1：4 内置类型 + 写作域 Conventions，无自定义类型）
  - `knowledge/novel-wiki/purpose.md`（spec §4.2：可检索/可执行/可证伪 + procedure 优先）
  - `knowledge/novel-wiki/taxonomy.md`（spec §4.3：6 分类轴 43 值，strict 解析通过）
  - `knowledge/novel-wiki/taxonomy_tags.md`（spec §4.4 独立文件：情绪/场景阶段/读者群/平台 枚举 + 保留前缀 + H4 并集过渡注记；独立于 taxonomy.md 防 O5 污染分类命名空间）
  - `tests/test_pipeline/test_schema_purpose_injection.py`（6 测试：资产落盘 + taxonomy strict + schema 无自定义 + purpose 标记 + tags 枚举 + **注入链路** generate_ingest 重读 project-root 三件套进 prompt）
- **验收**：`TaxonomyRegistry.from_project(novel-wiki, strict=True)` OK；`validate('写作技法','人物塑造')==[]`、bogus 报错；tags `读者群/男频` 通过、`读者群/其它` 违规；注入链路首调用 prompt 含 purpose/taxonomy/schema 文本。
- **环境注记**：真实解释器 `C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe`（WindowsApps 别名是空 stub，沙箱拒绝执行；py/conda/标准路径均无）。跑测试需 `$env:PYTHONPATH="."`；CLI 从非 repo cwd 跑需 `PYTHONPATH=<repo>`。

### 2.2 项目级模板 v3.0.0 确认 — ✅ commit `70515fdb`

- **产出**：`tests/test_wiki/test_templates_resolver.py` 新增 2 测试：
  - 项目级优先级命中 novel-wiki（4 模板 source=="project"、version=="3.0.0"、路径在项目 `.wiki-templates/`）
  - 零采纳可选槽（limitations?/conflicts?/source_meta?）已从项目模板清除
- **确认**：4 模板与 spec §4.5 一致（concept 8 必填 / source 5 必填 / entity 4 必填+aliases? 可选 / synthesis 5 必填）；`wiki-templates list`（cwd=novel-wiki）全部 project 3.0.0 ok；lint 解析 3.0.0 槽集正确（与 test_templates_v3.py EXPECTED 一致）。
- 旧 concept.md（ed2c6521 引入可选槽）已在 Phase 1.1 d5120d7c 被 v3.0.0 替换，无残留。

## Phase 3 实测首轮记录（2026-08-16）⚠️ 部分达标，回 Phase 1 修

**执行**：
- `scripts/plan_gap_first_batch.py`（新建）：B12 缺口优先清单生成器（unreferenced_raw 63 + hallucinated 70 → 47 可对齐 raw → 取 ≤20 个 ≤8000 字符 .md，排除 download_progress/长文档），落盘 `.index/reingest_backlog.json`
- `scripts/phase3_accept.py`（新建）：批内验收（mtime 窗口 + v3.0.0 版本双重过滤确定批内集合 → batch_gate_v3.gate_batch → 断言 M1/M4/M7/M6）
- 实测：18 raw（跳过 2 个问题文件）→ 110 页 commit，`gate PASS`、`POSTCHECK 过`，~27 次 LLM 调用；gap 账本落地 10 条

**Phase 3 实测发现的 4 个缺陷（已修复 + 提交）**：
1. `fix(pipeline): commit_ingest 接受 event 参数`（fe2e484b）——extras 反向关系页提交必失败（phase4_batch 传 event= 但签名无此参数）
2. `fix(lint): MISSING-SECTION 版本门——存量 2.0.0 页按 bundled 2.0.0 槽检查`（e601cc30）——项目级 v3.0.0 模板下 2.0.0 页被误要求 v3.0.0 槽
3. `fix(scripts): phase4_batch 透传 missing_slugs → commit_ingest`（9c45665c）——gap 账本在 batch 路径从未写入（1.3 O6 接线缺口）
4. `fix(wiki): M1 断链判定归一 slug 变体`（99480152）——双横线假断链

**验收结论（`.index/batch_reports/batch_001.json`，不入 git）**：
- ✅ 达标：M4 missing_sections=0、M7 全文污染=0、M6 synthesis 触发（1 页）、链路/门禁/POSTCHECK 全过
- ❌ 不达标：M1 批内残留 2 个断链（`玄幻小说→[[玄幻与仙侠区分对比]]`、`都市重生→[[重生文]]`——collect_missing_slugs 覆盖缺口，存量重建页引用未捕获）、M4 占位符 17 个（generator prompt 教 LLM 填"来源未提供具体例子"与 lint ERROR 冲突）
- 按 plan guidance 第 4 条：**任一不达标 → 回 Phase 1 修，不进入 Phase 4**

**Phase 1 follow-up 待办**（下次会话起点）：
- A. generator prompt 移除"来源未提供具体例子" fallback 指示（与 lint `_PLACEHOLDER_SUBSTRINGS` 对齐；改为省略空槽或改写）——M4 占位符归零
- B. collect_missing_slugs 对存量重建页（--allow-overwrite 覆盖的旧页）的引用捕获覆盖——M1 归零
- C. （可选）batch_gate_v3 的 gap 剔除用归一后匹配（当前精确匹配，gap 变体可能漏）

**环境注记（追加）**：真实 LLM provider = `sfkey-glm`（glm-5.2 @ api.sfkey.cn，注册于 `%LOCALAPPDATA%\ruflo-kb\ruflo-kb\llm-providers.json`）；`~/.config/ruflo-kb/env` 的 `RUFLO_LLM_PROVIDER=sfkey-glm` 是旧壳。Ollama 不可达。

## 回归

- `tests/test_wiki/` 399 passed；注入链路 + taxonomy/schema/tags 相关 57 passed；Phase 3 修复后 metrics/lint/retry/split 相关全绿。

## 下一步

**Phase 1 follow-up**（Phase 3 门槛未过，不进入 Phase 4）：
- A. generator prompt 占位符 fallback 与 lint 对齐（M4）
- B. collect_missing_slugs 存量重建页引用捕获（M1）
- 修复后重跑 batch_001 验收，达标才进 Phase 4 执行模型重写。
