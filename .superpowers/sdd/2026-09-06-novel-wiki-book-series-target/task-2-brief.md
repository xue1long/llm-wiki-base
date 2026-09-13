# Task 2 — 建立页面归属基线

## Goal
在 Task 0 已通过的快照上，形成可审计的页面归属基线：每个 eligible page_id 只允许一个 primary book/chapter，secondary topics 只做引用；重复、未知、无来源页面进入挂账，不进入主教程正文。不得调用 LLM。

## Required behavior
- 复用现有 scanner/partition 和 Task 0 gate 结果，不复制页面正文。
- 记录 page_type、primary taxonomy、来源状态、重复哈希、归属裁决和 reason code。
- 生成稳定、可重放的 JSON/Markdown 基线产物，包含 snapshot fingerprint 和统计分母。
- 检测 duplicate page_id、重复 canonical hash、跨书 primary 冲突、未知 taxonomy、无来源页、孤立关系；失败应 fail-closed。
- 书籍不足时保留 reference/unassigned 挂账，不伪造主教程章节。
- 不改变旧 outline/release 读取路径。

## Files
- `src/kc/views/book/wiki/scanner.py` / `partition.py`（仅在必要时）
- 新增归属基线模块/报告（优先复用现有数据结构）
- `tests/test_kc/test_book_series_partition.py`

## Tests first
先写失败测试，至少覆盖：空快照、未知 taxonomy、重复 canonical、无来源、跨书冲突、稳定 fingerprint、唯一 primary、挂账不进入正文、旧兼容不变。

## Verification
使用 bundled Python，设置 TEMP/TMP/TMPDIR=.tmp-pytest；运行新增测试和 Task 0/Task 1 回归。追加 task-2-report.md，提交一个逻辑 commit。
