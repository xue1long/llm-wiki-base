# Wiki 数据模型（WikiPage Model）介绍

> 本文档基于 2026-08-03 实测代码梳理，介绍 `ruflo-kb` 项目的核心数据模型 **`WikiPage`** 及其关联结构（页面类型、关系、标签、序列化）。代码真相源：`src/wiki/core/types.py`、`src/wiki/features/relations.py`、`src/wiki/features/tag_namespace.py`。
> 配套文档：`docs/guides/wiki-spec.md`（页面规范：ID/Frontmatter/Body）、`docs/guides/ingest-pipeline-overview.md`（WikiPage 如何被生成）。

---

## 1. 它是什么

**`WikiPage`** 是知识库的中心数据模型（`src/wiki/core/types.py:54`）。它表示一个被管理、可被检索的「知识卡片」。

- **内存形态**：一个 Python `@dataclass` 实例（字段见 §2）。
- **持久形态**：落盘为一个 **Markdown 文件**——文件头是 YAML `frontmatter`（对应模型字段），其后是 Markdown `body`（正文）。
- **真相源原则**：Markdown 文件是唯一真相源；`WikiPage` 只是它在运行时的内存表示，所有读写都围绕「frontmatter + body」展开。

> `src/wiki/core/page_model.py` 仅是一个**兼容桥**（重导出 `WikiPage`），没有第二套模型实现——模型身份唯一。

---

## 2. WikiPage 字段详解

定义在 `src/wiki/core/types.py:54`：

| 字段 | 类型 | 含义 | 来源/备注 |
|------|------|------|-----------|
| `id` | `str` | 页面唯一 ID（UUIDv7，slug 友好） | 由 `src/wiki/core/id_generator.py` 生成 |
| `title` | `str` | 页面标题 | 必填 |
| `type` | `PageType` | 页面类型（见 §3） | 必填，8 类枚举 |
| `sources` | `list[str]` | 来源引用（原始素材路径/URL） | |
| `created_at` | `str` | 创建时间戳（ISO 8601） | **v3.2 改为字符串**，如 `"2024-08-04T10:30:00Z"` |
| `updated_at` | `str` | 更新时间戳（ISO 8601） | **v3.2 改为字符串** |
| `body` | `str` | 正文（Markdown） | 不在 frontmatter 内，单独成段 |
| `relations` | `list[Relation]` | 页面间关系（见 §4） | |
| `grade` | `str` | 质量等级 `"A"\|"B"\|"C"` | **v2.2 新增**，默认 `"B"` |
| `processing_depth` | `str` | 处理深度 `"concept"\|"memory"` | **v2.2 新增**，默认 `"concept"` |
| `is_immutable` | `bool` | 是否只读不可改 | **v2.2 新增** |
| `heat` | `int` | 热度值（0–100） | **wiki-heat-5pool T1** 引入，默认 `50` |
| `last_used_at` | `str` | 上次被引用时间戳（ISO 8601） | **v3.2 改为字符串**，热度调度用 |
| `zombie_since` | `str \| None` | 进入「僵尸」状态的时间（ISO 8601） | **v3.2 改为字符串**，僵尸清理用 |
| `tags` | `list[str]` | 受控命名空间标签（见 §5） | 如 `题材/都市`、`素材/ugc` |
| `category` | `str` | 分类（LLM 指派），`""`=未分类 | **v3.1 taxonomy** 引入 |
| `taxonomy_sub` | `str` | 子类目 | **v3.1 taxonomy** 引入 |
| `related_entities` | `list[str]` | 低重要度实体引用（内联，不建 stub 页） | C3 优化引入 |
| `_ko_extra` | `dict?` | KOS（KnowledgeObject）扩展字段 | **非 dataclass 字段**，以属性形式附加；仅当存在时序列化进 frontmatter |

**字段演进特征**：`WikiPage` 是渐进式生长的——`grade`/`processing_depth`/`is_immutable`（v2.2）、`heat` 系列（热度调度）、`category`/`taxonomy_sub`（v3.1 分类）、时间戳改为 ISO 8601 字符串（v3.2）、`_ko_extra`（KOS 演进扩展）都是后来叠加的。模型用 dataclass 默认值保证向后兼容（旧页面缺字段也能 `from_dict` 还原，旧格式时间戳自动转换）。

---

## 3. PageType：8 类页面类型

`PageType` 是 `str` 枚举（`types.py:10`），决定页面的**语义角色**与**落盘目录**：

| 枚举值 | `type` 字符串 | 落盘目录（`_TYPE_TO_DIR`） | 说明 |
|--------|---------------|----------------------------|------|
| `SOURCE` | `source` | `wiki_sources` | 原始素材页 |
| `ENTITY` | `entity` | `wiki_entities` | 实体（人物/组织/地点…） |
| `CONCEPT` | `concept` | `wiki_concepts` | 概念 |
| `SYNTHESIS` | `synthesis` | `wiki_synthesis` | 综合/综述 |
| `CLAIM` | `claim` | `wiki_claims` | 论点/主张 |
| `DECISION` | `decision` | `wiki_decisions` | 决策 |
| `PROCEDURE` | `procedure` | `wiki_concepts` | 流程/步骤（**与 concept 同目录**） |
| `EVENT` | `event` | `wiki_concepts` | 事件（**与 concept 同目录**） |

> ⚠️ **已知不一致**：`procedure` 与 `event` 在 `_TYPE_TO_DIR` 中映射到 `wiki_concepts`（历史原因）；而 `CLAIM`/`DECISION` 各有独立目录。这与 `analyzer` 提示词（markdown 仅 4 类、JSON 6 类）及 `generator._DEPTH_BY_TYPE`（仅 4 类映射）并不同步——属于「页面类型三套矛盾」问题，已在 `docs/evaluations/wiki-spec-sync-audit.md` 与 `docs/superpowers/plans/2026-08-03-wiki-spec-sync.md`（决策门 G0/G1/G2）中处置。

---

## 4. Relation：页面间关系模型

定义在 `src/wiki/features/relations.py`。一个 `WikiPage.relations` 是 `Relation` 列表。

### RelationType（18 种语义关系，`relations.py:7`）
`is_part_of` / `contains` / `references` / `referenced_by` / `causes` / `caused_by` / `contradicts`（对称）/ `supports` / `supported_by` / `supersedes` / `superseded_by` / `depends_on` / `required_by` / `analogous_to`（对称）/ `opposite_of`（对称）/ `derived_from` / `derives`

- **逆关系表**（`INVERSE_RELATIONS`）：如 `is_part_of ↔ contains`、`references ↔ referenced_by`、`causes ↔ caused_by`，用于双向自动维护。
- **用户扩展**：`USER_TYPE_PREFIX = "x-"`——允许 `x-<name>` 形式的自定义关系类型，不破坏标准枚举。
- **对称关系**（`SYMMETRIC_RELATIONS`）：`contradicts` / `analogous_to` / `opposite_of`。

### Relation dataclass（`relations.py:51`）

| 字段 | 类型 | 含义 |
|------|------|------|
| `target_id` | `str` | 目标页面 ID |
| `type` | `str` | `RelationType.value` 或 `x-<name>` |
| `weight` | `float` | 关系强度，默认 `1.0` |
| `context` | `str` | 关系上下文说明 |

- 序列化：`to_dict()` → `{"target", "type", "weight", "context"}`（weight 四舍五入 2 位）。
- 反序列化：`from_dict()` 会对 `target` **做 slugify 归一化**（`relations.py:69`），避免「LLM 输出原始字符串」与「页面 ID 经 slugify 生成」不一致导致的**悬空关系**（B12 修复）。

---

## 5. 标签：受控命名空间

`WikiPage.tags: list[str]`，每个标签形如 `"前缀/值"`。

- **前缀**：10 个中文受控前缀（题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度）。
- **值域**：部分前缀有受约束值域（`TAG_VALUES`），如 `题材`、`功能`、`情绪`、`场景阶段`、`状态`、`素材`、`可信度`；`角色`/`事件`/`实体` 为自由前缀。
- **强制配对**：`MANDATORY_PAIRS = [("素材","ugc"), ("可信度","ugc")]`——UGC 来源页面必须同时带这两枚标签。
- **写入校验**：新建页面时 `page_writer.py:74` 调用 `validate_tag_compliance(tags)`，越界值或缺配对即抛 `TagValidationError` 阻断写入（仅新建触发，更新路径跳过——见 ingest 文档 §6）。
- 完整规则见 `src/wiki/features/tag_namespace.py` 与 `docs/CONSTRAINTS.md §3.4`。

---

## 6. 序列化：模型 ↔ Markdown

`WikiPage` 与磁盘之间靠两个方法互转（`types.py`）：

- **`to_frontmatter_dict()`**（`:79`）：把模型导出为 frontmatter 字典，写入所有字段；`_ko_extra` 仅当其作为属性存在时才加入。
- **`from_dict(d, body)`**（`:104`）：从字典 + body 文本还原 `WikiPage`，缺失字段用默认值兜底（保证旧文件可加载）。

实际落盘流程（由摄取/编辑链路调用）：
```
WikiPage ──to_frontmatter_dict()──> dict
dict + body ──YAML 序列化──> ────┐
                                 ├─> {id}.md  (frontmatter + body)
body ──────────────────────────> ┘
```
加载则反向：`读取 md → 拆 frontmatter/body → from_dict()`。

---

## 7. 与 wiki-spec.md 规范的关系

- **代码模型是事实，规范是约束**。`wiki-spec.md` 定义 frontmatter 的**必填/可选规则**与 ID 正则（如 `id` 必填且符合 UUIDv7 格式、`title`/`type` 必填），由 `wiki_rules_prompt.py`（从规范自动生成）在生成时注入 LLM 提示词。
- **已知差异**（详见 `docs/evaluations/wiki-spec-consistency.md`）：代码 `to_frontmatter_dict()` 实际写入的字段（如 `category`/`taxonomy_sub`/`related_entities`/`_ko_extra`）比规范早期版本列出的 optional 字段多；新类型（`claim`/`decision`/`procedure`/`event`）在规范文本与 bundled 模板中尚未完全对齐。这些已在同步方案 v2.0 中规划补齐。

---

## 8. 关键文件索引

| 文件 | 职责 | 关键位置 |
|------|------|----------|
| `src/wiki/core/types.py` | `WikiPage`、`PageType`(8类)、`_TYPE_TO_DIR`、`KnowledgeTask`、`ReviewItem`、序列化方法 | `WikiPage:54`；`PageType:10`；`to_frontmatter_dict:79`；`from_dict:104` |
| `src/wiki/core/page_model.py` | 兼容桥，重导出 `WikiPage` | 全文（无独立模型） |
| `src/wiki/core/id_generator.py` | 生成 `id`（UUIDv7） | `card_` 生成函数 |
| `src/wiki/features/relations.py` | `Relation`、`RelationType`(18种)、逆关系、对称集、用户扩展前缀 | `RelationType:7`；`Relation:51`；`INVERSE_RELATIONS:28`；`USER_TYPE_PREFIX:48` |
| `src/wiki/features/tag_namespace.py` | 标签命名空间（前缀/值域/配对/校验） | `TAG_PREFIXES`、`TAG_VALUES`、`MANDATORY_PAIRS`、`validate_tag_compliance` |
| `src/wiki/storage/page_writer.py` | 页面落盘 + 标签合规校验 | `validate_tag_compliance` 调用 `:74` |

---

## 9. 相关文档

- `docs/guides/wiki-spec.md` — 页面规范（ID / Frontmatter / Body / 模板）
- `docs/guides/ingest-pipeline-overview.md` — WikiPage 如何被摄取流程生成
- `docs/CONSTRAINTS.md` — 输出格式约束（含标签 API 表）
- `docs/evaluations/wiki-spec-consistency.md` — 模型/规范一致性核验（已知差异）
- `docs/evaluations/tag-namespace-evaluation.md` — 标签命名空间评估

---

## 10. 时间戳格式（v3.2）

**变更历史**：v3.2 将时间戳字段从 Unix 毫秒（`int`）改为 ISO 8601 字符串（`str`）。

### 时间戳字段

| 字段 | 类型 | 格式 | 示例 |
|------|------|------|------|
| `created_at` | `str` | ISO 8601 | `"2024-08-04T10:30:00Z"` |
| `updated_at` | `str` | ISO 8601 | `"2024-08-04T10:35:00Z"` |
| `last_used_at` | `str` | ISO 8601 | `"2024-08-04T12:00:00Z"` |
| `zombie_since` | `str \| None` | ISO 8601 | `"2024-07-01T00:00:00Z"` |

### 格式约定

- **格式**：ISO 8601，UTC 时区，后缀 `Z`
- **精度**：秒级（不含微秒）
- **默认值**：空字符串 `""` 表示"未设置"
- **工具函数**：`src/utils/timestamp.py` 提供 `now_iso()`、`parse_iso()` 等辅助函数

### 向后兼容

`from_dict()` 会自动转换旧格式：

```python
# 旧格式（int 毫秒）
created_at: 1722825600000

# 新格式（ISO 8601 字符串）
created_at: "2024-08-04T10:30:00Z"
```

### 迁移脚本

现有数据可使用迁移脚本批量转换：

```bash
python scripts/migrate_timestamps.py ./knowledge/novel-wiki
```

</content>
