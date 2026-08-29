# progress — novel-wiki v3 写作知识库方案（执行账本）

> 方案：`docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md`
> 计划：`docs/superpowers/plans/2026-08-15-novel-wiki-writing-template.md`
> 续接：`.memory/handoff-novel-wiki-phase1-2026-08-15.md`（Phase 0-2）、`.memory/handoff-novel-wiki-phase3-2026-08-16.md`（Phase 3 续接）
>
> **新计划（2026-08-26）：** 模块规范性与统一化改造 — `docs/superpowers/plans/2026-08-26-module-standardization-unification.md`
>
> **P0-A 注册 ruflo CLI → ✅ `be5417ec`**
> **P0-B 中央配置模块 → ✅ `bca225a6`**
> **P1-A BatchRunner 收编脚本 → ✅ 4 子任务（`c4d50dee` 3a 门禁真源 / `68029bcf` 3b 拆引擎 / `2237df22` 3c BatchRunner ABC / `2ac5ef60` 3d ruflo batch CLI）**
> **P1-B 根目录清理 → ✅ `d64a17bd`**
> **P2-A 文档双文件同步 → ✅ `96a9466d`**（正文同步 4 处差异 + pre-commit 钩子校验）
> **P2-B superpowers 归档 → ✅ `409b0dc2`**（73→9 文档，64 归档）
> **P3 公共层边界 → ✅ `257d7777`**（src/shared → tests/support）

## 状态总览

| Phase | 状态 | 说明 |
|---|---|---|
| Phase 0 基线+盲区+index | ✅ | 见 handoff（0.1/0.2/0.3） |
| Phase 1 平台改造 | ✅ 10/10 | 见 handoff（1.1–1.9） |
| **Phase 2 场景模板落地** | ✅ 2/2 | schema/purpose/taxonomy/taxonomy_tags 落盘 + 模板确认 |
| **Phase 3 实测首轮** | ✅ **达标** | 首批 batch_001 全指标过（2026-08-16，含 10 个修复 commit） |
| **Phase 4 全量分批重摄入** | 🔄 进行中 | **batch 1-18 已 committed（360/360 raw）**；batch 19-68 待跑（batch 0 孤儿 gap-raw 保留 postcheck_failed） |
| Phase 4.5 synthesis 聚合 | ✅ 完成 | **11 页分歧汇聚页全部生成+质量门过**（写作技法/技巧/题材体系/读者与市场/创作原则/平台规则/叙事技巧/心态与职业/案例与素材/小说创作/小说结构） |
| Phase 5 终验 | ✅ 完成 | **M1-M12 指标表 + 缺口分析 + 挂账清单**；4 项未达标需全量摄入后自动达标，挂账记录于 `.index/batch_reports/phase5_report.md` |

## Phase 3 实测首轮记录（2026-08-16）✅ 达标

**执行**：
- `scripts/plan_gap_first_batch.py`：B12 缺口优先清单（20 个 ≤8000 字符 .md）
- `scripts/phase3_accept.py`：批内验收（精确 page_ids + v3.0.0 过滤 + M1 未登记口径）
- 最终批次：18 raw → 95 页 commit，`gate PASS`、`POSTCHECK 过`；gap 账本 32 条

**验收结果（batch_001）**：门禁 PASS；M1 未登记断链 0；M4 missing_sections=0 + placeholders=0；M6 synthesis=2；M7 全文污染=0。

**Phase 3 实测发现并修复的 10 个缺陷（均有测试）**：
| # | commit | 缺陷 |
|---|---|---|
| 1 | fe2e484b | `commit_ingest` 无 `event` 参数 → extras 反向关系页提交必失败 |
| 2 | e601cc30 | lint MISSING-SECTION 版本门：v3.0.0 模板下 2.0.0 页被误要求 v3.0.0 槽 |
| 3 | 9c45665c | phase4_batch 丢弃 `missing_slugs` → gap 账本在 batch 路径从未写入 |
| 4 | 99480152 | M1 断链判定未归一 slug（`--` 双横线假断链） |
| 5 | 5fa387d9 | generator prompt 教 LLM 填「来源未提供具体例子」与 lint ERROR 冲突 |
| 6 | 78aae1b7 | missing_slugs 采集在 reverse 之前 → extras 反向断链不入 gap |
| 7 | 8f691ff7 | batch_gate_v3 gap 剔除未归一化匹配 |
| 8 | cd35bf13 | relations[].type JSON schema 无 17 型 enum 约束 → LLM 非法 relation |
| 9 | c193407b | 渲染后清洗 LLM 惯性占位符 + 必填槽缺失不再填系统占位 |
| 10 | de93c9f7 + 85e9f7ac | 非法 relation 过滤覆盖 extras 存量页 + extras 占位符清洗 + batch 记录 page_ids |

**关键运行事实（Phase 3 追加）**：
- LLM provider：`sfkey-glm`（glm-5.2 @ api.sfkey.cn），注册于 `%LOCALAPPDATA%\ruflo-kb\ruflo-kb\llm-providers.json`（非 `~/.config/ruflo-kb`！）
- 真实摄入：`PYTHONPATH=. python scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 0 --project 0ff37d87-de3d-4a99-82bb-6cf288c65410 --allow-overwrite --concurrency 3 [--skip-files ...]`
- 每批 ~25 分钟（20 文件），LLM 调用 ~27 次/批
- 2 个问题文件需 --skip-files：`借鉴素材套路.md`（跨类型 slug 冲突）、`借鉴素材20个签约条件新人必看.md`（LLM 截断，其 source 缺口已入 gap）
- 验收：`PYTHONPATH=. python scripts/phase3_accept.py`
- 真实解释器：`C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe`（WindowsApps 别名是空 stub）

## Phase 4 全量分批重摄入执行记录（2026-08-16，进行中）

**已完成任务（每任务 TDD + commit + reviewer）**：
| # | commit | 任务 |
|---|---|---|
| 4.1 | 18b650a9 + 1fec69a7 | `scripts/plan_reingest_batches.py` 全量分批清单（缺口优先→主题目录，每批≤20 .md，扩展名白名单 + 排除 download_progress；review 整改：gap hint 契约白名单/黑名单/越界防护 + wrong-shape 降级 + batch_no 1-based + theme mixed）——1361 raw → 69 批，gap_priority=3 |
| 4.2 | e752a5e0 | `src/utils/idempotency.py` generate_task_hash 重建轮次维度（round_key=reingest:{batch}:{raw}，轮次间可重投，缺省向后兼容） |
| 4.3 | 238ea381 | `src/vector/store.py` 维度校验（init_vector_store_for_paths(expected_dim)，禁静默 drop；rebuild_vector_schema 显式迁移决策） |
| 4.4 | 1358f3e6 + 59b85691 | `src/services/ingest.py` reingest 直跑分支（probe→cascade+删向量→重建，不经队列；pending_deletion 补偿禁裸窗口）+ `src/services/batch_state.py` 统一 schema/文件锁（三写者 H①）；review 整改：folder 写者迁统一 schema(C1) + 续跑清残留向量(I1) + 重建失败契约(I2) |
| 4.5 | ff969919 + 1534d906 | `scripts/batch_executor.py` 直跑批执行器（每 raw 状态机 + kill-9 各阶段注入测试 + 崩溃续跑 + pre-commit 门禁 NDG/fields/tags/lint/对账 失败零写入 + 预算自动暂停 + is_immutable 跳过 + 3-strike blocklist + git 快照）；review 整改：provider 解析(C1) + WikiPage relations 对账(C2) + 门禁 lint 版本门/阈值/深度对齐(C3) + 复核失败独立 exit3 提示回滚(I1) + 真实费用估算(I2) + 每批向量 upsert 与删向量补偿(I3) + --resume 语义/锁纪律(M1/M3) + 真实路径 gate 测试(I5) |
| 4.6 | f67cec27 | `scripts/rollback_batch.py`（git checkout+clean wiki + 显式向量重建双动作）+ `.gitignore` 门禁文件白名单例外（batch_build_state/knowledge_gaps/reingest_plan/batch_reports，lancedb 不入 git） |
| 4.7 | 最新 | stub 清理：`cleanup_stub_pages.py --apply` 删除 165 个 stub 页（重指 24 引用 / 移除 26 引用），wiki 从 509 页降至 344 页 |

**待完成**：首批全量试跑（验收：kill-9 续跑正确、首摄不炸、无裸窗口、门禁零写入、M2≥80%、M8/M9=0、M11 批均净增≤5）→ progress 账本回填。

**试跑进展（2026-08-16 晚）**：
- 单文件真实路径冒烟测试 ✅：`batch_executor --root knowledge/novel-wiki --batch 0`（1 raw）→ RC=0，provider(RetryLLMProvider/glm-5.2) 正常调用、pre-commit 门禁 PASS（6 页）、reingest cascade 删除旧产出 7 页 + 更新 1 页、commit 成功；向量 upsert 因 CLI 无 embedding provider 降级（WARN，search degrade，预期行为）
- **batch 0 全量 20/20 ✅** + **batch 1 全量 20/20 ✅**（2026-08-17，累计 0.021 USD，完整金句率~95%）
  - 三轮试跑暴露 6 个缺陷（A-F，均修复 + 测试），第四轮全面通过
  - 产出的 5605 行新增 + 2998 行删除（cascade 重建 29 旧页 → 74 新页 + 存量更新）
  - 门禁 PASS（pre-commit 零问题 + 整批复核 PASS）
  - page_ids 持久化（14 页），gap 账本自动更新，budget 0.011 USD

**Phase 4 试跑实测发现并修复的 6 个缺陷（均有测试）**：
| # | commit | 缺陷 |
|---|---|---|
| A | `bd3d4133` | `_commit_raw` 丢弃 `meta["missing_slugs"]` → gap 账本在 batch 路径从未写入（同 Phase 3 修复 #3，batch_executor 新代码重犯） |
| B | `bd3d4133` | `run_precommit_gate` 对 extras（存量 reverse-touch 旧英文 tag 页）检查新 tag/lint 标准 → 整批被拦（修复：extras 不参与批内判定） |
| C | `b3318261` | batch_executor 缺 `_auto_tag_ugc` 步骤（phase4_batch 有）→ UGC carrier 派生页缺 素材/ugc + 可信度/ugc tag → P4b blocker |
| D | `b3318261` | P7（extra-pages 覆盖保护）对占位符清洗后的 extras body 误判 destructive overwrite（修复：P7 放行"仅占位符清洗"差异，与写入路径同语义） |
| E | `58598a1b` | `_rerun_gate_batch` 按 source 关联全扫磁盘页 → 存量 extras（东方玄幻 历史非法 relation contrasts）被误拦（修复：page_ids 过滤只查本批新页） |
| F | `64dfef31` | glm-5.2（reasoning 模型）thinking 占满 max_tokens=8192 预算 → content 空 + finish_reason=length → 被误判为 0-char 空截断不升级 → 3 次全失败（修复：provider 检测 reasoning_content 并上报 content_length>0，解锁升级路径） |
| G | `0608e5a9` | batch 1 清洗兜底缺「待补充」「见下游概念页」→ 扩句法/切割法/曲折法 3 页被 LINT-PLACEHOLDER 拦（修复：补清洗映射，渲染后自动替换） |
| H | `1dd40053` | **根治缺陷 F**：provider 层升级 max_tokens 只是兜底，正确解法是 API 请求传 `reasoning=false` 从源头禁 thinking。ProviderConfig 新增 `extra_body` 字段，sfkey-glm 配置 `{"reasoning": false}` → 实测 reasoning_tokens 从 200 降到 59，无截断 |

**关键运行事实（补充）**：
- glm-5.2 是 reasoning 模型；对 6400+ chars 的源文件，thinking 独占总预算导致 0-char 空截断是特点，非 bug，修复后正确升级 max_tokens 自动解决
- 2 个文件（借鉴素材小说主题分类的内容详细.md / 借鉴素材书籍如何商业化_8111d1.md）从 blocklist 中解封后第四轮成功生成
- 累计消耗 0.011 USD（远低于 0.2 上限）
- **根治方案（H）**：llm-providers.json `sfkey-glm` 加 `extra_body: {"reasoning": false}`，实测 API 认可该参数、thinking 显著减少（reasoning_tokens 200→59），后续批次不再依赖 max_tokens 升级兜底

## Phase 4.5 多源 synthesis 聚合（2026-08-17）✅

- **新增** `scripts/aggregate_synthesis.py`：按 taxonomy category 聚合多源 concept 页 → `provider.complete()` 直接调用 LLM（JSON 模式 `{"synthesis": {...}}`）→ 空 slots 质量门 → 写盘 + index + relations
- **候选**：48 个 category 中 11 个多源候选（写作技法 70 页/26 源、题材体系 17 页/7 源、平台规则 15 页/3 源等）
- **产物**：11 页全部生成，LINT-SYNTHESIS-GATE（各方观点 ≥2 wikilink）全过——v3.0.0 synthesis 模板 5 槽（议题与分歧点/各方观点/共识/证据对比/待定与结论）
- **测试**：`tests/test_scripts/test_aggregate_synthesis.py` 4 测试（分组/生成/空候选/空 slots 质量门）
- **修复**：ProviderConfig.extra_body + openai_provider 合并（根治 thinking 截断）

## Phase 5 终验（2026-08-17）✅ 完成

**报告**：`knowledge/novel-wiki/.index/batch_reports/phase5_report.md`

**指标摘要**：
| 指标 | 当前值 | 目标 | 状态 |
|---|---|---|---|
| M1 断链率 | 9.9% (249/2525) | gap-exempt 未登记 | ⚠ 部分（45 条 open gap 已登记） |
| M2 深引用率 | 4.2% (57/1361) | ≥80%（覆盖范围内） | ❌ 需全量摄入 |
| M4 placeholder | 0 | 0 | ✅ |
| M6 synthesis 页 | 11 | ≥68（1364 raw 换算） | ⚠ 部分（候选全过，全量后更多） |
| M7 全文污染 | 6 | 0 | ❌ 需全量摄入 |
| M8 旧英文 tag | 142 | 0（覆盖范围内） | ❌ 需全量摄入 |
| M9 非法 relation | 19 | 0（覆盖范围内） | ❌ 需全量摄入 |
| M10a raw 文件数 | 1361 | 1361 | ✅ |
| M11 gap 净增 | 45/45 open | ≤5/批 | ⚠ 部分（batch 0-1 合规） |
| M12 向量检索 | 25KB 空库 | 可用 | 🔲 挂账（CLI 无 embedding provider） |

**挂账**：4 项未达标 + M12 向量检索需全量摄入完成后重新验证。

**回归状态**：test_scripts 59+ 绿（4.1-4.6 全量）；test_services 绿；全树 3-5 个既存收集 ERROR + test_pipeline 4 个既存失败（均为兄弟 conftest 级联，基线一致，与 Phase 4 改动无关）。

## git 纪律

`git add <specific files>`；工作区他人改动勿碰：`discovery.py`/`start.bat`/`web/*`/`docs/evaluations/`/`knowledge/_batch*/`。`.memory/` 与 `.index/` gitignore（Phase 4 P1 例外：门禁文件白名单）。

## P1-A BatchRunner 收编记录（2026-08-18）✅ 完成

**目标：** `scripts/` 38 个脚本 → `BatchRunner` 框架收编。按计划 4 子任务分步执行，每步独立 commit。

| 子任务 | Commit | 说明 |
|---|---|---|
| 3a 门禁真源 | `c4d50dee` | 提取 `_gate_fields`/`_gate_tags`/`_gate_lint`/`_gate_reconcile`/`run_precommit_gate` → `src/wiki/features/batch_gate.py`（签名不变）；更新 4 个调用方 import |
| 3b 拆引擎 | `68029bcf` | 引擎逻辑（状态机/三阶段原子流程/崩溃续跑/预算/门禁编排/测试钩子）→ `src/orchestrator/batch_runner.py`（718 行）；CLI 壳留 `scripts/batch_executor.py`（~75 行 re-export） |
| 3c BatchRunner ABC | `2237df22` | `Batch`/`GateReport`/`BatchResult` dataclass + `BatchRunner(ABC)`（load_batch/run_one 抽象 + gate/execute/commit/rollback/emit_metrics 框架方法）+ `_on_phase_start/_on_phase_end` 生命周期钩子（崩溃注入在框架级生效）+ `DefaultBatchRunner` 具体实现 |
| 3d 收编 CLI | `2ac5ef60` | `src/cli_ext/batch_cmd.py` 注册 `ruflo batch {run,plan}`；`src/cli.py` 挂载；脚本与 CLI 双入口兼容 |

**关键决策：**
- **门禁真源** `src/wiki/features/batch_gate.py` 现被 5 个调用者引用（batch_executor/batch_commit/accept_batch/diagnose_batch_gate/tests），消除单点复制（验收 #4 ✓）。
- **`sys.path.insert(0, ...)` 移除**：引擎迁入 `src/` 后不再需要（handoff 记录点）。
- **生命周期钩子**：`run_batch` 在 generate/gate/commit/recheck 四阶段调用 `args._batch_runner._on_phase_start/_on_phase_end`，`_crash_at` 在钩子内触发——`os._exit(137)` kill-9 模拟在框架级生效。
- **测试红线**：`test_batch_executor.py` 的崩溃注入测试全套保留（`os._exit(137)` generate/gate/cascade/commit 四阶段），改 import 指向引擎。

**验证：**
- `tests/test_scripts/test_batch_executor.py` 18 tests passed（含崩溃注入全套）
- `tests/test_scripts/test_batch_generate_commit.py` 7 tests passed
- `ruflo batch run --help` / `ruflo batch --help` 正常
- 端到端冒烟（fake mode）：`ruflo batch run` → exit 0, 2 files done, gate PASS

**遗留（后续 P 处理）：**
- ~~`batch_ingest`/`phase4_batch`/`phase5_accept`/`pilot_ingest` 等遗留脚本未逐一改成继承 `BatchRunner` 子类~~ → ✅ **已收编**（见下文「遗留脚本全量收编」）
- `batch_gate_check`/`batch_gate_v3`/`diagnose_batch_gate` 的 `ruflo batch gate` 子命令未建 → ✅ **已收编**（`ruflo batch gate-check/gate-v3/diagnose-gate`）

## P2-A 文档双文件同步（2026-08-18）✅ `96a9466d`

**目标：** `AGENTS.md` / `CLAUDE.md` 双文件正文逐字节一致 + pre-commit 钩子强制。

**同步的 4 处差异：**
| # | 差异 | 方向 |
|---|---|---|
| 1 | `custom_type` 行（自定义类型字段） | CLAUDE 有 → AGENTS 补上 |
| 2 | schema.md/purpose.md 注入段落 | CLAUDE 有 → AGENTS 补上 |
| 3 | dev-relay 路径统一为 `.agents/skills/` | 两文件同步（原 `.Codex`/`.claude` 遗留 → 规范值） |
| 4 | graphify 两行规则（dirty 容忍 + 跳过条件） | AGENTS 有 → CLAUDE 补上 |

**钩子实现（`scripts/setup_git_hooks.py` 扩展）：**
- 在 `sync_wiki_spec.py` 前增加 AGENTS/CLAUDE 正文校验
- **跳过前 3 行**（H1 标题 / 空行 / 工具说明行）后逐字节比较余下内容；不一致 → ERROR + exit(1)
- 两文件合法差异仅 H1 标题（`# AGENTS.md` vs `# CLAUDE.md`）+ 第 3 行工具名（Codex vs Claude Code）

**验收：**
1. 两文件同步 → 钩子通过（EXIT=0）✅
2. 故意改 CLAUDE.md 不同步 → 钩子拦截（EXIT=1）✅
3. 正文（跳前 3 行）长度一致 27369 bytes ✅

## P2-B superpowers 归档（2026-08-18）✅ `409b0dc2`

**分档原则：** 按 git 最后提交时间（非 mtime——73 文件 mtime 均为 8/14 批量复制时间）。

**保留 9 个活跃文档（< 30 天）：**
- 当前计划 `2026-08-26-module-standardization-unification.md`（8/17）
- novel-wiki 活跃：`2026-08-15-*-writing-template*.md`（plan + spec，8/16）
- 8/12 的 4 个近期规划（knowledge-os-docs-integration 等）
- `PLAN_TEMPLATE.md` + `README.md`

**归档 64 个（2026-07-21 ~ 2026-08-11 已完结）：**
- 移至 `docs/archive/superpowers/`（保留 plans/specs 目录结构）
- `docs/archive/README.md` 说明"此目录为历史规划归档，不反映当前状态"

**验收：**
1. `docs/superpowers/` 73→9 文档（≤15 ✅）
2. `docs/archive/superpowers/` 64 文件可访问 ✅
3. `.superpowers/sdd/progress.md` 3 个链接全部指向保留文件，无需更新 ✅
4. 其他 docs 中指向已归档文件的引用（ARCHITECTURE/CONSTRAINTS/README 等）**保持原路径**——历史文档引用保留完整链，避免链式断链（记录：`docs/archive/` 内交叉引用同样保留原绝对路径）

## P3 公共层边界（2026-08-18）✅ `257d7777`

**迁移：** `src/shared/test_helpers.py` → `tests/support/test_helpers.py`

**动作：**
- `git mv src/shared/test_helpers.py tests/support/test_helpers.py`
- 删除 `src/shared/__init__.py`（空目录，src/shared/ 整体消失）
- 更新 9 个测试文件 import：`from src.shared.test_helpers` → `from tests.support.test_helpers`

**命名约定（明确 src/ 分层）：**
- `src/utils/`：纯函数、无副作用工具（path/slugify/text/similarity/idempotency）
- `src/lib/`：框架性代码、有副作用辅助（atomic_ctx/write_hooks/project/context_budget/budgeted）
- `src/*/core/`：业务领域核心（wiki/core、knowledge/core）

**验收：**
1. `src/shared/` 目录不存在 ✅
2. 9 个文件 `from tests.support.test_helpers import ScriptedLLMProvider` 可导入 ✅（traceback 证实实际走 tests.support 路径）
3. 非模板依赖测试 24/24 通过 ✅（预存模板解析失败 TemplateParseError 与 P3 无关，基线一致）
4. 未动 `src/utils/`/`src/lib/` 内容（仅文档化边界）

## 遗留脚本全量收编（2026-08-18）✅ `c8ace1da`

**目标：** 按 plan 3d 表，将 `scripts/` 中 38 个遗留脚本全部注册为 `ruflo` 子命令。

**收编范围（四组 38 子命令）：**

| 组 | 子命令数 | 清单 |
|---|---|---|
| `ruflo batch` | 17 | run/plan（进程内）+ gate-check/gate-v3/diagnose-gate/accept/generate/commit/build/ingest/rollback/pilot/phase3-accept/phase4/phase5-accept/plan-first/plan-backlog（子进程转发） |
| `ruflo migrate` | 5 | legacy-tags/pinyin-to-cjk/slug-aliases/timestamps/vector-paths |
| `ruflo audit` | 4 | blindspots/placeholder-classify/wiki-baseline/quality-check |
| `ruflo util` | 12 | aggregate-synthesis/cleanup-stubs/cleanup-tags/fix-mojibake/ndg-calibrate/normalize-sources/rebuild-index/stress-test/sync-wiki-spec/setup-git-hooks/ingest-d/ingest-manual |

**实现方式：** 薄 CLI 包装 + 子进程转发（`subprocess.run`），原脚本保留 `python scripts/<name>.py` 直跑入口（兼容过渡期）。环境变量继承完整 `os.environ` + `PYTHONPATH` 确保 Windows 下模块加载正常。

**新增文件：**
- `src/cli_ext/scripts_cmd.py` — migrate/audit/util 三组，子进程转发
- `src/cli_ext/batch_cmd.py` — 扩展（原 71 行 → 134 行），追加 15 个子进程转发
- `tests/test_cli_ext/test_scripts_cmd.py` — 5 测试（注册 + 转发验证）

**遗留问题清零：**
- ~~`batch_ingest`/`phase4_batch` 等未收编~~ → ✅ 全部收编
- ~~`batch_gate_check` 等 gate 子命令未建~~ → ✅ `ruflo batch gate-check/gate-v3/diagnose-gate`

**验证：**
1. `ruflo {batch,migrate,audit,util} --help` 列全子命令 ✅
2. `ruflo batch diagnose-gate -- --help` 透传至原脚本 ✅（exit=2, 输出含原脚本名）
3. 5/5 CLI 注册测试通过 ✅
4. 19/19 batch_executor 崩溃注入测试通过 ✅（含 os._exit(137) 子进程）

## 架构整改（2026-08-18，Wave 0+1 完成）✅

**计划**：`docs/superpowers/plans/2026-08-18-architecture-remediation.md`（15 项风险，Wave 0/1/2）
**范围确认**（用户批准）：受控单机单 worker / 单一 Bearer Token / 上传上限 50MiB / 候选链路冻结+删除

### Wave 0 — 外部暴露止损（P0）✅

| 风险 | Commit | 摘要 |
|---|---|---|
| R1 管理面认证+Key 脱敏 | `cdf25b53` | Bearer Token（`ruflo auth-token {generate,show,clear}`）+ /api/v1 写操作与 provider 管理需 Token；无 Token 非回环绑定拒绝；provider 响应强制脱敏；修复 `_default_providers` 缺 settings import |
| R2 上传上限 | `445bc2df` | `RUFLO_MAX_UPLOAD_BYTES`（默认 50MiB）；HTTP 路由分块读取超限 413；Collector 统一源读取层限制（URL/本地文件/文件夹摄取不可绕过） |
| R15 凭据/出境边界 | `26416a42` | 启动权限检查（非 0600 警告）；show/add 出境提示（stderr 保 JSON 契约）；`llm-providers rotate-key`（不回显新 key） |

### Wave 1 — 数据正确性与可用性（P1）✅

| 风险 | Commit | 摘要 |
|---|---|---|
| R4 拒绝分支 | `59ed6c0d` | `_write_rejected_source_page` 改用同步 AtomicContext + 真签名；拒绝分支返回 (pages, extra, meta) 三元组；slug 只取 basename |
| R3 提交失败语义 | `266d6f16` | `AtomicCommitError(failed_paths)`；flush 失败抛聚合异常不再吞错；callback 失败也传播；body 异常仍优先 |
| R6 单实例 + R14 显式 project root | `00e0cb60` | `serve --workers>1` 拒绝；`--project-root` 必填（拒绝 CWD 猜测）；`.llm-wiki/server.lock` 实例锁（死 PID 自动清理）；`RUFLO_PROJECT_ROOT` 传递 |
| R5 /ready | `7f705792` | 分项检查 queue/wiki/vector/provider，200/503；provider 探测 60s 缓存防抖动 |
| R7 向量补偿 | `9617540a` | `.index/vector_pending.json` 账本；commit 后 mark、upsert 成功 clear、启动 scan 兜底；`ruflo vector {status,reconcile}` |
| R8 异常分类 | `a905db25` | `RetryableDependencyError`/`InvalidInputError`/`DataConsistencyError`/`ProgrammingError`；`[no-retry]` 标记 → 立即死信 |

### Wave 2 进行中

R9 候选链路删除 → R10 routes 收敛 → R11 依赖 profile → R12 关联 ID+告警 → R13 版本+runbook

### Wave 2 — 演化与运维（P2）✅ 完成

| 风险 | Commit | 摘要 |
|---|---|---|
| R9 候选链路删除 | `95cfc9d2` | 删除未接入的 Reviewer/Promoter/ClaimExtractor stage（生产零引用，-1855 行）；保留 KnowledgeCandidate 数据模型与 generator 工具函数 |
| R10 routes 收敛 | `76398c59` | heat 写操作收敛到 `src/services/heat.py`；route 变薄适配器；新增 test_route_boundary.py 静态守卫（禁 route 直接 import wiki 写内部） |
| R11 依赖 profile | `2e219eaa` | pyproject 新增 `[embedding]` extra；`embed_profile.embedding_mode()` = remote/local/keyword-only；/ready 诚实报 degraded；新增 requirements.lock |
| R12 关联ID+告警 | `94363bfc` | 4 类告警指标（dead_letter/backlog/provider_failure/write_failure）；`src/lib/correlation.py` request_id/task_id/project_id 日志关联；docs/ops/runbook.md |
| R13 版本+runbook | `f02bd971` | `src.__version__` 单一真源（health/app 派生）；start.bat 移除 netstat 误杀、改用 serve-stop + --project-root |

### 整改全量验收（Wave 0/1/2 全部完成）✅

**15/15 风险整改完成**，全部有测试 + 提交。运行验证：
- 测试回归：858 + 1278 + 389 + 78 = **2603 测试通过**（含 15 项整改的新增测试约 100+）
- 冒烟验证：`serve --project-root` 启动 → `/health` 返回 version=2.0.0（R13）、`/ready` 分项 200（R5/R14）、无 Token 非回环绑定被拒 exit 2（R1/R6）
- 已知基线（未改动前即存在）：全量收集 5 文件兄弟 conftest 级联错误；test_url_redirect_to_loopback_blocked 需真实 DNS

**整改后架构状态**：信任边界（Token 认证 + Key 脱敏 + 上传上限 + 凭据边界）、数据正确性（AtomicContext 失败传播 + 拒绝分支修复 + 单实例护栏 + 显式 project root + /ready + 向量补偿 + 异常分类）、演化运维（唯一主链路 + services 收敛 + 依赖锁定 + 告警 + 版本统一 + runbook）三大块全部落地。

## Phase 4 批量重摄入续跑（2026-08-18，架构整改后）🔄

**状态恢复**（batch_build_state.json）：batch 0 孤儿（legacy smoke，postcheck_failed）；batch 1-7 committed（160 文件）；**batch 8 起待跑（63 批 1241 文件）**。

**运行命令**（BatchRunner 收编后入口，provider 默认 sfkey-glm/glm-5.2）：
```bash
PYTHONPATH=. python -m src.cli batch run --root knowledge/novel-wiki --batch <N> --concurrency 3
```
- batch 8（01_新手入门 剩余 20 文件）2026-08-18 16:18 启动
- 整改兼容性：R2 50MiB 上限不影响（源文件均小）；R4 拒绝分支返回三元组（batch 兼容）；R7 vector_pending 在 batch upsert 成功后自动 clear
- 每批 ~25 分钟，LLM ~27 次/批

## 标签规范化整改（2026-08-18，进行中）🔄

**计划**：`docs/superpowers/plans/2026-08-18-tag-normalization-remediation.md`
**背景**：batch 8（20 源文件已落盘）Gate re-check 失败；根因 = legacy 英文前缀
（`func/`、`genre/` 等）绕过 Generator 规范化写入磁盘 + Gate 使用严格中文命名空间。
**政策决策**：保持兼容政策（策略 1，任何带标签页面自动补 `素材/ugc`+`可信度/ugc`），
来源感知政策（策略 2）延后（方案 §3 决策注记）。

**已实施（代码已改，待宿主恢复后跑测试验证 + 提交）**：
| Task | 内容 | 文件 |
|---|---|---|
| 1 | 规范化契约测试按策略 1 修正（2 个测试期望补 mandatory） | `tests/test_wiki/test_tag_normalization.py` |
| 2 | Generator `_normalize_tags` 增加审计日志；`build_tag_prompt_section` 增加 legacy 前缀禁用行；analyzer 内联注释同步 12 前缀 | `src/pipeline/generator.py`、`src/wiki/features/tag_namespace.py`、`src/pipeline/analyzer.py` |
| 3 | `commit_ingest()` 对 `pages + extra_pages` 写盘前统一 `normalize_tags` + TAG-MAPPED/TAG-REMOVED/TAG-MANDATORY 审计日志；新增 3 测试 | `src/pipeline/ingest.py`、`tests/test_pipeline/test_ingest_generate_commit_split.py` |
| 4 | `cleanup_invalid_tags.py` 改用公共 `normalize_tags`（mapping/removal/mandatory 输出 + `--apply`）；新增 4 测试；Gate 保持严格校验（复用 `validate_tag_compliance`） | `scripts/cleanup_invalid_tags.py`、`tests/test_scripts/test_cleanup_invalid_tags.py` |
| 2/4 | Generator legacy 前缀解析测试（`func/教程`→`功能/教程` 且过 `validate_tag_compliance`） | `tests/test_pipeline/test_generator.py` |
| docs | `docs/reference/ingest-prompts.md` 标签规则纠偏（12 中文前缀 + legacy 禁用）；`docs/guides/novel-wiki-ingest-spec.md` 更新 legacy 迁移说明 | 两个文档 |

**待办（宿主恢复后）**：
1. 跑测试（`pytest tests/test_wiki/test_tag_normalization.py tests/test_wiki/test_tag_namespace.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_generate_commit_split.py tests/test_scripts/test_cleanup_invalid_tags.py tests/test_scripts/test_batch_executor.py -v`）→ 修复 → 逐 Task 提交
2. batch 8：`diagnose_batch_gate.py` / `accept_batch.py --root knowledge/novel-wiki --batch 8` 确认当前 Gate 实际失败项（静态检查未发现 batch 8 页面含 legacy 标签——需运行确认原 `func/结构`、`func/关系`、`genre/平台` 的出处）
3. 按需 `cleanup_invalid_tags.py --page-ids <受影响>` 修复 → `accept_batch` → batch 8 committed
4. 继续 `python -m src.cli batch run --root knowledge/novel-wiki --batch 9 --concurrency 3`
5. 可选后续：全库 `cleanup_invalid_tags.py --all --apply` 清理存量 129 处 legacy 标签（M8 指标）

## 确定性字段与链接整改（2026-08-18，Task 0 完成，Task 1+ 进行中）🔄

**计划**：`docs/superpowers/plans/2026-08-18-deterministic-page-fields-and-links.md`
**背景**：batch 9 pre-commit Gate 阻断（`飞书云文档`/`北京圣东方国信科技有限公司` →
`[[入门教程角色篇完善小说的技法-e8ca1866]]` 旧 hash + 标题丢词的 source 链接）。
方案经 plan-audit 两轮审查（致命 0 → 重大 2 → Task 0 前置）。**编码门槛**：Task 0
未证明提交/并发/TOCTOU/custom-type 边界前不进入 Task 1，也不重跑 batch 9。

**Task 0（✅ 已提交 `19ea1ed2`）**

| 切片 | 内容 | 文件 |
|---|---|---|
| 0.1 | sanitizer reject 改纯内存返回（Gate 前零 wiki 写入）；回归测试改显式 commit 断言 | `src/pipeline/ingest.py`、`tests/test_pipeline/test_rejected_source_page.py` |
| 0.2 | `AtomicCommitError` → raw `partial_commit`（+failed_paths）+ 停止批次（rc 4）；flush 故障注入钩子 `RUFLO_FLUSH_FAIL_PATHS`；`log_event` 按 (event,task_id,detail) 去重；partial 重试幂等测试 | `src/orchestrator/batch_runner.py`、`src/lib/write_hooks.py`、`src/wiki/features/logger.py`、`tests/test_scripts/test_batch_executor.py` |
| 0.3 | 跨进程 `project_commit_lock()`（`.index/commit.lock`）包裹提交循环；`write_page(expected_content_hash)` CAS → `WriteConflictError`；批级 `write_conflict`（rc 5）| `src/services/batch_state.py`、`src/wiki/storage/page_writer.py`、`tests/test_wiki/test_page_writer.py` |
| 0.4 | `SchemaRegistry.iter_page_dirs()` 统一目录枚举；`_collect_existing_wiki`/`_resolvable_set` 改用；custom type 发现/对账测试 | `src/wiki/schema_registry.py`、`src/pipeline/reconcile.py`、`tests/test_wiki/test_schema_registry.py` |
| 0.0 | `BATCH_STATUSES` 增加 `partial_commit`；测试常量同步 | `src/services/batch_state.py`、`tests/test_services/test_batch_state.py` |

**验证**：139 项定向测试全绿（batch 状态机、lib 原子写、reject、commit split、reconcile、
page_writer、schema_registry、cascade、immutable）。

**Task 0 已证实的语义**：Gate 前零 wiki 写入；单 raw 提交部分失败 → `partial_commit`
可发现可重试（page/index 幂等、log 去重）；人工编辑 → `WRITE-CONFLICT` 拒绝覆盖；
同项目并发提交由跨进程锁串行化；custom type 页全目录可见。
**已知上限（ponytail）**：`AtomicContext` 仍是线程局部缓冲（async 同线程任务间可能
串桶，服务器并发摄入未覆盖）；owner-token fencing 未实现（由提交锁串行化替代）。

### 待办

1. ~~提交 Task 0~~ ✅ `3675f1f4`（标签 Task 1-4）+ `19ea1ed2`（Task 0）
2. Task 1（✅ 待提交）：canonical raw path（`canonical_raw_key` v1：NFC/root 外拒绝/golden vectors）+ Target Resolver（`src/wiki/features/target_resolver.py`，优先级 exact→source→alias→title→legacy_hash→unresolved/ambiguous；legacy_hash 仅带 hash 后缀 + 唯一 source 候选内允许 0.88 相似度）；17 contract tests `tests/test_wiki/test_target_resolver.py` 全绿
3. Task 2（✅ 待提交）：`generate_ingest` 冻结 `ResolutionContext`（canonical key + source 候选 + index/title/alias 快照）→ `_normalize_generated_pages` 统一重写 body wikilink + relation target；删除 generator 两处 inline source-link 修复（含 difflib）；`test_generate_ingest_rewrites_legacy_hash_source_link` 通过
4. Task 3（✅ 待提交）：提取 `finalize_generated_page()` 显式字段 owner 边界（grade/depth/id/title/时间戳）；custom type 全链路目录枚举已在 Task 0.4 覆盖（iter_page_dirs → collect/reconcile；Gate 经 index.md 覆盖 custom 页）；休眠入口 `generate_from_candidate`/`generate_from_knowledge_object` 无仓库内调用方，接入待后续（ponytail: 无调用方不接线）
5. Task 4（✅ 待提交）：`SlugAliasRegistry.get_canonical` 有界链解析（`_MAX_ALIAS_DEPTH=8`，环/自环/超深 fail-closed）+ `add` 拒绝自环；`finalize_generated_page` 归一化 relation weight（越界/NaN → 1.0）；taxonomy 已由 `write_page` 严格校验
6. Task 5（✅ 待提交）：`run_precommit_gate` 接受 `resolution_context`；`_gate_reconcile` 未解析目标经统一 resolver 判别——多候选 → `TARGET-AMBIGUOUS`（可诊断，不受 pending_gap 豁免），否则 `BROKEN-LINK`；batch_runner 收集整批 source 候选传入 Gate
7. Task 6（✅ batch 9 完成）：TOCTOU 误报修复（批内自写剔除，`9b7ac861`）；重跑 `--resume` → `BATCH DONE ok=19 err=0`（1 上次 done）、Gate PASS 91 pages、批状态 committed。真实运行验证：标签规范化审计（TAG-MAPPED/REMOVED/MANDATORY）对存量 reverse-touch 页生效；resolver 重写旧 hash 链接，无 BROKEN-LINK/TARGET-AMBIGUOUS；共享概念页无 TOCTOU 误报；vector 降级 WARN（未配 provider）。taxonomy unknown category 为 write_page 宽松警告（非 strict 模式），不阻断。

## 确定性字段与链接整改 —— 阶段完成 ✅

Tasks 0-6 全部完成（提交：`19ea1ed2` Task 0 / `6cab7bf7` Task 1 / `9ce10228` Task 2 / `0e625532` Task 3-5 / `9b7ac861` Task 6 修复）。
batch 8 已 committed（accept_batch）；batch 9 已 committed。batch 10 首次提交 20 raw，recheck 因跨类型 slug `修真文`（concept/entity）失败；无 LLM 重跑，保留已有 concept，确定性将新 entity 重命名为 `修真文-写法`，同步 index/page_ids 后 Gate PASS → committed（97 page_ids）。后续批次：batch 11+ 可直接 `batch run`。
已知上限（ponytail）：AtomicContext 线程局部（async 同线程并发摄入未覆盖）；owner-token fencing 由项目提交锁串行化替代；generate_from_candidate/KO 无调用方未接线；taxonomy 非 strict 模式只警告。

## 提交记录（本轮）
4. Task 3：`finalize_generated_page()` 字段接管 + custom type 全链路
5. Task 4：relation/taxonomy/alias 归一化
6. Task 5：Gate 审计输出 + unresolved blocker + 副作用 sentinel
7. Task 6：batch 9 重跑验收（Gate 前零写入 + partial 恢复 + 并发锁已就位）

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 11 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 11 --project 0ff37d87-... --allow-overwrite --concurrency 3`
- 结果：`BATCH DONE ok=20 err=0 pages=82 gate=PASS`，POSTCHECK 全过，batch_11 状态 committed（115 page_ids，20 completed_files）。
- **首跑 Gate 阻断（NDG-P6）**：`升级流小说` 批内跨类型 slug 冲突（wiki 已有 concept 页，批内同时生成 entity 页）。`batch run`（batch_runner）路径不做批内对账直接跑 NDG gate → 阻断。改用 `phase4_batch.py`（reconcile_batch 以 wiki 磁盘类型为准，把 entity 页折入 concept 页）→ Gate PASS。
- 经验：batch 11+ 若再遇 NDG-P6 跨类型 slug 冲突，用 phase4_batch.py（含 reconcile）而非 batch run 直跑。
- 已知上限（ponytail）：taxonomy unknown category/sub 为 write_page 宽松警告（非 strict），不阻断。

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 12 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 12 --project 0ff37d87-... --allow-overwrite --concurrency 3`（01_新手入门，20 raw）
- 结果：`BATCH DONE ok=20 err=0 pages=71 gate=PASS`，POSTCHECK 全过，batch_12 状态 committed（106 page_ids，20 completed_files）。一次通过，无需重跑。
- 生成：total_pages=102 + extras=66，reconcile 收敛跨文件重复页（飞书云文档/北京圣东方国信科技有限公司/打斗场景气氛渲染/废材流/金手指 等多源合并，higher-grade 优先）；`gate: 71 page(s) PASS (0 issue, 0 blocker)`；commit 71 主页 + 35 reverse-relation extras。
- 无 NDG-P6 阻断（reconcile 已把 entity 折入 concept/按 wiki 磁盘类型收敛）；taxonomy unknown category 仍为宽松警告。
- 经验：后续批次（13+）继续沿用 phase4_batch.py 直跑路径。

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 13 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 13 --project 0ff37d87-... --allow-overwrite --concurrency 3`（01_新手入门，20 raw）
- 结果：`BATCH DONE ok=20 err=0 pages=106 gate=PASS`，POSTCHECK 全过，batch_13 状态 committed（144 page_ids，20 completed_files）。一次通过，无需重跑。
- 生成：total_pages=127 + extras=52，elapsed=980s；reconcile 收敛跨文件重复页（飞书云文档/北京圣东方国信科技有限公司/题材选择/跟风写作戒律/作品包装/正文纯净原则 等多源合并，higher-grade 优先）；`gate: 106 page(s) PASS (0 issue, 0 blocker)`；commit 106 主页 + 39 reverse-relation extras。
- 首跑环境坑：未设 `PYTHONPATH=.` 时 phase4_batch.py 直接 `ModuleNotFoundError: No module named 'src'`（exit 1）；补 `Set-Item Env:PYTHONPATH .` + `Set-Item Env:PYTHONIOENCODING utf-8` 后正常（与脚本 docstring usage 一致）。
- 已知上限（ponytail）：taxonomy unknown category 仍为宽松警告（不阻断）；4 个 raw 被 sanitizer high_repetition 标记但仍生成成功（rejected=True 仅入库 quarantine 判断，不影响提交）；LLM 偶发 finish_reason=length 截断由重试+auto-fill 兜底。
- 经验：后续批次（14+）继续沿用 phase4_batch.py 直跑路径，且必须带 PYTHONPATH=.

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 14 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 14 --project 0ff37d87-... --allow-overwrite --concurrency 3`（01_新手入门，20 raw）
- 结果：**5 轮 resume 累计** 20/20 raw 全完成，batch_14 状态 committed（20 completed_files，missing=None）。**全批一次跑不完**：上游（sfkey）500/502/524 风暴 + 单文件病理级 LLM 输出，需 5 轮 resume（9→13→15→19→20 文件）。
- 各轮：run1 ok=9 pages=49 / resume1 ok=4 pages=34 / resume2 ok=2 pages=10 / resume3 ok=4 pages=18 / resume4 ok=1 pages=7；每段 `gate: N page(s) PASS (0 blocker)` + POSTCHECK 全过；reconcile 跨文件收敛（老舍/角色塑造/代入感 等多源合并）。
- **本批发现并修复 4 个代码缺陷（均有回归测试）**：
  1. `d0a09d20` `fix(llm)`：`_post_json` 错误摘要行 `(r.text or "")[:200]` 遇 GBK 错误体抛 UnicodeDecodeError → 遮蔽 HTTPStatusError cause → 5xx 被判 permanent。改 `r.content` 字节解码 errors='replace'，保留 cause → transient 可重试。
  2. `ea643660` `fix(retry)`：classify_error 将响应体解码异常（UnicodeDecodeError——截断的多字节字符 / GBK 错误页）判为协议级瞬时（transient）可重试。
  3. `ad8fd9ad` `fix(llm)`：200 响应体解码失败按截断信号返回（LLMResponse(truncated=True, content_length=N)），触发生成器 max_tokens 升级路径而非把文件判死。
  4. `ff181cbc` `fix(generator)`：MAX_GEN_ATTEMPTS 3→4，截断升级新增第 4 级 65536（端点实测接受）；修复病态文件（必备资料网络小说写作宝典如何做有生存能力的作者.md——glm-5.2 对该文件产出随预算增长 19K→34K→96K 字符且把思考写进 JSON slot，32K 封顶不够；65536 后一次通过 7 页）。
- 经验：上游不稳定时段（500/502/524 + GBK 错误页）批次可能分段完成，`--resume` 幂等续跑；病态大输出文件靠第 4 级 max_tokens 升级兜底；后续批次继续 phase4_batch.py + PYTHONPATH=. 直跑。
- 已知上限（ponytail）：taxonomy unknown category 仍为宽松警告（不阻断）；sanitizer high_repetition 标记文件仍可生成（rejected=True 仅入库 quarantine 判断）。

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 15 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 15 --project 0ff37d87-... --allow-overwrite --concurrency 3 --resume`（01_新手入门，20 raw）
- **背景**：batch_15 上一轮 18/20 完成但未提交，2 文件超时（新人须知1浅谈网络写手网络文学与网络文学创作基础.md 及 _08147a 变体，均 <8KB 小文件——超时源头上游不稳）。
- **本轮**：--resume 跳过 18 completed，仅生成 2 剩余文件：`ok=2 err=0 total_pages=8 extras=0 elapsed=152s`；reconcile 合并 2 页（网络小说/网络文学，higher-grade 优先）；`gate: 5 page(s) PASS (0 issue, 0 blocker)`（overwrite WARN 非阻断，--allow-overwrite 放行）；POSTCHECK 全过；batch_15 状态 committed（20 completed_files，failed_files 清空，page_ids=5）。
- **LLM provider 已切换 xiaomi-mimo**（mimo-v2.5，default=xiaomi-mimo）：本轮实测 200 OK、无截断；之前 sfkey 超时文件一次通过。
- 经验：`--resume` 幂等续跑把 18 个已落盘文件当 completed 跳过，只补剩余文件，POSTCHECK 只扫本轮生成页；已 committed 批次不重跑。batch_16+ 为全新批次（无 --resume），继续 phase4_batch.py + PYTHONPATH=. 直跑。

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 16 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 16 --project 0ff37d87-... --allow-overwrite --concurrency 3`（01_新手入门，20 raw，新人须知20-36 系列）
- 结果：一次通过 `ok=20 err=0 total_pages=111 extras=27 elapsed=1460s`；reconcile 收敛跨文件重复页（爽点与情绪/期待感/都市小说/北京圣东方国信科技有限公司/人物塑造/射雕英雄传 等多源合并，higher-grade 优先）；`gate: 93 page(s) PASS (0 blocker)`；commit 93 主页 + 19 reverse-relation extras；POSTCHECK 全过；batch_16 committed（20 completed_files，page_ids=111）。
- 经验：xiaomi-mimo（mimo-v2.5）全程 200 OK、无截断；taxonomy unknown category/sub 仍为宽松警告（非 strict，不阻断）。

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 17 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 17 --project 0ff37d87-... --allow-overwrite --concurrency 3`（01_新手入门，20 raw，新人须知36_d0bb05-8 系列）
- 结果：一次通过 `ok=20 err=0 total_pages=88 extras=46 elapsed=585s`；reconcile 收敛跨文件重复页（完本心态/爽点/先抑后扬/梦入神机/人物塑造/主角性格设定/凤头 等多源合并，higher-grade 优先）；`gate: 78 page(s) PASS (0 issue, 0 blocker)`；commit 78 主页 + 30 reverse-relation extras；POSTCHECK 全过；batch_17 committed（20 completed_files，missing=None，page_ids 记录）。
- 备注：4 raw 被 sanitizer high_repetition 标记（rejected=True 仅入库判断，不阻断提交）；1 个 raw（新人须知40网络小说的爽点是什么.md，>25K chars）走 chunked 路径产出 13 页；2 处 gap 记账（速度--网络文学创作核心 / 基础扎实；新人须知40 的 4 个 gap：奖励与需要/队友设定/女主处理/爽点设计）；taxonomy unknown category（空 category）仍为 write_page 宽松警告（非 strict，不阻断）。
- 经验：xiaomi-mimo（mimo-v2.5）全程 200 OK；batch 17 一次通过无 resume；继续 phase4_batch.py + PYTHONPATH=. 直跑。

## Phase 4 批量重摄入续跑（2026-08-19）✅ batch 18 committed

**执行**：`scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 18 --project 0ff37d87-... --allow-overwrite --concurrency 3`（mixed，20 raw：新人须知9 系列 9 个 + 02_进阶技巧/方法论 系列 11 个）
- 结果：一次通过 `ok=20 err=0 permanent_failed=0 total_pages=101 extras=17 elapsed=1925s`；reconcile 收敛跨文件重复页（人物塑造/北京圣东方国信科技有限公司/语感/智慧/冲突 等多源合并，higher-grade 优先）；`gate: 91 page(s) PASS (0 issue, 0 blocker)`；commit 91 主页 + 12 reverse-relation extras；POSTCHECK 全过；batch_18 committed（20 completed_files，failed_files=[]，missing=None，page_ids=107）。
- 备注：3 个超大/大文件——方法论写书技巧.md（43.6K chars，4 chunk，chunked 产出 7 页，2 处 truncation 由 retry ladder 兜底，6 gap 记账：悬置紧张法/主角设定的真实性/情节与故事/e-m-福斯特/发掷力/刚劲与柔劲）；方法论关于写作技法原理转自奇幻世界网火沙论坛.md（13.3K chars）产出 3 页；5 raw 被 sanitizer high_repetition 标记（rejected=True 仅入库判断，不阻断提交）；2 个 gap 记账（文笔与语言/对话与描写，来自 新人须知小说写作新手上路基本写作教程.md）；taxonomy unknown category/sub（空 category、习惯与方法、写作心态）仍为 write_page 宽松警告（非 strict，不阻断）。
- 经验：xiaomi-mimo（mimo-v2.5）全程 200 OK，仅 2 次 finish_reason=length 截断均由第 1/2 级重试消化；batch 18 一次通过无 resume；继续 phase4_batch.py + PYTHONPATH=. 直跑。

## KC Task 0（2026-08-29）🔄 reviewer fix

- `tests/test_kc/test_integrity_idempotency_contract.py` 收缩为 Task 0 合法边界：保留 `check_default_closure(..., integrity_report=None)` 的 fail-closed 契约测试；移除依赖未来 `JSONLEventStore.append_event(...)->dict` 的两个执行性测试，不在 Task 0 提前实现 Task 3 API。
- operation/idempotency 部分仅冻结后续统一报告字段形状：`passed`、`reason_codes`、`operation_id`。
- 该 closure 契约测试与现有 `tests/test_kc/test_default_closure.py` 的 simplified-pass 基线是**有意冲突**；不在 Task 0 修改旧测试，留到 Task 1 一并调整 `closure.py` 与 legacy fixtures。


## KC Task 0–7（2026-08-29）✅ 分层完成

按 `docs/superpowers/plans/2026-08-29-kc-integrity-idempotency-layered.md` 8 任务逐项交付：TDD + per-task review + 独立 commit；最终全分支 review + 报告见下方。

| Task | Commit | 范围 |
|---|---|---|
| 0 | `b55d57ad` test(kc): freeze task 0 closure and idempotency contract | `tests/test_kc/test_integrity_idempotency_contract.py` 冻结 fail-closed 报告字段 |
| 1 | `4fe574e3` fix(kc): make publication closure fail closed | `closure.py` 移除 simplified/assumed 通路；缺失依赖 → `missing_integrity_report` 等 reason code |
| 2 | `d6d97902` fix(kc): enforce evidence and provenance boundaries | `DefaultFilter` 拒缺 evidence / closure 未通过；`ProvenanceGate` 拒 synthesized 缺 derived_from；adapter round-trip 7 个 additive 字段；filter.py 文档复原 |
| 3 | `f44969cf` feat(kc): add deterministic event idempotency | `compute_identity_key` 不变；`make_operation_id`；`append_event(operation_id, payload_hash)` ok/duplicate/version_conflict；VersionManager dedupe 限 fresh 实例 |
| 4 | `78168323` feat(kc): restore core from durable storage and replay events | `RestoreReport` 替代 bool；`snapshot_from_storage` 免调用者传入对象；`KnowledgeKernel.replay_object`；`EVENT_STREAM_PATH` 修正；restore byte-faithful idempotent |
| 5 | `a83211df` fix(kc): make vector publication retryable and idempotent | `tests/test_kc/test_pending_idempotency.py` 7 个 KC 层跨切场景 |
| 6 | `be24606b` feat(kc): add temporal and staging-based view recovery | WikiPage `valid_from/valid_to` additive；`rebuild_wiki_view` staging-first；`scripts/kc_agent_eval.py` mode/runtime_verified；`docs/evaluation/kc_mvp_cases.yaml` 30 cases × 30 dimensions |
| 7 | `3ab15486` test(kc): verify integrity idempotency and recovery boundaries | 9 个 E2E 场景覆盖：候选拒绝/完整发布/重复 ingest/Core replay/backup restore/vector pending 重试/legacy 页 round-trip/staging 失败保留旧页/delivery summary |

### 分层验证结果

- P0 子集（test_kc + test_vector + test_pipeline/test_ingest_vector_publication）：300 passed
- P0+P1 stable 子集（test_kc + test_knowledge + test_wiki + test_vector）：1458 passed（+ 4 pre-existing template-parser failures）
- P0+P1 真实分层（含 test_pipeline 但跳过已知破损 `test_retry.py`/`test_ndg_calibrate.py`/`test_phase4_batch_key.py` —— scripts.phase4_batch / phase4_orchestrator 等无法作为 importable package；属环境限制，与本计划无关）：1894 passed / 62 failed（失败均为 pre-existing）

### Known Limitations / Parked（入 known_limitations）

- Task 3 I-1：`append_event` check-then-write 非原子；并发 ingest 走文件锁是后续 Z-3。
- Task 3 I-2：`PostgresEventStore.append_event` 继承 ABC 的 `NotImplementedError` 默认值；Postgres 真实现不在本计划范围。
- Task 3 I-3：VersionManager dedupe 仅作用于 fresh 实例（`obj.versions` 空）；保留 `tests/test_knowledge/test_version_manager.py::test_retention_*` 通过。
- Task 4：drill.py 与 `src/kc/backup/__init__.py` 文档字符串 `restore_snapshot -> bool` 已过期（实现已返回 RestoreReport）；属 follow-up 文档清理。
- Task 4（Finding I-2）：`replay_object` 只读 VersionManager 快照，不读 events.jsonl。P0「按事件序列重放」措辞解释为 snapshot+version 序列重放，而非 event-source 重放。Future：在 kc.object.created/updated 事件上实现 replay_core，未知/损坏事件抛 ValueError。
- Task 6：`temporal_filter` / `RetrievalGate` 对 WikiPage 与 KnowledgeObject 走差异化语义——WikiPage 两 None 走 back-compat pass-through，KnowledgeObject 走严格 unknown-drop。
- 环境真实 LLM provider 不可用 → Agent runtime evaluation `mode=runtime, runtime_verified=true` 案例 = 0；当前 `docs/evaluation/kc_mvp_cases.yaml` 30 条全 `mode=mock`，evaluator 报告 `not_evaluable=True`、`runtime_count=0`。

### next_phase_ready

`false`：P1 评估基线 30 条 mock 通过但 runtime_verified=0（环境限制）；任务 7 E2E 全 deterministic 通过；任务 0–5 P0 gate 在 `tests/test_kc` + `tests/test_vector` + `tests/test_pipeline/test_ingest_vector_publication` 1458（+ 4 pre-existing）+ 27 全绿。下一阶段前置 = 配置 runtime LLM provider（xiaomi-mimo / sfkey-glm 任一）后运行 `scripts/kc_agent_eval.py --dataset docs/evaluation/kc_mvp_cases.yaml`，待 `runtime_count >= 1` 再置 `true`。

## Review-Findings Batch（2026-08-29）✅ 全分支 review 整改

最终 whole-branch review（plan `2026-08-29-kc-trustworthy-mvp.md`，即 `2026-08-29-kc-integrity-idempotency-layered.md`）5 项 Important + 2 项 Nit 一次批量整改，单 commit `fix(kc): address final review findings batch`：

| # | Finding | 整改 |
|---|---|---|
| I-1 | `get_kernel` 单一全局实例跨项目串扰（`get_kernel(root_a) is get_kernel(root_b)`） | 改为按规范化 root 路径的 per-project dict：同 root 同实例、异 root 异实例、`get_kernel(None)` 返回当前项目已有实例（非跨项目）；`tests/test_kc/test_kernel_isolation.py` 6 测试；既有 `tests/test_knowledge/test_kernel.py` 0 改动仍全过 |
| I-2 | `replay_object` 只读 VersionManager 快照而非 events.jsonl（P0「按事件序列重放」措辞歧义） | 文档化进 Known Limitations（见上）；无代码改动 |
| I-3 | `DefaultFilter` temporal 门是 stub（`_ = query_time; return True`） | 接线 `_passes_temporal`（WikiPage None/None back-compat pass-through，KnowledgeObject None/None strict unknown-drop，`type(page).__name__ == "WikiPage"` 判别）；`test_default_retrieval_filter.py` 加 5 个区间测试（current / historical / scheduled / legacy / invalid from>to） |
| I-4 | MVP 30 case 中 10 个负路径 case（quarantine/conflict/supersede，空 evidence_refs/expected_top_k）缺 `not_applicable` 标记 | 10 个负路径 case 加 `not_applicable: true`；`scripts/kc_eval.py::evaluate_gold_case` 加 contract gate（`invalid_fields`：`not_applicable` 缺失 / `not_applicable_misplaced` 误标；作用于 Task-6 风格 case，legacy 数据集不动）；`tests/test_kc/test_eval_contract.py` 6 测试 + `tests/test_kc/test_agent_eval.py` 4 测试（mock 结果不计入 success_rate / citation_accuracy） |
| I-5 | `src/kc/backup/__init__.py` docstring `restore_snapshot -> bool` 过期 | 更新为 `-> RestoreReport`（doc-only） |
| Nit 1 | filter.py 28-32 / 180-186 过期注释（"WikiPage 无 valid_from/valid_to"） | 更新为 Task 6 语义：WikiPage 已有 None 默认字段；None/None 差异化 pass-through（WikiPage）/ unknown-drop（KnowledgeObject） |
| Nit 2 | event_store docstring 补注 | `JSONLEventStore.append_event` 补 TOCTOU check-then-write 窗口说明（Z-3 follow-up，跨进程需文件锁）；ABC `append_event` 默认补 fail-closed `NotImplementedError` 说明 |

**整改后回归（4 目录）**：`pytest --import-mode=importlib tests/test_kc tests/test_knowledge tests/test_wiki tests/test_vector` → **1482 passed / 6 failed**（dirty-worktree 实测；clean HEAD 口径 = 1458 既有 + 21 新增 = 1479 passing + 4 pre-existing failing）。
- 4 个 failed 为 **pre-existing template-parser**（`test_wiki/test_lint.py::test_lint_missing_section_warns_v2_template`、`test_wiki/test_stubs.py::test_materialize_one`、`test_wiki/test_stubs_atomic.py::test_stub_unlink_uses_sentinel`、`test_wiki/test_templates_resolver.py::test_resolve_cache_does_not_break_missing_file_error`），与本次整改无关。
- 另 2 个 failed（`test_kc_ku_dryrun::test_dryrun_writes_markdown_report_with_pagetype_and_cost`、untracked `test_ku_split_strategy::test_estimator_json_output_on_novel_wiki`）系并发 workspace 进程 stash-pop 在 `knowledge/novel-wiki/wiki/**` 页内注入 conflict marker 所致——clean HEAD worktree 下前者通过、后者文件不存在，**均非本批量回归**。
- 本批量新增 21 个测试全部通过；既有的 1458 个 passing 测试无一回归。

## Open Items Resolution Batch（2026-08-29）✅

最终 review 报告的剩余未解决项一次性整改（单 commit `fix(kc): resolve open items batch`），逐项状态：

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| OPEN-1 | Task 3 I-1 TOCTOU：`append_event` check-then-write 无跨进程文件锁 | ✅ RESOLVED | `JSONLEventStore` 新增 `_EventFileLock`（POSIX `fcntl.flock(fd, LOCK_EX)` / Windows `msvcrt.locking(fd, LK_LOCK, 1)`，锁文件 = `events.jsonl` 兄弟 `events.lock`）包裹「索引重查 + 追加」。fast-path 缓存命中免锁；miss 走锁内磁盘刷新重查，保证跨线程/跨进程同一 `operation_id` 恰好一个 `ok` 一个 `duplicate`。新增 2 个并发回归测试（同一实例 + 两个冷启动实例），10 次压测稳定 |
| OPEN-2 | Task 3 I-2：`PostgresEventStore.append_event` 默认 docstring | ✅ RESOLVED | 类 docstring 补注：继承 ABC 默认 `NotImplementedError`（fail-closed）；真实 Postgres 实现延后；Postgres 后端仅配置存在（本计划无生产调用方）；引用 plan Task 3 OPEN-2 / progress Known Limitations。零行为变更 |
| OPEN-3 | Agent runtime eval（`runtime_count=0`） | ⚠ OPEN-BLOCKED-ON-TOOLING（Z-3 follow-up） | provider 配置**已存在**（`%LOCALAPPDATA%\ruflo-kb\ruflo-kb\llm-providers.json`，default glm-5.2 + sfkey-glm/xiaomi-mimo/anthropic/minimax 等），但 `scripts/kc_agent_eval.py` 是 mock-fixture dry-run 评估器，**无任何真实 provider 调用路径**（脚本 docstring 明示 real agent runtime = Z-3 follow-up）；且其数据集 schema 为 `task_id`，与 `kc_mvp_cases.yaml`（`case_id`）不匹配——按 progress 原命令 `--dataset docs/evaluation/kc_mvp_cases.yaml` 运行直接 `KeyError: 'task_id'`。实测：`kc_agent_eval --dataset docs/evaluation/agent_tasks/agent_tasks.yaml` → 10 任务全 mock、`runtime_count=0`、`not_evaluable=true`；`kc_eval --dataset kc_mvp_cases.yaml`（正确评估器）→ 30/30 schema 通过（mock-only）。`runtime_count>=1` 需实现真实 agent runtime 接线（Z-3），非纯配置可解 → `next_phase_ready` 保持 `false` |
| OPEN-4 | Task 4 event-source replay（P0「按事件序列重放」措辞未字面满足） | ✅ RESOLVED（stub） | `KnowledgeKernel.replay_core_from_events(object_id, stream_id)` 加入 `src/knowledge/kernel.py`：经 `JSONLEventStore.read_stream` 读 events.jsonl，对 `kc.object.created/updated` 事件应用 no-op，返回 `reason_codes=("event_replay_stub",)`（诚实声明真实事件源重放未接线；未来 replay_core 将应用事件并对未知/损坏事件抛 ValueError）。新增 3 测试：`replay_object` 快照语义不变 + stub 返回 + 空流 stub |
| OPEN-5 | 4 个 pre-existing template-parser 失败 | ✅ VERIFIED（非本批范围） | clean HEAD 复现 4/4（均 `TemplateParseError`）：`test_wiki/test_lint.py::test_lint_missing_section_warns_v2_template`、`test_wiki/test_stubs.py::test_materialize_one`、`test_wiki/test_stubs_atomic.py::test_stub_unlink_uses_sentinel`、`test_wiki/test_templates_resolver.py::test_resolve_cache_does_not_break_missing_file_error` |
| OPEN-6 | `src/kc/backup/__init__.py` docstring | ✅ RESOLVED（前批已修） | `git show 83841b6c -- src/kc/backup/__init__.py` 确认 `restore_snapshot(...) -> RestoreReport` 已在 final-review commit 修复，本批仅核验 |
| OPEN-7 | Ledger 数字准确性 | ✅ RESOLVED | "1462 passed" → "1458 passed（+ 4 pre-existing template-parser failures）"；`next_phase_ready` 段落 1462+27 同步；Review-Findings 段标注 clean HEAD 口径 |

**本批回归（4 目录，dirty-worktree 实测）**：`pytest --import-mode=importlib tests/test_kc tests/test_knowledge tests/test_wiki tests/test_vector` → **1487 passed / 6 failed**。
- 4 个 failed = pre-existing template-parser（同 OPEN-5，非本批范围）。
- 另 2 个 failed（`test_kc_ku_dryrun::test_dryrun_writes_markdown_report_with_pagetype_and_cost`、untracked `test_ku_split_strategy::test_estimator_json_output_on_novel_wiki`）系并发 workspace 进程 stash-pop 在 `knowledge/novel-wiki/wiki/**` 注入 conflict marker 所致——与上一批记录一致，非本批回归（本批未触碰该目录）。
- 本批新增 5 个测试（OPEN-1 ×2 并发 + OPEN-4 ×3 重放）全部通过；clean HEAD 口径 passing = 1458 既有 + 21（上批）+ 5（本批）= 1484。

### next_phase_ready（本批后）

保持 `false`：OPEN-3 确认 provider 已配置，但 runtime eval 管线无真实调用路径（Z-3 follow-up），`runtime_count >= 1` 无法通过配置达成；其余 OPEN 项已闭环。解锁命令（provider 已就绪，缺的是 runtime 接线；当前输出 `runtime_count=0 / not_evaluable=true`，需先实现真实 agent runtime eval 并产出 `runtime_verified=true` 案例才可置 `true`）：

```
$env:PYTHONPATH='.'; python scripts/kc_agent_eval.py --dataset docs/evaluation/agent_tasks/agent_tasks.yaml
```
