# 第三方批判性审计：wiki-spec.md 同步方案（独立审计视角）

> 审计对象：`docs/superpowers/plans/2026-08-03-wiki-spec-sync.md`（v1.0）
> 审计立场：**独立第三方、抛弃原方案正向叙事、优先找缺陷**
> 审计方法：实际读源码逐项核证，非凭方案自述
> 审计日期：2026-08-03
> 结论速判：**方案方向（让规范与代码一致）合理，但执行机制设计有重大断裂，按原样执行不仅无法达成目标，还会放大既有不一致。属「需重写执行路径」级别，不是「微调」级别。**

---

## 0. 一句话总评

方案把"改 `wiki-spec.md` + 跑 `sync`"当成银弹，但**`sync` 只重写 `wiki_rules_prompt.py`，而真正决定页面 `type` 的 `analyzer.py` 根本不读 `wiki_rules_prompt.py`**；同时 `generator.py` 里还有 `_DEPTH_BY_TYPE`、5 处 `required_slots_by_type` 等**代码级类型映射**，`sync` 一个都碰不到。方案修了"提示词摘要文本"，却绕过了"类型词汇的真实来源"——这正是它声称要消除的"认知分裂"的根源。

---

## 1. 隐含假设清单（标注不确定性）

| # | 方案隐含假设 | 实测真相 | 不确定性 |
|---|------------|---------|---------|
| A1 | `wiki-spec.md` 是唯一真相源，sync 后所有提示词自动修好 | `analyzer.py` 全文件**未 import `wiki_rules_prompt`**；类型词汇来自两处硬编码清单（:61 / :112） | ❌ **已证伪** |
| A2 | 改 spec 的 PageType 章节 → `WIKI_RULES_SUMMARY` → Analyzer 引导 8 类 | Analyzer 不消费 `WIKI_RULES_SUMMARY`；`WIKI_RULES_SUMMARY` 仅注入 `generator.py`（≥7 处） | ❌ **已证伪** |
| A3 | 在 spec 补 8 类即"系统支持 8 类端到端" | 端到端支持还需：提示词清单 + `_DEPTH_BY_TYPE` + 5 处 `required_slots_by_type` + 模板 + slot schema；纯 spec 改动留代码断裂 | 🔴 **高不确定** |
| A4 | `types.py` 有注释可"提炼"4 新类语义 | `types.py:10-18` 仅裸枚举，无 docstring；`claim` 描述只在 `src/knowledge/claims/model.py:41`（知识层） | ❌ **已证伪** |
| A5 | pre-commit 钩子会在 commit 时自动跑 sync | 仓库**无 `.pre-commit-config.yaml`**，仅默认 sample hook；sync 未接线 | 🔴 **高不确定/基本未接线** |
| A6 | 枚举的 4 个新值（claim/decision/procedure/event）属于 WikiPage 规范范畴 | 它们疑似**知识层概念**：`wiki_claims/`、`wiki_decisions/` 目录 + `src/knowledge/claims/`；可能根本不是 WikiPage 类型 | 🔴 **高不确定/可能错误** |
| A7 | 策略 A 补 4 模板即可让渲染不缺骨架 | `generator.py:64` `_DEPTH_BY_TYPE` 缺 4 类 → **加载模板前就 KeyError 崩溃** | ❌ **已证伪** |
| A8 | 给 YAML `optional` 追加 5 字段是安全公开契约 | `category`/`taxonomy_sub` 是**未发布的 STS 分类字段**；`created_at/updated_at` 可能是内部元数据 | 🟡 **中不确定** |

---

## 2. 未覆盖的异常场景 / 边缘情况

1. **生成模块语法破坏**：`sync` 把 spec 正文包进 `'''...'''`（`sync_wiki_spec.py:_generate_prompt_module`）。若 spec 正文含 `'''` 或特殊反斜杠，生成的 `wiki_rules_prompt.py` 语法损坏，**运行时 import 才报错**，而脚本只打印 `Generated` 即认为成功。方案 §5 验证只查"含 8 个名称"，不 import 校验。
2. **YAML 解析失败静默跳过**：`sync` 在 `yaml.YAMLError` 时打 WARN 到 stderr 并 `exit 0`。方案 §5 的 MD5 检查能兜住，但该检查是步骤 3，开发者可能在步骤 2"commit 时自动跑"（实际没接钩子）就以为完成了。
3. **既有数据受影响**：grep 发现 `knowledge/novel-wiki/wiki/concepts/cand-274108b10c0b.md` 命中新类型字符串。方案未评估任何既有页面/测试数据会因 `optional` 字段变更或类型语义变更而失效。
4. **模板与 slot 契约不匹配**：bundled 模板按 `page_type.value` 加载（`resolver.py:56`），但渲染受 `required_slots_by_type`（代码定义）约束。方案补模板却未对齐 slot 契约，模板可能"能加载但校验失败/填错槽"。
5. **测试断言旧 4 类内容**：方案 §5 声称"pytest 全绿"，但可能存在断言 `WIKI_RULES_SUMMARY` 含 4 类或某旧行为的测试；改成 8 类会**反向**打破这类测试。方案未排查。
6. **两条 Analyzer 提示词自相矛盾**：`ANALYZER_PROMPT`（:61，4 类）与 `ANALYZER_JSON_PROMPT`（:112，6 类）并存且类型集合不同。方案只字未提"先统一这两条"，却假设"提示词"是单一干净来源。
7. **5 处 `required_slots_by_type` 都要改**：`generator.py` 在 466/803/1016/1227/1503/1639 多处定义 `required_slots_by_type`。方案只提补模板，**完全忽略这一组代码级类型映射**。
8. **`.wiki-spec-md5` 未 git 跟踪**：`git ls-files` 无结果。MD5 是单机工作区状态，方案"MD5 已更新=证明跑过"只在本机成立，无法进 PR、无法被 CI/协作者复现。

---

## 3. 逻辑断层 / 步骤缺失 / 前后矛盾 / 执行断点

- **L1（断层）**：方案因果链 `改 spec → sync → wiki_rules_prompt → 提示词修好` 在 **analyzer 处断掉**——analyzer 不读 `wiki_rules_prompt`。
- **L2（矛盾）**：方案 §3.1 写"sync 后效果：`WIKI_RULES_SUMMARY` 含 8 类 → **Analyzer 提示词引导 8 类**"。实测 Analyzer 完全不消费 `WIKI_RULES_SUMMARY`，此结论与代码直接冲突。
- **L3（断点）**：策略 A 声称"使 v2.3 渲染对 4 新类型不再缺骨架"，但 `generator.py:64` `_DEPTH_BY_TYPE` 缺 4 类，生成 claim/decision/procedure/event 页面时**在取到模板之前就 KeyError 崩溃**，模板补了也用不上。
- **L4（遗漏既有 bug）**：`ANALYZER_JSON_PROMPT:112` **已经允许** claim/decision/procedure/event（6 类），但 generator 无任何对应处理 → **这是已存在的潜伏崩溃**。方案只谈"让 spec 一致"，未触碰此根因，反而会因同步扩大 8 类引导而**提高触发概率**。
- **L5（回滚不完整）**：§6 回滚 `git checkout src/wiki/templates/bundled/`。若策略 A 的 4 个新模板是**未提交/单文件新增**，`git checkout <目录>` 只动 tracked 文件，**untracked 的新模板不会被删除**，残留且仍可被加载——回滚失败。
- **L6（单一来源幻象）**：方案把系统当成"spec→单一 prompt"；现实是 **2 条 analyzer 提示词（4/6 类）+ generator 代码映射（4 类）+ 5 处 slot dict + 模板**，共四层类型定义。方案只改其中最外层的一层。

---

## 4. 潜在 bug / 风险 / 合规 / 资源瓶颈

- **B1（bug，致命）**：`generator.py:64` `_DEPTH_BY_TYPE` 仅 4 类。一旦 LLM 产出新类型页面即 `KeyError`。方案未要求补充。
- **B2（风险）**：fail-soft 掩盖 YAML 错误；方案唯一兜底是"MD5 更新"，但 MD5 未进版本控制，跨机/CI 不可见。
- **B3（治理/合规）**：把 `category`/`taxonomy_sub` 写进"稳定"spec，等于**冻结一个未发布、未验证的 STS 分类字段**为公开契约。若 STS 后续改字段名，spec 再次失准。
- **B4（资源瓶颈）**：策略 A 不是配置改动，而是**内容创作**——需为 4 类各写一份与 `required_slots_by_type` 契约对齐的正确模板。方案把工作量低估为"纯新增 .md 骨架，低风险"，实为需设计 slot 契约的创作任务，质量风险被低估。

---

## 5. 信息盲区（缺哪些数据/条件才能落地）

1. **类型归属不明**：claim/decision/procedure/event 究竟是 WikiPage 类型，还是知识层（KOS）类型？缺架构裁决。
2. **生产路径不明**：`output_format` 默认走 markdown 还是 json？哪条 analyzer 提示词在生产生效？缺运行态确认。
3. **测试基线未知**：是否有测试断言"4 类"或旧 spec 内容？缺测试清单。
4. **既有数据范围未知**：有多少页面已写入新类型/新 optional 字段？缺全局扫描。
5. **CI 现状未知**：仓库有无 CI？能否承载"sync 纳入 CI 强制校验"（方案 §9 建议但无落地）？缺 CI 配置确认。
6. **`WIKI_RULES_SUMMARY` 是否真为类型词汇正确注入点**：实测它在 generator 出现 7 次、analyzer 0 次——方案对该文件的"作用域"理解可能错误。

---

## 6. 三类问题定级 + 漏洞定位 + 后果 + 整改

### ① 致命缺陷（方案无法按目标落地）

**F1 — 核心机制绕过了类型词汇的真实来源**
- 漏洞位置：`analyzer.py`（全文件无 `wiki_rules_prompt` 引用）；对比 `generator.py:40`（仅此处 import）。
- 风险后果：方案 §0 目标"消除规范—代码—提示词三方分裂"无法达成。sync 只更新 generator 侧摘要，analyzer 仍按 `:61`(4 类)/`:112`(6 类) 硬编码产出 `type`。执行后系统有**三套互相矛盾的类型清单**（4 / 6 / 8），分裂**加剧**。
- 整改建议：
  1. 放弃"只改 spec 即可"的假设；
  2. 将 analyzer 的类型清单改为**从 `PageType` 枚举单一来源生成**（重构 `ANALYZER_PROMPT`/`ANALYZER_JSON_PROMPT` 的类型段，删除硬编码，改为 `{"/".join(t.value for t in PageType)}`）；
  3. 或至少手动同步 :61 与 :112 两处清单到 8 类，且保证与 `WIKI_RULES_SUMMARY` 一致。

**F2 — generator 对新类型会运行时崩溃**
- 漏洞位置：`generator.py:64`（`_DEPTH_BY_TYPE` 仅 4 类）+ `generator.py:466/803/1016/1227/1503/1639`（`required_slots_by_type` 多处，均缺新类型）。
- 风险后果：只要 LLM（已被 JSON 提示词允许）产出 claim/decision/procedure/event 页面，generator 在 `_DEPTH_BY_TYPE[page.type]` 处 **KeyError**，整批摄取失败。这已是潜伏 bug，方案会放大而非修复。
- 整改建议：在启用 8 类引导**之前**，必须给 `_DEPTH_BY_TYPE` 与每一处 `required_slots_by_type` 补齐 4 新类型的映射与 slot 定义；并加单元测试断言"所有 `PageType` 成员均有深度映射与 slot 契约"。

### ② 重大隐患（容易失败）

**M1 — pre-commit 未接线，sync 不会自动跑**
- 位置：仓库无 `.pre-commit-config.yaml`；`.git/hooks/pre-commit` 为默认 sample。
- 后果：方案 §4"commit 时自动跑"不成立；开发者若依赖此假设，spec 改了但 `wiki_rules_prompt.py` 未重生，三方程序再次分裂。
- 整改：显式要求"总是手动跑 `python scripts/sync_wiki_spec.py` 并提交生成的 `.py`"；或补 `.pre-commit-config.yaml` 真正挂上该脚本。

**M2 — "从 types.py 注释提炼"不可执行**
- 位置：`types.py:10-18`（裸枚举无注释）；`src/knowledge/claims/model.py:41`（仅知识层 claim 描述）。
- 后果：方案 §3.1 给执行者的指令无法落地；若凭空补写 4 类语义，会与真实产品意图脱节。
- 整改：先由产品/架构确认 4 类的语义与例子（不依赖代码注释），再写入 spec。

**M3 — 类型归属可能搞错层**
- 位置：`types.py:26-29`（`wiki_claims`/`wiki_decisions` 目录映射）+ `src/knowledge/claims/`。
- 后果：把知识层概念当成 WikiPage 类型写入 wiki-spec，造成层级语义错误，后续 KOS 演进时更难梳理。
- 整改：先裁决"这 4 个枚举值是否应存在于 WikiPage 层"；若属知识层，应从 `types.py` 移除或仅在知识层文档化，而非塞进 wiki-spec。

**M4 — 两条 analyzer 提示词自相矛盾未统一**
- 位置：`analyzer.py:61`(4 类) vs `:112`(6 类)。
- 后果：即便修了 spec，analyzer 内部仍自相矛盾，产出类型不确定。
- 整改：统一为单一类型清单来源（见 F1 整改）。

**M5 — fail-soft 验证不足 + MD5 未跟踪**
- 位置：`sync_wiki_spec.py:105-114`（YAML 错静默 exit0）；`.wiki-spec-md5` 未 git 跟踪。
- 后果：YAML 改错时"以为同步了其实没"，且无法跨机/CI 复现。
- 整改：MD5 纳入 git 跟踪；或改为 YAML 解析失败时 **fail-hard**（非零退出）使 pre-commit/CI 阻断；CI 加一步"spec 变更必须伴随 `wiki_rules_prompt.py` 变更"。

**M6 — 策略 A 模板需 slot 契约对齐**
- 位置：`generator.py` 的 `required_slots_by_type`（多处）与 `resolver.py:56`（按 value 加载）。
- 后果：补的模板若 slot 名与代码期望不符，渲染失败或填错。
- 整改：模板与每类 `required_slots_by_type` 同步定义，并加"模板 slot 名 == slot 契约"一致性测试。

**M7 — optional 追加冻结未发布 API**
- 位置：`docs/guides/wiki-spec.md` YAML `optional` 拟追加 `category`/`taxonomy_sub`。
- 后果：把 STS 预发布字段固化为公开契约，后续改动成本上升。
- 整改：先确认字段稳定性；不稳定则标记为 `experimental` 或暂不纳入公开 optional。

### ③ 优化疏漏

- **O1（回滚不完整）**：§6 对 untracked 新模板 `git checkout` 无效 → 改用 `git clean -fd src/wiki/templates/bundled/` 或确保模板随 PR 一起提交后再 checkout。
- **O2（生成模块语法风险）**：`sync` 包 `'''` 未防御 → 整改：CI/本地加 `python -c "import wiki_rules_prompt"` 导入校验。
- **O3（既有数据）**：未扫描既有页面影响 → 整改：执行前 `grep -rn "type: (claim|decision|procedure|event)"` 全仓评估。
- **O4（测试基线）**：未排查断言旧内容的测试 → 整改：跑 `pytest` 并定位任何因 4→8 类失败的用例，按需更新。
- **O5（防漂移）**：§9 建议 CI 但无落地 → 整改：给出具体 CI 步骤（spec 与生成物 hash 比对）。

---

## 7. 审计结论与重做建议

**原方案不可按当前形态执行。** 它把"文档一致性"误当成"系统一致性"，而本系统的类型词汇真实分布在：**枚举（types.py）+ 2 条 analyzer 硬编码清单 + generator 代码映射（_DEPTH_BY_TYPE + 5 处 slot dict）+ 模板 + spec 摘要** 六处。方案只触达最后一层（spec→sync→generator 摘要），且连这一层也因 generator 代码映射缺失而失效。

**重做方向（非微调，是换执行路径）**：
1. 先做 **M3 架构裁决**：4 个新枚举值到底属于哪层。
2. 引入 **单一类型来源**：`PageType` 枚举驱动 analyzer 提示词 + generator 映射 + slot 契约 + spec 摘要，删除所有硬编码清单。
3. 补齐 generator 代码侧映射（F2）后再开 8 类引导。
4. 把 sync 接线进真实钩子/CI（M1/M5），并把 MD5 与生成物纳入版本控制。
5. 最后才是 spec 文本与模板的对齐（原方案 §3 的内容）。

> 注：本报告仅做批判性审查，未改动任何文件（含被审方案本身）。
