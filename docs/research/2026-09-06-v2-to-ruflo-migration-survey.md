# 调研报告：LLM_Knowledge_base_v2 → ruflo-kb 数据迁移

> **作者**：分段接力 · 阶段 1（架构设计）
> **日期**：2026-09-10（审计整改版）
> **状态**：调研完成 / Round 1、1.5、2 已完成 / P0 加固待实施
> **范围**：`10_raw/` 当前 3056 个文件 + `20_wiki/` 当前 2082 个 Markdown/support 文件 → ruflo-kb V6 迁移模型

---

## 1. 调研背景

`D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\` 是基于 Python 脚本 + Obsidian vault + SQLite 的「视频/文章笔记 → 结构化 Wiki」个人知识库；当前 CWD `D:\5-Project\20260903\llm-wiki-base` 是 ruflo-kb（FastAPI + 多 Agent 编排 + LanceDB + RRF 混合检索）。两个项目**数据结构完全不同**，v2 是「文件即真相 + SQLite 状态簿」，ruflo-kb 是「WikiPage 数据类 + 多维度 metadata + 向量索引」。本次迁移以 2026-09-09 实际清单为基线，并要求每个文件 exactly one disposition。

本调研回答三个问题：

1. **v2 有什么？要迁什么？**（数据盘点）
2. **ruflo-kb 要什么？接受什么？**（目标数据模型）
3. **两者之间有哪些差异点？**（差异矩阵 + 风险点）

---

## 2. v2 数据全貌（来源 + 体量）

| 维度 | 数量 / 体量 | 来源 |
|---|---|---|
| 原始素材总文件 | **3056** | `10_raw/` 全量清单 |
| 主要平台素材 | 2397 | 三个平台目录 |
| `.batch` 元数据 | 5 | metadata-only |
| 原始素材总大小 | 以 manifest 实测为准 | apply 前计算并加临时空间与 5 GB 安全余量 |
| Wiki 概念卡 | **1919** | `20_wiki/concepts/*.md` |
| Wiki 实体卡 | 5 | `20_wiki/entities/*.md`（Claude Code / Karpathy / Obsidian / …） |
| 待重编译草稿 | 155 | `20_wiki/concepts/_to_recompile/*.md`（与顶层概念卡部分重名） |
| 无效素材记录 | 1 | `20_wiki/invalid_BV1tdPDzQEpa.md`（quarantine 记录） |
| 已消化归档 | 637 | `10_raw/_archive/`（可选迁） |
| 种子文件 | 1 | `10_raw/_seed/`（优先编译标记） |
| `links.md` / `overview.md` | 2 | support artifact，不作为 Wiki 卡 |
| SQLite 状态库 | 若存在 | 存在则快照，不存在则记录 support disposition |

**关键观察**：
- `_to_recompile/` 子目录与顶层概念卡存在**文件名冲突**（如 `BV1AtwLzTEtB.md` 上下都有一份）。迁移必须做"主版本优先 + 草稿归档"决策。
- 实体卡 5 张均为「工具/人物/平台」类高价值卡（Claude Code、Obsidian、Karpathy 等），是网状关系的"节点"。
- `invalid_*.md` 用了**自定义字段**（`uid/bv/source/uploader/video_published_at/invalid_reason/...`），不是标准 v2 frontmatter——迁移工具必须能识别并保留（否则 quarantine 数据丢失）。

---

## 3. v2 Frontmatter 数据模型（13 项必填）

```yaml
# 标准 Wiki 卡片（concepts/BV113411K7tu.md 实际样本）
---
title: 网文萌新如何建立"读者马甲"自审作品
version: v2.1                  # v2.1 | v2.1-mini
tags: [网文创作, 读者视角, ...]
processing_depth: concept       # memory | concept | operation
source_grade: A                 # A | B | C
platform: B站                   # B站/抖音/小红书/...
url: https://...
author: N/A
category: 内容创作               # 3 一级
use_context: build              # build/ops/research/design/delivery（v3.5 新增）
maturity: A级-可借鉴
taxonomy_sub: 写作技巧           # 17 二级（SSOT in constants.py）
created: 2026-06-18             # ISO 8601 日期
updated: 2026-06-18
summary: ...                    # 摘要（v3.5 后常见）
type: concept                   # 与 processing_depth 同值，冗余
---

## 核心观点
...
## 使用方法与步骤
...
## 参考来源
...
```

**实体卡额外字段**（5 张 entity 独有）：
```yaml
type: entity                    # 强制 entity
aliases: [claude-code, claude_code, ClaudeCode]  # 多个别名
instance_of: 工具                # 「实例类型」，对应 ruflo-kb 的 custom_type
```

**v2 数据库（compile_db.sqlite）核心表**：

| 表 | 关键字段 | 用途 |
|---|---|---|
| `records` | record_id (md5[:16]), source_file, status, invalid_reason, compiled_at | 原始素材状态（pending/done/skipped）|
| `wiki_pages` | page_id, record_id, wiki_path, confidence | 链接 record → wiki 文件 |

---

## 4. ruflo-kb 数据模型（V5 严格 8-key 白名单）

### 4.1 写入磁盘的 8 个字段（V5 严格白名单）

```yaml
---
id: BV113411K7tu               # 文件名同名 slug
title: 网文萌新如何建立"读者马甲"自审作品
type: concept                  # source | entity | concept | synthesis
sources: ["https://..."]       # 列表（v2 的 url → 列表化）
created_at: 2026-06-18T00:00:00Z   # ISO 8601 datetime（V5 新格式）
updated_at: 2026-06-18T00:00:00Z
relations:                     # 17 种内置 + x-* 用户自定义
  - target: BV1AtwLzTEtB
    type: references
    weight: 1.0
    context: ""
tags: [网文创作, 读者视角, ...]
---
```

### 4.2 内存扩展字段（不写入磁盘，但代码层可读）

> **关键事实**（来自 `src/wiki/storage/page_writer.py` 第 8 行注释）：
> "All other fields (grade/processing_depth/heat/workflow_state/_ko_extra/decision_record/evidence_refs/valid_from/valid_to/custom_type/category/taxonomy_sub/...) live on the in-memory WikiPage dataclass for code that needs them, but are NOT written to disk."

可在内存读到的字段：`grade / processing_depth / is_immutable / heat / last_used_at / zombie_since / category / taxonomy_sub / related_entities / custom_type / workflow_state / verified_at / decision_record / evidence_refs / valid_from / valid_to`。

### 4.3 目录结构（ruflo-kb 项目布局）

```
<project>/
├── wiki/
│   ├── sources/   entities/   concepts/   synthesis/   _stubs/
│   ├── _archive/                # heat CLI archive target
│   ├── media/                   # extracted images
│   ├── index.md                 # catalog
│   └── log.md                   # audit trail
├── raw/sources/                 # 单一目录（vs v2 多子目录）
├── .llm-wiki/
│   ├── project.json             # 项目身份
│   ├── slug_aliases.json        # CJK slug → 规范别名
│   └── .backup/
└── .index/
    ├── lancedb/                 # 1536-dim 向量库
    ├── lint_cache/              # LLM lint 缓存
    ├── reviews.json, reviews_resolved.json
    ├── staging/, quarantine/, dedup_history/
    └── quality_settings.json
```

---

## 5. 字段差异矩阵（v2 → ruflo-kb）

| v2 字段 | v2 类型 | ruflo-kb 字段 | 处置策略 | 风险 |
|---|---|---|---|---|
| `title` | str | `title` | **直映** | 无 |
| *(无)* | — | `id` ⭐ | 从**文件名**生成 slug | 已有 slug 别名机制，可处理 CJK |
| *(无)* | — | `type` ⭐ | 推断：concepts/→concept，entities/→entity | 简单 |
| `url` | str | `sources: [url]` | 列表化包装；原始 scalar 保留为 `_ko_extra.v2_url` | 多 URL 由 v2 原始字段副本保留 |
| `created` | ISO 日期 | `created_at` ms int | 转 ms | 边界：日期 vs datetime，ruflo-kb 接受 ISO 8601 |
| `updated` | ISO 日期 | `updated_at` ms int | 转 ms | 同上 |
| `tags` | list[str] | `tags` + `_ko_extra._v2_tags_original` | 受控归一化；失败项进入 `_v2_legacy_tags` | 原 tag 总数必须可对账 |
| *(无 wikilink 索引)* | — | `relations: [Relation]` | 从 `[[xxx]]` 解析 | 大工程量 |
| `processing_depth` | str | V6 顶层 | **写入 V6 顶层** | V6 write/read 必须一致 |
| `source_grade` | str | V6 顶层 | 写入 V6 顶层 | 同上 |
| `platform` | str | V6 顶层 | 写入 V6 顶层 | 不重复写 `_ko_extra.platform` |
| `author` | str | 内存字段 | 写入 `_ko_extra` | 同上 |
| `category` | str | V6 顶层 | 写入 V6 顶层 | 同上 |
| `maturity` | str | 内存字段 | 写入 `_ko_extra` | 同上 |
| `taxonomy_sub` | str | V6 顶层 | 写入 V6 顶层 | 同上 |
| `use_context` | str | V6 顶层 | 写入 V6 顶层 | v3.5 新增 |
| `workflow_state` | str | V6 顶层 | 写入 V6 顶层 | v3.5 新增 |
| `version` | "v2.1" | *(无对应)* | 写入 `_ko_extra`（含迁移标识） | 标识 v2 来源 |
| `summary` | str | *(无对应)* | 写入 `_ko_extra.summary`，不改写原 body | 通过 read → write → read 保留 |
| `aliases` | list[str] | `slug_aliases.json` | **写入 `.llm-wiki/slug_aliases.json`**（5 张 entity 卡） | 已设计 API（`SlugAliasRegistry`） |
| `instance_of` | str | `custom_type` | 写入 `_ko_extra.custom_type` | v2 仅 entity 卡有此字段 |
| `uid/bv/source/uploader/...` | str | *(无对应)* | 仅 invalid_*.md 才有 | **必须保留**——这些是 quarantine 元数据 |

**结论**：

- **强写入**（核心 8 项 + V6 字段）：id / title / type / sources / created_at / updated_at / relations / tags，以及 V6 canonical 字段 → 转换器主任务
- **V6 + `_ko_extra`**：V6 顶层字段保存 canonical 业务字段；其余字段按 `docs/architecture/v2-to-v6-field-mapping.md` 进入 `_ko_extra`，所有字段必须可回读
- **特殊通道**（`aliases`）：走 `.llm-wiki/slug_aliases.json`，ruflo-kb 已设计
- **quarantine 通道**：invalid_*.md 单独存为 `.index/quarantine/`（ruflo-kb 已存在该目录）

---

## 6. wikilink 解析复杂度

v2 大量使用 `[[wikilink]]`，主要有 5 种格式：

| 形态 | 示例 | v2 文件 | 目标 |
|---|---|---|---|
| BV 号 | `[[BV1AtwLzTEtB]]` | B 站视频卡片 | `wiki/concepts/BV1AtwLzTEtB.md` |
| 抖音 ID | `[[7512800963258797321]]` | 抖音笔记卡片 | `wiki/concepts/7512800963258797321.md` |
| 中文标题 | `[[Claude Code]]`、`[[Obsidian]]` | 实体卡 | `wiki/entities/Claude Code.md` |
| 别名 | `[[ClaudeCode]]` | 实体卡引用 | 通过 `slug_aliases.json` 解析 |
| 视频卡反引源 | `[[BV1AtwLzTEtB]]` | 概念卡引用源视频 | `sources: [url]` + relations |

**ruflo-kb 已实现**（`src/wiki/features/wikilink.py` + `slug_aliases.py`）：

- `extract_wikilinks(text)` → 提取目标列表
- `resolve_wikilink(root, target)` → 在所有 typed wiki 目录按 slug 查找，找不到则查 `SlugAliasRegistry`
- `Relation.from_dict` 用 `slugify` 规范化 target

**迁移挑战**：

1. **CJK 标题 slug**：v2 中文标题 `Claude Code` → ruflo-kb 文件名预期也是 `Claude Code.md`？还是 slugify 后 `claude-code.md`？两者都允许但**整个 v2 vault 一致性**最重要——如果 v2 现存就是空格文件名，ruflo-kb 也保留。
2. **BV 号 → relations**：ruflo-kb 的 `relations` 是「卡片之间的关系」（references / supports / contradicts / ...），但 v2 的 wikilink 大部分是「参考资料」语义（不是 LLM 抽取的语义关系）。直接 1:1 转 `type: references` 最稳妥，后续可由 LLM 重新 enrich。
3. **链接解析失败**：1919 张卡互相 wikilink，迁移后立即 `validate` 必有断链（v2 自身就有断链——BV 字段 `来源` 引用的源视频未必有对应概念卡）。需要 `KnowledgeGapStore`（已存在）兜底。

---

## 7. 命名/路径策略

### 7.1 raw 文件名命名约定

v2 raw 文件**直接用 BV 号/抖音 ID/CJK 标题**：

```
10_raw/01_B站视频转录/BV113411K7tu.txt
10_raw/02_抖音视频笔记/7512800963258797321.md
10_raw/03_小红书收藏夹/Nano-Banana-Pro-Gemini3分镜控制.md
```

### 7.2 ruflo-kb raw 入口

ruflo-kb 只有 `raw/sources/` 单一目录（参见 `WikiPaths.raw_sources`）。

**迁移策略**：

| v2 路径 | ruflo-kb 路径 |
|---|---|
| `10_raw/01_B站视频转录/X.txt` | `raw/sources/bilibili__X.txt` |
| `10_raw/02_抖音视频笔记/X.md` | `raw/sources/douyin__X.md` |
| `10_raw/03_小红书收藏夹/X.md` | `raw/sources/xiaohongshu__X.md` |
| `10_raw/_archive/X.*` | `raw/_archive/X.*`（保留原路径） |
| `10_raw/_seed/X.*` | `raw/_seed/X.*`（保留原路径） |
| `10_raw/_skip/X.*` | `raw/_skip/X.*`（保留原路径） |

**关键决策点**：是否在文件名前加 `bilibili__` / `douyin__` / `xiaohongshu__` 前缀？

- **支持**（推荐）：避免 BV 号与抖音 ID 数字 ID 撞名（如两个不同平台都有 13 位纯数字 ID），保留 platform 元数据。
- **反对**：v2 原名不带前缀，简单迁移不该"主动改造"——ruflo-kb 后续读 raw 解析文件时也可从 `url` 字段推断 platform。

**建议**：第一版保守迁移（不加重命名），依赖 `url`/frontmatter `platform` 字段做平台区分；只在发现**确实撞名**时再加前缀。

### 7.3 wiki 文件名

v2 概念卡文件 = slug（与 frontmatter id 一致——v2 没显式 id 字段，靠文件名）。**迁移时直接保留文件名作为 WikiPage.id**，无需改动。

---

## 8. 数据库 (compile_db.sqlite) 处置

v2 的 `records` 表记录了每个原始素材的 status / 编译时间 / 关联 wiki_page。ruflo-kb **没有等价表**（它的"状态"在 wiki/index.md、log.md 里）。

**处置方案**：

1. **不迁移** records 表 → ruflo-kb（ruflo-kb 无对应抽象）
2. **导出为 CSV** 留在 v2 项目根目录供用户查阅：`compile_db_migration_snapshot_2026-09-06.csv`
3. **wiki_pages 表** 不需要迁；Wiki 页面和 manifest 才是目标事实源，SQLite 仅在存在时做 snapshot

---

## 9. 关键风险点（调研结论）

| 编号 | 风险 | 等级 | 描述 |
|---|---|---|---|
| R1 | wikilink 断链 | 🟡 中 | v2 自身有大量 `[[BV...]]` 引用未对应概念卡（如只有 raw 没有编译），迁移后必然触发 `KnowledgeGapStore` |
| R2 | `_to_recompile/` 子目录冲突 | 🟡 中 | 155 张草稿与顶层 1919 张有文件名冲突；必须决策保留策略 |
| R3 | 字段语义丢失 | 🟠 高 | v2 的 `processing_depth / source_grade / use_context / workflow_state` 在 ruflo-kb 不写盘，依赖 `_ko_extra` 逃生口；如果 ruflo-kb 后续清理 `_ko_extra`（未知），信息丢失 |
| R4 | 标签命名空间校验 | 🟡 中 | v2 有 `tool/AI编程` 等带前缀标签，ruflo-kb `validate_tag_compliance` 会拒绝；要么迁移前清洗标签，要么改 ruflo-kb 的 tag 规则 |
| R5 | `invalid_*.md` quarantine 元数据 | 🟡 中 | 用了非标准字段（uid/source/bv/...），如果不识别，会被 `from_dict` 抛弃 |
| R6 | CJK 文件名 slug 漂移 | 🟡 中 | v2 已有 `slug_aliases` 设计（CJK↔规范别名）；5 张 entity 卡 + 100+ 概念卡有 CJK 标题 |
| R7 | `_archive/` 637 文件 | 🟢 低 | 已消化归档，迁移时**默认排除**（除非用户明示要） |
| R8 | raw 文件体量 | 🟢 低 | 3.2 GB 总量；纯文件 IO，5 分钟内完成 |
| R9 | LanceDB 向量重建 | 🟡 中 | 迁移后必须**重新生成**所有向量（ruflo-kb `init_vector_store_for_paths` + 全量 upsert），对 LLM 服务有费用 |
| R10 | 增量迁移 vs 全量 | 🟠 高 | 当前清单规模较大；采用一次 run-id 全量迁移，但必须支持 checkpoint/resume，避免失败后从头开始 |
| R11 | 与 v2 vault 双写期 | 🟠 高 | 迁移后 v2 仍在维护（用户日常加素材）；如何保持双向同步？还是"切单行道"（迁移完成后 v2 冻结）？ |
| R12 | 测试覆盖 | 🟡 中 | ruflo-kb 项目目前**没有 wiki-migration 的测试套件**——需要新建 `tests/test_wiki_migration/` |

---

## 10. 推荐迁移架构（高层）

```
v2 (read-only)                    ruflo-kb project (target)
┌──────────────────┐              ┌──────────────────────┐
│ 10_raw/          │  ──copy──►   │ raw/sources/         │
│   01_B站视频转录 │              │   (preserve names)   │
│   02_抖音视频笔记│              │                      │
│   03_小红书收藏夹│              │                      │
│   _archive/      │  ──copy──►   │ raw/_archive/        │
│   _seed/ _skip/  │  ──copy──►   │ raw/_seed/ _skip/    │
│                  │              │                      │
│ 20_wiki/         │  ──convert─► │ wiki/                │
│   concepts/      │  ─►          │   concepts/          │
│   entities/      │  ─►          │   entities/          │
│   invalid_*.md   │  ─►          │ .index/quarantine/   │
│                  │              │                      │
│ compile_db.sqlite│  ──export─►  │ compile_db_snapshot  │
│                  │              │ .csv  (v2 留底)      │
└──────────────────┘              └──────────────────────┘
                                              │
                                              ▼
                                ┌──────────────────────────┐
                                │ tools/migrate_v2.py      │
                                │   - parse_yaml()         │
                                │   - convert_page()       │
                                │   - parse_wikilinks()    │
                                │   - write_page()         │
                                │   - report.csv           │
                                └──────────────────────────┘
                                              │
                                              ▼
                                ┌──────────────────────────┐
                                │ python -m src.cli project│
                                │   init <target>          │
                                │   --import-from-v2       │
                                └──────────────────────────┘
```

---

## 11. 推荐的执行顺序（5 阶段）

> 完整 Task 列表 + TDD 测试用例见 `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md`

| 阶段 | 名称 | 目标 | 关键产出 | 预估工时 |
|---|---|---|---|---|
| **Phase 0** | PoC（小样本试跑） | 迁 5 张概念卡 + 1 张 entity 卡 | 验证 frontmatter 转换、wikilink 解析、写入路径、ruflo-kb 能正常 read | 1-2 天 |
| **Phase 1** | 核心转换器 | 实现 `tools/migrate_v2.py`：解析 v2 + 写入 ruflo-kb | CLI 工具 + 单测套件（覆盖 frontmatter / relations / invalid_* / _to_recompile / CJK）| 3-4 天 |
| **Phase 2** | 全量迁移 + 报告 | 当前 manifest 的 raw/wiki/support 全量 + 可选 compile_db 快照 | manifest + report + 完整目标 KB | 以实际基线和 checkpoint 为准 |
| **Phase 3** | 验证 + 健康度 | `health_check` + 自定义检查（断链/字段保留/relations 完整）| 验证报告 + 任何修复提交 | 2-3 天 |
| **Phase 4** | LanceDB 重建 + 切换 | `python -m src.cli serve` + 全量 vector upsert + WebUI smoke test | 可用检索服务 + 旧 v2 vault 冻结说明文档 | 1-2 天 |

**总计**：8-13 天（单人串行，TDD per task，每任务一提交）。

---

## 12. 决策拍板记录（用户确认 · 2026-09-06）

> **状态**：✅ **D1-D9a 已锁定，审计整改版生效**（2026-09-10）。
> **生效时间**：方案阶段 1 → 阶段 2 切换时立即生效。
> **修改约束**：本决策表为后续实施方案的 SSOT，任何 Phase 实施过程中如发现决策不合理，必须先回到本节重新拍板，再修改代码。

| # | 决策点 | 最终决策（2026-09-06）| 影响代码 | 验收方法 |
|---|---|---|---|---|
| **D1** | `_to_recompile/` 155 张草稿如何处理？ | ✅ **保留为 `wiki/_pending/` 子目录**，不进入主 wiki 树；后续人工 review 后手动 promote | T6 决策器 + 主树过滤 | manifest 对账；无草稿混进主树 |
| **D2** | `_archive/` 637 文件是否迁移？ | ✅ **迁移到 `raw/_archive/`**，便于日后回查；使用 SHA-256 对账 | T5 raw 搬运器 | manifest + 全部 hash 一致 |
| **D3** | v2 字段如何进入目标？ | ✅ **V6 顶层 + `_ko_extra`**；按 `docs/architecture/v2-to-v6-field-mapping.md` 唯一归属，未知字段不得丢失 | T1 frontmatter 转换器 | 抽样 50 张卡 read → write → read 100% 一致 |
| **D4** | raw 文件名加 `bilibili__` 前缀？ | ✅ **否**（保守迁移）；冲突默认 fail 并写报告 | T5 撞名检测 → 用户手动介入 | collision 数 == manifest collision 数 |
| **D5** | 实体卡 `aliases` → `slug_aliases.json`？ | ✅ **是**；ruflo-kb 已支持 | T3 aliases 导出器 | `.llm-wiki/slug_aliases.json` 含 5 张 entity 卡 |
| **D6** | `invalid_*.md` quarantine 元数据？ | ✅ **保留全部**，写入 `.index/quarantine/<slug>.md` + 元数据 JSON | T4 quarantine 处理器 | `.index/quarantine/` 含 1 张 invalid 卡 + judgments.jsonl 1 行 |
| **D7** | 迁移后 v2 vault 状态？ | ✅ **冻结**；迁移器不写 v2，验收通过后由项目所有者单独标记并保留备份 | 文档 + 流程（无代码） | 人工确认 + 源 hash 不变 |
| **D8** | 增量同步 vs 单次迁移？ | ✅ **单次全量迁移**；由 run-id 管理，支持 checkpoint/resume/精确 rollback，后续新素材走 ruflo-kb 原生流程 | T0/T8/T10 | manifest 闭包 + 故障演练通过 |
| **D9a** | **v2 概念卡的 `type` 字段映射（Plan-Audit Round 1 综合报告 ①-2 新增）** | ✅ `type: concept` 落 `wiki/concepts/`；视频回溯走 `_ko_extra.video_id`；body 顶部插入 `<!-- capture-type: video-transcript -->` | T1 frontmatter 转换器 | 抽样 50 张概念卡 → type、capture_type、marker 均 100% |

### D9a 决策详情（Plan-Audit Round 1 综合报告 ①-2 修复）

**问题背景**：`src/services/capture.py:118-122` `_TYPE_MAP` 写死 `video-transcript → source`，与 v2 的 `concepts/*.md` 路径硬冲突。

**D9a vs D9b 对比**：

| 维度 | D9a（已选定）| D9b（备选）|
|---|---|---|
| `type` 字段 | `concept` | `source` |
| 落盘目录 | `wiki/concepts/` | `wiki/sources/` |
| capture 子类型语义 | 仅 body marker（`<!-- capture-type: video-transcript -->`）| 完整 capture video-transcript 语义 |
| video 回溯通道 | `_ko_extra.video_id` | `sources[0]` URL |
| 与 v2 文件位置一致 | ✅ 是 | ❌ 否（迁移后位置改变） |
| 与 novel-wiki 一致性 | ✅ 是（同样用 concept）| ⚠️ 引入新路径 |
| WebUI "按捕获类型筛选" | ✅ 通过 marker 实现 | ✅ 通过 type 实现 |
| WebUI "source 视图" 内容 | ❌ 看不到 v2 内容 | ✅ 看到 |

**为什么选 D9a**：
1. v2 文件名就是 `concepts/*.md`，保持路径一致降低迁移风险
2. 5 重视频 ID 追溯链路已设计，`_ko_extra.video_id` 是通道 4，独立于 type
3. capture marker 仍可注入，WebUI 筛选功能不受影响
4. 与 novel-wiki 的 `concept` 类型保持一致（v2 → ruflo-kb 都用 concept）

**D9a 实施细节**：
- T1 frontmatter 转换器设置 `page.type = PageType.CONCEPT`
- T1 同步在 `page.body` 顶部插入 `<!-- capture-type: video-transcript -->\n\n`（如果 v2 body 不含此 marker）
- T1 同步设置 `page.capture_type = "video-transcript"`（V6 schema 字段）
- 验收 §D2：概念卡 100% 在 `wiki/concepts/`；type = concept；body 顶部含 capture marker

### 决策落地对照表

| 决策 | 涉及模块 | 关键约束 |
|---|---|---|
| D1 | `src/wiki/migrate/v2_pending.py` | main 版本胜出；pending 版本路径含 `_to_recompile/` 来源标识；写 `pending_decisions.csv` 报告 |
| D2 | `src/wiki/migrate/v2_raw.py` | `10_raw/_archive/X.*` → `raw/_archive/X.*`（保留目录结构）；SHA-256 校验必须一致 |
| D3 | `src/wiki/migrate/v2_frontmatter.py` | V6 canonical 字段写顶层，其余字段按字段映射表进 `_ko_extra`；写入顶层 `v2_origin: true` |
| D4 | `src/wiki/migrate/v2_raw.py` | 默认不加平台前缀；`--add-platform-prefix` flag 仅在用户显式开启时启用 |
| D5 | `src/wiki/migrate/v2_aliases.py` | 仅 entity 卡处理 aliases；canonical = file stem；**正向格式** `{alias: canonical}` 写入 `.llm-wiki/slug_aliases.json`（修正自 ②-1 重大隐患）|
| D6 | `src/wiki/migrate/v2_quarantine.py` | invalid_*.md 全字段保留；写入 `.index/quarantine/<slug>.md` + `judgments.jsonl` |
| D7 | 文档层（非代码） | 验收通过后由项目所有者单独追加 v2 Changelog 条目；迁移器不写 v2 |
| D8 | `src/wiki/migrate/v2_full.py` + `v2_manifest.py` + `v2_run_state.py` + `scripts/run_v2_migration.sh` | run-id 管理 raw + wiki + quarantine + aliases + snapshot；支持 resume，promotion 前失败不触碰 live target |
| **D9a** | `src/wiki/migrate/v2_frontmatter.py` + capture marker 注入 | `type = PageType.CONCEPT`；body 顶部插入 `<!-- capture-type: video-transcript -->`；设置 `capture_type = "video-transcript"` |

---

## 13. 附录 A：v2 卡片样本（已收录于本报告，便于对照）

### 样本 1：标准概念卡（`20_wiki/concepts/BV113411K7tu.md`）

```yaml
---
title: 网文萌新如何建立"读者马甲"自审作品
version: v2.1
tags: [网文创作, 读者视角, 自审方法, 写作技巧]
processing_depth: concept
source_grade: A
platform: B站
url: https://www.bilibili.com/video/BV113411K7tu
author: N/A
category: 内容创作
use_context: build
maturity: A级-可借鉴
taxonomy_sub: 写作技巧
created: 2026-06-18
updated: 2026-06-18
summary: ...
type: concept
---
```

### 样本 2：实体卡（`20_wiki/entities/Claude Code.md`）

```yaml
---
title: Claude Code
type: entity
version: v2.1
created: 2026-06-25
updated: 2026-06-25
tags: [工具, AI编程, Anthropic]
aliases: [claude-code, claude_code, ClaudeCode]   # ← 关键
instance_of: 工具                                  # ← 关键
maturity: A级-可借鉴
---
```

### 样本 3：无效素材记录（`20_wiki/invalid_BV1tdPDzQEpa.md`）

```yaml
---
uid: 20260403-D2A1
title: （无效素材）BV1tdPDzQEpa
bv: BV1tdPDzQEpa
source: 10_raw/01_B站视频转录/BV1tdPDzQEpa.md
url: https://www.bilibili.com/video/BV1tdPDzQEpa
uploader: AI靓匠
video_published_at: '2026-03-09'
created: 2026-06-17
updated: 2026-06-17
classification: internal
status: done
category: 绱犳潗
maturity: C级-跳过
taxonomy_sub: AI工具
version: v2.1
tags: [AI工具, API]
processing_depth: concept
source_grade: C
platform: B站
invalid_reason: content_too_sparse
---
```

---

## 14. 附录 B：关键 ruflo-kb 引用清单

| 用途 | 文件 | 备注 |
|---|---|---|
| 数据模型 | `src/wiki/core/types.py` | WikiPage dataclass + V5 strict 8-key |
| 写入器 | `src/wiki/storage/page_writer.py` | `write_page(paths, page)` + V5 严格白名单 |
| 读取器 | 同上 | `read_page(path)` 容忍 legacy 字段 |
| wikilink | `src/wiki/features/wikilink.py` | `extract_wikilinks` / `resolve_wikilink` |
| slug 别名 | `src/wiki/features/slug_aliases.py` | `SlugAliasRegistry` |
| relations | `src/wiki/features/relations.py` | `Relation.from_dict` 自动 slugify |
| 标签校验 | `src/wiki/features/tag_namespace.py` | `validate_tag_compliance` |
| 健康度 | `src/wiki/features/lint.py` + `health_check.py` | 10 项检查 |
| 项目入口 | `src/cli.py` → `python -m src.cli project init/import` | 仅注册，不转换 |

---

## 15. 目标项目实例（已确认 · 2026-09-06）

| 字段 | 值 |
|---|---|
| **实例名** | `video-notes-wiki` |
| **项目 UUID** | `e3a0472c-06af-41e4-8d06-083146f195f7` |
| **项目路径** | `D:\5-Project\20260903\llm-wiki-base\knowledge\video-notes-wiki` |
| **schema 版本** | v2.0 |
| **创建时间** | 2026-09-06 22:49:01 UTC+8 |
| **选用模板** | `capture`（快速单鉴库） |
| **与 novel-wiki 关系** | 完全独立（独立 .index/ / 独立 .llm-wiki/ / 独立 wiki/） |

### capture 模板与 v2 的天然匹配

| capture 子类型 | 适用 v2 内容 | v2 frontmatter 字段映射 |
|---|---|---|
| `video-transcript` | **B 站 + 抖音 + 小红书视频转录** | platform / url / author / created → 来源元数据 |
| `article` | 文章类摘录 | 同上 |
| `inspiration` | C 级碎片 + _seed | summary + 散点想法 |

### capture 模板预置文件（已存在）

```
knowledge/video-notes-wiki/
├── schema.md                                  # source/entity/concept/synthesis 4 种类型
├── purpose.md                                 # "随想随记"快速单鉴库定位
├── .wiki-templates/
│   ├── video-transcript.md                    # ← 主要目标模板
│   ├── article.md                             # ← 文章类
│   └── inspiration.md                         # ← 碎片/灵感
├── .llm-wiki/project.json                     # { id, name, schema_version, created_at }
├── .index/                                    # lancedb / reviews / staging
├── raw/sources/                               # v2 raw 文件目标位置
└── wiki/
    ├── sources/  entities/  concepts/  synthesis/  claims/  decisions/  _stubs/
    ├── index.md                                # 卡片目录（自动生成）
    └── log.md                                  # 审计日志（自动生成）
```

### 关键决策点已确认

- **D3**（v2 字段 → V6 顶层 + `_ko_extra`）：按字段映射表保留 v2 全部业务字段；同时注入 `capture_type` 和 `<!-- capture-type: video-transcript -->` marker，便于后续筛选

---

## 16. 「平台 + 视频 ID」追溯设计（关键 · 2026-09-06 用户决策）

**用户反馈**："这些大部分都是抖音，B站，小红书视频转录文件，需要保留视频ID作为追溯原视频"

### 设计要点

v2 的卡片命名已经天然承载平台 + 视频 ID：

| 平台 | v2 文件名模式 | 平台标识 | 视频 ID 形态 | 原视频追溯 URL |
|---|---|---|---|---|
| **B 站** | `BV1AtwLzTEtB.txt` | `BV` 前缀 | `BV + 10-12 位 base58 | https://www.bilibili.com/video/BV1AtwLzTEtB |
| **抖音** | `7512800963258797321.md` | 19 位数字 | 19 位十进制 ID | https://www.douyin.com/video/7512800963258797321 |
| **小红书** | 笔记 ID 或 CJK 标题 | 24 位 hex 或中文 | 不规则 | https://www.xiaohongshu.com/explore/<id> |

### 保留方案（5 重追溯通道）

迁移后每张卡的追溯链路：

1. **文件名 / WikiPage.id**：`BV1AtwLzTEtB` / `7512800963258797321` / `Nano-Banana-Pro-...`
2. **frontmatter.sources[0]**：`https://www.bilibili.com/video/BV1AtwLzTEtB`（原始 URL）
3. **frontmatter.platform**：`B站` / `抖音` / `小红书`
4. **frontmatter._ko_extra.bv**（仅 B 站）：`BV1AtwLzTEetB`
5. **frontmatter._ko_extra.video_id**：原始平台视频 ID（去前缀或原值）
6. **raw/sources/ 同名文件**：转录稿正文（用于二次校验内容）

### 增强映射表（迁移器 T1 输出）

```python
# 由 v2 frontmatter 推导 URL 模板
URL_TEMPLATES = {
    "B站":    "https://www.bilibili.com/video/{bv}",
    "抖音":   "https://www.douyin.com/video/{video_id}",
    "小红书": "https://www.xiaohongshu.com/explore/{note_id}",
}

# video_id 提取逻辑
def extract_video_id(file_stem: str, frontmatter: dict) -> str:
    """从文件名或 frontmatter 提取原始视频 ID"""
    if frontmatter.get("bv"):           # B 站优先
        return frontmatter["bv"]
    if frontmatter.get("url"):
        # 从 URL 末段提取
        ...
    if file_stem.startswith("BV"):
        return file_stem                # B 站文件名 = 视频 ID
    if file_stem.isdigit():
        return file_stem                # 抖音/小红书纯数字 ID
    return ""  # CJK 标题（无法直接追溯，需用户手动补 URL）
```

### 模板字段固化建议（写入 capture/video-transcript.md 槽位）

```
## 来源元数据
<!-- slot:source_meta -->
- 平台：B站
- UP主：{{author}}
- BV 号：{{bv}}
- 原视频 URL：{{url}}
- 发布日期：{{video_published_at}}
- 获取日期：{{fetched_at}}
- 平台视频 ID：{{video_id}}
- raw 转录文件路径：{{raw_path}}
```

> **注意**：CJK 标题文件（如 `Nano-Banana-Pro-Gemini3分镜控制.md`）**无法自动追溯原视频**——这是 v2 自身的数据损失。迁移器对这类卡：
> - 写入 `_ko_extra.v2_url = "MISSING"` + `_ko_extra._v2_needs_manual_url_review = true`
> - WebUI / 健康度检查时显示 ⚠️ 待补 URL 标记

---

## 17. 下一步

1. ✅ ~~用户拍板 §12 的 D1-D9a 决策点~~ **已完成（2026-09-10，审计整改版）**
2. ✅ ~~撰写最终实施方案~~ **已完成** `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md`
3. ✅ ~~撰写验收清单~~ **已完成** `docs/migration/2026-09-06-v2-acceptance.md`
4. ✅ ~~执行 plan-audit Round 1 漏洞审计~~ **已完成（2026-09-06）** — 19 个问题（3 致命 + 7 重大 + 9 优化）；详见 `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration-audit-r1.md`
5. ✅ ~~方案路径拍板~~ **已完成（2026-09-06）** — 用户选 **路径 X（V6 扩展）**；详见 ADR-0008
6. 🔲 **ADR-0008 PR review + 接受**（V6 schema 字段 + tag 命名空间 + migration tools）
7. 🔲 **Plan-Audit Round 1 整改后复审**（独立 subagent 再跑一次漏洞审计，确认致命/重大问题修复）
8. 🔲 **Plan-Audit Round 2 压力测试推演**
9. 🔲 **人工复核 + 最终拍板**
10. 🔲 Phase 0 PoC（手选 5 张样本卡 + dry-run）
11. 🔲 Phase 1-4 TDD 实施

---

## 18. V6 Schema 扩展决策（ADR-0008 · 2026-09-06 用户确认）

> **完整决策记录**：`docs/adr/0008-v6-wiki-schema-extension-for-v2-migration.md`
> **选择路径**：路径 X（V6 扩展），**非**路径 Y（手写 frontmatter）/ Z（接受字段丢失）
> **目标**：修复 Plan-Audit Round 1 致命缺陷 ①-1（`_ko_extra` 不持久化）+ ①-2（v2 tag 不兼容）

### V6 schema 新增 9 字段

WikiPage dataclass 加 9 字段（5 已有内存字段升级为写盘 + 4 新字段）：

| 字段 | 类型 | 默认 | 来源 v2 | 备注 |
|---|---|---|---|---|
| `processing_depth` | str | `"concept"` | v2 同名 | 已内存，**V6 写盘** |
| `source_grade` | str | `"B"` | v2 同名 | 已内存，**V6 写盘** |
| `platform` | str | `""` | v2 同名 | V6 新增 |
| `category` | str | `""` | v2 同名 | 已内存，**V6 写盘** |
| `taxonomy_sub` | str | `""` | v2 同名 | 已内存，**V6 写盘** |
| `use_context` | str | `""` | v3.5 新增 | V6 新增 |
| `workflow_state` | str | `"draft"` | v3.5 新增 | 已内存，**V6 写盘** |
| `capture_type` | str | `""` | capture 模板子类型 | V6 新增（`video-transcript` / `article` / `inspiration`） |
| `v2_origin` | bool | `False` | 迁移标记 | V6 新增 |

### V6 tag 命名空间扩展

`tag_namespace.py` 加 5 个新前缀（受控）：

| 前缀 | 含义 | 用途 |
|---|---|---|
| `tool/` | 工具 | v2 既有命名空间（如 `tool/python`） |
| `scene/` | 业务场景 | v2 既有命名空间 |
| `status/` | 生命周期 | v2 既有命名空间 |
| `media/` | 媒体类型 | V6 新增（`media/视频` / `media/文章` / `media/灵感`） |
| `author/` | 作者/UP主 | V6 新增（仅 entity 卡） |

### V6 mandatory pair 调整

**V5 硬性强制**：`MANDATORY_PAIRS = [("素材", "ugc"), ("可信度", "ugc")]` —— 所有有 tag 的卡必须有这对

**V6 条件强制**：
```python
def validate_tag_compliance(tags, *, page_type=None, platform=None):
    # 仅当 page_type == "source" 且 platform in {"B站", "抖音", "小红书"} 时
    # 才强制 素材/ugc + 可信度/ugc
    # 其他情况（如 entity / concept）不强制
```

### V6 Migration Tools（拆分 3 PR）

| PR | 内容 | 工作量 | 阻塞 |
|---|---|---|---|
| PR 1 | WikiPage dataclass 9 字段 + `to_frontmatter_dict` 17-key + `from_dict` 兼容 V5 | 1-2 天 | 无 |
| PR 2 | `tag_namespace.py` 加 5 前缀 + `validate_tag_compliance` 条件化 | 1 天 | 无（PR 1 之后） |
| PR 3 | `src/wiki/migrate/v2_*.py` + `src/cli_ext/migrate_v2_cmd.py` + `scripts/rebuild_vectors.py` | 5-6 天 | PR 1+2 之后 |

### V6 Backward Compatibility

- novel-wiki 现有 1924 张卡的 8-key V5 frontmatter **继续可读**（`from_dict` 缺字段填默认）
- 写盘时 V6 字段缺失则填默认值；旧 V5 字段语义保持一致，允许 YAML 文本因新增默认字段而变化
- `_ko_extra` 逃生口保留 → 字段进一步扩展仍有路径
- 已有 novel-wiki 不受影响（V6 新字段默认空）

### 整改工作量

- 整改 P0：PR 1（V6 schema）+ PR 2（tag 命名空间） ≈ 2-3 天
- 整改 P1：PR 3（migration tools） ≈ 5-6 天
- 整合 + PoC：2 天
- **总计**：~10 天

---

**调研完成 · 待审计 · 待决策**
