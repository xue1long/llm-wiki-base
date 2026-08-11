# wiki-spec.md 与代码同步方案（修订版 v2.0）

> Version: v3.0 | 2026-08-03
> Status: 方向修订为 A（尊重 4 类治理），执行中
> 修订依据：独立第三方审计报告 `docs/evaluations/wiki-spec-sync-audit.md`，并实测修正其中一处偏差；v2.1 依据 2026-08-03 对 `analyzer.py` / `generator.py` / `types.py` / `sync_wiki_spec.py` / `wiki-spec.md` / `.git/hooks/pre-commit` 的**逐行代码复核**，修正了 v2.0 的若干行号与描述偏差（见 §0.1 复核记录）；v3.0 依据二轮复核发现——默认路径**刻意折叠**扩展类型、F2 前提不成立——**改走 A 方向**（见 §0.2）
> 前版：`2026-08-03-wiki-spec-sync.md` v1.0（已废弃，被本版取代）

---

## 0. 修订核心：原方案为什么不能直接用

原方案（v1.0）的因果链是 `改 wiki-spec.md → 跑 sync → wiki_rules_prompt.py 修好 → 系统一致`。
实测代码后，这条链**在源头就断了**，且原方案**漏掉了真正的类型词汇来源**：

1. **`analyzer.py` 从不读 `wiki_rules_prompt.py`**（`WIKI_RULES_SUMMARY` 仅在 `generator.py` 注入）。它依赖两处**硬编码类型清单**：
   - `analyzer.py:61`（markdown 提示词）：`source|entity|concept|synthesis`（4 类）
   - `analyzer.py:112`（JSON 提示词）：`concept|entity|claim|decision|procedure|event`（6 类）
   → 原方案只动 spec/sync，**碰不到这两处**，系统仍会产出 4/6 类，与 spec 的 8 类形成第三套矛盾清单。

2. **`generator.py` 有代码级类型映射**，sync 一个都碰不到：
   - `_DEPTH_BY_TYPE`（`:64`）仅 4 类
   - `response_format["properties"]["pages"]["items"]["properties"]["type"]["enum"]`（**`:481`**，另 3 处 `:818/:1031/:1257` 同构）硬编码 `["source","entity","concept","synthesis"]`
   - `required_slots_by_type` 字典出现于 `:466 / :803 / :1016 / :1227` 共 4 处，**均为模板驱动动态生成**（`{pt: required_slot_names(resolved_templates[pt]) for pt in PageType if pt in resolved_templates}`），并非硬编码 4 类；目前只有 4 类是因为 **bundled 只有 4 个模板**（concept/entity/source/synthesis）——slot 覆盖缺口由模板缺失导致
   → 只要 LLM 产出新类型页面（JSON 提示词 `:112` **早已允许** 6 类），generator 在 **`response_format` enum 的 schema 校验处失败**（新类型落到 `required_slots_by_type.get(ptype, [])` 兜底为空、`_DEPTH_BY_TYPE.get(page_type, "concept")` 兜底为 concept，均不会崩）。这是**已存在的潜伏 bug**，原方案会放大而非修复。
   - **附带发现（v2.1）**：`processing_depth` 枚举异常——`:503/:840/:1053/:1292` 为 `["source","entity","concept","synthesis","memory"]`，把 4 个 page type 名混入了本应为 `concept|memory` 的枚举，需一并修复。

3. **pre-commit 实际已接线**（审计 M1 此处有误，已实测纠正）：`.git/hooks/pre-commit`（**419 字节**，由 `scripts/setup_git_hooks.py` 安装；v2.0 误记为 4196）在每次 commit 调用 `sync_wiki_spec.py`。**但**该钩子仅在本地、不在版本控制内（`.git/hooks/` 永不入库），且 `.wiki-spec-md5` 被 `.gitignore:26` 忽略——因此**无法在 CI / 协作者克隆间复现**；加上 `sync` 的 fail-soft（YAML 错静默 exit 0），坏提交仍会被放行。

**结论**：本系统类型词汇真实分布在 **6 处**——`PageType` 枚举（`types.py`）+ 2 条 analyzer 硬编码清单 + generator 代码映射（`_DEPTH_BY_TYPE` + `response_format` enum；`required_slots_by_type` 4 处为模板派生的次要来源）+ 模板 + spec 摘要。原方案只触达最后一层，且连这层也因 generator 代码映射缺失而失效。

**v2.0 执行路径（换顺序，非微调）**：
> 架构裁决 → **建单一类型来源（PageType 驱动一切）** → 补 generator 代码映射（F2）→ 统一 analyzer 两清单（F1）→ 最后才对齐 spec 文本 + 模板 + sync → CI/验证加固。

### 0.1 复核记录（2026-08-03 代码实测，v2.1 追加）

对 `analyzer.py:61/:112`、`generator.py` 各映射点、`types.py:10-18`、`sync_wiki_spec.py`、`wiki-spec.md`、`.git/hooks/pre-commit`、`.gitignore:26` 逐行核对，**核心因果链全部成立**。以下为行号/描述级修正：

| 项 | v2.0 表述 | v2.1 修正 |
|---|---|---|
| `response_format` enum 行号 | `:477` | `:481`（另 3 处 `:818/:1031/:1257`） |
| `required_slots_by_type` 性质 | 「均仅 4 类」硬编码 | 4 处均为模板驱动动态生成；仅 4 类是因为只存在 4 个模板 |
| pre-commit 字节数 | 4196 | 419 |
| Task 3.4 行号 | spec `:174-180`→`:561-570` | `:561-570` 实为 spec 标题引用的**代码位置** `src/pipeline/ingest.py:561-570`；spec 全文仅 284 行，slugify 段在 spec `:240` |
| 附带发现 | 未提及 | `processing_depth` enum（`:503/:840/:1053/:1292`）混入 page type 名，正确应为 `concept\|memory` |

### 0.2 方向修订 v3.0（2026-08-03 二轮复核）：改走 A——尊重 4 类治理

二轮复核发现 v2.1 的 **F2 前提不成立**，故执行方向从「8 类对齐」改为「尊重治理、4 类页面层 + 8 类知识层」：

**新发现（推翻 F2）**：
1. 默认 candidate 路径（`ingest.py:795-801` 实际调用）走 `generate_from_knowledge_object`，其 `generator.py:1131-1132` 用 `KO_TYPE_TO_PAGE_TYPE.get(ko.type, PageType.CONCEPT)` **刻意折叠**扩展类型 → CONCEPT。该折叠由 commit `c5360c5`（消息「A2 procedure 类型治理」）引入，属**故意设计**，且 `generator_constraint.py:27-30` + `test_extended_types_map_to_concept` 明确断言。
2. `generate_from_candidate`（v2.1 依据的「直通类型」路径）**无活跃调用者**（仅 ingest.py:585 一条过时注释 + 自身定义），是死代码。
3. 计划提到的 `cand-274108b10c0b.md`（type: procedure）是治理 commit **之前**的陈旧数据；治理后默认路径不会再产出 procedure 页面。
4. 真正的既有问题是「无模板 → body 为空」，而非「schema 校验崩溃」。

**A 方向裁决**：
- **页面层（`WikiPage.type` / `PageType`）**：维持 4 类（source/entity/concept/synthesis）。`PageType` 枚举保留 8 值（`from_dict` 需解析陈旧数据），但仅 4 值可产出。
- **知识层（`KnowledgeType`）**：8 类，驱动 JSON analyzer。
- **单一真相源在 A 方向的落点**：analyzer markdown 提示词从 `PageType` 枚举派生（4 类）、JSON 提示词从 `KnowledgeType` 枚举派生（8 类）；generator 折叠经 `KO_TYPE_TO_PAGE_TYPE`（已正确且有测试）；spec 讲清「页面层 4 类 / 知识层 8 类」层分离。

**A 方向执行清单（替代 §2/§3 的 8 类改动）**：
| 原 Task | A 方向处置 |
|---|---|
| Task 1.1 analyzer 枚举驱动 | 保留，但 JSON 从 `KnowledgeType`（8 类）、markdown 从 `PageType`（4 类）派生 |
| Task 1.2 generator 补 4 映射 | **取消**（无崩溃可修）；仅修 `processing_depth` enum（4 处收窄 `concept\|memory`） |
| Task 1.3 契约测试 | 改为断言「markdown 提示词 == PageType 值 / JSON 提示词 == KnowledgeType 值」+ `KO_TYPE_TO_PAGE_TYPE` 全覆盖 |
| Task 3.1 spec 4→8 | **取消**；改为加「层分离」说明 |
| Task 3.2 补 4 模板 | **取消**（页面层无新类型可渲染） |
| Task 3.3 optional 字段 | 保留 |
| Task 3.5 tag 示例 | 保留 |
| Task 4.x sync/校验/CI | 保留 |
| 陈旧数据 `cand-274108b10c0b.md` | 列为已知陈旧数据，建议重摄取或手动改 concept，不默认自动处理 |

**不做（B 方向保留项）**：补 4 模板、`KO_TYPE_TO_PAGE_TYPE` 改 1:1、generator enum 扩 8、spec 改 8 类、改折叠测试。若未来产品需要 8 类页面，此为独立功能增量。

---

## 1. 决策门（已裁决，2026-08-03）

> **裁决汇总**：
> | 决策门 | 裁决结果 |
> |--------|----------|
> | G0 类型归属 | 维持为 WikiPage 类型（追认 `types.py` 现状） |
> | G1 模板策略 | A：补 `claim/decision/procedure/event` 4 个模板 |
> | G2 analyzer 主路径 | A：JSON 为主来源 + markdown 同步到 8 类，均枚举驱动 |

### 决策门 G0 — 4 个新类型的归属层（对应审计 M3）
**问题**：`claim/decision/procedure/event` 是否应作为 `WikiPage.type`（`wiki/core/types.py` 的 `PageType`）？
**事实**：代码已把 8 值全写进 `wiki/core/types.py:10-18` 的 `PageType`，且 `to_frontmatter_dict()` 直接写出。即**代码已裁决为 WikiPage 类型**。
**裁决**：**维持为 WikiPage 类型**（与代码一致），但 spec 文案必须写「WikiPage 层的页面类型语义」，不要与知识层 `src/knowledge/claims/` 的 Claim 对象混为一谈（二者命名撞车，需在 spec 明确区分）。
**若选「移出 WikiPage 层」**：则本方案 §3 的 PageType 扩展作废，改为从 `types.py` 删 4 枚举 + 在 KOS 文档单独描述——工作量更大，不推荐。
- **✅ 已裁决（2026-08-03）**：维持为 WikiPage 类型（追认 `types.py` 现状）。

### 决策门 G1 — bundled 模板策略（对应原 §3.2）
- **A（推荐）**：补 `claim.md/decision.md/procedure.md/event.md` 4 个模板，使模板与 8 类对齐。`required_slots_by_type` 由模板驱动生成（`required_slot_names()` 解析模板），**模板 slot 即契约来源**，无需另设常量对齐（M6 由 Task 3.2 模板可解析性保证）。
- **B**：仅把 `wiki-spec.md:173` 改为诚实表述「当前 4/8 类有 bundled 模板」，纯文档改动。
- **✅ 已裁决（2026-08-03）**：选 A，补 4 个模板；模板 slot 即 `required_slots_by_type` 的契约来源，需能被 `required_slot_names()` 正确解析（M6 约束）。

### 决策门 G2 — analyzer 提示词主路径（对应审计 M4 / 信息盲区 #2）
- 系统有 markdown（`:61`，4 类）与 JSON（`:112`，6 类）两条 analyzer 提示词。KOS 演进计划要求 `output_format="json"` 成为默认。
- **裁决**：以 JSON 提示词（`:112`）为 8 类引导的主来源；markdown 提示词（`:61`）同步更新到 8 类，保持两者一致。**两条都必须从 `PageType` 枚举生成，删除硬编码。**
- **✅ 已裁决（2026-08-03）**：选 A，JSON 为主 + markdown 同步到 8 类，两者均改为从 `PageType` 枚举生成、删除硬编码清单。

---

## 2. 阶段一：建单一类型来源（根因修复，先于一切文档改动）

**目标**：让 `PageType` 枚举成为类型词汇的唯一真相源，analyzer/generator/spec 全部从它派生，删除所有硬编码清单。

### Task 1.1 — analyzer 两处清单改为枚举驱动（修复 F1 / M4）
- 文件：`src/pipeline/analyzer.py`
- 位置：`:61`（markdown 提示词类型段）、`:112`（JSON 提示词类型段）
- 改动：
  1. 在 `analyzer.py` 顶部确认 `from src.wiki.core.types import PageType`（若无则加）。
  2. 在提示词模板中引入占位符 `{page_types}`，渲染时传 `page_types="|".join(t.value for t in PageType)`。
  3. 删除 `:61` 的 `source|entity|concept|synthesis` 与 `:112` 的 `concept|entity|claim|decision|procedure|event` 硬编码字符串。
- 验证：两处提示词渲染后均含 8 个 `PageType.value`，且集合相等。

### Task 1.2 — generator 代码映射补 4 新类型（修复 F2，必须在开启 8 类引导前完成）
- 文件：`src/pipeline/generator.py`：
  - `:64` `_DEPTH_BY_TYPE`：追加 `PageType.CLAIM/DECISION/PROCEDURE/EVENT` → 对应 depth 值（建议 `claim→concept`、`decision→concept`、`procedure→memory`、`event→concept`；需与 spec 语义自洽）。虽 `.get(page_type, "concept")` 有兜底不会崩，但显式映射避免语义歧义。
  - **`:481`（另 3 处 `:818/:1031/:1257` 同构）** `response_format` 的 `type` enum：追加 4 个值（`["source","entity","concept","synthesis","claim","decision","procedure","event"]`）。**这是 F2 崩溃的真正触发点，必须最先修。**
  - **修复 `processing_depth` enum 异常**：`:503/:840/:1053/:1292` 的 `["source","entity","concept","synthesis","memory"]` 收窄为 `["concept","memory"]`（v2.1 追加）。
  - `required_slots_by_type`（`:466/:803/:1016/:1227`）**无需改代码**——4 处均为模板驱动动态生成（`for pt in PageType if pt in resolved_templates`），Task 3.2 补齐 4 个模板后自动覆盖 8 类。**可选重构**：若追求消除重复，抽取模块级 `SLOT_CONTRACT` 时应**从模板解析而来**（包装 `required_slot_names`），而非硬编码新列表，否则会与模板再次漂移。
- **关键**：Task 1.2 必须在 Task 1.1（开 8 类引导）之前完成，否则 JSON 提示词允许产出新类型 → generator 在 `response_format` schema 校验处失败。

### Task 1.3 — 加契约测试（防回归）
- 新增测试：断言「`PageType` 每个成员在 `_DEPTH_BY_TYPE`、`response_format` enum（4 处）中均存在映射；且每个 `PageType` 若存在 bundled 模板则 `required_slots_by_type` 含之（模板驱动契约）」。
- 这样未来 `types.py` 加类型时，测试立刻红灯，杜绝再次漂移。

---

## 3. 阶段二：对齐 spec 文本 + 模板（原方案内容，放到此处才安全）

> 前提：阶段一已落地。此时改 spec 并经 sync，analyzer/generator 才不会与新类型冲突。

### Task 3.1 — PageType：规范 4→8（原 §3.1）
- 位置：`wiki-spec.md:107-128`（标题「4 种」、`:109`「4 类之一」、判定表 `:111-116`、启发式 `:118-122`）
- 改动：标题/措辞改 8；判定表与启发式各补 4 行。
- **语义来源**：从 `PageType` 枚举的**命名意图** + 代码用途写（不要凭空编造，也不要照搬知识层 Claim 对象的定义）。示例措辞：
  - `claim`：可从原文取证的具体断言/事实陈述（证据驱动）
  - `decision`：已作出的决策/结论（含取舍理由）
  - `procedure`：可复用的操作步骤/SOP/流程
  - `event`：具体发生的事件/时间节点/里程碑
- 并加一句区分说明：「WikiPage 的 claim 类型 ≠ 知识层 Claim 对象（见 KOS 文档）」。

### Task 3.2 — bundled 模板（按 G1 决策）
- 若选 **A**：新增 4 个模板，slot 名需能被 `required_slot_names()` 正确解析（M6 约束）——`required_slots_by_type` 由模板驱动生成，**模板即契约来源**，无需另行对齐常量。参照 `concept.md` 骨架格式。**注意**：模板新增后 `required_slots_by_type` 立即对 8 类生效，故 Task 3.2 与 Task 1.2 的 enum 修复须同步落地，避免「模板已加、enum 未加」或反序的中间态。
- 若选 **B**：改 `wiki-spec.md:173` 表述为诚实版本。

### Task 3.3 — frontmatter optional +5 字段（原 §3.3，但收紧）
- 位置：YAML `optional`（`wiki-spec.md:9`）
- 代码事实：`to_frontmatter_dict()` 写出 `created_at/updated_at/category/taxonomy_sub/related_entities`。
- **修订**（对应审计 M7 / A8）：`category`/`taxonomy_sub` 是**未发布的 STS 分类字段**，属不稳定 API。
  - 决策：若 STS 未定稿 → 仅追加 `created_at/updated_at/related_entities` 三项稳定字段，`category/taxonomy_sub` 标记为 `experimental` 或暂不列入公开 optional。
  - 若 STS 已定稿 → 全列，但注明 `experimental`。

### Task 3.4 — v2.4 slugify 段（已完成文本，待 sync 传播）
- `wiki-spec.md:240` 起已加 `slugify()` 片段。**修正（v2.1）**：v2.0 所记「行号 `:174-180`→`:561-570`」有误——spec 全文仅 284 行，`:561-570` 是 spec 标题中引用的**代码位置** `src/pipeline/ingest.py:561-570`，非 spec 自身行号。
- 本阶段只需跑 sync 把它写入 `WIKI_RULES_SUMMARY`。

### Task 3.5 — 素材标签示例非法（原 §3.5）
- 位置：`wiki-spec.md:98` 的 `素材/book`、`素材/excerpt`
- 代码：`TAG_VALUES["素材"]={ugc,official,转载,原创,投稿}` → 改为 `素材/原创`、`素材/投稿`（保留 `素材/ugc`）。
- `:99` 的 `可信度/book|ugc|mixed` 合法，不动。

---

## 4. 阶段三：执行 sync + 加固验证（对应 M1/M5/O2/O5）

### Task 4.1 — 跑 sync 并确认真实生成
- 命令：`python scripts/sync_wiki_spec.py`
- 必须确认：
  1. 输出 `Generated src/pipeline/wiki_rules_prompt.py`（不是 WARN + 静默跳过）。
  2. 脚本**返回码为 0 且确实重写了文件**（用 `git diff --stat` 看 `wiki_rules_prompt.py` 是否有变更；若 YAML 错，sync 静默 exit 0 但文件不变 → 必须本地核对 diff，不能只看退出码）。
- 提交生成的 `wiki_rules_prompt.py`（它是 spec 的派生物，必须随 PR 一起入库）。

### Task 4.2 — 导入校验（对应 O2）
- 加一步：`python -c "import src.pipeline.wiki_rules_prompt"` 确认生成的模块无语法错（sync 把 spec 正文包进 `'''...'''`，若正文含 `'''` 会损坏）。

### Task 4.3 — 既有数据与测试基线扫描（对应 O3/O4 / 信息盲区 #3#4）
- 执行前已扫描：`grep -rn "type: (claim|decision|procedure|event)"` 全仓，确认受影响页面（已知 `knowledge/novel-wiki/wiki/concepts/cand-274108b10c0b.md` 命中）。
- 跑 `pytest` 全量，定位任何因 4→8 类失败的用例（如断言 `WIKI_RULES_SUMMARY` 含 4 类、或 `response_format` enum 的旧测试），按需更新。
- 注意：可能存在断言旧 4 类内容的测试，改 8 类会**反向**打破它们——必须排查而非假设「全绿」。

### Task 4.4 — CI / 防漂移落地（对应 M5/O5，替代原 §9 空话）
- 因 `.git/hooks/pre-commit` 不在版本控制、`.wiki-spec-md5` 被 gitignore，**CI 是唯一可靠的跨机校验点**。
- 建议（二选一或叠加）：
  1. 在 CI 加一步：重新跑 `sync_wiki_spec.py`，`git diff --exit-code src/pipeline/wiki_rules_prompt.py` —— 若 spec 改了但生成物未同步提交，CI 红灯。
  2. 将 `.wiki-spec-md5` 从 `.gitignore` 移除并纳入版本控制（或改为校验生成物 hash），使漂移可被检测。
- 因仓库当前无 `.github/workflows/`（实测不存在），需新建最小 CI 配置或挂到现有 CI；若暂无 CI，至少在 PR 模板/审查清单写明「spec 变更须附带 sync 后的 `wiki_rules_prompt.py`」。

---

## 5. 验证标准（完成判定，覆盖全链路）

- [ ] `pytest` 全绿（含 Task 1.3 新增契约测试 + Task 4.3 排查后的全量测试）
- [ ] analyzer 两提示词渲染后 type 集合均为 8 值且相等（Task 1.1）
- [ ] `generator.py` 中 `_DEPTH_BY_TYPE` / `response_format` enum（4 处）均含 8 类；`processing_depth` enum（4 处）收窄为 `concept|memory`（Task 1.2）
- [ ] 4 个新模板就位后 `required_slots_by_type`（模板驱动）自动覆盖 8 类（Task 3.2）
- [ ] `python -c "import src.pipeline.wiki_rules_prompt"` 无语法错（Task 4.2）
- [ ] `wiki_rules_prompt.py` 的 `WIKI_RULES_SUMMARY` 含 8 个 PageType 名称 + `slugify` + 行号 `:561`
- [ ] `FRONTMATTER_RULES["optional"]` 含决策后的字段集（Task 3.3）
- [ ] `tag_namespace.is_valid_value` 对规范示例全 True（`素材/ugc|原创|投稿`）
- [ ] 若选 G1-A：4 新模板可被 `required_slot_names()` 正确解析，且解析结果与 `required_slots_by_type` 实际生成值一致（M6 一致性）
- [ ] `git diff --stat` 显示 `wiki_rules_prompt.py` 确有变更（证明 sync 真跑通，非 fail-soft 放行）
- [ ] 既有命中页面（如 `cand-274108b10c0b.md`）重新生成后无破坏

---

## 6. 回滚（修正 O1 不完整）

- 文档 + 代码 +（G1-A 时）模板，无破坏性。
- 回滚命令：
  ```bash
  git checkout docs/guides/wiki-spec.md src/pipeline/analyzer.py src/pipeline/generator.py src/pipeline/wiki_rules_prompt.py
  # G1-A 新增的 4 模板若是 untracked（未随 PR 提交），git checkout 删不掉：
  git clean -fd src/wiki/templates/bundled/   # 或手动 rm 4 个新模板
  ```
- 回滚后重跑 sync 恢复 `wiki_rules_prompt.py`。

---

## 7. 风险登记（对应审计全部条目）

| 审计项 | 类型 | v2.0 处置 |
|--------|------|-----------|
| F1 analyzer 不读 wiki_rules_prompt | 致命 | Task 1.1 枚举驱动两清单 |
| F2 generator 新类型崩溃 | 致命 | Task 1.2 补 `_DEPTH_BY_TYPE` + `response_format` enum + 修复 `processing_depth` enum + Task 1.3 契约测试 |
| M1 pre-commit 接线（审计误判为未接） | 重大→降级 | 实测已接；但补 CI 跨机校验（Task 4.4） |
| M2 types.py 无注释可提炼 | 重大 | G0 裁决 + Task 3.1 按枚举命名意图写 |
| M3 类型归属层 | 重大 | G0 裁决维持 WikiPage 层，spec 注明与知识层区分 |
| M4 两 analyzer 清单矛盾 | 重大 | Task 1.1 统一为枚举来源 + G2 主路径裁决 |
| M5 fail-soft + md5 不入库 | 重大 | Task 4.1 核对 diff + Task 4.4 纳入 CI/hash |
| M6 模板 slot 契约 | 重大 | G1-A + Task 3.2 模板可被 `required_slot_names()` 解析（模板即契约） |
| M7 optional 冻结未发布 API | 重大 | Task 3.3 收紧为稳定字段 / experimental |
| O1 回滚不完整 | 优化 | §6 `git clean -fd` |
| O2 生成模块语法风险 | 优化 | Task 4.2 导入校验 |
| O3 既有数据 | 优化 | Task 4.3 扫描 |
| O4 测试基线 | 优化 | Task 4.3 pytest 排查 |
| O5 防漂移 | 优化 | Task 4.4 CI |

---

## 8. 执行顺序总览（不可跳步）

```
G0/G1/G2 决策门（人工）
   ↓
Task 1.1  analyzer 枚举驱动             ┐
Task 1.2  generator 补 enum+_DEPTH 映射  ├─ 阶段一：根因（先代码）
Task 1.3  契约测试                      ┘
   ↓
Task 3.1~3.5  spec 文本 + 模板对齐  ┐
   ↓                                ├─ 阶段二：文档（后 spec）
Task 4.1  sync + 核对 diff         ┘
   ↓
Task 4.2~4.4  导入校验 / 扫描 / CI  ── 阶段三：加固
```

**严禁**：在未完成 Task 1.2 前开启 8 类引导（会触发 F2 潜伏崩溃）。
**严禁**：只改 wiki-spec.md 不跑 sync / 不核对 diff（fail-soft 会放行坏提交）。

---

## 9. 执行结果（2026-08-03，Path A 方向已完成）

> §5 验证标准里凡指向「8 类 / 4 新模板」的条目，在 Path A 下 **N/A**——本方案最终**不开 8 类**，只做枚举驱动 + 修 bug + 文档对齐 + 防漂移。

### 阶段一（代码根因）— 完成
- **Task 1.1 analyzer 枚举驱动**：`analyzer.py:62` markdown 提示词用 `{page_types}`（PageType 4 类白名单，`:308` 传值）；`:113/:125` JSON 提示词用 `{knowledge_types}`（KnowledgeType 8 类，`:484` 传值）。**行为变化**：JSON 提示词从 6 类扩到 8 类（预期）。
- **Task 1.2 generator**：新增 `PROCESSING_DEPTH_VALUES = ["concept","memory"]`（generator.py:74），4 处 processing_depth enum（:508/:845/:1058/:1297）改用它。`_DEPTH_BY_TYPE` 与 4 处 page-type enum 保持 4 类（A 方向不动）。→ F2「新类型崩溃」**前提已证伪**（`KO_TYPE_TO_PAGE_TYPE` 折叠治理，c5360c5），无需补 8 类。
- **Task 1.3 契约测试**：`tests/test_pipeline/test_generator.py` 断言 PROCESSING_DEPTH_VALUES == ["concept","memory"] 且不含其他 PageType 值（排除 concept 后）。

### 阶段二（spec 文本）— 完成
- Task 3.1/3.2 按 G0 裁决不做（维持 4 类规范）；spec 新增「页面层与知识层分离」小节（`docs/guides/wiki-spec.md:109-116`）解释两层关系。
- Task 3.3 `frontmatter.optional` 收紧为稳定字段 + experimental 注释（`category, taxonomy_sub` 标注 STS 未定稿）。
- Task 3.5 素材 tag 示例改为合法值（`素材/ugc`、`素材/原创`、`素材/投稿`）。

### 阶段三（sync + 加固）— 完成
- **Task 4.1 sync 真实生成**：`python scripts/sync_wiki_spec.py` 输出 `Generated src/pipeline/wiki_rules_prompt.py`；`git diff --stat` = `+23/-8`（**确认真实变更**，非 fail-soft）。
- **Task 4.2 导入校验**：`python -c "import src.pipeline.wiki_rules_prompt"` OK（本地全依赖）。
- **Task 4.3 全量测试 + 数据扫描**：
  - 全量 `pytest --continue-on-collection-errors`：**2532 passed / 40 failed / 1 collection error**。40 失败 + 1 收集错误**全部 pre-existing WIP**（stub_cap 10≠3、tag 硬校验未同步到测试、project context `_registry_path`、llm registry、storage 等），与本次改动无关——改动的 pipeline 文件测试 **67/67 通过**。
  - 数据扫描：**仅 1 个 stale 扩展类型页** `knowledge/novel-wiki/wiki/concepts/cand-274108b10c0b.md`（`type: procedure`，index.md:2544）。**报告不自动改**（计划决定）。
  - ⚠️ 新发现的环境坑：`tests/test_knowledge/conftest.py` 缺「restore real module」处理，导致全量收集 `test_memory_retrieval.py` 报 `src.searcher is not a package`（SETUP.md §4.4 复现）。已记入 `.memory/arch-constraints.md`。
- **Task 4.4 CI**：新建 `.github/workflows/wiki-spec-sync.yml`。四步：① 严格校验 spec frontmatter（复用 `sync_wiki_spec.py._parse_frontmatter`，异常传播 → 堵 fail-soft 漏洞）；② `python scripts/sync_wiki_spec.py`；③ `py_compile` 生成物（比 `import src.pipeline.*` 更稳——后者会触发 pipeline 包全链导入）；④ `git diff --exit-code src/pipeline/wiki_rules_prompt.py` 防漂移。PR path filter + push main。

### §5 验证标准对照（Path A）
- pytest 全绿 → ❌ 未达成（40 pre-existing WIP 失败，非本方案引入；本方案改动 67/67 绿）
- analyzer 8 值相等 → N/A（A 方向 JSON 8 类、markdown 4 类白名单，分层有意不同）
- generator enum 含 8 类 → N/A（保持 4 类）
- processing_depth 收窄 concept|memory → ✅（契约测试覆盖）
- 4 新模板 → N/A
- `import wiki_rules_prompt` → ✅（+ py_compile 加固）
- WIKI_RULES_SUMMARY 含 8 类名 → N/A
- FRONTMATTER_RULES.optional 字段集 → ✅（含 experimental 注释）
- 素材 tag 全 True → ✅（spec 文本已修；`tag_namespace.is_valid_value` 代码未变）
- `git diff --stat` 有变更 → ✅（+23/-8）
- 既有命中页无破坏 → ✅（`cand-274108b10c0b.md` 未改、未重新生成，保持原样）

### 未提交事项
- 工作树含大量 prior-session WIP（数百个 M 文件），本次改动尚未 commit，等待用户决定提交策略。
- `cand-274108b10c0b.md` 的 `type: procedure` 修复留给用户/后续任务。
