# Wiki Page Templates — 设计方案

**Goal:** 为每种 `PageType` (source/entity/concept/synthesis) 提供**结构化的章节模板**,
让 LLM 生成的 wiki 页面 body 一致、完整、可预测;同时支持用户自定义。

**Why now:** 当前 `GENERATOR_PROMPT` 只说"render Markdown content",LLM 自由发挥,所以同类
页面的章节结构差异很大(同一 concept 页有的有"定义",有的只有"概述"),知识图谱消费
方(搜索、聚合、UI 渲染)难以依赖稳定结构。

---

## 范围 — 三期一次性完成

| Phase | 内容 | 工作量 |
|---|---|---|
| **v1** 基本模板 | bundled 模板 + resolver + generator 注入 + CLI | 半天 |
| **v2** 条件 slots + 继承 | `<!-- if: -->` `<!-- slot:? -->` `<!-- include: -->` | 半天 |
| **v3** 版本/迁移 | 版本头解析 + status/upgrade/diff CLI + 自动迁移 | 半天 |

---

## 模板格式

模板是 Markdown 文件,用 HTML 注释做**机器可读标记**:

```markdown
<!-- wiki-template-version: 1.0.0 -->
<!-- wiki-template-type: concept -->

<!-- include:_base.md -->

## 定义

<!-- slot:definition -->

## 例子

<!-- slot:examples -->

## 别名

<!-- if:has_aliases -->

<!-- slot:aliases -->

<!-- /if:has_aliases -->

## 相关概念

<!-- slot:related -->
```

### 三种标记

| 标记 | 含义 | 示例 |
|---|---|---|
| `<!-- wiki-template-version: X.Y.Z -->` | 模板版本头(v3 解析) | `1.0.0` |
| `<!-- wiki-template-type: TYPE -->` | 类型(v1 必填,resolver 验证) | `concept` |
| `<!-- include:PATH -->` | 引用另一个模板(v2) | `<!-- include:_base.md -->` |
| `<!-- if:COND -->` ... `<!-- /if:COND -->` | 条件块(v2) | `<!-- if:has_aliases -->` |
| `<!-- slot:NAME -->` | LLM 应填充的位置 | `<!-- slot:definition -->` |
| `<!-- slot:NAME? -->` | 可选 slot(v2,语义同 if) | `<!-- slot:aliases? -->` |
| `<!-- for:REL -->` ... `<!-- /for:REL -->` | 按 relation 类型循环(v2 预留) | `<!-- for:references -->` |

`_base.md` 是**公共片段**,下划线开头,**不出现在模板列表里**。

---

## 解析器 (`src/wiki/templates/parser.py`)

```python
@dataclass
class Slot:
    name: str
    is_optional: bool = False          # `<!-- slot:NAME? -->`
    condition: str | None = None        # `<!-- if:COND -->` 包裹
    raw_marker: str                     # 原始标记,用于 round-trip

@dataclass
class Include:
    path: str
    raw_marker: str

@dataclass
class TemplateAST:
    type: PageType
    version: str | None
    sections: list[Section]              # heading + slots 的有序列表
    includes: list[Include]              # 顶层 include
    raw: str                            # 原始 markdown,用于 round-trip

def parse(markdown: str, expected_type: PageType) -> TemplateAST:
    """解析模板为结构化 AST。

    规则:
    - `<!-- wiki-template-version: X.Y.Z -->`  → version
    - `<!-- wiki-template-type: TYPE -->`     → expected_type 验证,不匹配 raise
    - `<!-- include:PATH -->`                 → includes.append
    - `<!-- if:COND -->...<!-- /if:COND -->`  → 把包含的 slot 标记 conditional=True
    - `## HEADING`                            → section 边界
    - `<!-- slot:NAME -->` / `<!-- slot:NAME? -->` → Slot
    """
```

### round-trip 保证

`render(ast) -> str` 必须能从 `parse(text)` 来回还原(用于 status/upgrade CLI 的 diff)。

---

## Resolver (`src/wiki/templates/resolver.py`)

### 优先级

| 路径 | 来源标识 | 优先级 |
|---|---|---|
| `<project>/.wiki-templates/<type>.md` | `project` | 1 (最高) |
| `~/.config/ruflo-kb/wiki-templates/<type>.md` | `user` | 2 |
| `src/wiki/templates/bundled/<type>.md` | `bundled` | 3 (最低) |

```python
@dataclass(frozen=True)
class Template:
    type: PageType
    body_markdown: str          # 已展开 include,但保留 if/slot 标记
    version: str | None         # 从 version 头解析
    source: Literal["project", "user", "bundled"]
    path: Path                  # 实际加载的文件路径

PROJECT_TEMPLATE_DIR = ".wiki-templates"
USER_TEMPLATE_DIR = Path.home() / ".config" / "ruflo-kb" / "wiki-templates"
BUNDLED_DIR = Path(__file__).parent / "bundled"

def resolve(page_type: PageType, project_root: Path) -> Template:
    """按 project → user → bundled 优先级加载。"""
    candidates = [
        (project_root / PROJECT_TEMPLATE_DIR / f"{page_type.value}.md", "project"),
        (USER_TEMPLATE_DIR / f"{page_type.value}.md", "user"),
        (BUNDLED_DIR / f"{page_type.value}.md", "bundled"),
    ]
    for path, source in candidates:
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            ast = parse(raw, expected_type=page_type)  # 验证 type 匹配
            return Template(
                type=page_type,
                body_markdown=_expand_includes(ast, base_dir=path.parent),
                version=ast.version,
                source=source,
                path=path,
            )
    raise FileNotFoundError(f"No wiki template for PageType.{page_type.value}")
```

### include 展开

```python
def _expand_includes(ast: TemplateAST, base_dir: Path, depth: int = 0) -> str:
    """递归展开 include 指令。深度 ≤ 3 防循环。"""
    if depth > 3:
        raise RecursionError(f"include depth exceeded in {base_dir}")
    # 把 include 标记替换为对应文件的内容(也展开其 includes)
    expanded = ast.raw
    for inc in ast.includes:
        included_path = base_dir / inc.path
        if not included_path.is_file():
            # 找不到的 include:留原标记,提示用户
            continue
        included_raw = included_path.read_text(encoding="utf-8")
        included_ast = parse(included_raw, expected_type=ast.type)
        included_expanded = _expand_includes(included_ast, base_dir, depth + 1)
        expanded = expanded.replace(inc.raw_marker, included_expanded)
    return expanded
```

**安全约束**:
- **路径白名单(Bug 1 修复)**:`<!-- include:PATH -->` 的 `PATH` 必须是**纯文件名**(不含 `/`、`\`、`..`),只接受同目录下的片段
- **循环检测(Bug 15 修复)**:`visited` 集合记录已展开的 include 路径,出现过就 raise `RecursionError`
- **深度 ≤ 3**(防御性,visited 已经能挡住所有循环)
- include 解析失败留原标记 + warning,不静默

### `_base.md` 命名规则(Bug 2/3 修复)

- **片段** = 文件名以 `_` 开头(如 `_base.md`、`_helpers.md`),不出现在 `wiki-templates list` 里
- **模板** = 文件名匹配 `<type>.md`(如 `concept.md`),出现在 `list` 里
- resolver **只**接受显式 `<!-- include:_base.md -->` 引用,不靠"以下划线开头就跳过"启发式
- `_base.md` 走完整三级优先级:project > user > bundled

### `<!-- if:COND -->` 语义澄清(Bug 4/5 修复)

**原始方案问题**:COND 字符串(`has_aliases`)无法被 LLM 自动判定,且与"可选 slot"语义重叠。

**修订方案**:
- `<!-- if:X -->...<!-- /if:X -->` ≡ `<!-- slot:NAME? -->` (语法糖,X 只是标签,无动态逻辑)
- parser 把两种写法都归一化到 `Slot(is_optional=True)`
- 语义统一:**整个章节(标题+内容)都省略** if LLM 决定无内容
- generator prompt 明确说明 "If a section would be empty, OMIT the heading and slot marker entirely"

### v3 升级检测改设计(Bug 6/7 修复)

**原方案问题**:`is_user_modified` 用 sha256 对比不可靠,跨版本 state 不更新。

**修订方案**:
- `wiki-templates upgrade` **不**主动检测 modified
- 只提供 `wiki-templates diff concept` 显示当前 vs bundled
- 用户用 `--force` 强制覆盖,否则跳过
- bundled 升级时:启动时重新计算 sha256,与 state 对比;不同则**清空所有 user 的 `installed_sha256`**(基线失效,需要重新评估)

### 跨大版本迁移 移出 v3(Bug 8 修复)

- v3 只做:**同大版本内的 bundled 升级** + diff 提示 + force 覆盖
- **跨大版本迁移(v1 → v2):OUT OF SCOPE**,留到 v4

### `edit` 命令不打开编辑器(Bug 16 修复)

- `wiki-templates edit concept` 只**创建文件 + 打印路径**,用户用外部编辑器打开
- 不在 daemon server 里 spawn `$EDITOR`(会卡住 daemon)

---

## Generator 集成 (`src/pipeline/generator.py`)

```python
from ..wiki.templates.resolver import resolve as resolve_template

async def generate(paths, analysis, existing_wiki_index, provider, model="gpt-4o-mini"):
    # 1. 加载所有 PageType 的模板
    templates_by_type: dict[str, Template] = {}
    for pt in PageType:
        try:
            templates_by_type[pt.value] = resolve_template(pt, paths.root)
        except FileNotFoundError:
            pass  # bundled 应该总有;只在删文件时才 raise

    # 2. 渲染模板片段注入 prompt
    template_section = _render_template_section(templates_by_type)

    prompt = GENERATOR_PROMPT.format(
        analysis_json=analysis_json,
        existing_wiki_index=existing_wiki_index or "(empty)",
        WIKI_RULES_SUMMARY=WIKI_RULES_SUMMARY,
        PAGE_TEMPLATES=template_section,
    )
    ...
```

`_render_template_section` 输出:

```
## Page Templates (use these to structure body_markdown)
Match the section headings exactly. Fill each `<!-- slot:NAME -->` with
content. For `<!-- slot:NAME? -->` (optional), OMIT the entire heading
+ slot if the content doesn't warrant it.

### source
<!-- wiki-template-version: 1.0.0 -->
<!-- wiki-template-type: source -->

## 来源

<!-- slot:source_meta -->

## 摘要

<!-- slot:summary -->

...

### entity
...

### concept
...

### synthesis
...
```

### Prompt 升级提示

GENERATOR_PROMPT 增加:

```
- Every page body MUST follow the template for its `type`.
  - Match the `## Heading` lines verbatim.
  - Fill each `<!-- slot:NAME -->` with substantive content from the source.
  - For `<!-- slot:NAME? -->`, omit the entire section (heading + slot) if the slot is empty.
  - Do NOT add new `##` sections not in the template.
  - Do NOT omit `##` sections present in the template.
```

---

## CLI (`src/cli_ext/wiki_templates_cmd.py`)

```bash
# 列出可用模板(bundled + user,不含 _base)
python -m src.cli wiki-templates list
# 输出:
#   source     (bundled@1.0.0)
#   entity     (user@1.0.0)
#   concept    (bundled@1.0.0)
#   synthesis  (bundled@1.0.0)

# 查看某模板内容
python -m src.cli wiki-templates show concept

# 编辑用户级模板(打开 $EDITOR)
python -m src.cli wiki-templates edit concept
# 等价于: cp bundled/concept.md ~/.config/ruflo-kb/wiki-templates/concept.md && $EDITOR <path>

# 编辑项目级模板
python -m src.cli wiki-templates edit concept --project novel-wiki

# 重置(删除用户/项目级覆盖,回落到 bundled)
python -m src.cli wiki-templates reset concept
python -m src.cli wiki-templates reset concept --project novel-wiki

# 查看每页状态(v3)
python -m src.cli wiki-templates status
# 输出每种 type 的 source/version/hash/is_modified

# 升级到最新 bundled(v3)
python -m src.cli wiki-templates upgrade concept        # 强制覆盖
python -m src.cli wiki-templates upgrade concept --if-modified  # 只覆盖未改过的

# 看 diff(v3)
python -m src.cli wiki-templates diff concept
```

---

## v3 — 版本/迁移详细设计

### 数据结构

```python
# ~/.config/ruflo-kb/wiki-templates/.bundled-state.json
{
  "_schema_version": 1,
  "bundled": {
    "concept": {
      "version": "1.1.0",
      "sha256": "abc123...",
      "captured_at": "2026-07-25T12:00:00Z"
    },
    ...
  },
  "user": {
    "concept": {
      "installed_version": "1.0.0",
      "installed_sha256": "xyz789...",
      "current_sha256": "xyz789...",  # 与 installed 相同 → 未改过
      "installed_at": "2026-07-20T..."
    }
  }
}
```

### 升级检测

```python
def is_user_modified(type: PageType) -> bool:
    """用户模板相对安装时是否被改过。"""
    state = load_state()
    user_state = state["user"].get(type.value)
    if not user_state:
        return False  # 用户没有覆盖 → 用 bundled
    return user_state["current_sha256"] != user_state["installed_sha256"]
```

### `upgrade --if-modified` 行为

| 用户模板状态 | 行为 |
|---|---|
| 没改过 | 直接覆盖到最新 bundled |
| 改过 | 跳过,提示 "已自定义,跳到下一次手动 merge" |
| 不存在 | 不动(bundled 直接生效) |

### 跨大版本迁移

`<!-- wiki-template-version: 1.0.0 -->` 升级到 `2.0.0` 时,**强制要求手动迁移**:
- `wiki-templates upgrade` 拒绝自动覆盖(报 v1 → v2 重大变化)
- `wiki-templates migrate concept` 命令启动迁移向导:
  - 备份当前模板到 `<type>.bak`
  - 复制新版 bundled 到目标位置
  - 用 LLM 把用户的旧 slot 内容迁移到新 slot(如果有内容)
  - 标记 `installed_sha256` 为新版 bundled 的 hash

### 失败处理

- bundled 模板被删:resolver raise FileNotFoundError,**generator 不崩溃**,fallback 到无模板结构(向后兼容)
- 用户模板解析失败(wikitemplate-type 不匹配):raise,但 CLI 提供 `wiki-templates validate` 子命令做体检

---

## 测试策略

### 单元测试

| 测试文件 | 覆盖 |
|---|---|
| `tests/test_wiki_templates/test_parser.py` | parse + render round-trip;各标记正确识别 |
| `tests/test_wiki_templates/test_resolver.py` | 三级优先级;include 展开;循环检测;深度限制 |
| `tests/test_wiki_templates/test_bundled.py` | 4 个 bundled 模板都存在且含 version/type 头 |
| `tests/test_wiki_templates/test_versioning.py` | 升级检测;is_modified;upgrade flow |
| `tests/test_wiki_templates/test_conditional.py` | if/slot:?;嵌套;空 slot |

### 集成测试

| 测试文件 | 覆盖 |
|---|---|
| `tests/test_wiki_templates/test_generator_uses_template.py` | Generator 接收模板内容;生成页面包含模板章节 |
| `tests/test_wiki_templates/test_cli.py` | list/show/edit/reset/status/diff/upgrade CLI 命令 |

### E2E

`tests/test_e2e/test_ingest_happy_path.py` 增加:
- 断言生成的 wiki 页 body 包含 `##` 章节标题(由模板定义)
- 验证模板版本号出现在页面元数据(可选)

---

## 风险

| 风险 | 缓解 |
|---|---|
| LLM 不严格按模板填充 | prompt 显式约束 "MUST match headings, MUST fill slots, MUST NOT add/omit sections";测试断言关键章节存在 |
| 用户模板被损毁(忘记 type 头) | parser raise + CLI `wiki-templates validate` 体检命令 |
| include 循环 | 深度限制 + visited set |
| 模板改坏后旧 wiki 页找不到字段 | **不修改旧页**(body 是快照);新页用新模板 |
| bundled 删除 | resolver raise FileNotFoundError;generator fallback 到无模板(向后兼容) |
| `_base.md` 改名 | include 找不到时留原标记 + warning;不影响其他部分 |
| LLM 在 if 块外填充可选 slot | parser 标记 `is_optional`;LLM 在 prompt 里被告知"if 块外可省略" |

---

## 实施顺序

1. **v1 — 基本模板**
   - [ ] 写 `src/wiki/templates/types.py`(Template dataclass)
   - [ ] 写 `src/wiki/templates/bundled/{source,entity,concept,synthesis}.md`(4 个默认模板,带 version 头)
   - [ ] 写 `src/wiki/templates/parser.py`(版本头解析 + type 验证)
   - [ ] 写 `src/wiki/templates/resolver.py`(三级优先级)
   - [ ] 写 `src/wiki/templates/__init__.py`(对外 API)
   - [ ] 修改 `src/pipeline/generator.py`,注入模板到 prompt
   - [ ] 修改 `src/wiki/templates/wiki_rules_prompt.py`,同步 WIKI_RULES_SUMMARY
   - [ ] 写 `src/cli_ext/wiki_templates_cmd.py`(list/show/edit/reset)
   - [ ] 在 `src/cli.py` 注册子命令
   - [ ] 写测试:parser/resolver/bundled/generator_uses_template/cli
   - [ ] 跑测试套件 → 0 failed

2. **v2 — 条件 + 继承**
   - [ ] parser 支持 `<!-- if:COND -->` `<!-- slot:? -->` `<!-- include: -->` `<!-- for:REL -->`
   - [ ] resolver `_expand_includes()` 实现
   - [ ] generator prompt 模板分段:required slots + optional slots + relations
   - [ ] 写测试:conditional/parser_edge_cases
   - [ ] 跑测试套件

3. **v3 — 版本/迁移**
   - [ ] parser 提取 version 头
   - [ ] `Template.version` 字段
   - [ ] `~/.config/ruflo-kb/wiki-templates/.bundled-state.json` 读写
   - [ ] CLI: `status/diff/upgrade/migrate` 命令
   - [ ] 自动检测升级(对比 bundled hash)
   - [ ] 写测试:versioning/migration
   - [ ] 跑测试套件

4. **集成验证**
   - [ ] 重启 server,re-ingest 5 个 MD 文件
   - [ ] 验证生成页面有标准化章节
   - [ ] 跑全套测试 → 全绿

---

## 不在本期范围

- 自定义条件类型(用户可注册 `<!-- if:has_diagrams -->` 这样的自定义判断)— 等用户反馈
- GUI 模板编辑器(纯 CLI)
- 模板市场/分享(用户之间)
- Obsidian Templater 兼容
- 多语言模板(`concept_zh.md` / `concept_en.md`)— 等多语言需求出现

---

## 关键决策记录

- **格式**:`<!-- slot:NAME -->`(HTML 注释)而不是 `{{name}}`(Jinja),因为 HTML 注释不会出现在渲染输出且不与 Markdown 语法冲突
- **优先级**:project > user > bundled,提供"项目级"和"用户全局级"两层粒度
- **bundled 版本**:每个模板头带 `<!-- wiki-template-version: 1.0.0 -->`,bundled 修改即更新版本
- **向后兼容**:bundled 缺失时 generator 不崩,fallback 无模板结构;旧 wiki 页 body 不变
- **prompt 设计**:模板分段呈现,required slots 在前,optional slots 在后,让 LLM 知道哪些必填
- **per-relation 模板**:v1 不实现,LLM 默认按 `## <relation type>` 分组 + `- [[target]]: context` 格式;v2 预留 `<!-- for:REL -->` 语法

---

**Open questions for review:**
1. bundled 模板初版内容 — 我会写 4 个合理的默认章节骨架,你看看是否符合预期?
2. user template 升级 — `upgrade --if-modified` 默认行为是 "未改过才升级",需要 `--force` 才强制覆盖,可接受吗?
3. 是否需要 v1 一开始就强制 type 头(`<!-- wiki-template-type: TYPE -->`)?parser 拒绝不匹配的 type,可以避免配置错误。