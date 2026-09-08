# Book 编译结果登记到 SQLite Lineage

## Context

项目需要管理大量 Raw/Wiki，能够判断处理状态、追溯 Book 来源，并在中断后恢复。Markdown 和 Book release 仍是内容与阅读产物，SQLite 负责状态和关系。

## Decision

Book 编译采用“文件发布 + SQLite 记录”的双写协议：

1. `apply=True` 的编译创建 `build_runs` 和章节 `build_members`；
2. 章节文件写入并校验 hash 后标记为 staged；
3. `CURRENT.json` 指针和 release manifest 发布成功后，才将 Book artifact、章节和构建任务标记为 published；
4. SQLite 写入失败时不宣称成功；下次打开 lineage store 只恢复指针、manifest 和文件 hash 均可验证的运行；
5. dry-run 不创建数据库或写入 lineage；现有历史文件不自动伪造历史记录。

## Consequences

- 文件仍可由 Git/Obsidian/阅读工具直接使用；
- `state.db` 可以查询 Raw、Wiki、章节和 Book release 的状态与 hash；
- 文件系统和 SQLite 不是单一物理事务，恢复逻辑必须保留；
- 现有 corpus 需要从启用时刻开始建立权威 lineage，不能仅凭文件存在推断历史。

## Alternatives

- 只写文件：无法可靠查询处理状态和恢复；
- 只写 SQLite：破坏 Markdown 内容与人工编辑边界；
- 将 lineage 逻辑塞进 `safe_write`：造成底层写入层与业务数据库耦合。

## Implementation Notes

实现位于 `src/lineage/api.py` 和 `src/kc/views/book/wiki/compiler.py`。`build-from-wiki` 是当前 Book lineage 登记入口。
