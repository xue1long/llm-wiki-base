# V7 extract Task 7 试点（2026-09-14）

- 新增 `scripts/extract_pilot.py`，直接执行时自动引导仓库根目录导入。
- 试点只读取 `raw/sources`，调用 Stage 1/3/4/5，输出 JSON/Markdown，不调用 Wiki writer，不写 `wiki/`。
- 50 篇真实素材 dry-run：`complete=43`、`incomplete=7`、`errors=0`、`topics/pages=60/60`。
- 已完成 10 篇代审：严格 accepted `1/10 = 10%`，低于 80% 门槛；报告保留逐篇理由，Task 8 全量 apply 继续阻断。
- Task 9 已增加写盘前敏感内容闸门；审核决定绑定内容 hash，accepted 只对同一内容生效。
