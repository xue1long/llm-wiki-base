# NDG 摄取流水线整改方案（v2，含对抗复审 F1-F10）— 2026-08-01

> **依据**：① 2026-08-01 第三方对抗性审计（A1-A3 / B1-B9 / C1-C9，逐行核对实现）；
> ② 2026-08-01 对抗复审（F1-F10，对 v1 整改方案自身的批判）；审计与复审结论见会话记录；
> ③ batch 0（2026-08-01）门禁实测暴露 P7 误报 6 例（夔/猰貐/穷奇/共工/白虎/中国神话人物）——
> **实证确认 F1**；④ 吸收 `2026-08-01-ndg-p7-extras-remediation.md`（其 R1-2a/b、P7、B6、R2-2a 方向一致，
> 已并入本文档对应任务；其"命中批页→无条件批页胜"**不吸收**，保留本方案的 grade 裁决）。
> 本方案只做整改，不引入新功能；每任务 TDD + 一次一 commit + per-task reviewer。
>
> **修正声明**：
> 1. **撤销"批级原子写盘 / 回滚粒度=批"**。commit 按 source 分组、每组独立 `AtomicContext`
>    （`ingest.py:446`），批内 N 文件 = N 个提交点。整改后承诺改为：
>    **全批 gate 前置校验 + per-file 原子提交 + per-file 精确续跑**（`completed_files` 落盘）。
> 2. **D1/V16（UGC 载体强制打标）此前未落地** → 本方案以**确定性 auto-tag + P4b 校验**落地（零 LLM）。
> 3. **阈值标定（D3）产物缺失** → 本期执行一次标定写盘，并在文档中如实标注
>    "P2 属 lint 事后检查、不参与写前门禁"。
> 4. **【复审 F1】P7 会把"反向边更新既有页"误杀为覆盖保护** → 本期改为**内容保持判定**
>    （extra 与磁盘页 body 相同 → 放行；body 不同 → 才拦截）。这是 v1 漏掉的、比 A1-A3
>    更早触发、直接卡死"46 批放行"的阻断路径。**batch 0 实测 6 例误报全部 body 一致**，判定成立。
> 5. **【复审】retry 子批撞已提交同 slug 页无操作员路径** → 定义 retry 语义 + `--skip-files` 逃生门。

---

## 决策记录

### D1 — 续跑语义 = 文件级 `completed_files`（状态无关读取）
- **规则**：commit 循环**每文件成功后**原子落盘 `completed_files`；`--resume` 只重新生成
  `files - completed_files`，已完成文件不再烧 LLM；剩余文件作为**子批**重新 reconcile/gate/commit。
- **读取**：`_batch_completed_files` **按 entry 存在即取**（不按 status 白名单过滤，
  覆盖 `committing` / `partial` / `committed` / `postcheck_failed` 四态）；`gate_failed` 的
  completed_files 恒空（未 commit），天然正确。
- **键**：completed_files 存 manifest 的 `raw_rel`；**判定"某文件已提交"依据其 SOURCE 页已落盘**
  （SOURCE 页的 `sources` **包含** raw_rel——Fix D 追加页由 `normalize_source_path` 写入恒等于 raw_rel
  `ingest.py:841`；LLM 生成的 source 页也因 Fix A 的 `llm_already_has_source` 判定而 sources 含 raw）——
  **不依赖任意页的 `sources[0]`**（后者可被 LLM 写别名，见 F5）。
- **理由**：批级 reconcile 需要整批页可见，因此整批 skip 不成立；文件级 skip + 子批化才既省
  LLM 又保住批级校验。
- **例外**：`gate_failed` 批未 commit → resume 全量重生成（正确但烧 LLM，见遗留）。

### D2 — 反向边 = 批级重算（reconcile 之后、gate 之前）
- **规则**：`reconcile_batch` 合并完成后，对 `pages ∪ extras` 统一重算一次反向边
  （目标在本批 → 加逆边；目标在磁盘 → 由 per-file `_compute_reverse_relations` 的 extra 机制承担）。

### D3 — extras 归 reconcile 统一管理（含 grade 裁决）
- **规则**：删除 `phase4_batch.py:297-305` 的 first-wins 去重；`reconcile_batch` 负责：
  (a) 同 id extras 折叠 relations（按 `(target_id,type)` 去重、weight 高者胜）；
      无需 body 差异分支——单进程 dry 批内磁盘不可变、同页加载的 extras body 恒等（M2 不可达，删除）；
  (b) extra 的 `(id,type)` 命中合并后批页 → **按 grade 裁决**：
      批页 grade ≥ extra grade → 折入批页、丢弃 extra；批页 grade < extra grade →
      保留 extra、丢弃批页，并记 `MergeEntry`（与批页合并的 grade 高者胜规则一致，见 F3）；
  (c) 其余 extras 原样进 `ReconcileResult.extras`。
- **作用域**：该折入仅在 `--allow-overwrite` 路径可达（默认路径 B6 在 commit 前已拦截碰撞页）；
  文档明确，避免误以为默认路径会静默合并。
- **取舍**：丢弃低 grade 批页时，其**出向关系随页丢弃**（不折入 extra）——"质量优先于连通性"；
  若需保留关系，操作员应将该文件 `--skip-files` 而非 `--allow-overwrite`。
- **影响**：`ReconcileResult` 增 `extras` 字段；`phase4_batch` 删除
  `len(all_extra)` 切片依赖（`phase4_batch.py:333-334`），改由 `result.pages` + `result.extras` 分流。

### D4 — state 双工具容错（无需命名空间）
- **规则**：`phase4_batch` 沿用顶层 `batch_key`（已实测 `migrate_state_paths` 对顶层 `batch_N`
  原样保留、不冲突，无需收拢命名空间）；`_load_state` 加 try/except；`batch_build.py` 的
  `load_state` 对 `ingested/archived/failed` 缺键补默认、`save_state` 改原子写。

### D5 — UGC = reconcile **之后** auto-tag + P4b 校验（零 LLM）
- **规则**：`lint.py` 新增 `_is_ugc_carrier(header)`；`phase4_batch` 在 **reconcile 之后、gate 之前**
  对载体 raw 派生的**非 stub 页**补齐双 UGC 标；`ndg_gate` 加 P4b（载体派生页缺任一标 → blocker）。
- **顺序修正（F2）**：reconcile 合并只折 relations/sources、**不折 tags**（`batch_reconcile.py:211-236`），
  因此 auto-tag 必须在 reconcile **之后**（对最终页集打标），否则 loser 页的标在合并时被丢。
- **排除 stub**：占位页不打标（修正 v1 未排除 stub 的疏漏）。

### D6 —【复审 F1】P7 = 内容保持判定
- **规则**：`_check_p7_extra_pages` 增加 body 比较——extra 与磁盘页 **body 相同**（仅 relations
  增改，即 B13 的反向边更新）→ 放行；body 不同（破坏性覆盖）→ 才需 `--allow-overwrite`。
- **理由**：extra 本质是"被引用但未新建的既有页 + 逆边"；存量 1678 个实体/概念页意味着 829 个
  重摄取文件几乎必然引用既有页 → 现状 P7（`ndg_gate.py:312-349`）几乎每批拦截，或逼操作员
  全批 `--allow-overwrite` 使门禁失效。**必须先修此条，46 批才能放行。**

### D7 —【复审】retry 子批语义 + 逃生门
- **规则**：resume 重试文件若产出与已提交页同 `(slug,type)` → B6 拦截并**显式列出碰撞页**；
  操作员二选一：`--allow-overwrite`（重试页胜），或 `--skip-files <raw_rel,...>`（永久排除该文件）。
- **理由**：整批时同 slug 由 reconcile 合并，子批看不到已提交页 → 撞车不可避免；必须给操作员
  一个不破坏保护的可执行出口。`--skip-files` 同时充当"持续失败文件"的逃生门（F10）。

---

## 验收总目标（整改后）

- `--resume` 精确跳过已完成文件；中断/`committing`/`postcheck_failed` 后均可续跑且不重复落盘。
- `ok==0`（含全 missing 空批）必失败，exit ≠ 0，不再假提交 `committed`。
- 批内跨文件关系反向边 100% 落盘（关系图双向）。
- **P7：反向边更新（body 未变）零拦截；破坏性覆盖仍需 `--allow-overwrite`**。
- `--allow-overwrite` 下新生成内容不被旧 extra 覆盖（grade 裁决）。
- 载体 raw 派生页 100% 双 UGC 标（reconcile 后 auto-tag，P4b 零命中）。
- POSTCHECK 缺页 → exit 3、state 标 `postcheck_failed` 且**记录 completed_files + 缺页清单**。
- 持续失败/撞车文件可经 `--skip-files` 永久排除。
- 全部测试通过；批 1 实测：P7 拦截数下降为 0（内容保持）、每批 ≥1 文件、gate PASS 才落盘。

---

## 执行顺序（依赖硬约束）

```
R0  零散：R0-1 logger NameError（C1）→ R0-2 ok==0 守卫（B4）
R1  地基：R1-1 state 双工具容错+状态无关读取（B7/F7）
         → R1-2 reconcile extras+grade 裁决（A3/B2/F3/D3）
         → R1-3 P7 内容保持判定（F1/D6）
R2  管线：R2-1 批级反向边重算（B1/D2）→ R2-2 commit 循环重写（A1/B3/B4/B6/B9/F4/F5/F6/F7）
R3  UGC：R3-1 reconcile 后 auto-tag + P4b（B5/F2/D5）
R4  标定与文档：R4-1 执行标定 + 修正声明落文档（B8）
R5  清理：R5-1 C2/C3/C4/C7/C8（保留 file_results，F5）→ R5-2 P1-P4 以 warning 进 gate（F9）
R6  实测：R6-1 batch 0 重跑验收（F1 实证；E4 并发约束）
```

---

## 任务分诊（三档）

**必须做（7，缺任一影响"46 批安全落盘"）**：R1-3（P7 内容保持）、R1-2 核心（result.extras 分离 + grade 折入 + B6 回归）、
R2-2 核心（SOURCE 页判定 resume + POSTCHECK 入状态 + extras 单独 commit 路径）、R1-1 核心（双工具容错 + 状态无关读取）、
R0-2（ok==0 守卫）、R0-1（logger 一行）、R6-1（batch 0 实测闸）。

**可选（建议做，不阻塞放行）**：R2-1（批级反向边，关系图完整性）、R3-1（UGC，避免事后全库补标）、
R5-1 C8（archive 跳过 stub）、R2-2 `--skip-files`（逃生门）、R4-1（标定+文档）、R5-1 C3/C4/C7 + F10（加固/运维）。

**没有必要做（删除）**：M2（同 id extras body 差异分支——单进程 dry 批内磁盘不可变、不可达）；
命名空间收拢（顶层 `batch_N` 经 `migrate_state_paths` 原样保留，不冲突）；C5 slug 跨平台 posix 化（Windows-only，无触发路径）。

---

## Phase R0 — 零散缺陷

### R0-1 `ingest.py:314` `logger` NameError → `_logger`（C1）
- **Files**：`src/pipeline/ingest.py`
- **Tests**：monkeypatch `read_page` 抛 `OSError`，调 `_compute_reverse_relations`，断言不抛 NameError、仅记 warning。
- **Implementation guidance**：`logger.warning(...)` → `_logger.warning(...)`。
- **验收**：错误路径不再被 NameError 掩盖。
- **Commit**：`fix(pipeline): _compute_reverse_relations 错误路径 logger→_logger（NameError）`

### R0-2 空批/全失败守卫（B4）
- **Files**：`scripts/phase4_batch.py`
- **Tests**：抽 `_decide_abort(ok, err, pending, resume, completed, skip) -> (abort, reason)` 并单测：
  ① `ok==0, err>0` → abort；② `ok==0, err==0, pending非空` → abort（全 missing）；
  ③ `ok==0, pending空, resume且 files⊆completed` → 不 abort（"已完成"）；④ 其余 → 不 abort。
- **Implementation guidance**：generate 汇总后按上表决定；abort 写 `state[batch]={status:"failed", ...}` 并 return 1。
- **验收**：CWD 错误 → 退出码非 0，不写 `committed`。
- **Commit**：`fix(scripts): phase4_batch 空批/全失败守卫（ok==0 必失败）`

---

## Phase R1 — 地基

### R1-1 state 双工具容错 + 状态无关读取（B7 / F7 / D4）
- **Files**：`scripts/phase4_batch.py`、`scripts/batch_build.py`
- **Tests**：
  - `_load_state` 遇损坏 JSON → `{}`（不崩）。
  - `_batch_completed_files` 对 `{status:"committing", completed_files:[...]}` / `postcheck_failed` → 均返回 completed_files（**状态无关**，F7）。
  - `batch_build.load_state` 缺 `ingested/archived/failed` → 补 `{}`（`phase_archive` 不再 KeyError）。
  - `batch_build.save_state` 中途异常 → 磁盘仍是旧完整文件（tmp+os.replace）。
  - 顶层 `batch_N` 经 `migrate_state_paths` 后原样保留（键非绝对路径、列表值原样存）——不冲突，无需命名空间。
- **Implementation guidance**：
  - `phase4_batch`：`_load_state` 包 `try/except (OSError, json.JSONDecodeError) → {}`；
    `_batch_completed_files` 改为
    `entry = state.get(batch_key); return set(entry.get("completed_files", [])) if isinstance(entry, dict) else set()`。
  - `batch_build`：`load_state` 后 `state.setdefault("ingested", {}); ...`；`save_state` 改原子写。
- **验收**：两脚本交替读写同一文件不再互踩/崩溃；四态 resume 读取一致。
- **Commit**：`fix(scripts): batch_build_state 双工具容错 + completed_files 状态无关读取`

### R1-2 reconcile 统一管理 extras + grade 裁决（A3 / B2 / F3 / D3）
- **Files**：`src/wiki/features/batch_reconcile.py`、`scripts/phase4_batch.py`
- **Tests**（`tests/test_wiki/test_batch_reconcile.py` 扩展）：
  - 两个同 id extra → 保留一个、**relations 并集**（B2）。
  - extra 命中批页且 **批页 grade ≥ extra** → 折入批页、extra 丢弃、合并记 1 条（A3：新内容存活）。
  - extra 命中批页且 **批页 grade < extra** → 保留 extra、批页丢弃、合并记 1 条（F3：既有 A 级页不被降级）。
  - 无碰撞 extra → 进 `ReconcileResult.extras`。
  - `pages` 只含批页、`extras` 只含保留的 extra（不再混排）。
- **Implementation guidance**：
  - `ReconcileResult` 增 `extras` 字段。
  - 现有 merge 之后：建 `batch_by_id={(p.id, p.type): p}`；遍历 `extra_pages`——
    命中批页 → 用 grade 比较决定 winner（复用 `_grade_order`），`_fold_relations(winner, loser.relations)`
    后把 loser 从对应集合剔除并记 `MergeEntry`；未命中 → 同 id extras 折叠 relations 后留一个进 `extras`。
  - `phase4_batch`：**删除 297-305 预去重**；`reconcile_batch(all_pages, all_extra, paths)` 后
    用 `result.pages`（批页）+ `result.extras`（保留 extra）分别走 gate 与 commit；**删除 333-334 切片**。
  - **B6 作用域**：`_check_overwrite_protection(result.pages, ...)`——extras **移出覆盖保护**（只查批页；
    它们由 P7 内容校验 + R1-2 管理）；补回归测试（构造含 extras 的批 → B6 只对批页报覆盖、extras 不报）。
- **验收**：A3 场景磁盘保留新内容；F3 场景高 grade 页（无论新旧）胜出；现有 reconcile 单测全绿（extras 断言改为 `result.extras`）。
- **Commit**：`fix(wiki): reconcile 统一管理 extras——同 id 折叠 + 碰撞按 grade 裁决（A3/B2/F3）`

### R1-3 【复审 F1】P7 内容保持判定
- **Files**：`src/wiki/features/ndg_gate.py`、`tests/test_wiki/test_ndg_gate.py`
- **Tests**：
  - extra 与磁盘页 body 相同 + 仅 relations 增改（反向边更新）→ P7 **零 issue**（batch 0 场景）。
  - extra 与磁盘页 body 不同 → blocker；`--allow-overwrite` → warning。
  - 磁盘页为 stub → 放行（既有 stub 升级行为不变）。
  - **命中批页的 extra 不再由 P7 处理**（R1-2 已折入）——P7 只面对残留 extras，无"命中批页"分支。
- **Implementation guidance**：`_check_p7_extra_pages` 中，命中非 stub 磁盘页后增加
  `if ep.body == existing.body: continue  # 反向边更新，内容保持`；再做覆盖判定。
  （extra 由 `read_page` 载入、仅 relations 被 `_compute_reverse_relations` 修改，body 恒等于磁盘——
  已确认 `ingest.py:272-334` 来源单一；若 quality gate 曾改 body 则该判定自动收紧为需 `--allow-overwrite`。）
- **配套**：必须与 R1-2 一起上线——R1-2 折入后剩余 extras 均为"body 未变"，P7 放行；
  若先放 P7 而 R1-2 未上，A3 的"旧内容覆盖新内容"会经 extras 复活；同样地，若 B6 作用域未随
  R1-2 收窄（只查批页），P7 放行的 extras 仍会被 B6 拦。
- **验收**：batch 0 实测 P7 误报 6 例（body 一致）全部放行、批 commit；破坏性覆盖仍被拦。
- **Commit**：`fix(wiki): P7 改内容保持判定——反向边更新既有页不再误拦（F1）`

---

## Phase R2 — 管线

### R2-1 批级反向边重算（B1 / D2）
- **Files**：`src/wiki/features/batch_reconcile.py`
- **Tests**：
  - 批页 A → 批页 B（同批）：reconcile 后 `B.relations` 含逆边。
  - A → 磁盘既有页 X（extra）：X 的逆边由 per-file pass 已加，批级重算不重复。
  - 对称关系（`SYMMETRIC_RELATIONS={contradicts,analogous_to,opposite_of}`）不加逆边。
  - **全类型核对**：`Relation.inverse()` 对每个 `RelationType` 成员返回非 None（除对称集）——实现时逐个 type 断言。
- **Implementation guidance**：reconcile 合并、extras 折叠完成后，新增 `_recompute_reverse_relations(pages)`：
  建 `by_id`（批页 + extras 共用），遍历每页 relations，`rel.inverse()` 非空且非对称且命中 `by_id`
  → 按 `(target_id,type)` 去重并入目标页。
- **验收**：构造"文件 A 引用文件 B 产出页"合成批 → 重算后 B 含逆边；磁盘 extras 不被破坏。
- **Commit**：`feat(wiki): reconcile 批级反向边重算——批内引用关系图双向（B1）`

### R2-2 commit 循环重写（A1 / B3 / B4 / B6 / B9 + F4 / F5 / F6 / F7）
- **Files**：`scripts/phase4_batch.py`（抽 `_generate_batch` / `_commit_all` 纯协程，F8）
- **Tests**（`tests/test_scripts/test_phase4_batch.py`，新增 conftest，monkeypatch `commit_ingest`/`generate_ingest`/`read_index`）：
  - **续跑**：模拟第 3 文件 commit 后抛异常 → state 含 `completed_files=[前2]`；`--resume` 只重新生成剩余文件
    （断言 `generate_ingest` 调用次数 = 剩余文件数）。
  - **F5**：构造某页 `sources[0]` 为别名（≠ raw）→ completed_files **仍按 SOURCE 页判定**记录正确文件。
  - **F4**：POSTCHECK 缺页 → exit 3、state `postcheck_failed` 含 completed_files + 缺页清单；
    再 `--resume` 只补缺页，不重生成已提交页。
  - **F6**：retry 页撞已提交同 slug → B6 报错列出碰撞页；`--skip-files` 后该文件被永久排除。
  - **B3**：err>0 时 state 记录 `failed_files` 明细。
  - **B9**：extras 单独一次 `commit_ingest(event="reverse-relation")`，无伪 ingest 日志。
- **Implementation guidance**：
  1. `_generate_batch`：现有 generate + reconcile + gate + B6 汇总；返回 `(result, ok, err, raw_headers)`。
  2. commit 前构建 `{raw_rel: source_page_id}`（遍历 `result.pages` 中 SOURCE 页的 `sources`，
     **包含** raw_rel 即判定归属——Fix D 追加页 sources 恒等于 raw_rel、LLM 页也因 Fix A 含 raw，
     见 D1；**不依赖 `sources[0]`**）。
  3. `_commit_all`：按 `result.pages` 的 `sources[0]` 分组（仅批页）；每组 `commit_ingest` 成功后，
     把组内**含其 source 页的 raw_rel** 加入 `committed_files`，写
     `state[batch_key]={status:"committing", completed_files:[...], failed_files:[...]}` 并 `_save_state`；
     **`failed_files` 在每次 resume 后被本轮新失败集替换**（旧失败已被本轮重试，避免累积陈旧条目）；
  4. 循环后：`if result.extras: commit_ingest(paths, Path("(batch-reconcile)"), [], result.extras, task_id, event="reverse-relation")`；
  5. POSTCHECK：`_post_errors>0` → `status="postcheck_failed"` + **completed_files（已提交者）+ missing 清单**、exit 3；
     否则 `status="committed"`、`completed_files` 全量、exit 0。
  6. `--skip-files <raw_rel,...>`：generate 前从 pending 剔除；撞车（B6 拦 retry 页）时
     报错列出碰撞页，提示 `--allow-overwrite` 或 `--skip-files`。
  7. **保留 `file_results`**（F5，R5-1 的 C2 只删 `_TYPE_DIR`）。
- **验收**：中断任一点 → `--resume` 精确续跑；postcheck 后只补缺页；持续失败/撞车文件可 `--skip-files` 排除；
  退出码：0 提交 / 1 生成失败 / 2 gate 拦截 / 3 postcheck 失败（更新脚本 docstring）。
- **Commit**：`feat(scripts): commit 循环重写——SOURCE 页判定续跑 + failed_files + extras 分离 + POSTCHECK 入状态 + --skip-files`

---

## Phase R3 — UGC 落地（B5 / F2 / D5）

### R3-1 `_is_ugc_carrier` + reconcile 后 auto-tag + P4b
- **Files**：`src/wiki/features/lint.py`、`src/wiki/features/ndg_gate.py`、`scripts/phase4_batch.py`
- **Tests**：
  - `_is_ugc_carrier`：命中 `feishu.cn`/`mp.weixin.qq.com`/`公众号`… → True；普通文本 → False。
  - **auto-tag 顺序（F2）**：构造载体文件 A、B 同时产出同 slug 实体 → reconcile 合并后，
    merged 页仍有双 UGC 标（auto-tag 在 reconcile 之后，标不再被合并丢掉）。
  - 非 stub 才打标；extra（既有页）不被反溯打标。
  - P4b：载体派生页缺标 → blocker；补标后 → 通过；非载体 → 不受影响。
- **Implementation guidance**：
  - `lint.py`：`_UGC_CARRIER_RE` + `_is_ugc_carrier(header)`（复用 `_read_raw_header` 的 4000 字符）。
  - `phase4_batch`：执行序 **generate → reconcile（R1-2）→ auto-tag → gate（P4b）→ commit**；
    auto-tag 遍历 `result.pages`（+`result.extras`？**否**——extras 是既有页，不反溯打标），
    对 `p.sources` 含载体 raw 且 `processing_depth != "stub"` 的页补齐 `素材/ugc`+`可信度/ugc`。
  - `ndg_gate`：`check_batch` 增 P4b——载体 raw 的派生页缺任一标 → `GateIssue("P4b", ..., is_blocker=True)`。
- **验收**：载体派生页 100% 双标（含合并页）；P4b 防线有效。
- **Commit**：`feat(wiki): UGC 载体 auto-tag（reconcile 后）+ P4b 门禁（D1/F2 落地）`

---

## Phase R4 — 标定与文档（B8）

### R4-1 执行标定 + 修正文档
- **Files**：`scripts/ndg_calibrate.py`（如运行时报错顺带修）、`.index/quality_settings.json`、`2026-08-01-ingestion-gate-ndg.md`
- **Tests**：标定写出的 `quality_settings.json` 含 `raw_paste.source_threshold/non_source_threshold`；
  `lint._load_raw_paste_thresholds` 读到该值。
- **Implementation guidance**：从 manifest 抽 25 文件 dry-run（seed 固定），`--write-thresholds` 落盘；
  人工过目 Top-10 长 run 后确认。文档补一句：**P2 属 lint 事后检查，不参与写前门禁；阈值仅被 lint 消费**。
- **验收**：阈值有据可查；文档不再声称"写前拦截 RAW-PASTE"。
- **Commit**：`chore(wiki): NDG 阈值标定落地 + P2 归属文档修正（D3）`

---

## Phase R5 — 清理

### R5-1 死代码与坏模式清理（C2/C3/C4/C7/C8；F5）
- **Files**：`scripts/phase4_batch.py`、`src/pipeline/ingest.py`、`src/wiki/features/lint.py`、`scripts/batch_build.py`、`src/pipeline/generator.py`
- **Tests**：每项改动伴随最小单测/既有回归。
- **Implementation guidance**：
  - C2：删 `_TYPE_DIR`（`phase4_batch.py:30-31`）；**`file_results` 保留**（R2-2 依赖，F5）。
  - C3：B6 的 `except Exception: pass` 收窄为仅吞 `PageNotFoundError`，其余记 warning 后按 blocker 处理。
  - C4：模板缺失 fallback（`ingest.py:786-809`）不再内嵌 `## 正文内容` 全文——改为 log ERROR + 保持蒸馏形态。
  - C7：批级 `time.monotonic()` 阶段计时，单批 >60min 记 WARN。
  - C8：`batch_build.phase_archive` 跳过 `processing_depth=="stub"` 页。
  - 【F10】provider 并发安全：在并发 3 + `asyncio.wait_for` 超时下验证共享 httpx client 不被取消破坏；
    若失败，改为每任务独立 client（验证项，随 R5 落地）。
- **验收**：`grep` 确认 `_TYPE_DIR`/裸 `logger` 零引用；lint/单测全绿。
- **Commit**：`refactor(scripts): NDG 清理——死代码、B6 收窄、模板回退、slug 稳定、archive 跳过 stub、provider 并发验证`

### R5-2 【复审 F9】P1-P4 以 warning 进 gate
- **Files**：`src/wiki/features/ndg_gate.py`、`tests/test_wiki/test_ndg_gate.py`
- **Tests**：构造空 body 页 → gate report 含 P1 warning、`passed=True`（不 block）。
- **Implementation guidance**：`run_ndg_gate` 在 `check_batch` 后对每页调 `check_page`，
  将 P1-P4 issue 以 `is_blocker=False` 并入 report（消费 lint 单一事实源，与 D4 不冲突——
  不改变 block 语义，仅让"写时可见坏页"）。
- **验收**：P1-P4 从死代码捞回"写时告警"；gate 的 `passed` 语义不变。
- **Commit**：`feat(wiki): NDG gate 以 warning 复现 P1-P4——写时可见页级质量（F9）`

---

## 审计/复审发现 → 整改任务对照表（追溯）

| 发现 | 级别 | 整改任务 |
|---|---|---|
| A1 `--resume` 死代码 | 致命 | R2-2（SOURCE 页判定 completed_files） |
| A2 批非原子 + 无法恢复 | 致命 | 修正声明#1 + R2-2（per-file 精确续跑替代"伪原子"） |
| A3 extras 覆盖新生成内容 | 致命 | R1-2（grade 裁决折入） |
| B1 批内跨文件反向边丢失 | 重大 | R2-1 |
| B2 extras 去重丢边 | 重大 | R1-2（同 id 折叠） |
| B3 失败文件无重试路径 | 重大 | R2-2（`failed_files` + resume 子批化） |
| B4 空批假提交 | 重大 | R0-2 |
| B5 UGC 未实现 | 重大 | R3-1 |
| B6 flush 吞错→误报 committed | 重大 | R2-2（POSTCHECK 入状态/退出码） |
| B7 state schema 冲突 | 重大 | R1-1 |
| B8 标定产物缺失 | 重大 | R4-1 |
| B9 extras 归组伪日志 | 重大 | R2-2（extras 分离提交） |
| C1 `logger` NameError | 轻微 | R0-1 |
| C2 `_TYPE_DIR` 死代码 | 轻微 | R5-1（`file_results` 保留） |
| C3 B6 通用 except | 轻微 | R5-1 |
| C4 模板回退含全文 | 轻微 | R5-1 |
| C5 slug 跨平台非确定 | 轻微 | 不处理（N3：Windows-only，无触发路径） |
| C7 无批级时间护栏 | 轻微 | R5-1 |
| C8 archive 给 stub 建向量 | 轻微 | R5-1 |
| **F1 P7 误杀反向边更新** | **致命** | **R1-3（内容保持判定）+ R6-1（batch 0 实证）** |
| **F2 auto-tag 顺序反了** | **重大** | **R3-1（reconcile 后打标）** |
| **F3 extras 折入无 grade 裁决** | **重大** | **R1-2（grade 高者胜）** |
| **F4 postcheck 漏记 completed_files** | **重大** | **R2-2（postcheck_failed 含 completed+missing）** |
| **F5 sources[0] 映射脆弱 / 删 file_results 矛盾** | **重大** | **R2-2 + R5-1（SOURCE 页判定 + 保留 file_results）** |
| **F6 retry 撞车无出口** | **重大** | **R2-2 + D7（--skip-files 逃生门）** |
| **F7 状态白名单漏 committing** | **重大** | **R1-1（状态无关读取）** |
| **F8 可测性缺口** | 轻微-重大 | **R2-2（抽 `_generate_batch`/`_commit_all` + tests/test_scripts）** |
| **F9 P1-P4 死代码** | 优化 | **R5-2（gate warning）** |
| **F10 provider 取消安全 / 持续失败空转** | 优化 | **R5-1（并发验证）+ D7（--skip-files）** |

---

## R6 — batch 0 实测（F1 实证 / E4）

### R6-1 重跑 batch 0 验收
- **前置**：R1-2 + R1-3 + B6 作用域 + R2-2 全绿（即 `2026-08-01-ndg-p7-extras-remediation.md` 的
  R1-2a/b、P7、B6、R2-2a 已并入并落地）。
- **Tests**：无新代码，跑 `phase4_batch.py --batch 0`（成本护栏：单批 >60min 告警）。
- **Implementation guidance**：
  - 预期：P7 误报 6 例（夔/猰貐/穷奇/共工/白虎/中国神话人物）因 `body` 一致全部放行，批 commit 落盘。
  - 验收：wiki 页数增加；`batch_build_state["batch_0"].status="committed"`；
    extras 以 `reverse-relation` 事件单独记入 log.md。
  - **E4 并发约束**：批跑期间**不并行** `batch_build --only archive` / `batch_build.py`（避免磁盘页竞态），文档化到操作手册。
- **Commit**：无（实测验证项；若暴露新问题，另立任务）。

---

## 遗留（本方案范围外，挂账）

- 存量 7 个含转录/长摘要 source 页、36 个 synthesis 长文页、59 个漂移 source 页——独立 cleanup 任务，不动。
- `gate_failed` 批 resume 全量重生成浪费 LLM——可后续持久化 generate 结果到 `.index/staging/`（优化，本期不实现）。
- `--count` 与 manifest 分批语义（`files[:count]` 在 theme 内截断）未处理，仅文档化。
- 若后续仍需要**真·整批原子提交**（单 `AtomicContext` flush 全部），可另加 `commit_batch` 选项；
  本期以 per-file + 精确续跑为准（修正声明#1）。
