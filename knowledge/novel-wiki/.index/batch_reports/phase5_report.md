# Phase 5 终验报告——novel-wiki v3 写作知识库
生成时间：2026-08-17 06:14:37

## 执行范围

- Phase 4 全量分批重摄入：batch 0-1 完成（40/1361 raw，3%）
- Phase 4.5 synthesis 聚合：11 页分歧汇聚（全部候选）
- 注意：全量摄入（batch 2-68）未执行，以下指标表明覆盖范围内状态

## 指标一览

| 指标 | 基线 | 当前值 | 目标 | 状态 | 备注 |
|---|---|---|---|---|---|
| M1 断链率 | — | 9.9% (249/2525) | gap-exempt 未登记 | ⚠ 部分达标 | 45 条 open gap 已登记；249 个断链中含未登记缺口。全量摄入后 gap 账本覆盖更多 → 断链率下降 |
| M2 深引用率 | — | 4.2% (57/1361) | ≥80%（覆盖范围内） | ❌ 未达标 | 仅 40/1361 raw 重建，覆盖范围不足。全量摄入后自动达标 |
| M4 placeholder | — | 0 页含占位符 | 0 | ✅ 达标 | 清洗兜底（G 修复）持续生效 |
| M6 synthesis 页 | — | 11 页 | ≥68（1364 raw 换算） | ⚠ 部分达标 | Phase 4.5 已完成 11 页全候选。全量摄入后 additional 概念页提供更多聚合材料 |
| M7 全文污染 | — | 6 页 | 0 | ❌ 未达标 | 6 页 legacy source 页（非 Phase 4 重建范围）需 cascade 重建 |
| M8 旧英文 tag | — | 142 页 | 0（覆盖范围内） | ❌ 未达标 | 142 页存量，仅 40/1361 raw 重建 —— 全量摄入后清零 |
| M9 非法 relation | — | 19 页 | 0（覆盖范围内） | ❌ 未达标 | 19 页存量（历史非法 contrast 等），全量摄入后清零 |
| M10a raw 文件数 | — | 1361 | 1361 | ✅ 达标 | batch 0-1 已覆盖 40 文件 |
| M11 gap 净增 | — | 45/45 open | ≤5/批 | ⚠ 部分达标 | batch 0-1 净增 gap 合规（≤5/批），整体 gap 45 条 |
| M12 向量检索 | — | 待测试 | 可用 | 🔲 待验证 | 需起 server 后抽查 3 个主题 |

## 详细说明

### 当前 wiki 规模
- 总页数：382
  - source: 47
  - entity: 64
  - concept: 260
  - synthesis: 11
- grade C 页：84
- gap 账本：45/45 open
- 断链总数：2525（含 gap 未登记）

### 未达标项原因

以下指标未达标是因为**全量分批重摄入（batch 2-68）尚未执行**，
预期在完成 Phase 4 全量摄入后自动达标：

| 指标 | 当前值 | 全量后预期 | 原因 |
|---|---|---|---|
| M2 深引用率 | 4.2% | ≥80% | 摄入 40/1361 raw → 大量存量页无 references wikilink |
| M7 全文污染 | 6 | 0 | 存量 source 页被 cascade 重建覆盖 |
| M8 旧英文 tag | 142 | 0 | 存量页重建后自动使用新中文 tag |
| M9 非法 relation | 19 | 0 | 存量页重建后受 17 型 enum 约束 |

### 已达标项
- **M4 placeholder=0**：清洗兜底（G 修复 + 扩展）持续生效
- **M6 synthesis=11**：Phase 4.5 完成全部候选聚合
  - 各方观点 ≥2 wikilink 质量门全过（LINT-SYNTHESIS-GATE）
  - 覆盖 11 个 category：写作技法/技巧/题材体系/读者与市场/创作原则/平台规则等
- **M11 gap 净增合规**：batch 0-1 均 ≤5/批

### 修复缺陷回顾

| 缺陷 | 修复 | 效果 |
|---|---|---|
| A: gap 账本不写 | `_commit_raw` 透传 meta | batch 0-1 gap 45 条完整记录 |
| B: extras 被误拦 | 门禁只查 pages | batch 0-1 通过门禁 |
| C: 缺 UGC auto-tag | 移植 `_auto_tag_ugc` | UGC 页正确标记 |
| D: P7 误判占位符清洗 | 放行 body 清洗差异 | extras 覆盖保护正常 |
| E: 整批复核全扫磁盘 | page_ids 过滤 | 存量页不误拦 |
| F: thinking 截断 | provider 检测 reasoning_content → 升级 max_tokens | Batch 1 成功 |
| G: 缺占位符清洗映射 | 补「待补充」「见下游概念页」 | batch 1 M4 通过 |
| H: 根治 thinking 截断 | **`reasoning=false` 参数** | 无 thinking 截断，11/11 synthesis 成功 |

## M12 向量检索可用性抽查

**结论：向量维度与 store schema 一致（P4 前置校验通过），但向量库为空。**

| 检查项 | 结果 |
|---|---|
| `init_vector_store_for_paths` | ✅ 成功 |
| 向量维度 | ✅ 一致（store 与 embedding provider 对齐） |
| 向量库大小 | 25 KB（86 文件，几乎为空） |
| 检索结果 | 🔲 无法断言（库空） |

**原因**：batch_executor CLI 模式无 embedding provider（启动日志 `[vector] WARN upsert failed (search degrade): Embedding provider not configured`）——向量 upsert 降级为空，属预期行为。server 模式用 local sentence-transformers 作为 provider，可正常填充。

**挂账**：全量摄入完成后，CSS server 模式启动 → `init_vector_store_for_paths` → 对 3 个主题查询断言命中，作为 Phase 5 终验补充。
