# Plan: Task 51 — canonical_id 与 page_id 的 migration 工具

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第四批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 51)

## 0. 上下文

master plan §6 提及：旧 wiki page（无 canonical_id 关联）需要 migration 工具。
本 Task 实现一个**只读分析器** + **可选 dry-run 应用器**：
- `analyze_unmigrated_pages(project_root)` 返回旧 page 列表 + 建议的 canonical 关联
- `migrate_pages(..., *, dry_run=True)` 输出迁移报告

**重要**：默认 **dry-run only**，**不**自动改写 page frontmatter。需用户显式调用 `dry_run=False`。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `MigrationReport` dataclass：scanned / already_migrated / would_migrate / unmigrated
2. `analyze_unmigrated_pages(project_root, *, registry)` 函数返回 report
3. CLI 入口：`ruflo migrate-pages --dry-run / --apply`
4. 5 个测试覆盖：empty / no-canonical / some-migrated / dry-run / apply

### 1.2 Non-Goal

- **不**改 page frontmatter（除非显式 `dry_run=False`，且测试覆盖）
- **不**做 LLM-driven canonical suggestion（用简单 alias 匹配）
- **不**跨项目迁移

## 2. 模型

```python
@dataclass
class MigrationReport:
    scanned_pages: int
    already_migrated: int          # canonical_id 已在 frontmatter
    would_migrate: list[tuple[str, str]]   # (page_id, suggested_canonical_id)
    unmigrated: list[str]          # 无法匹配的 page_id
    dry_run: bool
    applied: bool = False
```

## 3. Files

- `src/reconciliation/migrate_pages.py`（新建）
- `tests/test_reconciliation/test_migrate_pages.py`（新建）

## 4. Tests

```python
def test_analyze_empty_project():
    """空 wiki/concepts/ → 0 scanned"""

def test_analyze_finds_pages_without_canonical_id_in_frontmatter():
    """page frontmatter 无 canonical_id → unmigrated"""

def test_analyze_skips_pages_with_canonical_id():
    """page frontmatter 含 canonical_id → already_migrated"""

def test_migrate_dry_run_does_not_modify_files():
    """dry_run=True → 不写盘"""

def test_migrate_apply_writes_canonical_id_to_frontmatter(tmp_path):
    """dry_run=False → page frontmatter 加 canonical_id 字段"""
```

## 5. Implementation

```python
def analyze_unmigrated_pages(
    project_root: Path | str,
    *,
    registry: CanonicalRegistry | None = None,
) -> MigrationReport: ...

def migrate_pages(
    project_root: Path | str,
    *,
    dry_run: bool = True,
    registry: CanonicalRegistry | None = None,
) -> MigrationReport:
    """若 dry_run=False → 改 page frontmatter 加 canonical_id 字段"""
```

**简单 alias 匹配**：`registry.get_by_alias(page.title)` 命中即建议；
否则尝试 `page.title` 中含 canonical preferred_label 子串 → 匹配。

## 6. Acceptance

- ✅ 5 个测试全绿
- ✅ dry-run 默认安全
- ✅ 现有 38 reconciliation 测试 0 回归
- ✅ 不引入新依赖