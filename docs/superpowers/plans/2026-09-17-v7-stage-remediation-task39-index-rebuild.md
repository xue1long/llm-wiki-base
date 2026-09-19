# Plan: Task 39 — Stage 7 Index rebuild 命令

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 39)

## 0. 上下文

现有 `WikiWriter._append_index` 在 commit_and_index 末尾 incremental append。
当 wiki/index.md 因外部原因（人工编辑、批量回滚、磁盘故障）变得不一致时，
需要从磁盘扫描 `wiki/concepts/*.md` 重建。

**Task 39 目标**：增加 `WikiWriter.rebuild_index()`（或在 scripts 侧加 CLI）扫所有
已 committed 的 wiki page frontmatter（按 `pages_dir` 扫描），重生 `wiki/index.md`。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `WikiWriter.rebuild_index()` 方法
2. `python -m src.cli serve / build` 或独立 `scripts/rebuild_index.py` 入口
3. 重生 index.md 后保持现有 append_index 兼容（重新增量时不会重复行）

### 1.2 Non-Goal

- **不**改 frontmatter schema
- **不**改 checkpoint 持久化
- **不**改 write 路径（仅加 read-from-disk 入口）

## 2. Files

- `src/pipeline/v7_extract/wiki_writer.py`（追加 `rebuild_index` 方法）
- `tests/test_pipeline/test_v7_extract_stage7.py`（追加 2 测试）

## 3. Tests

```python
def test_rebuild_index_reads_existing_pages_from_disk(tmp_path: Path):
    """预先在 wiki/concepts/ 放 2 个 page md，跑 rebuild_index → index.md 含两条"""

def test_rebuild_index_handles_empty_pages_dir(tmp_path: Path):
    """空目录 → index.md 仅含 header，无 rows"""
```

## 4. Implementation

```python
def rebuild_index(self) -> int:
    """Scan self.pages_dir for .md files; parse frontmatter (yaml.safe_load).
    
    Extract (id, title, type). Append to wiki/index.md in sorted order (id asc).
    
    Returns: count of pages indexed.
    
    Defensive:
      - .md without frontmatter → skip + log warning
      - missing 'id' or 'title' in frontmatter → skip
      - atomic write (tmp + rename), same as _append_index
      - existing index.md is overwritten (full rebuild semantics)
    """
```

## 5. Acceptance

- ✅ 重建 index.md 含所有 disk 上 page
- ✅ 空目录 → 仅 header
- ✅ 现有 15 个 stage7 测试 0 回归
- ✅ 不引入新依赖