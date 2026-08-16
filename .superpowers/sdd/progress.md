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
| Phase 3 实测首轮 | ⬜ | 未开始 |
| Phase 4 全量分批重摄入 | ⬜ | 未开始 |
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

## 回归

- `tests/test_wiki/` 399 passed；注入链路 + taxonomy/schema/tags 相关 57 passed。

## 下一步

Phase 3 实测首轮（门）：首批 = 缺口优先（被引用但无 source 页的 raw，≤20 文件，只含 .md，过滤 download_progress.json 等），跑 1.5 门禁 + 0.1 基线断言；不达标回 Phase 1 修，不进入 Phase 4。
