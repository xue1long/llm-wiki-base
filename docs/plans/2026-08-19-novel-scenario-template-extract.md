# 抽取 novel-wiki 为可复用「小说写作场景模板」 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `knowledge/novel-wiki/` 自带的 v3.0.0 模板素材（purpose/schema/taxonomy/.wiki-templates）抽取成一个**独立、opt-in 的 bundled 场景模板 `novel`**，使他人可用 `project init --template novel` 一键生成「网文写作知识库」脚手架。

**Architecture:** 纯模板资产搬运 + 注册，不动 `src/templates/bundled/general` 等既有默认模板。新增一个目录 `src/templates/bundled/novel/`，内含 `template.json + purpose.md + schema.md + taxonomy.md + taxonomy_tags.md + .wiki-templates/{source,entity,concept,synthesis}.md`，复用现有 `loader.list_templates/load/apply_template` facade 与 CLI `templates list` / `project init --template`。**不**触发 Phase 1 的 lint 质量门改造（见 §依赖与限制）。

**Tech Stack:** Python（现有 `src/templates/loader.py` facade）、FastAPI 路由（`src/server/routes/scenario_templates.py`，已存在、无需改）、CLI（`src/cli.py` 的 `templates` / `project init --template`，已存在、无需改）、pytest。

---

## 0. 决策与冲突澄清（务必先读）

- **冲突来源**：`docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md` §8 / H3 已"编辑锁定"，要求 v3.0.0 **只落 novel-wiki 项目级**、`bundled` 保持 2.0.0 不动，理由为"bundled 是平台默认模板，改写会污染全平台"。
- **本方案不违反 H3**：H3 防的是**改写共享默认模板**（general 等）。本方案是**新增一个独立 id `novel` 的 bundled 模板**，默认模板（general 2.0.0）完全不动；只有通过 `--template novel` 显式选择才生效，其他项目无影响。
- **与既有 novel-wiki 项目的关系**：现有 `knowledge/novel-wiki/` 根目录已有一份项目级副本（它本就是 v3.0.0 的落地对象）。本方案产出的 bundled `novel` 是给**未来新建**的同类知识库用的"模板源"，二者内容同源、互不干扰；不回写 novel-wiki 项目。
- **taxonomy_tags.md 处理**：novel-wiki 把 tags 受控枚举独立成 `taxonomy_tags.md`（设计文档 O5，避免污染分类命名空间）。本方案**原样保留该独立文件**随模板一起复制（loader 的 `apply_template` 会递归复制除 `template.json` 外的所有文件到项目根），不做合并。
- **✅ C 决策（已确认）：页面模板版本头降为 2.0.0 入库**。源 `knowledge/novel-wiki/.wiki-templates/*.md` 首行均为 `<!-- wiki-template-version: 3.0.0 -->`。按设计文档版本门规则（design §499 N1 / plan 1.2-2：`页声明版本 ≥ 项目解析模板版本` 才按该版本查必填槽；synthesis 质量门 design §349 仅对 `≥3.0.0` 生效），**入库时把四份页面模板首行降为 `2.0.0`**，写作域 section（适用场景/反模式/证据强度…）原样保留为"建议性结构"。理由：① 落在平台原生 2.0.0 线，与 general/research/business 同代，字面 + 精神都满足 H3（"bundled 保持 2.0.0"）；② 规避版本门炸弹——novel 页(2.0.0) ≥ 模板(2.0.0) 只查 2.0.0 必填槽（generator 能填），Phase 1.2 lint 落地后 novel 项目不会整库 MISSING-SECTION 全红。代价：写作域强约束暂降级为建议性，待 design Phase 1.2(版本门)+1.4(taxonomy_tags 解析)+1.6(generator 填写作域槽) 落地后，把首行改回 3.0.0 即一键升级（见 §升级路径）。

## 1. 源素材清单（已读取确认）

| 源文件 | 用途 |
|---|---|
| `knowledge/novel-wiki/purpose.md` | 摄取时注入 LLM 的目标/上下文 |
| `knowledge/novel-wiki/schema.md` | 4 类 PageType + 写作域 Conventions |
| `knowledge/novel-wiki/taxonomy.md` | 受控分类轴（6 组：写作技法/题材体系/平台规则/读者与市场/案例与素材/心态与职业） |
| `knowledge/novel-wiki/taxonomy_tags.md` | tags 受控枚举节（情绪/场景阶段/读者群/平台 + 保留前缀） |
| `knowledge/novel-wiki/.wiki-templates/source.md` | v3.0.0 来源页模板（含转录质量/可信度槽） |
| `knowledge/novel-wiki/.wiki-templates/entity.md` | v3.0.0 实体页模板（含写作价值槽） |
| `knowledge/novel-wiki/.wiki-templates/concept.md` | v3.0.0 概念页模板（含适用场景/反模式/证据强度槽） |
| `knowledge/novel-wiki/.wiki-templates/synthesis.md` | v3.0.0 综述页模板（分歧汇聚五槽） |

> **注（C 决策落地）**：四份页面模板源文件首行均为 `<!-- wiki-template-version: 3.0.0 -->`；**入库时（Task 2）将其降为 `2.0.0`**，body 写作域 section 不变。根级四份 .md 不改写版本（无版本头概念）。

## 2. 目标产物（新增 bundled 模板 `novel`）

```
src/templates/bundled/novel/
├── template.json          # 新建：name=novel, description, icon, extra_dirs（参考设计文档，本项目 4 类已有目录，extra_dirs=[]）
├── purpose.md             # 复制自 knowledge/novel-wiki/purpose.md
├── schema.md              # 复制自 knowledge/novel-wiki/schema.md
├── taxonomy.md            # 复制自 knowledge/novel-wiki/taxonomy.md
├── taxonomy_tags.md       # 复制自 knowledge/novel-wiki/taxonomy_tags.md
└── .wiki-templates/
    ├── source.md          # 复制自 novel-wiki/.wiki-templates/source.md
    ├── entity.md          # 复制
    ├── concept.md         # 复制
    └── synthesis.md       # 复制
```

> `template.json` 的 `extra_dirs` 取 `[]`：4 类页面目录（wiki/sources|entities|concepts|synthesis）由 general 的 `.wiki-templates`/schema 约定已存在，`apply_template` 仅写入模板内声明的文件；novel 模板不引入自定义 PageType 目录（遵守设计文档 D3=b 保持 4 类）。

---

## Task 1: 搬运 purpose.md / schema.md / taxonomy.md / taxonomy_tags.md

**Files:**
- Create: `src/templates/bundled/novel/purpose.md`
- Create: `src/templates/bundled/novel/schema.md`
- Create: `src/templates/bundled/novel/taxonomy.md`
- Create: `src/templates/bundled/novel/taxonomy_tags.md`
- Create: `src/templates/bundled/novel/template.json`

**Step 1: 复制四个 .md 文件（内容原样，不改写）**

将 `knowledge/novel-wiki/` 下的 `purpose.md`、`schema.md`、`taxonomy.md`、`taxonomy_tags.md` 内容逐字复制进 `src/templates/bundled/novel/` 对应文件。务必保留 `taxonomy_tags.md` 首行的"与 taxonomy.md 独立解析"说明与枚举表。

**Step 2: 新建 `template.json`**

```json
{
  "name": "novel",
  "description": "网文写作知识库：技法/题材/平台规则/读者市场，可检索可执行的写作域模板",
  "icon": "📝",
  "extra_dirs": []
}
```

**Step 3: 验证 loader 能识别（仅 Task 1 落地的根级文件）**

Run: `python -c "from src.templates.loader import load; t=load('novel'); print(t.name, t.builtin, sorted(t.files))"`
Expected: `novel True ['purpose.md','schema.md','taxonomy.md','taxonomy_tags.md']`（顺序不限；`.wiki-templates/*` 在 Task 2 才落地，此处不应出现；`template.json` 被 loader 排除在 `files` 外不列出）

**Step 4: Commit**

```bash
git add src/templates/bundled/novel/
git commit -m "feat(templates): 新增 bundled 小说写作场景模板 novel（purpose/schema/taxonomy）"
```

## Task 2: 搬运 .wiki-templates 四份 v3.0.0 页面模板

**Files:**
- Create: `src/templates/bundled/novel/.wiki-templates/source.md`
- Create: `src/templates/bundled/novel/.wiki-templates/entity.md`
- Create: `src/templates/bundled/novel/.wiki-templates/concept.md`
- Create: `src/templates/bundled/novel/.wiki-templates/synthesis.md`

**Step 1: 复制四份页面模板并降版本头（C 决策）**

将 `knowledge/novel-wiki/.wiki-templates/{source,entity,concept,synthesis}.md` 复制进 `src/templates/bundled/novel/.wiki-templates/`，**body 内容逐字保留，仅把每份首行的 `<!-- wiki-template-version: 3.0.0 -->` 改为 `<!-- wiki-template-version: 2.0.0 -->`**（写作域 section 不动）。确认：`## 标题` 独占行、slot 注释在 body（符合设计文档 §4.5 格式契约）。

> 用 `sed -i '1s/3.0.0/2.0.0/' file` 或 Read+Edit 单文件首行最稳妥；禁止改动除首行版本号外的任何内容。

**Step 2: 验证文件计数**

Run: `python -c "from src.templates.loader import load; t=load('novel'); print([f for f in t.files if f.startswith('.wiki-templates/')])"`
Expected: 列出 4 个 `.wiki-templates/*.md`

**Step 3: Commit**

```bash
git add src/templates/bundled/novel/.wiki-templates/
git commit -m "feat(templates): novel 模板附 v2.0.0 页面模板（source/entity/concept/synthesis，写作域结构保留）"
```

## Task 3: 测试——list/load/apply 全链路

**Files:**
- Modify: `tests/test_cli_ext/test_scenario_templates.py`

**Step 1: 写失败测试**

在 `test_scenario_templates.py` 末尾追加（保持已有测试不变）：

```python
def test_novel_bundled_template_registered():
    from src.templates.loader import list_templates, load
    ids = [t.name for t in list_templates()]
    assert "novel" in ids
    t = load("novel")
    assert t.builtin is True
    # 必需文件齐备
    for must in ("purpose.md", "schema.md", "taxonomy.md", "taxonomy_tags.md"):
        assert must in t.files, f"missing {must}"
    # 四个页面模板齐备
    wt = [f for f in t.files if f.startswith(".wiki-templates/")]
    assert set(wt) == {
        ".wiki-templates/source.md",
        ".wiki-templates/entity.md",
        ".wiki-templates/concept.md",
        ".wiki-templates/synthesis.md",
    }


def test_novel_apply_template_scaffold(tmp_path):
    from src.templates.loader import apply_template
    written = apply_template("novel", tmp_path)
    names = {p.name for p in written}
    assert "purpose.md" in names and "schema.md" in names and "taxonomy_tags.md" in names
    # 页面模板落到 .wiki-templates/
    assert (tmp_path / ".wiki-templates" / "concept.md").exists()
```

**Step 2: 运行测试确认通过**

Run: `pytest tests/test_cli_ext/test_scenario_templates.py -v -k novel`
Expected: PASS（Task 1/2 已落地文件，loader 直接加载）

**Step 3: Commit**

```bash
git add tests/test_cli_ext/test_scenario_templates.py
git commit -m "test(templates): novel 场景模板 list/load/apply 全链路断言"
```

## Task 4: CLI 验证（端到端冒烟）

**Step 1: `templates list` 能看到 novel**

Run: `python -m src.cli templates list`
Expected: 输出含 `- novel (bundled) 网文写作知识库：...`

**Step 2: `project init --template novel` 在临时目录生成脚手架**

Run（**从仓库根运行**，输出到绝对临时路径，避免 `/tmp` 下找不到 `src` 模块）:
```bash
rm -rf /tmp/novel_demo && python -m src.cli project init /tmp/novel_demo --template novel && ls -R /tmp/novel_demo
```
Expected: `/tmp/novel_demo/` 下出现 `purpose.md`、`schema.md`、`taxonomy.md`、`taxonomy_tags.md`、`.wiki-templates/{source,entity,concept,synthesis}.md`（页面模板首行版本头为 `2.0.0`）。

**Step 3: 确认未改动默认模板**

Run: `python -c "from src.templates.loader import load; print(load('general').files)"`
Expected: general 仍只有 4 类基础文件 + 其自身 `.wiki-templates`（**不含 taxonomy_tags.md**，证明未污染默认模板）。

**Step 4: Commit（若有脚手架脚本/快照产出，否则本步仅记录，无文件提交）**

---

## § 依赖与限制（实现前须知，非本次范围）

1. **lint 质量门与版本门：novel@2.0.0 已规避 v3.0.0 强约束**。C 决策下四份页面模板首行为 `2.0.0`，故：版本门（design §499：页版本≥模板版本才查必填槽）只按 2.0.0 必填槽集检查（generator 能填，绿）；synthesis 质量门（design §349，仅 `≥3.0.0` 生效）对 novel 不触发。写作域 section（适用场景/反模式/证据强度…）保留为**建议性结构**，空着不报 ERROR，但也**不被强制填写**。Phase 1.2 的其余平台级 lint 改造（RAW-PASTE 强化、tags 枚举校验、relation 类型校验）属全局行为，与 novel 模板无关；本次不实现这些门禁，只搬运资产。
2. **taxonomy_tags.md 解析依赖 Phase 1.4**：该独立枚举文件的解析/注入是平台改造项；本次只保证文件随 `apply_template` 落到项目根，平台是否读取由 Phase 1.4 决定。
3. **source 页确定性槽（转录质量/可信度）依赖 Phase 1.6**：若 generator 未同步，这些槽由 LLM 填充，可能出现占位符（被 lint 抓到与否取决于限制 1）。
4. **不回写 novel-wiki 项目**：现有 `knowledge/novel-wiki/` 已有项目级副本，本方案不修改它。
5. **注册即生效**：bundled 模板由 `list_bundled()` 自动发现，无需改 `src/cli.py` / `scenario_templates.py`。

## § 升级路径（C 决策的后续，非本次范围）

当设计文档 Phase 1.2（版本门 lint）+ 1.4（taxonomy_tags 解析器）+ 1.6（generator 填写作域槽）落地后，把 novel 的强 schema 约束一键升级回 3.0.0：

1. 将 `src/templates/bundled/novel/.wiki-templates/{source,entity,concept,synthesis}.md` 首行由 `2.0.0` 改回 `3.0.0`；
2. 确认 generator（Phase 1.6）已能为写作域槽（转录质量/可信度/适用场景/反模式/证据强度…）填值；
3. 重新 `project init --template novel`（或 `templates apply novel --force`）使存量项目 `.wiki-templates/` 同步；
4. 此时版本门按 3.0.0 查必填槽，写作域约束正式生效。

> 升级是"只改版本号 + 确认 generator 支撑"的增量操作，无需重写结构；本次发布的 2.0.0 是安全占位，不阻塞任何未来改造。

## § 回滚

- 删除 `src/templates/bundled/novel/` 整个目录即可注销模板；
- 撤销 Task 1–3 三个 commit（`git revert`）。
- 不触及 general 或其他 bundled 模板，无平台级副作用。

## § 验收标准

1. `templates list` 显示 `novel (bundled)`；
2. `load('novel')` 含 purpose/schema/taxonomy/taxonomy_tags + 4 份 .wiki-templates，且 `builtin=True`；
3. `project init <x> --template novel` 生成的项目含上述全部文件；
4. `load('general')` 不受任何影响（无 taxonomy_tags.md、无 novel 页面模板）；
5. `test_novel_*` 两个测试通过；
6. 不修改 `src/cli.py`、`scenario_templates.py`、`loader.py`、general 模板。
