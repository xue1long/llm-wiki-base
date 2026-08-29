# A8 Book 完整验收与重建链路实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 A8 剩余的 Outline Proposal、Book Diff、受影响章节增量重编译、真实 Book 重建脚本和 Gate A8 E2E 验收，使 Book 在视图被删除后可仅凭 Knowledge Core 与固定 Template 重建。

**Architecture:** Book 继续作为 Knowledge Core 的可删除消费视图。Proposal Engine 只生成冻结的 `proposed` 建议，只有显式 `approved` 的 Proposal 才能产生新目录；Diff 只计算稳定 ID 与 KU 来源变化；Rebuild API 先在内存中编译全部目标章节，所有完整性检查通过后再通过单一原子 writer 写入 Book 目录。CLI 只负责加载项目数据、调用 API 和输出结构化报告，不复制业务规则。

**Tech Stack:** Python 3.11+、现有 frozen dataclasses、标准库 `json/hashlib/pathlib`、pytest；沿用现有 `KnowledgeCoreView`、`compile_chapter`、`render_chapter`、`IntegrityGate`、`PublicationGate` 和 wiki 的原子写入模式，不增加依赖。

**Spec:** `C:/Users/HP/Documents/Codex/2026-08-26/referenced-chatgpt-conversation-this-is-an/outputs/DEVELOPMENT_PLAN.md` §12.5、§14 A8、§17 D-18；补充设计见 `.superpowers/sdd/HANDOFF_A8_BOOK_VIEW.md` §5。

## Global Constraints

- A8 Gate：章节映射金标准准确率 `>= 0.90`；`Unsupported Fact = 0`；无 approved Proposal 时目录不变；只重编译受影响章节。
- Proposal 状态严格为 `proposed → approved → applied`；`proposed` 或 `rejected` 不得修改 `Book.chapter_ids`、Chapter 稳定目录或 `outline_version`。
- 所有 Book 编译必须使用 `core_view.current_publication_version()`；不得从 Chapter、CLI 参数或本地计数器伪造 publication version。
- 重建必须是 staging-first：任一章节解析、IntegrityGate、Evidence Binder、Markdown 或写入失败，都不能覆盖已有 Book 页面。
- 旧的 `scripts/kc_book_rebuild_dryrun.py` 和 `scripts/kc_book_rebuild_migrate.py` 只保留兼容，不改造为新重建入口。
- 不触碰 `knowledge/novel-wiki/`；所有测试使用 `tmp_path` 和内存 `SimpleKnowledgeCoreView`。
- 每个任务遵循 TDD：先新增失败测试，再写最小实现；每个任务一个逻辑 commit，提交前运行对应测试和 Book 全套测试。
- 失败报告必须包含失败对象 ID、reason codes、分子/分母；空数据集标记 `not_evaluable`，不能把 0/0 当作通过。

---

## 现状与文件边界

已存在并作为上游输入：

- `src/kc/views/book/contract.py`：`Book`、`Chapter`、`KnowledgeBlock`、`OutlineProposal`。
- `src/kc/views/book/mapper.py`：KU → Chapter 映射与 32-case 金标准。
- `src/kc/views/book/compiler.py`：`compile_chapter()`、`ChapterRender`、`CompileError`。
- `src/kc/views/book/template.py`、`markdown.py`：固定 7 段 Book Template 与 `BookView`。
- `src/kc/views/book/core_view.py`：只读 Core seam。
- `src/kc/publish/batch.py`：Publication watermark。

本计划新增/修改的生产文件：

- `src/kc/views/book/outline.py`：Proposal 创建、批准、应用；只返回新 frozen 对象。
- `src/kc/views/book/diff.py`：Book/Chapter Diff 与单次运行内的影响集合合并。
- `src/kc/views/book/rebuild.py`：内存编译、staging、原子提交、重建报告。
- `scripts/kc_book_rebuild.py`：真实 CLI adapter；加载 JSON snapshot/fixture，调用 rebuild API，支持 `--dry-run`、`--apply`、`--chapter`。
- `src/kc/views/book/__init__.py`：只 re-export 上述公共 API。

本计划新增测试文件：

- `tests/test_kc/test_book_outline.py`
- `tests/test_kc/test_book_diff.py`
- `tests/test_kc/test_book_rebuild.py`
- `tests/test_kc/test_book_a8_gate.py`
- `tests/fixtures/book_rebuild_fixture.json`：最小 1 Book / 3 Chapter / 4 KU / Evidence / Conflict fixture。

---

### Task 1: Outline Proposal Engine

**Files:**
- Create: `src/kc/views/book/outline.py`
- Modify: `src/kc/views/book/__init__.py`
- Test: `tests/test_kc/test_book_outline.py`

**Interfaces:**

```python
def create_outline_proposal(
    book: Book,
    *,
    trigger_knowledge_unit_ids: tuple[str, ...],
    affected_chapter_ids: tuple[str, ...],
    migration_mapping: dict[str, str],
    rollback_mapping: dict[str, str],
) -> OutlineProposal

def approve_outline_proposal(
    proposal: OutlineProposal, *, reviewer: str
) -> OutlineProposal

def apply_outline_proposal(
    book: Book, proposal: OutlineProposal
) -> tuple[Book, OutlineProposal]
```

- [ ] **Step 1: Write failing tests**：覆盖空触发集合、稳定 key 映射完整性、默认 `proposed`、Proposal frozen、未批准 apply 拒绝、`rejected` 拒绝、approved apply 只增加一次 `outline_version` 并将 status 变为 `applied`。
- [ ] **Step 2: Run red test**：`PYTHONPATH=. pytest tests/test_kc/test_book_outline.py --import-mode=importlib -q`；预期因 `outline.py` 不存在而失败。
- [ ] **Step 3: Implement minimum contract**：调用现有 `OutlineProposal` dataclass；创建时复制 tuple/dict，去重并保持输入顺序；校验 `affected_chapter_ids` 与 migration keys 一致，校验 rollback value 能反向对应；`apply` 只接受 `approved`，返回新 Book/Proposal，不原地修改。
- [ ] **Step 4: Run green test**：同一命令必须全绿，并运行 `tests/test_kc/test_book_contract.py` 确认序列化无回归。
- [ ] **Step 5: Commit**：`git add src/kc/views/book/outline.py src/kc/views/book/__init__.py tests/test_kc/test_book_outline.py`；`git commit -m "feat(kc-views): add Book outline proposal engine"`。

### Task 2: Book Diff 与影响集合

**Files:**
- Create: `src/kc/views/book/diff.py`
- Modify: `src/kc/views/book/__init__.py`
- Test: `tests/test_kc/test_book_diff.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class BookDiff:
    added_chapter_ids: tuple[str, ...]
    removed_chapter_ids: tuple[str, ...]
    changed_chapter_ids: tuple[str, ...]
    changed_knowledge_unit_ids: tuple[str, ...]

def compute_book_diff(old: Book, new: Book, *, old_chapters: tuple[Chapter, ...] = (), new_chapters: tuple[Chapter, ...] = ()) -> BookDiff
def affected_chapters(chapters: tuple[Chapter, ...], knowledge_unit_ids: tuple[str, ...]) -> tuple[str, ...]
```

- [ ] **Step 1: Write failing tests**：覆盖新增/删除/顺序变化、Chapter title/source KU/publication version 变化、同一 KU 多次输入只返回一次、返回顺序遵循 Book chapter 顺序、无影响 KU 返回空集合。
- [ ] **Step 2: Run red test**：`PYTHONPATH=. pytest tests/test_kc/test_book_diff.py --import-mode=importlib -q`。
- [ ] **Step 3: Implement**：只比较稳定 ID 和显式字段；`affected_chapters` 对一次调用内的多个 KU 做 union（这就是增量管线的 debounce/coalescing 边界），不启动线程、不引入计时器；未知 KU 不制造章节。
- [ ] **Step 4: Run green test**：通过 Diff 测试并重跑 mapper 测试。
- [ ] **Step 5: Commit**：`feat(kc-views): add Book diff and affected chapter analysis`。

### Task 3: Book Rebuild API 与原子 writer

**Files:**
- Create: `src/kc/views/book/rebuild.py`
- Modify: `src/kc/views/book/__init__.py`
- Test: `tests/test_kc/test_book_rebuild.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class BookRebuildReport:
    status: Literal["planned", "committed", "failed"]
    book_id: str
    publication_version: int
    rebuilt_chapter_ids: tuple[str, ...]
    failed_chapter_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    rendered_hashes: dict[str, str]
    not_evaluable: bool = False

def rebuild_book(
    book: Book,
    chapters: tuple[Chapter, ...],
    core_view: KnowledgeCoreView,
    integrity_gate: IntegrityGate,
    *,
    template: BookTemplate | None = None,
    target_chapter_ids: tuple[str, ...] | None = None,
    output_dir: Path | None = None,
    apply: bool = False,
) -> BookRebuildReport
```

- [ ] **Step 1: Write failing tests**：覆盖空 Book、全量 3 Chapter 成功、指定目标章节只重编译目标、Core publication version 透传、Evidence 缺失失败、IntegrityGate block 失败、Markdown/render 异常失败、`apply=False` 不写盘、staging 失败保留旧文件、写入成功后每章文件 hash 可复现。
- [ ] **Step 2: Run red test**：`PYTHONPATH=. pytest tests/test_kc/test_book_rebuild.py --import-mode=importlib -q`。
- [ ] **Step 3: Implement**：先筛选目标章节并逐章调用 `compile_chapter` → `render_chapter`；任何 `CompileError` 立即返回 `failed` 且不写盘；成功时把 `BookView.markdown` 与 JSON metadata 写入临时 staging 目录，全部成功且 `apply=True` 才用 `os.replace` 逐文件提交；写入异常返回 failed 并保留旧页面。输出 `rendered_hashes` 与统一 publication version。
- [ ] **Step 4: Run green test**：通过 rebuild 测试，并运行已有 `tests/test_kc/test_book_markdown.py` 与 `test_book_compiler.py`。
- [ ] **Step 5: Commit**：`feat(kc-views): add atomic Book rebuild API`。

### Task 4: 真实 Book 重建 CLI

**Files:**
- Create: `scripts/kc_book_rebuild.py`
- Create: `tests/test_kc/test_book_rebuild_cli.py`
- Create: `tests/fixtures/book_rebuild_fixture.json`

**Interfaces / CLI:**

```text
PYTHONPATH=. python scripts/kc_book_rebuild.py \
  --project-root <path> --snapshot <path> --dry-run

PYTHONPATH=. python scripts/kc_book_rebuild.py \
  --project-root <path> --snapshot <path> --apply [--chapter <chapter_id>]
```

Snapshot 内容固定为 `{book, chapters, knowledge_units, evidences, ku_evidence_map, publication_version}`；CLI 只把它适配为 `SimpleKnowledgeCoreView` 和现有 Gate，不从 Book 页面反推 Core。`--dry-run` 默认模式只输出 JSON 报告。

- [ ] **Step 1: Write failing tests**：覆盖 snapshot 解析、dry-run 零写入、apply 后从空 `book/` 生成 3 个 Markdown、重复 apply hash 相同、指定 `--chapter` 不改无关章节、坏 snapshot 返回非零退出码和失败 ID。
- [ ] **Step 2: Run red test**：`PYTHONPATH=. pytest tests/test_kc/test_book_rebuild_cli.py --import-mode=importlib -q`。
- [ ] **Step 3: Implement**：复用 `Book.from_dict`、`Chapter.from_dict`、`KnowledgeUnit`/`Evidence` 现有构造路径；publication version 由 snapshot/Core view 提供；报告只用 JSON 可序列化字段；禁止调用旧 migration 脚本。
- [ ] **Step 4: Run green test**：运行 CLI 测试，并对 fixture 做一次 dry-run 与一次 apply。
- [ ] **Step 5: Commit**：`feat(kc-views): add real Book rebuild CLI`。

### Task 5: Gate A8 完整验收与 E2E 演练

**Files:**
- Create: `tests/test_kc/test_book_a8_gate.py`
- Create: `scripts/kc_book_a8_accept.py`
- Modify: `.superpowers/sdd/progress.md`
- Modify: `.superpowers/sdd/HANDOFF_A8_BOOK_VIEW.md`（将 B-T3c 后续表更新为完成状态）

**Interfaces / acceptance command:**

```text
PYTHONPATH=. python scripts/kc_book_a8_accept.py \
  --fixture tests/fixtures/book_rebuild_fixture.json
```

验收报告必须包含：

1. mapper accuracy 分子/分母与 `>= 0.90` 判定；
2. Unsupported Fact 总数，必须等于 0；
3. 无 approved Proposal 时 `outline_version`、`chapter_ids`、Chapter stable keys 前后完全相同；
4. 变更一个 KU 时，`affected_chapters` 只含关联章节，且只有这些章节的 hash 变化；
5. 删除全部 Book 输出后，从同一 snapshot/Core + Template 重建成功；
6. 重建前后按 `chapter_id` 的结构化 hash 完全一致；
7. Core、BookView、章节渲染使用同一 `publication_version`；
8. 空 fixture 明确为 `not_evaluable=true`，不得通过 Gate。

- [ ] **Step 1: Write failing E2E tests**：实现上述 8 项；额外注入 unsupported evidence、open conflict、未批准 Proposal、无关 KU 变更和中途写入异常。
- [ ] **Step 2: Run red test**：`PYTHONPATH=. pytest tests/test_kc/test_book_a8_gate.py --import-mode=importlib -q`。
- [ ] **Step 3: Implement acceptance runner**：只组合已有 mapper/diff/rebuild API，不增加第二套编译逻辑；报告每项 gate 的 pass/fail、计数和样本 ID；失败返回非零退出码。
- [ ] **Step 4: Run green + regression**：
  - Book 全套：`PYTHONPATH=. pytest tests/test_kc/test_book_*.py --import-mode=importlib -q`（PowerShell 下先显式展开文件列表）；
  - KC 全套：`PYTHONPATH=. pytest tests/test_kc/ --import-mode=importlib -q`；
  - 记录与 A8 无关的既有失败，不把它们标成 A8 通过。
- [ ] **Step 5: Update ledger and commit**：追加 A8 完成批次、验收报告摘要、已知非 A8 限制；提交 `feat(kc-views): complete A8 Book acceptance and rebuild chain`。

---

## 两轮方案自我审查

### 第一轮：全面漏洞审计

| 级别 | 漏洞位置 | 风险后果 | 整改措施 |
|---|---|---|---|
| 重大隐患 | CLI snapshot 适配 | 若从 Markdown 反推 Core，会把消费视图当事实源 | CLI 只接受 Core snapshot，明确禁止反推 |
| 重大隐患 | Proposal apply | frozen dataclass 可能被绕过而原地改目录 | 所有 API 返回新对象；非 approved 直接抛错并测试原对象不变 |
| 重大隐患 | partial write | 第 N 章失败会留下前 N-1 章新版本 | 全部先 staging，单章替换只在全量 compile 成功后执行 |
| 重大隐患 | publication version | CLI 参数或 Book 自带版本可能覆盖 Core 水位 | rebuild 只读取 `core_view.current_publication_version()` |
| 重大隐患 | 增量范围 | 多 KU 事件重复触发全书重编译 | 先 union 影响章节，再传 `target_chapter_ids` |
| 重大隐患 | hash 等价性 | Markdown 文本相同但证据引用变化，错误判定等价 | hash 输入显式包含 evidence `(id, strength)` |
| 重大隐患 | 空数据 | 0/0 指标被误判为 Gate 通过 | 报告设 `not_evaluable=true` 并返回失败/未通过 |
| 重大隐患 | 无关页面 | 只重建目标章节时误覆盖其他章节 | staging 仅生成 target IDs，并增加无关页面 hash 断言 |
| 优化疏漏 | conflict 双源 | block conflict 与 fallback conflict 同时存在时重复展示 | 规定 block source 优先，fallback 仅在无 conflict block 时使用 |
| 优化疏漏 | snapshot schema 演进 | 缺字段时可能静默使用空默认值 | CLI 对 book/chapters/KU/evidence/version 做显式 schema 校验 |
| 优化疏漏 | 文件系统异常 | 替换阶段权限/磁盘错误缺少可恢复信息 | 报告失败路径与 reason code，staging 保留或可清理，不删除旧文件 |
| 优化疏漏 | 旧脚本混淆 | 用户误把 migration 当 rebuild | 新 CLI 命名独立，文档明确旧脚本不满足 A8 |

### 第二轮：压力测试推演

| 场景 | 连锁反应 | 兜底/加固 |
|---|---|---|
| Core 缺一个 KU | 单章 compile error，若先写盘会产生半套 Book | compile 全量预检；失败 ID 进入报告，零覆盖 |
| Evidence 文件缺失 | Unsupported Fact > 0，章节不能发布 | Binder 原子失败；Gate 明确失败，不生成替代正文 |
| IntegrityGate 抛异常 | 可能绕过质量门直接写 Markdown | `compile_chapter` 的 `compile_exception` 被 rebuild 当失败处理 |
| Proposal 未批准但触发 rebuild | 目录漂移，后续 stable_key 无法迁移 | Proposal 与 rebuild 分离；rebuild 只读当前 Book 目录 |
| 中途磁盘满/权限撤销 | 已写章节与旧章节混合 | staging + replace；写入失败报告，旧目标文件不主动删除，E2E 注入失败 |
| 两个 KU 同时变更 | 两次全书 rebuild 造成抖动或 hash 不一致 | 单次 acceptance/rebuild 输入先 union affected chapters；不在模块内引入后台线程 |
| snapshot publication version 过期 | Book 看似成功但与 Core 水位不一致 | rebuild 前读取 Core view 当前版本并报告；CLI snapshot version 只作为输入校验，不作为旁路来源 |
| 空 Book / 空 Core | 报告“成功”但没有可验收对象 | `not_evaluable`，Gate 不通过；非空 fixture 才能完成 A8 |
| 章节顺序重排 | 若按数组位置比较会误报所有章节变化 | Diff 按 stable chapter ID 比较，顺序只影响输出顺序 |
| 自定义 renderer 抛错 | footer/hash 可能已生成但内容不完整 | 所有 section 渲染在 staging 中完成，任一异常整体失败 |

### 复审结论

上述重大隐患均已在任务接口、测试或 staging/版本约束中有明确封闭路径；没有把旧 Book migration 演示脚本误当成 Core 重建实现。进入编码阶段前必须先由用户确认本计划，随后按 Task 1 → Task 5 顺序执行；执行阶段切换到 ponytail full，完成后再切换到 mattpocock code-review。

## 完成定义

- Task 1–5 均有独立 commit，且所有新增测试通过。
- Book 全套测试达到新增测试后的全绿；A8 Gate 报告 8 项全部 PASS，非空 fixture 的 `not_evaluable=false`。
- 空视图删除后可从 Core snapshot + 固定 Template 重建；前后 chapter hash、KU 顺序、Evidence refs、publication version 一致。
- 未批准 Proposal 不改变目录；批准 Proposal 的应用有明确版本变化和审计报告。
- 只修改目标章节；无关章节 hash、文件内容和目录顺序保持不变。
- `progress.md` 与 A8 handoff 已更新，明确 A8 完成、剩余工作转入 A9。
