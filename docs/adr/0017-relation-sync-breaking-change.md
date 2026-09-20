# ADR: RelationSync.sync_page 语义从重置改为保留+追加，及反向边收集函数重构

- **状态**: accepted
- **日期**: 2026-09-20
- **触发**: 架构体检发现 `_compute_reverse_relations` 与 `RelationSync.sync_page` 存在同义重复实现与语义冲突（候选 3）。
- **关联**: `docs/superpowers/plans/2026-09-19-pipeline-ingest-relation-bug-fix.md`；dev-relay 阶段 4 成果。

## Context（背景）

- 历史遗留原因，`_compute_reverse_relations`（原 `src/pipeline/ingest.py:261`）重写了反向边收集逻辑，其文档注释明确说明：“sync_page resets a page's own relations to the passed list and would clobber an inverse edge that a prior page's sync just wrote.”
- 两个模块在同一知识库内形成了语义冲突：`sync_page` 采用覆盖式重置，导致依赖其写入的调用方容易踩坏已有关系；`ingest.py` 借此绕开了 `sync_page`。
- `Relation` 数据模型在本次修复中明确保持非冻结（`frozen=False`），以与 `batch_reconcile.py:133` 等处现有的 `inv.target_id = ...` 属性修改兼容。

## Decision（决策）

1. **修正 `RelationSync.sync_page` 语义**：
   - 不再将页面现有的 `relations` 彻底清空并重写，而是保留既有关系，追加新传入的关系，并以 `(target_id, type)` 为主键进行防重复判定（保留首个权重，`setdefault` 语义）。
2. **重命名 `_compute_reverse_relations` 为 `_collect_inverse_relations`**：
   - 明确其“仅内存收集/合并反向边，实际落盘由调用方通过 `AtomicContext` 批量事务完成”的定位，原名保留为废弃别名并发出 `DeprecationWarning`。
3. **标记 `target_resolver.resolve_wiki_target` 为废弃**：
   - 增加 `DeprecationWarning`，为后续大版本（Plan B）中全面收口至 `ResolvabilityIndex.resolve_with_kind` 铺平道路。

## Rationale（理由）

- 消除重复实现与设计冲突：`sync_page` 的保留+追加语义使得关系同步具备幂等性且不会踩坏既有边。
- 极小侵入性（Ponytail 敏捷原则）：放弃了激进的 `frozen=True` 全局修改，避免了对 `batch_reconcile.py` 等其他调用链路的大面积破坏。

## Consequences（后果）

### 收益
- 解决了页面多轮摄取与关系反向连接时的边丢失风险。
- 为 Plan B（全面 Strategy 化与索引收口）扫清了关系子系统的遗留阻碍。

### 遗留约束
- 外部如有强依赖“清空并覆盖关系”的极少数历史测试/调用方，需显式使用清空逻辑或升级调用。当前代码库内 500+ 个 wiki 测试已全部验证通过无回归。
