# novel-wiki Task 5 canary 与恢复

- 3 个真实 raw 在隔离项目副本中通过批门禁，生成 6 个派生页；离线 fake provider 只作为流程与安全证据，不能证明语义质量。
- 首次失败演练暴露 LanceDB 0.27 `DeleteResult` 没有 `num_deleted_rows`，以及相对 `--root` 导致 lineage pending reservation 清理路径错误；两处已修复并加入回归。
- 注入写入失败后批次进入 `partial_commit`，raw 哈希保持不变；清除故障后 `--resume` 恢复到 `committed/done`。
- 放行边界：只允许当前 15 页 actionable 写作索引继续受控 canary；全库仍有 1206 pending，禁止全量扩展。
