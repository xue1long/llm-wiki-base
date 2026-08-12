# 数据化模板传导 — 真正的自定义类型支持（路 B）

> 将 llm_wiki-main 的「schema.md 定义自定义页类型 + 路由」模式引入 LLM-Wiki。
> 与路 A（纯文本注入）不同，路 B 实现**真正的自定义类型运行时支持**：schema.md 中
> 声明的类型（如 thesis）可被 LLM 输出、被 Generator 接受、被写到独立目录。

**设计决策来源：** `.claude/skills/grilling/`（2026-08-12 grilling）+ `.claude/skills/plan-audit/`（两轮审查）

---

## 1. 动机

### 现状（plan-audit 第一轮 F1 确认）

LLM-Wiki 的架构中 **LLM 无法控制输出目录**：
- Generator 的 `response_format` 里页面只有 `id/type/title/slots/...`，没有 path 字段
- 目录由代码 `_TYPE_TO_DIR[type]` 决定（`concept → wiki_concepts`）
- `PageType(p.get("type"))` 遇到未知类型直接 `except ValueError: continue`（丢弃页面）

而 `schema.md` 在 `project init` 时写入项目根目录，摄取时从不读取——模板创建的自定义类型声明是死文本。

### 目标

让 schema.md 中声明的自定义类型（如 `| thesis | wiki/thesis |`）：
1. 被 `SchemaRegistry` 解析为运行时数据
2. 被 Analyzer 提示（`page_types` 并集）
3. 被 Generator 接受（`response_format` enum 动态化 + `PageType` 回退）
4. 被写到独立目录（`wiki/thesis/`）
5. 回退到 base type 的 slot 模板渲染

---

## 2. 设计决策总表

| # | 决策 | 结论 |
|---|------|------|
| D1 | SchemaRegistry 位置 | `src/wiki/schema_registry.py`（独立新模块） |
| D2 | 已知类型判定 | `PageType` 枚举值全部视为已知（含 claim/decision/procedure/event），schema 中不在枚举的才是自定义类型 |
| D3 | 自定义类型 base type | 默认 `extends = CONCEPT`；schema 可用第三列扩展 |
| D4 | 目录解析 | `\| type \| directory \|` 第二列取 `wiki/` 后的相对路径（如 `wiki/thesis` → `thesis`） |
| D5 | 退化行为 | 无 schema.md / 无自定义类型 → `all_custom_type_names() == []`，行为完全不变 |
| D6 | 模板回退 | 自定义类型无独立模板 → 回退 base type 模板（`resolve(base_type)`） |
| D7 | 候选管道 | `KO_TYPE_TO_PAGE_TYPE` 扩展；`generate_from_knowledge_object` 的 `PageType()` 回退同样生效 |
| D8 | 注入范围 | Analyzer 注入 schema + purpose；Generator 注入 schema（AUTHORITATIVE） |
| D9 | 目录创建 | `ensure_knowledge_base` 读取 registry 创建自定义目录 |
| D10 | schema_routing.py | 保持现状（只做验证），不支配写路径 |

---

## 3. 任务分解

### Task 1：SchemaRegistry 核心

**文件：** `src/wiki/schema_registry.py`（新增）

```python
@dataclass
class CustomTypeDef:
    name: str                # "thesis"
    directory: str           # "thesis"（wiki 下的相对目录）
    extends: PageType        # PageType.CONCEPT

class SchemaRegistry:
    @classmethod
    def from_project(cls, paths: WikiPaths) -> SchemaRegistry  # 读 root/schema.md
    @classmethod
    def from_schema_text(cls, schema_text: str) -> SchemaRegistry
    @classmethod
    def empty(cls) -> SchemaRegistry

    def get_def(self, type_name: str) -> CustomTypeDef | None
    def get_directory(self, type_name: str) -> str | None
    def get_base_type(self, type_name: str) -> PageType   # 未知 → CONCEPT
    def is_custom(self, type_name: str) -> bool
    def all_custom_type_names(self) -> list[str]
    def all_type_names(self) -> list[str]  # 基础 4 + 已知扩展 + 自定义
```

- 解析 `schema.md` 中 `## Page Types` 下的 `| type | directory |` 表格行
- 跳过 `PageType` 枚举中的已知类型
- 自定义类型默认 `extends = CONCEPT`；第三列（若有）指定 base type

### Task 2：WikiPaths + page_path_for + ensure 支持自定义目录

**`src/wiki/core/paths.py`：**
```python
def get_custom_dir(self, name: str) -> Path:
    return self.root / "wiki" / name
```

**`src/wiki/storage/page_writer.py`：**
- `page_path_for(paths, type_, slug, registry=None)`：
  - 已知类型走 `_TYPE_TO_DIR`
  - 未知类型且 registry 有 def → `paths.root / "wiki" / def.directory / f"{slug}.md"`
  - 否则 `raise ValueError`（现状保持）

**`src/wiki/storage/ensure.py`：**
- `ensure_knowledge_base(root, registry=None)`：有 registry 时创建自定义目录

### Task 3：Generator 支持自定义类型

**`src/pipeline/generator.py`：**
- 所有 `response_format` 的 `type` enum：`["source","entity","concept","synthesis"] + reg.all_custom_type_names()`
- 所有 `PageType(p.get("type"))` 调用处：`except ValueError` 时查 registry，`get_base_type(raw_type)` 回退
- 注入 `## Project Schema and Routing (AUTHORITATIVE)` 节（schema 文本）
- 4 个入口：`generate` / `unified_generate` / `generate_from_candidate` / `generate_from_knowledge_object`

**`src/pipeline/generator_constraint.py`：**
- `KO_TYPE_TO_PAGE_TYPE` 逻辑扩展：自定义 KnowledgeType → 查 registry

### Task 4：Analyzer 支持自定义类型

**`src/pipeline/analyzer.py`：**
- `page_types` 占位符 = `reg.all_type_names()` 的 `|` 连接（替代硬编码 4 类型）
- 注入 `## Project Schema` + `## Wiki Purpose` 节
- `ANALYZER_JSON_PROMPT` 的 `knowledge_types` 保持 `KnowledgeType` 枚举不变

### Task 5：generate_ingest 集中编排

**`src/pipeline/ingest.py`：**
- `generate_ingest` 集中读取 `root/schema.md` → `SchemaRegistry.from_project(paths)`
- 通过参数传递给 `analyze()` / `generate()` / `unified_generate()`
- 与 `existing_wiki_index` 同模式：1 次 I/O，多处复用

### Task 6：测试 + 文档

**新增：** `tests/test_wiki/test_schema_registry.py`（7 个测试）

| 测试 | 验证点 |
|------|--------|
| `test_parse_schema_with_custom_types` | `\| thesis \| wiki/thesis \|` → `CustomTypeDef("thesis","thesis",CONCEPT)` |
| `test_parse_schema_only_builtin` | 只有基础类型 → `all_custom_type_names() == []` |
| `test_parse_schema_missing_file` | 无 schema.md → `SchemaRegistry.empty()` |
| `test_page_path_for_custom_type` | 自定义类型写入正确目录 |
| `test_generator_accepts_custom_type` | `response_format` enum 含 thesis |
| `test_analyzer_page_types_union` | `page_types` 含 thesis |
| `test_candidate_pipeline_custom_type` | `generate_from_knowledge_object` 接受自定义类型 |

**`CLAUDE.md`：** Architecture 补充自定义类型机制说明。

---

## 4. 改动文件清单

| 文件 | 改动类型 |
|------|----------|
| `src/wiki/schema_registry.py` | 新增 |
| `src/wiki/core/paths.py` | 修改（`get_custom_dir`） |
| `src/wiki/core/types.py` | 修改（`_TYPE_TO_DIR` 保持，不加枚举） |
| `src/wiki/storage/page_writer.py` | 修改（`page_path_for` 接受 registry） |
| `src/wiki/storage/ensure.py` | 修改（接受 registry 创建自定义目录） |
| `src/pipeline/generator.py` | 修改（enum 动态化 + 回退 + 注入） |
| `src/pipeline/generator_constraint.py` | 修改（`KO_TYPE_TO_PAGE_TYPE` 扩展） |
| `src/pipeline/analyzer.py` | 修改（page_types 并集 + 注入） |
| `src/pipeline/ingest.py` | 修改（集中读取 + 传递） |
| `tests/test_wiki/test_schema_registry.py` | 新增 |
| `CLAUDE.md` | 修改 |

---

## 5. 不纳入范围

- 自定义类型的独立 slot 模板（回退 base type；后续按 `wiki/templates/<type>.md` 扩展 resolver 候选路径即可）
- 自定义类型的独立 frontmatter 字段（llm_wiki-main 的 research 有 confidence/status；后续加）
- `schema_routing.validate_schema_routing` 重写（只做验证，不支配写路径）
- `UNIFIED_PROMPT` 强化（已废弃，仅顺带注入）

---

## 6. 验收标准

1. ✅ schema.md 定义 `| thesis | wiki/thesis |` → `SchemaRegistry` 正确解析
2. ✅ 无 schema.md / 只有基础类型 → 行为完全不变
3. ✅ LLM 输出 `type: thesis` → Generator 不丢弃，写入 `wiki/thesis/`
4. ✅ 自定义类型用 CONCEPT 的 slot 模板渲染
5. ✅ `ensure_knowledge_base` 创建自定义目录
6. ✅ 候选管道（`generate_from_knowledge_object`）支持自定义类型
7. ✅ 所有现有测试通过（baseline 828+）