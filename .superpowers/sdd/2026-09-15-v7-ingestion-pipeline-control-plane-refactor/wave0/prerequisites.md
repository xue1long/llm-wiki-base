# Wave 0 — 启动前置条件核对

> 日期:2026-09-15(plan 整改 + Wave 0 同日)
> 主 agent:MiniMax-M3(DSH 当前会话)
> BASE:`b1657ed9e589afd23017b5fdf8b285fcbd90adc5`

## A1-A7 逐条核对

| # | 条件 | 状态 | 证据 |
|---|---|---|---|
| **A1** | v3 实施 Phase 1.0~2.5 全部 commit 已落地 | ✅ | `60cc15c6` Phase 1 / `69842753` Phase 2 / `431cd867` Phase 3;progress.md 第 9 行 |
| **A2** | `_legacy.py` 已存在且 `V7_USE_V3=false` 回退路径已验证 | ❌ | `_legacy.py` 是 22 行 placeholder;`__init__.py:74-77` 引用 `_legacy_<module_name>` 4 个分离文件,**这些文件根本不存在**。`V7_USE_V3=false` 会 ImportError。**真回退路径未落地** |
| **A3** | 4 个 stage 顶层 async + `_extract_one` async | ✅ | `classify_doc:122` / `check_completeness:42` / `cluster_topics:51` / `fill_slots:134` / `_extract_one:144` |
| **A4** | WikiWriter P4/__other__ 闸门已落地 | ✅ | `wiki_writer.py:31` `OTHER_TOPIC_ID`;`:87-88` 闸门 A |
| **A5** | §1.5 反映当前真实代码 | ⚠️ | §1.5 大部分准确,但**有 2 处与现状不符**(见下方"§1.5 与 git grep 差异") |
| **A6** | progress.md v3 阶段勾选 | ✅ | progress.md 第 9 行 |
| **A7** | 本计划专属 ledger | ✅(刚落地) | 本文件 + README.md |

### 启动决策

| 通过项 | 3 项(A1/A3/A4) |
|---|---|
| 部分通过 | 1 项(A5 — §1.5 微调即可) |
| 阻塞 | 1 项(A2 — `_legacy.py` 缺失真回退路径) |

**A2 阻塞 Wave 1。** plan 整改时假设 H1 回退路径可通过 `V7_USE_V3_CONTROL_PLANE` + `V7_USE_V3=false` 实现,但**当前 `V7_USE_V3=false` 路径根本不可用**(导入会抛 ImportError)。必须先决定:

- (a) 接受现状,把 `V7_USE_V3_CONTROL_PLANE=false` 作为本次 plan 的**唯一**回退路径,**不依赖** `V7_USE_V3=false`(需要 plan 修订)
- (b) 补全 `_legacy_<module_name>.py` 4 个文件(可能引入 v2 实现到 v3 已删除启发式逻辑,风险大)
- (c) 修复 `__init__.py` 让 fallback 不存在的 legacy 文件时静默退到 v3(降低回退能力,但不引入新代码)

**推荐 (a)** — 与 plan-audit H1 整改"提供 Wave 1-3 的回退路径"一致,且不引入新代码。

### 决策落地(2026-09-15,用户确认)

| 项 | 决策 | 落地位置 |
|---|---|---|
| **A2** | 选 (a):仅依赖 `V7_USE_V3_CONTROL_PLANE` 单一回退 | plan §1.5 已固化 |
| **H4** | 改 `required=True`,删除 `default=DEFAULT_ROOT` | plan Task 3 已固化 |

**A1-A7 最终状态:** 7 项中 6 项 ✅ + 1 项 ⚠️(A2 通过 (a) 决策化解为可接受风险)。**Wave 1 启动条件全部满足,等待 git commit 落地后即可派发 Luna-A/B/C**。

## §1.5 与 git grep 差异(A5 微调需求)

| §1.5 假设 | 真实现状 | 影响 |
|---|---|---|
| `reviews_queue.py` 只有 `enqueue(source_id, title, matches, content_hash)`,**没有** `enqueue_failure` | `failures.py:125-153` **已实现** `enqueue_failure(source_id, stage, reason, payload, *, queue_path)`,签名与 §1.5 不同;**用 uuid4 随机 ID,不是稳定 hash** | Task 3 Luna-B 工作量减少(不必新建方法),但**稳定 ID 改造必须做** |
| `v7_checkpoint.json` 由 WikiWriter 写入 | WikiWriter 写 `v7_checkpoint.json`(page-level,`completed: [page_ids]`);`extract_full.py:33` 写 `v7_full_checkpoint.json`(batch-level,`completed_batches: [int]`),**两者已并存** | Task 4 工作量更聚焦于 source-level 改造,而非"新增独立文件" |

## 其它发现(对 plan 执行有影响)

1. **`extract_full.py` 参数支持(O2 加固前置):** `--root / --batch-size / --checkpoint / --json-out / --markdown-out / --apply` **已全部支持**;但 `--root` 当前 `default=DEFAULT_ROOT`(`knowledge/novel-wiki`),**不传会用默认值** — 与 H4 加固"缺则 exit 2"冲突。**需 Wave 0 决策:保留 default(用户友好)还是改 required(强制显式)**。
2. **`enqueue_failure` 当前签名:** `enqueue_failure(source_id, stage, reason, payload=None, *, queue_path=...)` — 缺 `page_id/topic_id/content_hash` 参数,无法生成稳定 hash ID。Task 3 改造必须**扩签名**。
3. **Stage 6 调研结果(H6):** `relation_extractor.py:37` 已实现 LLM + heuristic 双模式;**scripts/ 无任何调用方**;`__init__.py:22` 文档说"6. relation_extractor → extract_relations(pages) -> Relations",确认 v3 架构第 5 节流程图与代码现实不符。Task 6 修订文档有依据。

## Wave 0 已完成动作

- [x] 记录 BASE = `b1657ed9`
- [x] 记录 dirty files(仅整改后 plan)
- [x] 创建本 ledger(`README.md` + `wave0/prerequisites.md`)
- [x] H6 Stage 6 调研(输出见 `wave0/stage6-investigation.md`)
- [x] 冲突表初稿(见 `wave0/conflict-table.md`)
- [x] 共享 fixture 创建(见 `wave0/shared-fixture.md`)

## Wave 0 待补

- [ ] **A2 决策**:由用户/主 agent 在 (a)/(b)/(c) 中选择
- [ ] H4 决策:`--root` default 行为保留 vs 改成 required
- [ ] §1.5 微调(反映 `enqueue_failure` 已存在 + checkpoint 双文件并存)
- [ ] 共享 fixture 物理创建(`tests/fixtures/v7_control_plane/` + `source_a.md` + `source_b.md` + `expected_ids.json`)
- [ ] 创建 `_queue_lock.py` 软提示(O1 加固)
- [ ] 提交整改后的 plan + ledger commit

**Wave 1 启动条件:** A2 + H4 决策落地 + ledger + §1.5 微调完成 + 共享 fixture 物理创建 + `_queue_lock.py` 创建。
