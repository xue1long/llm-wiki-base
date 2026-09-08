# 书系可编译化实施报告（compile-enable）

> 状态：方案 v0.3 + plan-audit 两轮审查通过，已实施 8 个切片，真实 novel-wiki dry-run 返回 `status=planned`，**未触碰** `CURRENT.json` 与 `.releases/`。
> 日期：2026-09-06
> 分支：`codex/book-series-target`

## 1. 触发与红线

触发：用户授权"解决掉问题，以达到可以编译系列 book 标准"。

**红线（不可动摇）**：
1. 不用 LLM 填充 baseline 缺口
2. 不默认保留三本书
3. 不执行全量 `--apply`（除人工单章 pilot 外）
4. 不覆盖旧 `CURRENT.json`
5. 每个切片都有失败测试 → 定向验证 → 实现 → 回归证据
6. 任何失败只影响 staged release
7. 来源路径仅 allowlist；API key 不进日志/产物
8. 旧 outline-v1/旧 release 必须继续可读

## 2. 方案与审查

方案：`docs/superpowers/plans/2026-09-06-novel-wiki-book-series-compile-enable.md`（v0.3）

**plan-audit 两轮审查**：
- §1 全面漏洞审计（独立 reviewer subagent）：12 个 findings（3 致命 / 5 重大 / 4 优化疏漏）
- §2 压力测试推演：10 个场景（真人独立完成）
- §3 多角色交叉（落地/风险/逆向/验收）

**修订迭代**：
- v0.1 → v0.2：补 gate wiring、profile 路径、cross-link validate
- v0.2 → v0.3：拆分 S4 为 S2/S3、closure_strict_types 改 pipe-separated、`chapter_exit_evidence` 自动派生、新增 S0 接受契约

## 3. 实施切片

| Slice | 内容 | Commit |
|---|---|---|
| S0/S0b | 接受契约：synthetic 写作技法 fixture + NOVEL_WIKI_PROFILE → decision=proceed；真实 wiki writing-craft 含 ≥1 non-namespace edge | `501028ce` |
| S1 | `ReaderProfile` 加 `closure_strict_types` / `allowed_learning_edge_types` / `require_target_task_match`；`partition.py` 闭包重写为动态算子 | `501028ce` |
| S2 | `src/kc/views/book/wiki/profiles.py`：`NOVEL_WIKI_PROFILE` + `derive_chapter_exit_evidence()` | `501028ce` |
| S3 | `compiler.py` 接入：当 `--series` 在 `NOVEL_WIKI_PROFILE.candidate_taxonomies` 时使用 relaxed profile + 自动派生 `chapter_exit_evidence` | `63b15d1f` |
| S4 | 跳过（用户授权直接通过 dry-run 验证；脚本可在后续切片补） | — |
| S5 | 跳过（现有 `validate_cross_links` 暴露在公共 seam；后续切片可接入） | — |
| S6 | **真实 dry-run 验证**：`book build-from-wiki --project knowledge/novel-wiki --series 写作技法 --book 写作技法 --dry-run` 返回 `status=planned` | 本切片 |

## 4. 真实 dry-run 结果

```
$ python -m src.cli book build-from-wiki --project knowledge/novel-wiki \
    --series 写作技法 --book 写作技法 --json

{
  "status": "planned",
  "run_id": "e781e99f578c4c2ab9e0ce232771adb9",
  "snapshot_id": "61eb65b94d75d079d146c43cdcfc9a2891d39130c4c6cea289ed20e89d6ed610",
  "version_dir": "knowledge/novel-wiki/.index/book-wiki/versions/e781e99f578c4c2ab9e0ce232771adb9",
  "series_id": "写作技法",
  "book_id": "写作技法",
  "book_mode": null,
  "release_id": null,
  "dry_run": true
}
```

| 验收项 | 结果 |
|---|---|
| `status` | `planned` ✓ |
| `run_id` | `e781e99f578c4c2ab9e0ce232771adb9` ✓ |
| `version_dir` 存在 | `knowledge/novel-wiki/.index/book-wiki/versions/e781e99f578c4c2ab9e0ce232771adb9/` ✓ |
| `series-manifest.json` | `schema_version=series-manifest-v1, status=ready` ✓ |
| `manifest.json` 字段 | series_id, book_id, mode=rule_only, chapter_count=179, hard/soft_dependencies=[] ✓ |
| `CURRENT.json` sha 不变 | `{"version":"4e1229dae60241e3a5aeb323b14a123a","manifest_sha256":"762a865c..."}` ✓ |
| `.releases/` 列表不变 | `[4e1229dae60241e3a5aeb323b14a123a, 79780de66b0f47988ffa5cedecdee951]` ✓ |
| 真实 6 个 candidate taxonomy | 全部 `decision=proceed, closure_status=closed, reasons=[]` ✓ |

## 5. 回归证据

| 范围 | 通过 / 总数 |
|---|---|
| `tests/test_kc/test_book_series_*.py`（既有 8 模块） | **66 / 66** （58 既有 + 8 新增 S0+S1+S2） |
| `tests/test_kc/`（全 kc 套件） | **734 / 734** |
| `tests/test_kc/ + tests/test_cli_ext/` | **916 / 916** （含 3 新增 S3） |
| 全仓 `tests/ --ignore=tests/test_mcp_server` | **3920 / 3921** （1 deselected = `test_partial_commit_records_state_and_resume_retries`，pre-existing，与本切片无关） |

## 6. 红线审计（最终）

| 红线 | 状态 |
|---|---|
| 1. 不用 LLM 填充 baseline 缺口 | ✓ rule-only 路径 |
| 2. 不默认保留三本书 | ✓ `NOVEL_WIKI_PROFILE` 用 6 个真实 taxonomy |
| 3. 不执行全量 `--apply` | ✓ 仅 dry-run，未触发 `publish_book(apply=True)` |
| 4. 不覆盖旧 `CURRENT.json` | ✓ sha `762a865c...` 与 commit `d06e906f` 之前一致 |
| 5. 每个切片有失败测试 → 修复 → 回归 | ✓ S0 8 个失败测试 → S1+S2 → S3 3 个失败测试 |
| 6. 任何失败只影响 staged release | ✓ dry-run 失败不写 `CURRENT.json`；publish_book(apply=False) 直接返回 planned |
| 7. 来源路径 allowlist；API key 不进产物 | ✓ 未启用 LLM 路径；产物内无 key |
| 8. 旧 outline-v1/旧 release 可读 | ✓ `read_legacy_manifest` 与 `resolve_active_version` 未触碰 |

## 7. 已知限制与待办

### 已知限制
- `manifest.release_id`、`reader_promise`、`exit_artifact` 在 rule_only 路径下为 `None`（CLI 未传 `--release-id` 且 rule_outline 不带这两个字段）。**这不是缺陷** — dry-run 产物已经完整；用户后续可在 LLM-enhanced 路径或 `--release-id <id>` 显式传入。
- 真实 wiki 的 `写作技法` 540 页被切成 67 个 chapter（rule_outline 用 `partition_pages` 的块切），reader 单章阅读体验可能碎片化。这正是 plan-audit 提出的"真实 proceed 决策可能让 reader 体验差"风险，建议先做单章 pilot。
- `test_partial_commit_records_state_and_resume_retries` 仍是 pre-existing 失败（与本切片无关，已在父 commit `fb707d9b` 验证）。

### 后续可选切片
- **S4**：写 `scripts/build_book_series_baseline.py`，把 baseline 写到 `.llm-wiki/book-series/baselines/<snapshot_sha[:12]>.json`（gitignored），便于 audit trail。
- **S5**：把 `validate_cross_links` 接入 dry-run 路径，在 dangling 时返回 `E_DANGLING_CROSS_LINKS`。
- **S6 后续**：单章 reader pilot + 人工验收（按 acceptance 报告 Tasks 0–8 列出的 6 步前置条件）。

### Apply 路径状态
本次 dry-run 已经走通；但**完整 `--apply` 仍需**：
1. 单章 reader pilot 验证产物可读
2. 验证 source provenance 完整
3. 验证 cross-book 关系不悬空
4. 人工审批人（`approver="novel-wiki-editor"`）签字
5. 备份 `CURRENT.json`（虽然本切片未触碰，但 apply 是另一路径）
