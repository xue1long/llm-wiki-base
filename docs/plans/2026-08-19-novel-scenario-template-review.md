# 审查报告：抽取 novel-wiki 为可复用「小说写作场景模板」

> 审查对象：`docs/plans/2026-08-19-novel-scenario-template-extract.md`
> 审查方式：真实阅读方案 + 核对 `src/templates/loader.py`、`src/cli_ext/project_cmd.py`、`src/wiki/templates/resolver.py`、`src/wiki/templates/state.py`、`src/wiki/storage/ensure.py`，并比对锁定设计 `specs/2026-08-15-novel-wiki-writing-template-design.md` 的 H3 / §5.4。
> 结论：方案**整体可行（纯搬运+注册，无核心回归）**，但存在 **2 处字面 bug** 与 **1 处与锁定设计的重大时序冲突（最关键，需用户决策）**，以及若干"预期差"需文档澄清。

---

## 一、已核实成立的方案假设（无问题）

| # | 方案假设 | 代码事实 | 结论 |
|---|---|---|---|
| 1 | `load()` 会读入 `.wiki-templates/*` 与 `taxonomy_tags.md` | `loader.py:58-62`：`root.rglob("*")` 递归读全部文件，仅排除 `template.json` | ✅ 成立 |
| 2 | `apply_template()` 会复制全部文件（含 `.wiki-templates/`、`taxonomy_tags.md`） | `loader.py:109-126`：遍历 `template.files` 全部写出 | ✅ 成立 |
| 3 | `project init --template` 不会因默认文件冲突而跳过模板 | `project_cmd.py:46`：`apply_template(args.template, paths.root, force=True)`，force 覆盖 schema/purpose | ✅ 成立 |
| 4 | 新增 `novel` 目录即被自动注册，无需改 cli/route/loader | `loader.list_bundled()`（`loader.py:83-84`）按目录自动发现 | ✅ 成立 |
| 5 | novel 的 v3.0.0 页面模板对新项目真的生效 | `resolver.py:53-57` 优先级：`项目 .wiki-templates/` > user > bundled 2.0.0 | ✅ 成立 |
| 6 | novel 的 v3.0.0 不会被 `wiki-templates status` 重置回 2.0.0 | `state.py:117-164` `capture_current_bundled` 只扫 `BUNDLED_DIR`，不写项目级 `.wiki-templates/` | ✅ 成立 |
| 7 | 新项目含 4 个基础目录，脚手架可用 | `ensure_knowledge_base` 默认建 `wiki/sources|entities|concepts|synthesis`（+claim/decision） | ✅ 成立 |
| 8 | `general` 的 `template.json` 写 `name:"General"` 但注册名是 `general`，无碍 | `loader._read` 用**目录 id** 作 `Template.name`，忽略 JSON 里的 name 字段 | ✅ 无碍 |

---

## 二、字面 bug（必须修，无争议）

### Bug A — Task 1 Step 3 验证命令自相矛盾 ⛔
- **现状**：Task 1 只创建 `purpose.md / schema.md / taxonomy.md / taxonomy_tags.md / template.json`；`.wiki-templates/` 四份文件要到 **Task 2** 才建。
- **方案原文 Task 1 Step 3** 的 Expected 却列出：
  `['purpose.md','schema.md','taxonomy.md','taxonomy_tags.md','.wiki-templates/source.md','.wiki-templates/entity.md','.wiki-templates/concept.md','.wiki-templates/synthesis.md']`
- **后果**：若在 Task 1 后立即跑该验证命令，会因缺少 `.wiki-templates/*` **失败**，误导执行者以为搬运出错。
- **修法**：把该验证命令拆到 Task 2 末尾；或 Task 1 的 Expected 仅列根级 4 文件。

### Bug B — Task 4 Step 2 冒烟命令在 `/tmp` 下找不到 `src` 模块 ⛔
- **方案原文**：`cd /tmp && rm -rf novel_demo && python -m src.cli project init novel_demo --template novel && ls -R novel_demo`
- **后果**：`cd /tmp` 后 `python -m src.cli` 因 CWD 不在仓库根、`src` 包不可导入而**直接报错**。
- **修法**：从仓库根运行并传绝对路径：`python -m src.cli project init /tmp/novel_demo --template novel`（或 `cd` 回仓库根）。

---

## 三、与锁定设计 H3 / 版本门的**重大时序冲突**（最关键，需用户决策）

### 3.1 H3 的真实范围（字面成立，但 spirit 冲突）
锁定设计 `specs/.../design.md` §8 / H3（已编辑锁定）：
> "v3.0.0 只落 novel-wiki **项目级**，bundled 保持 2.0.0 不动（bundled 是平台默认模板，改写会污染全平台）。"

方案把 novel-wiki 的 v3.0.0 页面模板做成**一个新的 bundled 模板 `novel`**：
- 字面：没改 `general`，默认模板仍是 2.0.0 → 满足"bundled 保持 2.0.0 不动"。
- 精神：把 novel-wiki 的 v3.0.0 作为"平台可默认选择的 bundled 资产"发布，正是 H3 反对的"把 novel-wiki 的 v3.0.0 当平台模板"——H3 的判词把 v3.0.0 定位为**与 novel-wiki 项目重摄入耦合的项目级产物**，本不打算成为平台模板。
- **判定**：灰区 / 需用户拍板。方案 §0 的"本方案不违反 H3"只论证了字面，未触及精神。

### 3.2 更硬的致命时序：版本门耦合（在 Phase 1.2 前发布 = 埋雷）
设计 `specs §5.4` 的 lint **版本门**（Phase 1.2，当前**未实现**）判定规则：
> "页声明版本 ≥ 项目解析出的模板版本，才检查该模板的必填槽"。

- 一旦 Phase 1.2 落地，novel 项目（页面模板头 `<!-- wiki-template-version: 3.0.0 -->`）的页面会被按 **v3.0.0 必填槽**检查；
- 而 v3.0.0 的必填槽（concept 的 适用场景/反模式/证据强度、source 的 转录质量/可信度、entity 的 写作价值、synthesis 的 各方观点≥2 等）由 **generator 静态槽表 Phase 1.1（未落地）** 填充；
- 当前 generator 不填这些槽 → **novel 项目的所有页面届时都会 lint ERROR**，且 synthesis 因"各方观点 wikilink <2"整体失败。
- 即：在 Phase 1.1 / 1.2 之前把 bundled `novel@3.0.0` 发布出去，**现在能建、现在能摄入（空槽），但 Phase 1.2 一落地整库变红**。这是真实的时序炸弹。

### 3.3 三种处理建议（请用户决策）

| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **C（推荐）** | bundled `novel` 仍做，但把 4 份页面模板头的 `<!-- wiki-template-version: 3.0.0 -->` **降级为 2.0.0** 再入库；写作域 section（适用场景/反模式…）保留为模板里的"额外结构" | 2.0.0 必填槽 generator 能填、未来 lint 只查 2.0.0 槽 → **不会触发版本门炸库**；写作域结构仍可见；完全规避 H3 spirit 冲突 | novel 项目级 v3.0.0 与 bundled 副本出现版本差（文档注明即可） |
| **B** | 把 `novel` 做成**用户级模板**：`templates create novel --source general` + 改内容（落到 `~/.config/ruflo-kb/templates/novel/`） | 完全不进 bundled，H3 字面+精神都满足 | 不可版本控制/不可跨机共享（用户本意要共享，故次选） |
| **A** | 保持 v3.0.0 头，但方案明确标"bundled novel 在 Phase 1.2 前仅脚手架、不保证写作域槽填充/强制"，并等 Phase 1.2 后再正式启用 | 不改版本号，忠实于 novel-wiki 源 | 未来 Phase 1.2 落地时 novel 项目会爆 lint，需届时同步修 |

> 推荐 **C**：它让 bundled `novel` 成为"立刻可用、且未来不被版本门误伤"的干净脚手架，同时把真正的 v3.0.0（含 generator 槽同步 + lint 版本门）留给锁定设计自己的 Phase 1→2 落地。

---

## 四、预期差 / 惰性文件（需方案文档澄清）

1. **写作域槽当前是空的**：v3.0.0 页面模板的 适用场景/反模式/证据强度/转录质量/可信度/写作价值/各方观点 等槽，当前 generator 不填、lint 不查 → 新 novel 项目摄入后这些 section 为**空**，模板"看起来在工作、其实没驱动写作域抽取"。必须在方案"验收/限制"加醒目说明，避免用户误判端到端生效。
2. **`taxonomy_tags.md` 当前惰性**：设计 1.4（Phase 1）才实现独立枚举解析；当前平台**无任何代码读项目根 `taxonomy_tags.md`** → 随 `apply_template` 落地但完全不生效，要等 Phase 1.4。同理 `taxonomy.md` 虽能被 `TaxonomyRegistry` 解析，但门禁未强制枚举（也属 Phase 1.4）。
3. **`claim/decision` 目录残留**：scaffold 默认 schema 含 claim/decision 且 `ensure_knowledge_base` 建了 `wiki/claims`、`wiki/decisions`；novel schema 只有 4 类 → 这两目录存在但 novel 不使用（无害，记一笔即可）。

---

## 五、次要 / 已澄清无碍
- `general` 含 `.wiki-templates/operation.md`，novel 不含 → operation 类型回退 bundled 2.0.0，与 novel（4 类）无关，无碍。
- `template.json` 的 `name` 字段为 cosmetic（loader 用目录 id），方案写 `name:"novel"` 无误。
- HTTP route `_payload`（`scenario_templates.py:9-14`）直接返回 `t.files`（含 `taxonomy_tags.md`、`.wiki-templates/*`），WebUI 也能看到，无需改 route。

---

## 六、建议的修正动作（待用户确认方向）
1. 修 **Bug A**：Task 1 验证命令移到 Task 2 后 / 收窄 Expected。
2. 修 **Bug B**：Task 4 冒烟命令用仓库根 + 绝对路径。
3. 处理 H3/版本门：默认采用 **方案 C**（页面模板头降 2.0.0 入库），并在方案 §0 补"本 bundled novel 与锁定设计 H3 的关系 + 为何降版本"。
4. 方案"限制"增一条醒目说明：写作域槽当前空 + `taxonomy_tags.md` 惰性，待 Phase 1.1 / 1.2 / 1.4。
5. 回滚/副作用段补一句 `claim/decision` 目录残留无害。

> 未决项（需用户拍板）：H3/版本门走 **C / B / A** 哪条？确认后我再据此修订方案文件并进入实施。
