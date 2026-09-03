# ADR-002: Wiki 字段理想态终态（V4 · 8 键 · accepted）

Status: accepted (supersedes 2026-08-31 V3 16-key version)

Date: 2026-08-31 (revised)

## Context

整改方案 [wiki-fields-remediation-plan-2026-08-31.md](../evaluations/wiki-fields-remediation-plan-2026-08-31.md)
完成 T0-T5 第一阶段收敛后，多视角评审
[wiki-fields-template-multiview-review-2026-08-31.md](../evaluations/wiki-fields-template-multiview-review-2026-08-31.md)
指出 V3 16 键方案有 4 项问题：

1. **基于错误数据假设**：5 个 V3 新增字段（`confidence`/`provenance`/`versions`/`lifecycle`/`lock_until`）
   在 novel-wiki **0% 填充**——从未在生产中使用
2. **KO 镜像过重**：9 字段强同步 KO（`id`/`title`/`confidence`/`provenance`/`relations`/`sources`/`versions`/`lifecycle`），
   与"wiki 不成为第二事实源"原则有冲突（事实上这 9 字段就是第二事实源）
3. **死字段未清理**：现状 19 字段中 5 个（`heat`/`is_immutable`/`last_used_at`/`zombie_since`/`related_entities`）
   **100% 取固定值**——属于"未运行逻辑的占位符"
4. **编辑守卫机制未运行**：`is_immutable`/`lock_until` 在 novel-wiki 永远是 false/null——删除

用户 2026-08-31 决策：**"不考虑成本和迁移问题，旧的 wiki 都会删掉"**
+ **"不考虑成本，删除掉所有wiki不考虑与旧wiki兼容问题"**

→ ADR-002 简化为单一理想态：**V4 = 8 键严格白名单**。

## Decision

采用 **V4 8 键严格白名单**作为 novel-wiki 的唯一终态：

| # | 字段 | 类型 | 必填 | 业务语义 |
|---|---|---|---|---|
| 1 | `id` | str | ✅ | 文件系统唯一键 |
| 2 | `title` | str | ✅ | 人类可读标题 |
| 3 | `type` | enum | ✅ | `source` \| `entity` \| `concept` \| `synthesis` |
| 4 | `relations` | list | ✅ | 知识图谱边（21 类型 + x-*）|
| 5 | `tags` | list | ✅ | 业务轻量标签 |
| 6 | `sources` | list | ✅ | 原始来源路径 |
| 7 | `created_at` | datetime (ISO 8601) | ✅ | 物理创建时间（V5；旧页 ms int 兼容）|
| 8 | `updated_at` | datetime (ISO 8601) | ✅ | 物理更新时间（V5；旧页 ms int 兼容）|

**字段集外（11 项全部删除）**：

| 字段 | 删除理由 |
|---|---|
| `slug` | 路径派生，不存 frontmatter |
| `grade` | 网文素材不需要 A/B/C 评级 |
| `category` / `taxonomy_sub` | 用 `relations[taxonomy_of]` 替代 |
| `processing_depth` / `custom_type` | schema 子类型机制未启用 |
| `workflow_state` / `verified_at` | wiki 不存治理状态 |
| `heat` / `last_used_at` / `zombie_since` | 热度系统未运行，永远是固定值 |
| `is_immutable` | 编辑守卫未启用，永远是 false |
| `related_entities` | KO 模型字段未启用，永远是 [] |
| `_ko_extra` | KO 镜像通道废弃 |
| `confidence` / `provenance` / `versions` / `lifecycle` / `lock_until` | V3 提议字段，从未在 novel-wiki 使用 |

## V4 迁移实施

### 工具

- `scripts/validate_novel_wiki_frontmatter.py` — 严格白名单验证（V4 = 8 keys only）
- `scripts/migrate_novel_wiki_to_v4.py` — 一键迁移脚本
  - 用 `yaml.safe_load()` 替代手写 YAML 解析（解决 V3-slim 迁移脚本的 multi-line list bug）
  - round-trip 验证：迁移前后 relations+tags 总数对比，防止数据丢失
  - atomic write：单页面失败不影响其他

### 实际迁移结果（2026-08-31）

| 指标 | 数量 |
|---|---|
| 总页数 | 4892 |
| skipped（已是 V4 格式） | 3145 |
| migrated（v2.2 → V4） | 1747 |
| rejected（round-trip 数据丢失） | 0 |
| errors | 0 |

**字段转换统计**：
- `category` → `relations[taxonomy_of]`：3095 处
- `tags[X/Y]` → `relations[Y, type=...]`：4884 处
- 死字段删除：1747 页 × 13 字段 = 22711 字段删除

### 验证

```
$ python scripts/validate_novel_wiki_frontmatter.py
[validate-v4] scanned=4892
[validate-v4] P0=0  ← 全量通过 V4 严格白名单
```

## Invariants

- **Wiki 是知识存储，不是治理系统**：治理走外部流程（workflow_state 已删除）
- **8 字段严格白名单**：CI 拒绝任何非白名单字段
- **slug 从不存 frontmatter**：从 `<type_dir>/<id>` 派生（无运行时计算成本）
- **round-trip 数据完整性**：迁移/写入路径必须保证 relations+tags 总数不减少
- **frontmatter 必须有合法闭合符**：写入路径禁止 `---` 与上一行黏在一起
- **type 仅 4 选 1**：不允许第 5 类型（claim 已迁移到 source）
- **relations 仅命名空间化 target**：`taxonomy_of`/`belongs_to_audience`/`hosted_on_platform`/`has_credibility` 必须带前缀

## Rejected alternatives

### A. V3 16 键方案（已弃用，见 [wiki-fields-template-2026-08-31.deprecated.md](../architecture/wiki-fields-template-2026-08-31.deprecated.md)）

- 问题：5 字段从未使用（`confidence/provenance/versions/lifecycle/lock_until`）
- 问题：5 字段是死字段（`heat/is_immutable/last_used_at/zombie_since/related_entities`）
- 决策：**改为 V4 8 键**

### B. V3-slim 14 键方案（过渡，已被 V4 替代）

- 思路：保留 5 个死字段（"暂缓执行"）+ 删 5 个 V3 提议字段
- 问题：死字段保留意味着 WikiPage 模型继续背负未运行逻辑
- 决策：**全部删除**

### D. WikiPage 进一步收敛到 < 8 字段（如 4 字段）

- 思路：只保留 `id/title/type/body`
- 风险：丢失 relations（16728 条边）+ sources（100% 页面有）+ tags（4846 页有真实内容）
- 决策：**保留 8 字段**

### E. KO 完全持有所有元数据，Wiki 仅 body

- 思路：frontmatter 只剩 body，KO 持有 relations/sources/tags
- 风险：编辑器失去元信息可见性；wikilink 解析失去 relation 数据
- 决策：**保留 frontmatter 但只存知识图谱必需字段**

## Implementation timeline

| 步骤 | 完成 |
|---|---|
| V4 文档（8 键严格白名单） | ✅ 2026-08-31 |
| V4 验证脚本（strict mode） | ✅ 2026-08-31 |
| V4 迁移脚本（round-trip 安全） | ✅ 2026-08-31 |
| 全量迁移（4892 页） | ✅ 2026-08-31（1747 migrated, 0 rejected）|
| KO 写入路径改造（WT-1~WT-6） | ⏸️ 待实施（见 [wiki-fields-ideal-state-2026-08-31.md](../architecture/wiki-fields-ideal-state-2026-08-31.md)） |

## References

- ADR-001：Knowledge Compiler migration（基础决策）
- [wiki-fields-ideal-state-2026-08-31.md](../architecture/wiki-fields-ideal-state-2026-08-31.md)：理想态实施指引
- [novel-wiki-fields-template-2026-08-31.md](../architecture/novel-wiki-fields-template-2026-08-31.md)：V4 模板（8 键）
- [wiki-fields-template-2026-08-31.deprecated.md](../architecture/wiki-fields-template-2026-08-31.deprecated.md)：V3 原模板（已弃用）
- [wiki-fields-remediation-plan-2026-08-31.md](../evaluations/wiki-fields-remediation-plan-2026-08-31.md)：原 T0-T5 计划
- [wiki-fields-template-multiview-review-2026-08-31.md](../evaluations/wiki-fields-template-multiview-review-2026-08-31.md)：多视角评审