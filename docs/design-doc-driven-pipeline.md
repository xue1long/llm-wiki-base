# 设计文档：以字段契约文档驱动 LLM 摄取流水线

> **状态**：设计稿，尚未落地
> **日期**：2026-07-27
> **目标读者**：未来要实施本方案的人（可能就是你自己）
> **关联文档**：`docs/wiki-template-field-guide.md`（字段契约快照）

## 1. 背景与目标

当前 `docs/wiki-template-field-guide.md` 是一份**单向快照**——它描述了流水线的字段契约，但流水线不读它。改文档对 ingest 行为零影响；反过来，改模板或 prompt 也不会自动更新文档，导致漂移（2026-07-27 实检已发现 3 处不一致）。

**目标**：让这份文档成为

1. **编辑入口**：改文档 → 下次 ingest 行为跟着变（针对规则类内容）。
2. **查看入口**：看这一份文档就能掌握整个流水线的字段契约，无需翻代码。

## 2. 核心判断：事实源分两类，不能全塞文档

流水线的"事实源"不是一坨，是两类，处理方式不同：

| 类别 | 内容举例 | 性质 | 归属 |
|---|---|---|---|
| **规则类** | 禁用词、句数、wikilink 要求、id/relation/tag 契约、slot 填写说明 | 自然语言 prompt 文案 | **文档驱动**，注入 prompt |
| **结构类** | slot 名、必填性、章节顺序、JSON schema | 机器结构 | **模板/代码驱动**，文档展示 + 校验防漂移 |

**为什么结构类不能文档化**：slot 名/必填性是 `parser.py` 要解析的结构，JSON schema 是 provider 层硬校验，写成自然语言让 LLM 解析既臃肿又脆弱。结构该用结构化文件（`.wiki-templates/*.md`）管理，文档只负责展示和说明。

**为什么规则类适合文档化**：这些内容本来就是 prompt 里的自然语言段落，文档版本和 prompt 版本本质是同一份文案的两个读者（人 vs LLM）。让文档成为唯一编辑源，prompt 运行时注入，天然不漂移。

## 3. 方案设计：文档分段注入 + 模板驱动 + 漂移校验

### 3.1 文档加注入标记

在 `wiki-template-field-guide.md` 里用 HTML 注释圈定"可注入区段"，代码按标记提取：

```markdown
<!-- BEGIN INJECT:global_rules -->
## 通用填写规则

| 规则 | 要求 | 违反后果 |
|---|---|---|
| 非空 | 每个 slot 值 trim 后 ≥ 1 字符 | ... |
...
<!-- END INJECT:global_rules -->

<!-- BEGIN INJECT:frontmatter -->
## Frontmatter 契约
（id 规则、17 种 relation、8 个 tag 前缀）
<!-- END INJECT:frontmatter -->
```

每个 slot 的"应填什么/常见错误"也可标注入区段（按 type 分组），注入到 prompt 里对应字段的说明位。

**标记规则**：
- 标记成对出现，`BEGIN/END INJECT:<name>`。
- 区段内是标准 Markdown，既要给人看也要能给 LLM 看，**避免纯口语**，保持表格/列表结构。
- 区段外的内容（如 §10 人工编辑注意）不注入，只给人看。

### 3.2 新增 `src/pipeline/doc_source.py`（约 30 行）

```python
"""从字段契约文档提取注入区段，作为 prompt 的事实源。"""
from functools import lru_cache
from pathlib import Path
import re

_DOC_PATH = Path("docs/wiki-template-field-guide.md")
_INJECT_RE = re.compile(
    r"<!--\s*BEGIN INJECT:(\w+)\s*-->(.*?)<!--\s*END INJECT:\1\s*-->",
    re.DOTALL,
)

@lru_cache(maxsize=8)
def load_inject_section(name: str) -> str:
    """返回指定注入区段的原文（含 Markdown）。找不到抛 KeyError。"""
    text = _DOC_PATH.read_text(encoding="utf-8")
    m = _INJECT_RE.search(text)
    sections = {n: s.strip() for n, s in _INJECT_RE.findall(text)}
    if name not in sections:
        raise KeyError(f"inject section '{name}' not found in {_DOC_PATH}")
    return sections[name]

def list_inject_sections() -> list[str]:
    text = _DOC_PATH.read_text(encoding="utf-8")
    return [n for n, _ in _INJECT_RE.findall(text)]
```

**注意**：
- `lru_cache` 使单次 ingest 内只读一次文件。
- 路径相对 cwd（serve 时是项目根），CLI 时需 `current_project_paths()` 锚定——落地时按项目现有约定取路径，不要硬编码相对路径。
- 加长度告警：注入段超过 N token 时 WARN（避免 prompt 臃肿压垮小 context 模型）。

### 3.3 改 `generator.py` 与 `wiki_rules_prompt.py` 读文档

**`generator.py`**：`GENERATOR_PROMPT` 里硬编码的规则文案段（如"Good slot content"规则、禁用词清单）替换为占位符，运行时填入：

```python
# 改前
GENERATOR_PROMPT = """...
## 填写规则
- 每个 slot 填 1-3 句话...
- 严禁用 .../TBD/（待补充）...
..."""

# 改后
GENERATOR_PROMPT = """...
{GLOBAL_RULES}
..."""

def _build_prompt(...):
    return GENERATOR_PROMPT.format(
        GLOBAL_RULES=load_inject_section("global_rules"),
        ...
    )
```

**`wiki_rules_prompt.py`**：`WIKI_RULES_SUMMARY` 里的人工文案段（id 命名规则、relation 类型表、tag 前缀表）改为从文档 `frontmatter` 区段注入。

**逐 slot 说明注入**（可选增强）：把文档 §3-6 每个 slot 的"应填什么"行，注入到 `render_for_prompt(ast)` 产出的骨架里，让 LLM 看到每个 slot 旁边有填写指引。实现：解析文档 slot 表，按 `type+slot_name` 建字典，渲染骨架时拼到对应 slot 标记后。

### 3.4 结构仍走 `.wiki-templates/*.md`，加漂移校验

模板的 slot 名/必填性/章节顺序继续用 `wiki-templates edit` 管理（这是结构化文件，该走结构化工具）。新增校验脚本 `scripts/check_doc_sync.py`（约 60 行）：

```python
"""校验字段契约文档与模板结构是否漂移。不一致 exit 1。"""
from pathlib import Path
from src.wiki.templates.parser import parse, required_slot_names
# 解析文档 §7 全景表（约定表格格式：<type> | <slot> | <必填>）

def parse_doc_table(doc_text): ...
def parse_template_slots(root):
    out = {}
    for t in ["source","entity","concept","synthesis"]:
        ast = parse(Path(f"src/wiki/templates/bundled/{t}.md").read_text())
        out[t] = set(required_slot_names(ast))  # 必填
        out[t+"_optional"] = ...                 # 可选
    return out

# 比对，不一致打印 diff，exit 1
```

**挂载点**：① `cli health` 增加一项 H5「文档模板同步」检查；② 可选写进 CI/pre-commit。

### 3.5 文档顶部加事实源声明

```markdown
> **事实源声明**
> - §2 通用规则 / §8 Frontmatter 契约 / 各 slot 说明：**本文档为唯一编辑源**，
>   改完下次 ingest 自动注入 prompt 生效。
> - §3-6 章节结构 / §7 全景表：来自 `.wiki-templates/*.md`，用 `wiki-templates edit` 改，
>   改完跑 `python scripts/check_doc_sync.py` 同步本文档。
> - JSON schema 硬约束：仍需改 `generator.py` 代码（少数情况）。
> - 最后核对：YYYY-MM-DD（校验脚本通过后手动更新）
```

## 4. 改完后的日常工作流

| 你想改什么 | 改哪里 | 怎么生效 | 谁验证 |
|---|---|---|---|
| 填写规则（禁用词、句数） | 文档 §2（`global_rules` 区段） | 下次 ingest 自动注入 | 跑一次 ingest 看 LLM 输出 |
| frontmatter 契约（relation/tag） | 文档 §8（`frontmatter` 区段） | 下次 ingest 自动注入 | 同上 |
| 某 slot 的"应填什么" | 文档 §3-6 对应行 | 注入 prompt | 同上 |
| 增删 slot / 改必填性 | `wiki-templates edit` | 改完跑 `check_doc_sync.py` 提醒同步 §7 | 校验脚本 |
| 硬 schema 约束（如真拒绝额外 key） | `generator.py` 代码 | 改代码 | 跑 ingest + 测试 |
| 查看整个流水线契约 | 只看这一份文档 | — | — |

## 5. 落地步骤清单（执行时照做）

1. **加注入标记**：在 `wiki-template-field-guide.md` 的 §2、§8、§3-6 slot 表外加 `BEGIN/END INJECT` 标记。
2. **写 `src/pipeline/doc_source.py`**：`load_inject_section` + `list_inject_sections`，路径走 `current_project_paths()`。
3. **改 `generator.py`**：`GENERATOR_PROMPT` 规则段替换为 `{GLOBAL_RULES}` 占位，`_build_prompt` 调 `load_inject_section`。跑一次 ingest 验证 prompt 注入正确。
4. **改 `wiki_rules_prompt.py`**：`WIKI_RULES_SUMMARY` 文案段改注入。验证同上。
5. **（可选）slot 说明注入**：改 `render_for_prompt`，把文档 slot 说明拼到骨架。增强项，可后做。
6. **写 `scripts/check_doc_sync.py`**：解析文档 §7 表 + 模板 slot，比对。本地跑通。
7. **挂进 `cli health`**：加 H5 检查项调 `check_doc_sync`。
8. **文档顶部加事实源声明 + 核对日期**。
9. **跑一次完整 ingest** 冒烟，确认 LLM 输出符合新注入的规则。
10. **更新 `CLAUDE.md` / 项目记忆**：记录"文档为规则类事实源"这一约定，防止后人误改回硬编码。

## 6. 风险与边界

- **prompt 长度膨胀**：注入会让 prompt 多几百 token。`doc_source.py` 加长度告警（>2000 字符 WARN），对 MiniMax/DeepSeek 等 16k+ context 模型影响小，但若换小 context 模型需注意。
- **文档双读者冲突**：注入区段既要人读又要 LLM 读。原则：保持表格/列表结构化，避免纯口语；"常见错误"列对 LLM 尤其有效（反例比正例更管束）。
- **注入失败兜底**：`load_inject_section` 找不到区段时，应 fallback 到代码内联的默认规则（不抛异常中断 ingest），并 WARN。建议保留一份精简默认值在代码里。
- **schema 仍是代码**：硬结构校验（如真 `additionalProperties: false`）不适合文档化，继续在 `generator.py` 改。文档 §9 已说明校验链，改 schema 时同步更新文档 §9 文案即可（这部分不注入，纯展示）。
- **并发读**：`lru_cache` 是进程内缓存，多 worker serve 下各进程独立读文件，无一致性问题（文档改完下次进程启动才生效——可接受，文档改动低频）。

## 7. 不做的事（明确排除）

- ❌ 不把 JSON schema 写进文档让 LLM 解析——schema 是 provider 层硬约束，该在代码里。
- ❌ 不把模板 slot 结构写进文档当事实源——结构该用 `.wiki-templates/*.md`，文档只展示。
- ❌ 不做双向自动同步（文档↔模板互写）——双向同步复杂且易循环，单向（文档驱动规则 / 模板驱动结构 + 校验防漂移）已够。
- ❌ 不把整份文档全量塞 prompt——只注入标记区段，控制 token。

## 8. 验证标准（落地后如何确认成功）

- [ ] 改文档 §2 一条规则（如把"1-3 句"改成"2-4 句"），跑 ingest，抓 prompt log 确认新规则已注入。
- [ ] 改模板加一个 slot，不更新文档 §7，跑 `check_doc_sync.py`，确认报错指出差异。
- [ ] 改模板加 slot 后更新文档 §7，跑校验脚本，确认通过。
- [ ] `cli health` 输出含 H5 且通过。
- [ ] 文档顶部事实源声明存在且日期正确。
