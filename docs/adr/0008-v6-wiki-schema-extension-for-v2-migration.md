# ADR-0008: Wiki Schema V6 Extension for v2 (LLM_Knowledge_base_v2) Migration

- **状态**: proposed
- **日期**: 2026-09-06
- **触发**: v2 数据迁移需要保留 v2 业务字段，但 V5 严格 8-key 白名单不写 `_ko_extra`
- **关联**: `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md`、`docs/architecture/v2-to-v6-field-mapping.md`、`docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration-audit-r1.md`、`docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration-audit-r1-comprehensive.md`

## D9a 决策（Plan-Audit Round 1 综合报告 ①-2 修复）

**v2 概念卡的 `type` 字段映射**：`type: concept`（落 `wiki/concepts/`），视频回溯走 `_ko_extra.video_id`，body 顶部插入 `<!-- capture-type: video-transcript -->` 作为筛选标记。

详细对比见调研报告 §12 + 实施方案 T1。

## Context（背景）

LLM_Knowledge_base_v2 项目（位于 `D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\`）按 2026-09-09 清单包含 1919 张 concepts、155 张 pending、5 张 entities、1 张 quarantine、2397 个主要 raw、5 个 `.batch` 元数据、637 个 archive、16 个 skip、1 个 seed 和 2 个 support 文件。迁移目标项目 `video-notes-wiki`（UUID `e3a0472c-06af-41e4-8d06-083146f195f7`，capture 模板）已创建。

v2 的 frontmatter 有 13 项必填字段（v2.1 spec）：`title / version / tags / processing_depth / source_grade / platform / url / author / category / maturity / taxonomy_sub / created / updated`，外加 v3.5 新增的 `use_context / workflow_state / summary / type / aliases / instance_of` 等可选字段。

ruflo-kb 当前 V5（ADR-002 + `wiki-fields-template-2026-08-31.md`）严格 8-key 白名单：
- `id / title / type / relations / tags / sources / created_at / updated_at`
- 写入磁盘时只输出这 8 个字段（`src/wiki/core/types.py:194-224` `to_frontmatter_dict()`）
- 其余字段（`grade / processing_depth / heat / workflow_state / category / taxonomy_sub / _ko_extra / ...`）仅存在内存 dataclass 上

**冲突点**（plan-audit Round 1 致命缺陷 ①-1）：
- v2 业务字段（processing_depth / source_grade / use_context / workflow_state / platform / category / taxonomy_sub / maturity / version / summary / aliases / instance_of）共 12+ 项
- 这些字段在 v2 是 frontmatter 一部分，必须保留（用户的 5 重视频 ID 追溯需求依赖 platform / url / bv）
- V5 不写 `_ko_extra` → T1 转换器无法用 V5 round-trip 保留字段
- 验收清单 B2「每张抽样卡的 _ko_extra 字段全部保留」必失败

**附加冲突**（plan-audit Round 1 致命缺陷 ①-2）：
- ruflo-kb 的 `tag_namespace.py:18-31` `TAG_PREFIXES` 是中文前缀（题材/功能/角色/...），要求 `prefix/value` 格式
- `tag_namespace.py:86-89` `MANDATORY_PAIRS = [("素材", "ugc"), ("可信度", "ugc")]` 强制所有有 tag 的卡必须含这对
- v2 的 tag 是 free-form CJK 文本（`网文创作`、`读者视角`、`自审方法`、`写作技巧`、`AI编程`、`tool/python`...），不符合 `prefix/value` 格式 → `validate_tag_compliance` raise TagValidationError
- T1 写第一张卡就中断

## Decision（决策）

> **D1-D9a 决策记录**：`docs/research/2026-09-06-v2-to-ruflo-migration-survey.md` §12
> **D9a 决策**（Round 1 综合报告新增）：v2 概念卡 `type: concept` 落 `wiki/concepts/`，视频回溯走 `_ko_extra.video_id`，body 顶部插入 capture marker

### V6 Schema 扩展（ruflo-kb 主线修改）

**D1**：WikiPage dataclass 加 5 个 V6 字段（v2 业务字段 + capture 子类型）：

| 字段 | 类型 | 默认 | 来源 v2 | 备注 |
|---|---|---|---|---|
| `processing_depth` | str | `"concept"` | v2 同名 | 已在内存，**V6 起写盘** |
| `source_grade` | str | `"B"` | v2 同名 | 已在内存，**V6 起写盘** |
| `platform` | str | `""` | v2 同名 | V6 新增 |
| `category` | str | `""` | v2 同名 | 已在内存，**V6 起写盘** |
| `taxonomy_sub` | str | `""` | v2 同名 | 已在内存，**V6 起写盘** |
| `use_context` | str | `""` | v3.5 新增 | V6 新增 |
| `workflow_state` | str | `"draft"` | v3.5 新增 | 已在内存，**V6 起写盘** |
| `capture_type` | str | `""` | capture 模板子类型 | V6 新增（`video-transcript` / `article` / `inspiration`） |
| `v2_origin` | bool | `False` | 迁移标记 | V6 新增（`True` 表示从 v2 迁入） |

> `maturity` / `url` / `author` / `summary` / `aliases` / `instance_of` 等其他 v2 字段**继续走 `_ko_extra` 逃生口**（保留既有行为，不强制升级）。

**D2**：`WikiPage.to_frontmatter_dict()` 改为输出 **V6 完整白名单**（8-key + 9 字段 = 17-key）。

**D3**：`WikiPage.from_dict()` 容忍 V5/V6 两种格式（V5 缺字段时填默认值），保证向后兼容；验收采用字段语义一致，不要求 V6 写盘后的 YAML 字节级一致。

**D4**：保留 `_ko_extra` 逃生口继续工作（schema-routing 的 round-trip 不变）。

### V6 Tag Namespace 扩展（ruflo-kb 主线修改）

**D5**：`tag_namespace.py:18-31` `TAG_PREFIXES` 加入 v2 既有 CJK free-form 前缀（受控）：

| 前缀 | 含义 | 是否受控 |
|---|---|---|
| `tool/` | 工具（保留 v2 既有命名） | 受控（保留现有 TOOL_TAGS 集合） |
| `scene/` | 业务场景 | 受控 |
| `status/` | 生命周期 | 受控 |
| `media/` | 媒体类型（B站/抖音/小红书...） | V6 新增，受控 |
| `author/` | 作者/UP主（仅 entity 卡） | V6 新增，受控 |

**D6**：`MANDATORY_PAIRS` 调整：
- 删除硬性 `("素材", "ugc")` 强制要求
- 改为**条件强制**：仅当 page.type == `source` 且 platform 是 video 类时，要求 `素材/ugc` + `可信度/ugc`
- 具体逻辑：`validate_tag_compliance(tags, *, page_type=None, platform=None)` 增加可选参数

**D7**：v2 自由文本 tag 自动归一化（不改原值，仅在迁移期）：
- T1 转换器识别 v2 free-form CJK tag
- 写盘前通过 `normalize_tags()` 映射到受控 `prefix/value`
- 映射失败保留在 `_ko_extra._v2_legacy_tags` 字段

### V6 Migration Tooling

**D8**：新增正式的 `scripts/rebuild_vectors.py`：
- 只在 staging LanceDB 中调用 `init_vector_store_for_paths(WikiPaths)` + `vector_upsert_chunks`
- 接受 `--project <id> --run-id <id> --resume` 参数
- provider 预检必须实际 embed 一次并记录 dimension；429/5xx 最多重试 5 次并指数退避
- 每 100 张页面写入 checkpoint；校验 chunk manifest 后才原子替换 live table

**D9**：新增 `src/cli_ext/migrate_v2_cmd.py` + `src/wiki/migrate/v2_*.py`：
- 转换器库 + CLI 入口
- 12 个 TDD Task（T0-T10 + T10.0 rebuild_vectors）

### V6 Backward Compatibility

**D10**：
- 已有 novel-wiki 卡的 frontmatter（8-key V5 格式）继续可读
- 写盘时 V6 字段缺失则填默认值（不报错）
- `from_dict()` 对 8-key + 17-key 两种输入都正常解析
- 字段优先级：V6 写盘字段 > V5 内存默认 > None

### 文档同步

**D11**：
- 新增 `docs/architecture/wiki-fields-template-v6.md`（V6 schema 完整定义）
- 更新 `docs/architecture/wiki-fields-template-2026-08-31.md` → 标记 superseded by V6
- 更新 `src/wiki/storage/page_writer.py` 顶部注释
- 更新 `src/wiki/core/types.py` 顶部注释

## Rationale（理由）

为什么选 V6 扩展而非其他路径：

- **路径 X（V6 扩展，本次方案）**：
  - ✅ 保留全部 v2 业务字段，符合用户 5 重视频 ID 追溯诉求
  - ✅ v2 tag 经受控映射保留语义，不丢失信息
  - ✅ 与现有 novel-wiki 等 KB 向后兼容（V5 read 仍可用）
  - ✅ 为后续「多源异构 KB 迁移」铺路（v2 不是唯一外部源）
  - ⚠️ 需要改 ruflo-kb 主线代码 → PR review + 充分测试
  - ⚠️ 增加 dataclass 字段数 → 轻微性能影响（dict copy 略慢）

- **路径 Y（手写 frontmatter）**：能迁但污染 V5 契约（前端/工具读不到 V6 字段），违背 ADR-002 的 8-key 设计
- **路径 Z（接受字段丢失）**：违背用户 5 重追溯需求

### 为什么不延迟 V6 到「迁移后」

- v2 页面**必须**按 `docs/architecture/v2-to-v6-field-mapping.md` 保留 processing_depth / source_grade / platform / url / category / taxonomy_sub / use_context / workflow_state 等字段
- 不在迁移期同步升级 V6，迁移后这 1919 张卡就**永久丢失**这些字段
- novel-wiki 当前 1924 张卡的 `_ko_extra` 字段也已存在（如 `_ko_extra.credibility`），但因为写盘时不写，等于"内存有 / 磁盘无"的假象 → 升级 V6 是为 novel-wiki 也恢复这些字段

### 为什么不引入「外部 metadata 表」而非加字段

- WikiPage 的字段是 core domain 的一部分，不是「可丢弃的 metadata」
- 外部表方案增加 join 开销（每次 read 都要查 metadata 表）
- V6 字段写盘后 WikiPage 的语义自洽 → 任何下游工具都能直接读

## Consequences（后果）

### 正面

- v2 页面完整保留 12+ 业务字段 → B2 验收通过
- v2 free-form tag 经受控映射保留 → 不丢失信息 → ①-2 致命缺陷修复
- novel-wiki 现有卡可通过可选字段填默认值自动迁移到 V6
- V6 schema 是 ruflo-kb 应对「外部 KB 迁移」的通用方案，未来 v3 / Novel-Knowledge-Base 等都可复用
- `_ko_extra` 逃生口保留 → 字段进一步扩展仍有路径

### 负面

- WikiPage dataclass 字段数从 18 → 27（+50%），构造性能轻微下降
- `to_frontmatter_dict()` 输出 dict 从 8-key → 17-key，写盘 yaml 体积增加 ~30%
- tag_namespace.py 增加 5 个新前缀，需要更新 `TAG_PREFIXES` 文档
- 改动 ruflo-kb 主线代码 → 必须 PR review 通过 + 完整测试 + 不破坏 novel-wiki

### 风险与缓解

- **R1**（V6 写盘可能污染 novel-wiki 现有卡）：mitigation — V6 字段缺失时使用默认值，`v2_origin` 默认 False；既有 V5 页面旧字段语义不变，允许新增默认字段导致 YAML 文本变化
- **R2**（`_ko_extra` 在 V6 后失去意义）：mitigation — 保留 `_ko_extra` 逃生口，作为「未知字段」的兜底（不再用于 v2 业务字段，但仍可存其他未识别的字段）
- **R3**（PR review 阻塞）：mitigation — 拆分 PR 为 3 个独立提交（V6 schema 字段 → V6 tag 命名空间 → V6 migration tools），每个独立可测
- **R4**（迁移后回滚成本高）：mitigation — Wiki 文件是 source-of-truth；向量在 staging 中按 run-id/checkpoint 构建，校验后原子替换，可 resume 或回滚
- **R5**（V6 schema 后续若再有 v3 / v4 需求）：mitigation — 评估走 `_ko_extra` 兜底而非再加字段

### Trigger to Revisit（重审触发条件）

- 当 V6 字段数超过 25 个（dataclass 字段过多开始影响可读性）
- 当 novel-wiki 也开始大量需要 V6 字段（说明 V6 已被广泛接受，可考虑升 V7）
- 当外部 KB 迁移场景超过 3 个（应抽象为通用迁移框架）
- 当写盘性能成为瓶颈（V6 dict 复制成为热点）

## Alternatives Considered（备选方案）

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **X. V6 schema 扩展**（本次方案）| 完整保留 v2 字段；novel-wiki 兼容；通用迁移方案 | 改主线；dataclass 字段变多 | ✅ chosen |
| Y. T1 手写 frontmatter | 不改 ruflo-kb；快速 | 污染 V5 契约；下游工具读不到 V6 字段；`_ko_extra` 假数据 | ❌ rejected |
| Z. 接受字段丢失 | 简单 | 违背用户追溯诉求；D3 决策作废 | ❌ rejected |
| W. 引入 sidecar JSON metadata 表 | 不污染 frontmatter | 增加 IO；join 开销；语义不自洽 | ❌ rejected |

## References（参考）

- `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md` — 迁移方案
- `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration-audit-r1.md` — Round 1 审计（19 个问题）
- `docs/architecture/wiki-fields-template-2026-08-31.deprecated.md` — V4 schema（V5 已 deprecated）
- `src/wiki/core/types.py:129-308` — WikiPage dataclass（V5 内存字段已存在）
- `src/wiki/storage/page_writer.py:125-130` — V5 写盘只输出 8-key
- `src/wiki/features/tag_namespace.py:18-89` — V5 tag 前缀 + mandatory pair
- ADR-001/0007 — 现有 ADR 格式参考

## Implementation Notes（实施笔记）

### 拆分策略（3 个独立 PR）

**PR 1: V6 WikiPage dataclass + 写盘字段**
- `src/wiki/core/types.py` 加 9 字段（已存在的 5 个：processing_depth / source_grade / category / taxonomy_sub / workflow_state；新加 4 个：platform / use_context / capture_type / v2_origin）
- `src/wiki/core/types.py` 改 `to_frontmatter_dict()` 输出 17-key
- `src/wiki/core/types.py` 改 `from_dict()` 容忍 V5 格式（缺字段填默认值）
- `src/wiki/storage/page_writer.py` 第 8 行注释更新
- 测试：`tests/test_core/test_types.py` 加 V5 → V6 round-trip 用例

**PR 2: V6 Tag Namespace 扩展**
- `src/wiki/features/tag_namespace.py` 加 `tool/ scene/ status/ media/ author/` 前缀（受控集合从 constants.py 读）
- `validate_tag_compliance(tags, *, page_type=None, platform=None)` 增加可选参数
- 文档同步：`docs/architecture/tag-namespace-v6.md`
- 测试：v2 free-form tag → V6 prefix/value 映射用例

**PR 3: V6 Migration Tools**
- `src/wiki/migrate/__init__.py` + `v2_frontmatter.py` + `v2_wikilinks.py` + `v2_aliases.py` + `v2_quarantine.py` + `v2_raw.py` + `v2_pending.py`
- `src/cli_ext/migrate_v2_cmd.py`
- `scripts/rebuild_vectors.py`（provider 自检 + 全量 upsert）
- 测试：`tests/test_wiki_migrate/` 全套

### Rollback Procedure

- PR 1 回滚：`git revert` + WikiPage 字段删除 + `to_frontmatter_dict()` 恢复 8-key
- PR 2 回滚：删除新增前缀 + `validate_tag_compliance` 恢复硬性 mandatory pair
- PR 3 回滚：删除 migration tools + CLI 子命令
- 数据层：迁移只写 `.staging/<run-id>/`；promotion 前失败删除该 staging。promotion 后必须指定 project UUID + run-id，恢复 promotion 前快照；禁止用无范围递归删除代替 rollback，且不得删除 v2 来源。

### 测试策略

- V5 → V6 round-trip：现有 novel-wiki 页面读 → 写 → 读的 8 个旧字段值保持语义一致；不要求 V6 YAML 字节级一致
- v2 → V6 转换：1919 张卡按 5 种典型形态抽样测试（concept / entity / invalid / _to_recompile / CJK 标题）
- tag 校验：v2 12+ 典型 tag 输入测试（含 free-form / 受控 / 边界情况）
- 向量重建：100 张样本卡 → LanceDB 行数 == 100 → 检索冒烟 5 个关键词

### 工作量

- PR 1：1-2 天（V6 schema 字段）
- PR 2：1 天（tag 命名空间 + 适配）
- PR 3：5-6 天（迁移工具 + 全套测试）
- 整合 + PoC：2 天
- **总计**：~10 天
