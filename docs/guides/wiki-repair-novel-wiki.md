---
rules:
  id:
    pattern: "^[a-z0-9-一-鿿]+$"
  frontmatter:
    required: [title]
---

# novel-wiki Wiki 安全修复方案（V4 兼容）

> 状态：方案稿（待执行）
> 范围：`knowledge/novel-wiki/wiki/`
> Schema：`NOVEL_WIKI_FIELD_SCHEMA_VERSION = "5.0.0"`
> 制定日期：2026-09-03

本方案针对 novel-wiki 实例 Wiki 在 2026-09-03 质检中暴露的 P0/P1 问题，给出一套**安全、可回滚、可审计**的修复流程。修复严格在 V4 8 键白名单内进行，不破坏现有关系图谱，不批量改写正文。

---

## 0. 背景

novel-wiki 当前 Wiki 由 4892 个 Markdown 页面组成，包含：

- 480+ `sources/`
- 900+ `concepts/`
- 300+ `entities/`
- 综合 `synthesis/`（待清点）

质检发现的主要问题：

1. 个别页面存在**重复 Frontmatter**（两个 `---` 区段）
2. 关系 `target` 使用了错误的 slug 或旧版 ID（明确断链）
3. 索引 (`index.md`) 中存在同标题不同 ID 的变体
4. 模板版本混用（`2.0.0` 与 `3.0.0`）
5. 部分 Wikilink 目标可能不存在
6. 来源页转录质量差异大，部分含 ASR/OCR 噪声

这些问题都不会一次性全部修完，按风险等级分四阶段推进。

---

## 1. 总体策略

四阶段治理：

```text
结构体检 → 数据修复 → 内容治理 → 质量门禁
```

原则：

1. **先备份，后修改**：每个修复前生成 `.bak` 副本
2. **先修关系，再修内容**：关系是图谱骨架
3. **先做自动检查，再做人工/LLM 修复**：减少误改
4. **所有修复都必须可审计**：每个文件改动保留 diff
5. **不直接删除重复页面**：优先建立 alias/合并机制
6. **来源页保留原始版本**：新增"清洗版"内容
7. **不破坏 V4 8 键白名单**：CI 严格拒绝其他字段

---

## 2. 阶段一：建立只读体检基线

## 2.1 生成全量统计

先做一次只读扫描，输出基线 JSON 到：

```text
knowledge/novel-wiki/.index/wiki-quality-baseline-YYYYMMDD.json
```

建议统计项：

| 类别 | 字段 |
|---|---|
| 规模 | `total_files`, `source_pages`, `entity_pages`, `concept_pages`, `synthesis_pages` |
| 结构 | `missing_required_fields`, `duplicate_ids`, `duplicate_frontmatter`, `template_versions` |
| 关系 | `broken_relations`, `orphan_pages`, `relation_direction_issues` |
| 链接 | `broken_wikilinks` |
| 索引 | `missing_from_index`, `stale_index_entries` |
| 内容 | `empty_pages`, `short_pages`, `ocr_noise_pages` |

使用仓库自带的 V4 校验脚本作为基线工具：

```bash
python scripts/validate_novel_wiki_frontmatter.py knowledge/novel-wiki/wiki
```

输出保存：

```bash
python scripts/validate_novel_wiki_frontmatter.py knowledge/novel-wiki/wiki \
    > knowledge/novel-wiki/.index/wiki-quality-baseline-20260903.txt
```

## 2.2 页面分层

将所有页面分为四类，决定后续处理路径：

| 类别 | 描述 | 处理方式 |
|---|---|---|
| A | 结构健康 | 不动 |
| B | 可自动修复 | 自动脚本处理 |
| C | 需语义判断 | 进入人工/LLM 队列 |
| D | 保留不动 | 历史归档页 |

判定规则：

```text
A: 8 键齐全 + ID 等于文件名 + 关系全部解析 + 索引存在
B: 重复 Frontmatter / 路径分隔符 / 缺时间戳 / 关系目标有旧 slug / 未入索引
C: 同标题多 ID / 关系方向可疑 / 转录质量低 / 内容明显错误
D: _archive/, _stubs/ 或来自旧批次、且内容明确属于历史快照
```

不允许自动修复器处理 C/D 类页面。

---

## 3. 阶段二：结构与索引优化（自动）

## 3.1 重复 Frontmatter 清理

**已知问题（2026-09-03 已确认）：**

```text
knowledge/novel-wiki/wiki/sources/借鉴素材书籍如何商业化-8111d1-ec21fd6e.md
  第 1-15 行：合法 V4 Frontmatter
  第 16 行：---（多余空分隔符）
  第 17 行：---（重复）
  第 18 行：<!-- wiki-template-version: 3.0.0 -->
```

V4 校验脚本目前**不检测**重复 Frontmatter，需要额外脚本：

```python
# scripts/check_duplicate_frontmatter.py
import re
from pathlib import Path

ROOT = Path("knowledge/novel-wiki/wiki")

for md in ROOT.rglob("*.md"):
    text = md.read_text(encoding="utf-8")
    # 跳过只有一个 --- 的情况
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            rest = text[end + 4:]
            # 检查正文里是否又出现 ---
            if "\n---\n" in rest[:200]:
                print(f"{md.relative_to(ROOT)}")
```

**修复规则：**

- 保留**第一个**完整 YAML 区段
- 删除**第二个空 `---`** 分隔符
- 保留模板注释（`<!-- wiki-template-version ... -->`）
- **不改正文**

修复前模板：

```markdown
---
id: ...
...
sources: [...]
---
---
<!-- wiki-template-version: 3.0.0 -->
...
```

修复后模板：

```markdown
---
id: ...
...
sources: [...]
---
<!-- wiki-template-version: 3.0.0 -->
...
```

## 3.2 时间戳规范化

不要继续混用：

```yaml
created_at: '2026-08-10'   # ISO 日期字符串
created_at: 1787118225775  # Unix ms
```

V4 规范要求 Unix 毫秒时间戳。迁移方案：

```yaml
created_at: 1786952723402
created_at_iso: 2026-08-18T00:00:00Z  # 仅作为补充字段
```

不要新增字段到 V4 8 键白名单之外。`created_at_iso` **不能**写入磁盘，只在内存模型保留。

## 3.3 ID 规范

V4 ID 两种格式：

```text
- kebab-case slug（含 CJK）：如 悬念设置 / shuang-dian
- UUID v7：card_<13hex>_<8hex>_<slug>
```

字符集：

```text
- ASCII a-z, 0-9, 连字符 -
- CJK 基本区 U+4E00–U+9FFF
```

**禁止：**

- 大写 ASCII
- 下划线 `_`
- Latin Extended
- 控制字符
- `[` / `]`

**已知问题：**

```text
小三克堂.contains 旧 target: 1-增强文章悬念之画外音第-1-段-94ef8ce7
实际页面 ID:          1增强文章悬念之画外音第1段-94ef8ce7
差异:
  - 是否带连字符
  - 第 vs 第-
  - 1 段 vs 第-1-段
```

**修复规则：**

- 优先使用 alias 解析，不直接重命名源文件
- 在 `.llm-wiki/slug_aliases.json` 注册旧 ID → canonical ID

```json
{
  "1-增强文章悬念之画外音第-1-段-94ef8ce7": "1增强文章悬念之画外音第1段-94ef8ce7"
}
```

## 3.4 索引双写

当前只有 `index.md`。新增 `index.json` 作为机器校验源：

```json
{
  "pages": [
    {
      "id": "...",
      "title": "...",
      "type": "concept",
      "path": "concepts/xxx.md",
      "status": "active"
    }
  ]
}
```

写入一致性约束：

```text
页面存在
+ Frontmatter 可解析
+ ID 唯一
+ index.md 有条目
+ index.json 有记录
```

缺一项即拒绝写入。

---

## 4. 阶段三：关系和 Wikilink 修复

## 4.1 关系校验器

针对每条边检查：

```text
1. target 是否存在
2. target 是否是合法 ID
3. 当前页面是否真的有该来源
4. source 和 target 类型是否兼容
5. 关系方向是否合理
```

`src/services/quality.py` 中已经存在 LINT 规则，需要扩展：

| 规则 | 检查 |
|---|---|
| `LINT-ILLEGAL-RELATION` | 关系类型不在 21 个内置 |
| `LINT-DANGLING-RELATION`（新增）| target 不存在 |
| `LINT-AMBIGUOUS-RELATION`（新增）| target 有多个候选 |
| `LINT-RELATION-DIRECTION`（新增）| 方向与语义不符 |

## 4.2 兼容层

不立即替换旧 ID。优先用 alias 解析：

```text
1. 精确 ID
2. canonical ID
3. alias
4. title
5. 规范化标题
6. 仍无法确定：标记 AMBIGUOUS
```

维护 `slug_aliases.json`：

```json
{
  "1-增强文章悬念之画外音第-1-段-94ef8ce7": "1增强文章悬念之画外音第1段-94ef8ce7"
}
```

## 4.3 关系方向标准化

V4 内置 21 种关系。方向语义：

| 关系 | 含义 |
|---|---|
| `derived_from` | 当前概念从来源推导（概念 → 来源）|
| `supports` | 当前页面支持目标 |
| `supported_by` | 当前页面由目标支持 |
| `references` | 当前页面引用目标 |
| `contains` | 当前实体包含子页面 |
| `is_part_of` | 当前页面属于目标 |
| `depends_on` | 当前页面依赖目标 |
| `analogous_to` | 页面与目标类似 |
| `taxonomy_of` | 当前页面属于分类 |
| `has_credibility` | 当前页面具有可信度属性 |

校验重点：

- 关系类型符合 schema
- 同义关系不重复
- 反向关系不同时出现
- 无证据关系需标注

## 4.4 断链处理

生成三类报告：

### P0：明确断链

```text
小三克堂.contains
  → 1-增强文章悬念之画外音第-1-段-94ef8ce7
```

自动修复：

```text
→ 1增强文章悬念之画外音第1段-94ef8ce7
```

### P1：可能是旧 ID

使用 alias 解析，不直接删除。

### P2：疑似错误或虚构目标

输出人工确认清单，不自动修复。

---

## 5. 阶段四：内容质量优化

## 5.1 来源页三层结构

```markdown
## 来源元数据

## 清洗后摘要

## 关键观点

<details>
<summary>原始转录内容</summary>

这里是未经纠错的原始文本。

</details>
```

同时满足：

- 证据可追溯
- 内容可读
- 原始材料不丢失

## 5.2 转录质量分级

新增 V4 字段（待审批）：

```yaml
transcription_quality: A
```

分级：

| 等级 | 定义 | 处理 |
|---|---|---|
| A | 人工撰写/高质量整理 | 可直接进入摘要 |
| B | 少量 OCR/ASR 错误 | 自动轻量纠错 |
| C | 明显识别错误 | 只用于检索，不作为正文依据 |
| D | 无法阅读 | 标记不可用，不进入知识抽取 |

**已知 C 级页面：**

```text
knowledge/novel-wiki/wiki/sources/1增强文章悬念之画外音第1段-94ef8ce7.md
  - 大量同音字识别错误
  - 摘要来自转录内容的人工整理
```

## 5.3 概念页模板

```markdown
# 概念名称

## 定义

## 核心特征

## 适用场景

## 不适用场景

## 常见错误

## 例子

## 证据强度

## 参考来源

## 相关概念
```

## 5.4 事实可信度

UGC 经验性内容必须标注：

```markdown
## 可信度声明

本文为 UGC 经验分享。
涉及市场规模、作者收入、行业比例等数字未经独立验证，
不应作为事实数据直接引用。
```

---

## 6. 重复页面治理

| 情况 | 处理 |
|---|---|
| 标题相同、正文高度相同 | 合并 |
| 标题相同、来源不同 | 保留多来源，合并正文 |
| 标题相近、概念相同 | 建立 alias |
| 标题相近但内容不同 | 保留，分别增加 disambiguation |
| 同名人物/作品 | 按作品、作者、时间区分 |

合并后不要直接删除旧页面。生成 supersede 标记：

```yaml
superseded_by: <canonical-id>
status: superseded
```

---

## 7. 质量门禁

## 7.1 结构门禁

```text
合法 Frontmatter
id 唯一
title 非空
type ∈ {source, entity, concept, synthesis}
created_at / updated_at 存在
body 非空
仅含 V4 8 键白名单字段
```

## 7.2 关系门禁

```text
所有 relation target 存在
无 dangling relation
关系类型合法
关系方向通过规则校验
```

## 7.3 索引门禁

```text
所有有效页面进入 index.md
所有索引条目都能找到文件
index.json 与 index.md 一致
```

## 7.4 内容门禁

```text
摘要非空
来源非空
概念页有定义
实体页有简介
低质量转录有质量声明
关键观点不能明显超出来源
```

---

## 8. 建议的 CLI/工具能力

新增 Wiki 质量检查命令：

```bash
python -m src.cli wiki-quality \
  --project novel-wiki \
  --check all
```

子命令：

```bash
python -m src.cli wiki-quality --check structure
python -m src.cli wiki-quality --check relations
python -m src.cli wiki-quality --check links
python -m src.cli wiki-quality --check index
python -m src.cli wiki-quality --check content
```

输出：

```text
STRUCTURE:
  [OK] 4,890 pages have valid frontmatter
  [WARN] 2 pages contain duplicate frontmatter

RELATIONS:
  [OK] 8,234 relation targets resolved
  [ERROR] 1 dangling relation in entities/小三克堂.md

INDEX:
  [OK] all pages indexed

CONTENT:
  [WARN] 47 low-quality transcription pages
```

支持：

```bash
--json-out <path>
--fail-on error
--fix-auto
--dry-run
```

---

## 9. 实施顺序与验收标准

## 9.1 第一批：只修结构风险

目标：

- 清掉所有重复 Frontmatter
- 修掉明确断链
- 补齐缺失时间戳
- 输出质量基线报告

验收：

```text
duplicate_frontmatter = 0
known_broken_relations = 0
index_mismatch = 0
```

## 9.2 第二批：统一关系模型

目标：

- 解析所有 target
- 增加 alias
- 检查关系方向
- 移除重复关系
- 生成关系拓扑报告

验收：

```text
dangling_relations = 0
invalid_relation_types = 0
orphan_active_pages = 0 或有明确原因
```

## 9.3 第三批：治理转录内容

目标：

- 标记转录质量
- 增加质量声明
- 分离原始转录和清洗内容
- 对摘要和关键观点做来源回链

验收：

```text
低质量转录页面 100% 有 quality 声明
关键观点 100% 有来源页或来源片段
```

## 9.4 第四批：内容增强

目标：

- 补概念定义
- 补例子
- 补证据边界
- 处理重复概念
- 增加综合页

验收：

```text
核心概念页定义覆盖率 100%
高价值来源页关键观点覆盖率 100%
同标题重复页面有 canonical resolution
```

---

## 10. 安全执行规则

不要直接批量执行：

- 批量删除重复页
- 批量改写 `id`
- 批量替换 Wikilink
- 批量重写全部正文
- 批量把所有 ASR 页面标为低质量
- 批量调整关系方向

所有批量修复必须满足：

```text
可预览（dry-run）
可回滚（.bak）
有报告（baseline.json）
有 diff
```

每次修改前：

```bash
# 1. 备份
cp -p <file> <file>.bak.$(date +%Y%m%d)

# 2. 校验
python scripts/validate_novel_wiki_frontmatter.py <file>

# 3. 修改
edit <file>

# 4. 回读校验
python scripts/validate_novel_wiki_frontmatter.py <file>
diff <file>.bak.$(date +%Y%m%d) <file>
```

## 10.1 权限与沙箱约束

DSH 工具沙箱的写入要求：

- `approval policy = ask`：每次写操作需用户在客户端确认
- `file policy = workspace-write`：仅可写入工作区目录
- `file policy = danger-full-access`：可写入任意位置

当策略切换或 `sandbox_permissions` 解析异常时，写入会被自动拒绝。修复脚本必须在 DSH 工具权限恢复后才能继续运行。

---

## 11. 推荐的目标目录结构

```text
knowledge/novel-wiki/
├── wiki/
│   ├── index.md
│   ├── index.json
│   ├── log.md
│   ├── sources/
│   ├── entities/
│   ├── concepts/
│   └── synthesis/
└── .index/
    └── quality/
        ├── baseline-20260903.json
        ├── baseline-20260903.txt
        ├── broken-relations.json
        ├── broken-links.json
        └── duplicate-pages.json
```

质检结果属于运营数据，不放入 `wiki/` 目录。

---

## 12. 风险矩阵

| 风险 | 影响 | 缓解 |
|---|---|---|
| 重复 Frontmatter 误删正文 | 高 | dry-run + 备份 |
| 关系 target 重命名误改 | 高 | alias 优先 |
| 索引批量改写漏页面 | 中 | index.json 双写校验 |
| 模板版本不兼容 | 中 | 升级脚本 round-trip 验证 |
| 转录质量标记主观 | 低 | 沿用 V4 `transcription_quality` 字段（待审）|
| 审批策略限制 DSH 写入 | 高 | UI 切换 approval=ask |
| 删除 canonical ID 文件 | 高 | 不直接删除，使用 supersede_by |

---

## 13. 一句话方案

> 先建立 `wiki-quality` 只读体检和基线报告，再按"Frontmatter → 关系/Wikilink → 索引 → 转录质量 → 语义去重与内容增强"的顺序整改；所有修复先 dry-run、后批量执行，并通过全量回归保证结构零断链、索引零失配。

---

## 14. 附录：已知问题清单（2026-09-03）

| 文件 | 问题 | 严重度 |
|---|---|---|
| `wiki/entities/小三克堂.md` | 关系 target 失效（已修复：2026-09-03 宿主机执行）| P0 |
| `wiki/entities/斗破苍穹.md` | 重复 Frontmatter | P0 |
| `wiki/sources/借鉴素材书籍如何商业化-8111d1-ec21fd6e.md` | 重复 Frontmatter | P0 |
| `wiki/sources/借鉴素材书籍如何商业化-e7e5c9c5.md` | 与上一行同标题不同 ID | P1 |
| `wiki/sources/借鉴素材网文中的九线-2b7fc4-ccda91ed.md` | 与下一行同标题不同 ID | P1 |
| `wiki/sources/借鉴素材网文中的九线-ec648061.md` | 与上一行同标题不同 ID | P1 |
| `wiki/sources/1增强文章悬念之画外音第1段-94ef8ce7.md` | 转录含大量 ASR 噪声 | P2 |

更多问题待阶段一全量扫描后补充。

---

**生效日期**：2026-09-03
**作者**：DeepSeek Harness 自动会话
**关联文档**：

- `docs/guides/wiki-spec.md`（V4 schema）
- `docs/architecture/novel-wiki-fields-template-2026-08-31.md`（V4 字段模板）
- `docs/adr/ADR-002-wiki-fields-long-term-evolution.md`（V4 ADR）
- `scripts/validate_novel_wiki_frontmatter.py`（V4 校验脚本）