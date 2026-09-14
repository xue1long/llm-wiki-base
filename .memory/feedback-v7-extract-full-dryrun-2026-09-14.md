# V7 extract Task 8 全量 dry-run（2026-09-14）

- 新增 `scripts/extract_full.py`，按 500 条/批处理全部支持的 raw 文件，保存 checkpoint，失败最多重试 3 次。
- 当前 raw 清单为 1362 个文件；真实 dry-run 处理 3 批，0 errors，生成 1480 个候选 concept pages。
- 使用正式 checkpoint 重跑时 3 批全部跳过，`processed=0`，同时保留上次 1362 条结果明细。
- `--apply` 在人工 spot-check 批准前 fail-closed；没有写入 Wiki。
