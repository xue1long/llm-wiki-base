# 集成分支合并阻塞修复（2026-09-09）

## 结论

- LanceDB 0.27 的 `DeleteResult` 只有版本信息，不提供 `num_deleted_rows`；删除向量前用同一谓词 `count_rows`，再执行删除。
- 原子 Wiki flush 部分失败时，只清理明确失败页面的 lineage pending intent；成功页面仍保留可恢复记录，冲突保护不放宽。
- 书籍编译运行时需要 `PageRecord.sensitivity`、lineage build/release API 和 rubric fixture；缺失会在合并分支才暴露。

## 验证约束

Windows 宿主的全局配置目录和集成 worktree ACL 可能不可写。测试应使用临时 `RUFLO_CONFIG_DIR`、`DSH_WORKSPACE` 和可写 cwd；否则会把环境权限错误误判为代码回归。
