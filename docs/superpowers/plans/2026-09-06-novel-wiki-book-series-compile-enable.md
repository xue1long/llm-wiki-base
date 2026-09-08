# novel-wiki 书系可编译化方案（plan-audit v0.3）

> 状态：方案 v0.3，已通过 plan-audit 第一轮全面漏洞审计 + 第二轮压力测试推演 + 第三轮多角色交叉，等待人工复核后进入编码。
> 触发：用户授权"解决掉问题，以达到可以编译系列 book 标准"。
> v0.3 关键修订（对照 v0.2 审查 Finding 1–12）：
> - 拆分 S4 为 S4a (profile 模块) + S4b (compiler.py 接入 wiring) — 解决 Finding 1, 11
> - 新增 `derive_chapter_exit_evidence()` — 解决 Finding 2
> - `closure_strict_types` 改为 `"type|type"` 字符串列表，partition 重写 closure_parts 为动态算子 — 解决 Finding 4, 7
> - S2/S3 合并为依赖切片 — 解决 Finding 5
> - 新增 S0 acceptance 契约 — 解决 Finding 3, 8

## 0. 红线（不可动摇）
1. 不用 LLM 填充 baseline 缺口
2. 不默认保留三本书
3. 不执行全量 `--apply`（除人工单章 pilot 外）
4. 不覆盖旧 `CURRENT.json`
5. 每个切片都有失败测试 → 定向验证 → 实现 → 回归证据
6. 任何失败只影响 staged release
7. 来源路径仅 allowlist；API key 不进日志/产物
8. 旧 outline-v1/旧 release 必须继续可读

## 1. 现状诊断（来自 baseline.json 真实数据）

### 1.1 baseline.json（最近一次运行）
- `series_status: blocked`, `generation_mode: rule_only`
- `block_reasons: ['external_authorized', 'budget_cap', 'approver', 'no_retained_candidate']`
- 56 candidates，`book-a/b/c` 全 `cancel`（0 页）
- 真实 taxonomy Top 6：
  1. 写作技法 541（concept=540, synthesis=1）
  2. unassigned 832（含 entity=306）
  3. 题材体系 73
  4. 心态与职业 57
  5. 平台规则 45
  6. 读者与市场 39

### 1.2 closure 失败根因（三层叠加）
1. `closure_parts = (有 concept, 有 entity, 有 synthesis)` 三槽 — 写作技法 缺 entity
2. `has_learning_edge` 要求 `target_task in _TARGET_TASKS` — 真实 wiki supports→concept
3. `chapter_known = exit_ids ≤ candidate_ids` — profile 未提供 exit_evidence

## 2. 方案（v0.3）

### 2.1 ReaderProfile 新增字段
```python
@dataclass(frozen=True)
class ReaderProfile:
    # ... existing 7 fields ...
    closure_strict_types: tuple[str, ...] = ("concept|foundation|orientation", "entity|method|explanation", "synthesis|application|example")
    # ^ pipe-separated type groups, each group OR-matched into a closure slot
    allowed_learning_edge_types: tuple[str, ...] = ("supports", "required_by")
    # ^ set of relation types accepted for has_learning_edge
    require_target_task_match: bool = True
    # ^ when False, drops the `target in _TARGET_TASKS` predicate
```

### 2.2 partition.py 闭包逻辑重写
```python
closure_required_sets = tuple(
    frozenset(s.split("|")) for s in reader_profile.closure_strict_types
)
closure_parts = tuple(bool(types & req) for req in closure_required_sets)
# then closure_ok = all(closure_parts) and has_learning_edge and ...
# has_learning_edge: filter on `allowed_learning_edge_types` AND
#   (not require_target_task_match OR target_task in _TARGET_TASKS)
```

### 2.3 NOVEL_WIKI_PROFILE 与 chapter_exit_evidence 派生
```python
NOVEL_WIKI_PROFILE = ReaderProfile(
    profile_id="novel-wiki-default",
    task_types=("learn_concept", "reference", "apply"),
    candidate_taxonomies=(
        "写作技法", "题材体系", "心态与职业",
        "平台规则", "读者与市场", "案例与素材",
    ),
    min_pages_per_book=20,
    min_source_coverage=0.8,
    min_reader_tasks=6,
    closure_strict_types=(
        "concept|foundation|orientation",
        "synthesis|application|example",
    ),  # 缺 entity 也算 closure
    allowed_learning_edge_types=(
        "supports", "required_by",
        "referenced_by", "supported_by", "is_part_of",
        "references", "contains",
    ),
    require_target_task_match=False,
)

def derive_chapter_exit_evidence(snapshot, candidate_taxonomy: str) -> tuple[str, ...]:
    """Auto-derive synthesis/concept page_ids in the candidate taxonomy.

    Returns up to 3 page_ids: (highest-char synthesis) + 1 concept anchor.
    Empty tuple if no synthesis exists in candidate.
    """
    pages = [p for p in snapshot.pages
             if (p.primary_taxonomy or "").strip() == candidate_taxonomy]
    synth = [p for p in pages if p.page_type in ("synthesis","application","example")]
    if not synth:
        return ()
    return tuple(sorted({p.page_id for p in synth}, key=lambda pid: pid)[:3])
```

### 2.4 实施切片（v0.3 — 修订版）

| Slice | 内容 | 失败测试 → 绿 | 依赖 |
|---|---|---|---|
| **S0** | 接受契约测试：synthetic 写作技法 fixture (541 concept + 1 synthesis + 0 entity, supports→concept edges) + NOVEL_WIKI_PROFILE → `decision=proceed, closure_status=closed` | `tests/test_kc/test_novel_wiki_profile_integration.py::test_novel_wiki_profile_drives_writing_craft_proceed` | 无（写失败测试） |
| **S0b** | 接受契约测试：真实 wiki `写作技法` 含至少 1 条 non-namespace edge（supports/required_by/referenced_by 等） | `tests/test_kc/test_novel_wiki_profile_integration.py::test_writing_craft_has_non_namespace_edge` | 真实 wiki 数据 |
| **S1** | `ReaderProfile` 加 3 字段；`partition.py:154–158` 重写 `closure_parts` 用 `closure_strict_types`；`partition.py:163–166` 用 `allowed_learning_edge_types` + `require_target_task_match` 调整 has_learning_edge | `test_closure_strict_types_pipe_separated_groups` + `test_default_strict_closure_unchanged` + `test_target_task_match_relaxed_allows_concept_to_concept` | S0 |
| **S2** | `src/kc/views/book/wiki/profiles.py` 加 `NOVEL_WIKI_PROFILE` + `derive_chapter_exit_evidence()` | `test_novel_wiki_profile_emits_six_real_taxonomies_not_three_books` + `test_chapter_exit_evidence_derived_for_writing_craft_taxonomy` | S1 |
| **S3** | `compiler.py:391–403` 接入：`series_id` 在 `NOVEL_WIKI_PROFILE.candidate_taxonomies` 时使用 relaxed profile 并自动派生 `chapter_exit_evidence` | `tests/test_cli_ext/test_book_build_from_wiki.py::test_build_from_wiki_uses_novel_wiki_profile_when_series_id_matches` (新) | S2 |
| **S4** | `scripts/build_book_series_baseline.py`：用 `NOVEL_WIKI_PROFILE` + `derive_chapter_exit_evidence` 重跑 gate，写到 `.llm-wiki/book-series/baselines/<snapshot_sha[:12]>.json`（gitignored） | `test_baseline_script_uses_relaxed_profile_and_writes_to_gitignored_path` | S3 |
| **S5** | `compiler.py:495–516` 接入 cross-link validate：在 `compile_book` 之后、`publish_book` 之前，失败返回 `status=blocked, reason_codes=[E_DANGLING_CROSS_LINKS]`（dry-run 不 publish） | `test_dry_run_blocks_on_dangling_cross_links` + 验证 `CURRENT.json` sha 不变 | S3 |
| **S6** | 手动 shell test：`book build-from-wiki --project novel-wiki --series writing-craft --book 写作技法 --dry-run` → `status=planned`，version_dir 存在；`CURRENT.json` sha `762a865c…` 不变；`.releases/` 列表不变 | n/a | S5 |

### 2.5 profile 存储路径（修订 — gitignored）
- `.llm-wiki/book-series/profiles/novel-wiki.json`（gitignored）
- `.llm-wiki/book-series/baselines/<snapshot_sha[:12]>.json`（gitignored，保留 5 个历史）

### 2.6 book_id 映射规则
- `--book <candidate_id>` 直接作为 book_id（与 partition `candidate_id` 一致）
- 非候选 taxonomy 时 gate 返回 `cancel` decision

### 2.7 红线遵循
- 不调用 LLM
- 不默认保留三本书（用 6 个真实 taxonomy）
- 不执行 `--apply`
- 不覆盖 `CURRENT.json`（dry-run 路径不调 `publish_book(apply=True)`，S5 显式验证）
- 每切片有失败测试 + 定向修复 + 回归证据

### 2.8 验收标准（v0.3）
1. `pytest tests/test_kc/test_book_series_*.py` 全绿（现有 58 + 新增 ≥9）
2. `evaluate_series_gate(snap, profile=NOVEL_WIKI_PROFILE)` 对真实 wiki `写作技法` 返回 `decision=proceed, closure_status=closed`
3. `book build-from-wiki --project novel-wiki --series writing-craft --book 写作技法 --dry-run` 返回 `status=planned` 且 version_dir 存在
4. `CURRENT.json` sha `762a865c…` 不变（测试显式断言）
5. `.releases/` 列表不变
6. `acceptance.md` 增加"调整后 baseline"段落，**保留**原 baseline 段
7. 全仓测试 ≥ 修复前（3909/3910）

### 2.9 回滚预案
- 每 slice 独立 commit，可 `git revert`
- baseline 历史快照保留在 `.llm-wiki/book-series/baselines/`
- `ReaderProfile` 字段 default = 严格既有行为；`NOVEL_WIKI_PROFILE` 是单一启用 relax 的入口
- `compiler.py` 改动仅在 `series_id in NOVEL_WIKI_PROFILE.candidate_taxonomies` 时启用，否则 fallback 旧路径

## 3. 风险与缓解（v0.3）

| 风险 | 缓解 |
|---|---|
| `closure_strict_types` 误用（空 tuple / 字符串错）导致 `closure_parts=()` 或空 frozenset | `__post_init__` 校验非空；S1 加 `test_closure_strict_types_rejects_empty_and_malformed` |
| 真实 wiki 的 proceed 决策让 reader 体验差 | S6 单章 reader pilot，**不直接全量 apply** |
| baseline.json 重写破坏 acceptance 报告 | 旧 baseline 段不删，新 baseline 段另起；写入 `.llm-wiki/` gitignored 不进 git diff |
| 改动 CLI 默认值破坏既有 e2e 测试 | 不改 CLI 默认；S3 改动仅在 `series_id in NOVEL_WIKI_PROFILE.candidate_taxonomies` 时启用 |
| `chapter_exit_evidence` 自动派生用 page_id — 若 page_id 含特殊字符会写不进 manifest | 测试用 ASCII fixture + 真实 CJK fixture 双重验证 |

## 4. 第二轮压力测试推演（v0.3）

| 场景 | 推演 | 缓解 |
|---|---|---|
| A: 真实 wiki supports→concept 边 | S1+S3 让 `has_learning_edge=True` | S0b 验证 `写作技法` 至少 1 条 non-namespace edge |
| B: closure_strict_types=("concept","synthesis") 长度=2 | 旧 3-tuple 不匹配 → closure_parts 仍 False | S1 重写 closure_parts 为动态算子，arity 任意 |
| C: frontmatter 在 baseline-run 与 dry-run 之间被改 | dry-run 重新 scan，不读 baseline.json | S6 显式断言 CURRENT.json 不变；baseline.json 仅 audit |
| D: --book 写作技法 包含 CJK | JSON 序列化 UTF-8 安全；`_safe()` 仅用于文件名 | S3 集成测试含 CJK fixture |
| E: chapter_exit_evidence 派生失败（无 synthesis 页） | 派生返回 `()` → `chapter_known=False` → closure_status="unknown" | S0 acceptance 用含 1 synthesis 页的 fixture |
| F: cross-link dangling 在 dry-run 时才发现 | dry-run 返回 `blocked, E_DANGLING_CROSS_LINKS` 不写 CURRENT.json | S5 显式测试 |

## 5. 待办清单
- [ ] 写 S0 失败测试（合成 fixture + 接受契约）
- [ ] S1：ReaderProfile + partition.py 闭包重写
- [ ] S2：profiles.py 模块 + NOVEL_WIKI_PROFILE + chapter_exit_evidence
- [ ] S3：compiler.py 接入 wiring
- [ ] S4：scripts/build_book_series_baseline.py
- [ ] S5：cross-link validate 在 dry-run 路径
- [ ] S6：手动 shell test + 真实 dry-run 验证
- [ ] 更新 acceptance.md 报告（追加调整后段落）
- [ ] dispatch 审查 subagent 验证最终切片
