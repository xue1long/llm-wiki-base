# V7 extract Task 7 试点（2026-09-14）

- 新增 `scripts/extract_pilot.py`，直接执行时自动引导仓库根目录导入。
- 试点只读取 `raw/sources`，调用 Stage 1/3/4/5，输出 JSON/Markdown，不调用 Wiki writer，不写 `wiki/`。
- 50 篇真实素材 dry-run：`complete=43`、`incomplete=7`、`errors=0`、`topics/pages=60/60`。
- `spot_check` 与准确率保持 pending；未完成人工审核前不进入 Task 8 全量抽取。
