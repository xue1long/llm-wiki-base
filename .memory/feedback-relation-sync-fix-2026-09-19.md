# Plan A 实施与验证总结：关系同步语义与反向边收集重构 (2026-09-20)

## 背景与目标
在阶段 4 架构体检中，发现 `_compute_reverse_relations` 与 `RelationSync.sync_page` 存在逻辑重复与破坏性覆盖问题。通过多角色交叉审查，将庞大的重构拆分为轻量级的 Plan A（Bug 修复）与后续 Plan B（架构拆解）。

## 完成的工作
1. **Task 1 (commit `7a432242`)**:
   - 修正了 `RelationSync.sync_page` 的语义，不再覆盖重置页面关系，而是保留既有关系、追加新关系，并通过 `(target_id, type)` 进行幂等去重。
   - 补齐了针对此变更的 5 个行为测试，全量 524 个 wiki 测试无一回归。
2. **Task 2 (commit `fcd85580`)**:
   - 将 `src/pipeline/ingest.py` 中的 `_compute_reverse_relations` 重命名为 `_collect_inverse_relations`，以消除对其“写盘”职责的误解。
   - 保留原函数名为废弃别名，添加 `DeprecationWarning`，平滑兼容所有历史调用。
   - 补充 4 个关于别名兼容与行为一致性的单元测试。
3. **Task 3 (commit `8157e0d6`)**:
   - 在 `target_resolver.resolve_wiki_target` 入口处补充 `DeprecationWarning`，为 Plan B 的统一索引铺垫。
   - 补充测试断言此警告。
4. **Task 4**:
   - 沉淀 `docs/adr/0017-relation-sync-breaking-change.md` 并更新索引。
