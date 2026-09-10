# Plan: LLM_Knowledge_base_v2 → ruflo-kb 数据迁移

> status: **remediation-required-before-poc**（Round 1/1.5/2 已完成，P0 加固待实施）
> branch: feature/2026-09-06-v2-to-ruflo-migration
> **前置依赖**：✅ 调研报告已完 / ✅ D1-D9a 决策已拍板（2026-09-06） / ✅ Round 1、Round 1.5、Round 2 审计完成 / 🔲 P0 加固 / 🔲 Round 2.5 复审 / 🔲 ADR-0008 PR review

---

## 目标项目（已创建 · 2026-09-06）

| 字段 | 值 |
|---|---|
| **实例名** | `video-notes-wiki` |
| **项目 UUID** | `e3a0472c-06af-41e4-8d06-083146f195f7` |
| **项目根路径** | `D:\5-Project\20260903\llm-wiki-base\knowledge\video-notes-wiki` |
| **schema 版本** | v2.0 |
| **选用模板** | `capture`（快速单鉴库） |
| **创建命令** | `python -m src.cli project init knowledge\video-notes-wiki --template capture` |

### capture 模板与 v2 的天然匹配

| capture 子类型 | 适用 v2 内容 | v2 frontmatter 字段映射 |
|---|---|---|
| `video-transcript` | **B 站 + 抖音 + 小红书视频转录** | platform / url / author / created → 来源元数据 |
| `article` | 文章类摘录 | 同上 |
| `inspiration` | C 级碎片 + _seed | summary + 散点想法 |

### 平台+视频 ID 追溯设计（关键 · 用户决策 2026-09-06）

v2 文件名天然承载平台+视频 ID，迁移器必须保留 5 重追溯链路：

1. **WikiPage.id**（=文件名）：`BV1AtwLzTEtB` / `7512800963258797321` / `Nano-Banana-Pro-...`
2. **sources[0]**：`https://www.bilibili.com/video/BV1AtwLzTEtB`
3. **V6 顶层 `platform`**：`B站` / `抖音` / `小红书`
4. **`_ko_extra.bv`**（B 站专属）：`BV1AtwLzTEetB`
5. **`_ko_extra.video_id`**：原始平台视频 ID
6. **`raw/sources/` 同名文件**：转录稿正文（用于二次校验内容）

```python
# 迁移器 T1 输出（已写入调研报告 §16）
URL_TEMPLATES = {
    "B站":    "https://www.bilibili.com/video/{bv}",
    "抖音":   "https://www.douyin.com/video/{video_id}",
    "小红书": "https://www.xiaohongshu.com/explore/{note_id}",
}
```

CJK 标题文件无法自动追溯原视频，迁移器标记 `_v2_needs_manual_url_review = true`，WebUI 显示 ⚠️ 待补 URL。

---

## Goal
将 `D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\` 作为只读来源，迁移为独立的 `video-notes-wiki` 实例。当前清单基线（2026-09-09）必须写入 run manifest，不得继续使用历史估算数字：

| 来源范围 | 数量 | 去向/处置 |
|---|---:|---|
| `10_raw/` 主要平台素材 | 2397 | `raw/sources/` |
| `10_raw/` `.batch` 元数据 | 5 | `migration/legacy/`，不进入 Wiki/向量 |
| `10_raw/_archive/` | 637 | `raw/_archive/` |
| `10_raw/_skip/` | 16 | `raw/_skip/`，保留但默认不索引 |
| `10_raw/_seed/` | 1 | `raw/_seed/` |
| `20_wiki/concepts/` 主卡 | 1919 | `wiki/concepts/` |
| `20_wiki/concepts/_to_recompile/` | 155 | `wiki/_pending/` |
| `20_wiki/entities/` | 5 | `wiki/entities/` |
| 根目录 `invalid_*.md` | 1 | `.index/quarantine/` |
| `links.md` / `overview.md` | 2 | `migration/support/`，不作为 Wiki 卡 |

迁移必须满足“每个源文件 exactly one disposition”，并且**保留全部 v2 元数据**（V6 顶层字段 + `_ko_extra` 非核心字段），使迁入后的 KB 能：

1. **保持可检索性**（ruflo-kb 全文 + 向量检索可读到全部内容）
2. **保留 v2 业务字段**（V6 顶层保存 canonical 字段；maturity / url / author / summary 等进入 `_ko_extra`，全部通过 read → write → read）
3. **保留 v2 wikilink 网络**（所有语法可解析的 `[[xxx]]` 都进入 relations 或 knowledge-gap 记录；不静默丢失）
4. **保留 v2 实体别名**（5 张 entity 卡的 `aliases` 写入 `.llm-wiki/slug_aliases.json`）
5. **保留 v2 quarantine 数据**（`invalid_*.md` 全部进 `.index/quarantine/`）
6. **重新构建 LanceDB 向量索引**（按 chunk 对账，provider、维度、失败重试和 checkpoint 全部有记录）

### 放行原则

以下任一硬门失败，整体判定 **NO-GO**，不得用“部分迁移成功”替代：

- manifest 闭包不成立；
- v2 源文件 hash 在迁移期间变化；
- V6 字段或 `_ko_extra` 写盘后不可回读；
- 存在未解释的 collision、tag 丢失、wikilink 丢失或损坏卡静默跳过；
- 向量构建未完成或无法从 checkpoint 恢复；
- rollback 演练不能恢复目标实例；
- `/health`、项目隔离或全文/向量检索失败。

### Non-goals（明确不做）

- ❌ 不重命名 v2 文件（除非 R10 撞名）
- ❌ 不改 v2 vault 内容（迁移脚本只读 v2；v2 留底作为 SSOT）
- ❌ 不实现双向同步（迁移后 v2 冻结）
- ❌ 不在 V5 8-key 契约下直接迁移；必须先完成 V6 持久化扩展
- ❌ 不重新编译 v2 的 wiki 卡（直接搬运 markdown + frontmatter）
- ❌ 不将 `_skip/` 纳入 Wiki 或向量索引；文件本身仍按 manifest 保留到 `raw/_skip/`
- ❌ 迁移器不写入 v2；v2 冻结标记是验收后的独立人工动作

---

## V6 Schema 扩展路线图（ADR-0008 · 路径 X）

> **完整 ADR**：`docs/adr/0008-v6-wiki-schema-extension-for-v2-migration.md`
> **目的**：修复 Plan-Audit Round 1 致命缺陷 ①-1（`_ko_extra` 不持久化）+ ①-2（v2 tag 不兼容）+ ②-7（验收方法 bug）
> **拆分**：3 个独立 PR，每个独立可测 + 独立可回滚

### PR 1: V6 WikiPage dataclass + 写盘字段（依赖：无 · 工作量：1-2 天）

**目标**：WikiPage dataclass 加 9 字段，`to_frontmatter_dict()` 输出 17-key，`from_dict()` 兼容 V5 格式

**Files:**
- Modify: `src/wiki/core/types.py`
  - 加 9 字段（5 已内存 + 4 新增）
  - 改 `to_frontmatter_dict()` 输出 V6 完整白名单（17-key）
  - 改 `from_dict()` 容忍 V5 格式（缺字段填默认值）
- Modify: `src/wiki/storage/page_writer.py` 第 8 行注释更新（V5 → V6）
- Modify: `docs/architecture/wiki-fields-template-2026-08-31.deprecated.md` → 标记 superseded
- Create: `docs/architecture/wiki-fields-template-v6.md`（V6 schema 完整定义）

**Acceptance:**
- ✅ novel-wiki 现有 V5 卡的 8 个字段值在 read → write → read 后保持语义一致；不再要求 V6 写盘后的 YAML 字节级一致
- ✅ V6 字段缺失时填默认值；旧 V5 页面仍可读、可写、可再次读取
- ✅ `WikiPage.to_frontmatter_dict()` 明确输出 V6 17-key；`_ko_extra` 也能真实写盘并回读
- ✅ 测试覆盖：V5 兼容、V6 完整字段、`_ko_extra` 持久化、V6 缺字段、现有 novel-wiki 回归

**Test outline:**
```python
def test_v5_frontmatter_round_trip():
    """V5 8-key frontmatter 读 → 写 → 读，旧字段语义一致"""
    fm = {"id": "x", "title": "X", "type": "concept",
          "sources": ["a"], "created_at": 1, "updated_at": 1,
          "relations": [], "tags": ["t"]}
    page = WikiPage.from_dict(fm)
    out = page.to_frontmatter_dict()
    # V5 8-key 必须在，V6 9 字段默认值也必须在
    for k in ["id", "title", "type", "sources", "created_at", "updated_at", "relations", "tags"]:
        assert k in out
    # V6 新字段默认值
    assert out["processing_depth"] == "concept"
    assert out["source_grade"] == "B"
    assert out["platform"] == ""
    assert out["category"] == ""
    assert out["taxonomy_sub"] == ""
    assert out["use_context"] == ""
    assert out["workflow_state"] == "draft"
    assert out["capture_type"] == ""
    assert out["v2_origin"] is False

def test_v6_full_frontmatter_round_trip():
    """V6 17-key frontmatter 读 → 写 → 读 字节级一致"""
    fm = {"id": "x", "title": "X", "type": "concept",
          "sources": ["a"], "created_at": 1, "updated_at": 1,
          "relations": [],
          "tags": ["t"],
          "processing_depth": "memory",
          "source_grade": "A",
          "platform": "B站",
          "category": "AI技术",
          "taxonomy_sub": "AI编程",
          "use_context": "build",
          "workflow_state": "ready",
          "capture_type": "video-transcript",
          "v2_origin": True}
    page = WikiPage.from_dict(fm)
    assert page.processing_depth == "memory"
    assert page.platform == "B站"
    assert page.v2_origin is True
    out = page.to_frontmatter_dict()
    assert out["processing_depth"] == "memory"
    assert out["v2_origin"] is True

def test_novel_wiki_card_no_regression():
    """novel-wiki 现有卡不被 V6 schema 升级破坏"""
    # 抽样 10 张 novel-wiki 现有卡，read → write → read，断言旧字段语义一致
    ...
```

**Commit:** `feat(wiki): V6 schema — 9 字段写盘 + V5 向后兼容`

---

### PR 2: V6 Tag Namespace 扩展（依赖：PR 1 · 工作量：1 天）

**目标**：`tag_namespace.py` 加 5 个新前缀 + `validate_tag_compliance` 条件化

**Files:**
- Modify: `src/wiki/features/tag_namespace.py`
  - `TAG_PREFIXES` 加 `tool/ scene/ status/ media/ author/` 5 个新前缀
  - `validate_tag_compliance(tags, *, page_type=None, platform=None)` 增加可选参数
  - mandatory pair 仅在 `page_type == "source" and platform in VIDEO_PLATFORMS` 时强制
- Create: `docs/architecture/tag-namespace-v6.md`

**Acceptance:**
- ✅ v2 free-form tag `[网文创作, 读者视角, ...]` 不再 raise TagValidationError
- ✅ v2 source 卡仍保留 `素材/ugc` + `可信度/ugc`（条件强制）
- ✅ entity / concept / synthesis 卡不强制 mandatory pair
- ✅ 测试覆盖 v2 12+ 典型 tag

**Test outline:**
```python
def test_v2_freetext_tag_no_longer_raises():
    """v2 free-form tag 通过校验"""
    tags = ["网文创作", "读者视角", "自审方法", "写作技巧"]
    validate_tag_compliance(tags, page_type="concept")  # 不 raise

def test_source_card_with_video_platform_still_needs_mandatory():
    """source 卡 + 视频平台 → 仍需 mandatory pair"""
    tags = ["网文创作"]  # 无 mandatory pair
    with pytest.raises(TagValidationError) as exc:
        validate_tag_compliance(tags, page_type="source", platform="B站")
    assert "missing mandatory" in str(exc.value)

def test_source_card_with_article_platform_no_mandatory():
    """source 卡 + 文章平台 → 不强制 mandatory pair"""
    tags = ["文章摘录"]
    validate_tag_compliance(tags, page_type="source", platform="公众号")  # 不 raise

def test_v2_namespace_prefix_recognized():
    """v2 既有 tool/scene/status 前缀通过校验"""
    tags = ["tool/python", "scene/视频笔记", "status/Agent核心记忆"]
    validate_tag_compliance(tags)  # 不 raise
```

**Commit:** `feat(wiki): V6 tag namespace — 5 新前缀 + mandatory pair 条件化`

---

### PR 3: V6 Migration Tools（依赖：PR 1+2 · 工作量：5-6 天）

**目标**：实现 v2 → ruflo-kb 迁移工具全套（T0-T10 + T10.0）

**Files:**
- Create: `src/wiki/migrate/__init__.py`
- Create: `src/wiki/migrate/v2_frontmatter.py`
- Create: `src/wiki/migrate/v2_wikilinks.py`
- Create: `src/wiki/migrate/v2_aliases.py`
- Create: `src/wiki/migrate/v2_quarantine.py`
- Create: `src/wiki/migrate/v2_raw.py`
- Create: `src/wiki/migrate/v2_pending.py`
- Create: `src/wiki/migrate/v2_full.py`（Phase 2 全量迁移主入口）
- Create: `src/wiki/migrate/v2_manifest.py`（清单、hash、disposition 对账）
- Create: `src/wiki/migrate/v2_run_state.py`（checkpoint、resume、run-id）
- Create: `src/cli_ext/migrate_v2_cmd.py`
- Create: `scripts/rebuild_vectors.py`
- Create: `tests/test_wiki_migrate/__init__.py`
- Create: `tests/test_wiki_migrate/conftest.py`
- Create: `tests/test_wiki_migrate/test_v2_frontmatter.py`
- Create: `tests/test_wiki_migrate/test_v2_wikilinks.py`
- Create: `tests/test_wiki_migrate/test_v2_aliases.py`
- Create: `tests/test_wiki_migrate/test_v2_quarantine.py`
- Create: `tests/test_wiki_migrate/test_v2_raw.py`
- Create: `tests/test_wiki_migrate/test_v2_pending.py`
- Create: `tests/test_wiki_migrate/test_v2_full.py`
- Create: `tests/test_wiki_migrate/test_v2_manifest.py`
- Create: `tests/test_wiki_migrate/test_v2_run_state.py`
- Create: `tests/test_wiki_migrate/test_rebuild_vectors.py`
- Create: `tests/test_wiki_migrate/test_migrate_v2_cmd.py`
- Create: `scripts/run_v2_migration.sh`

**Acceptance:**
- ✅ T1-T10 全部 PASS（每个 Task 单独提交）
- ✅ 当前 manifest 的所有源文件均有且只有一个 disposition；无未解释的 failed/collision
- ✅ 1919 张 concepts + 155 张 pending + 5 张 entities + 1 张 quarantine 按映射规则落位
- ✅ v2 业务字段 read → write → read 100% 一致；未知字段不得静默丢失
- ✅ v2 tag 原始数量 = 规范化 tag 数 + `_v2_legacy_tags` 数；所有 warning 可追溯
- ✅ 向量按 chunk manifest 完成重建；5 个检索词全部达到目标命中数
- ✅ 中断后 `--resume` 不重复、不漏数据；rollback 只影响本次 run

**Commit:** 每个 Task 一提交，共 12 个 commit

---

### V6 路线图工时汇总

| 阶段 | 内容 | 工作量 | 顺序 |
|---|---|---|---|
| PR 1 | V6 schema dataclass | 1-2 天 | 1（PR review） |
| PR 2 | V6 tag 命名空间 | 1 天 | 2（PR 1 通过后） |
| Plan-Audit Round 1.5 复审 | 整改后漏洞审计 | 0.5 天 | 3（PR 1+2 通过后） |
| PR 3 | Migration tools | 5-6 天 | 4 |
| Plan-Audit Round 2 压力测试 | 极限推演 | 0.5 天 | 5 |
| 人工复核 + 最终拍板 | — | 0.5 天 | 6 |
| Phase 0 PoC | 5 张样本卡试跑 | 1-2 天 | 7 |
| Phase 1-4 | 全量迁移 + 验证 + 向量 | 5-6 天 | 8 |
| P0 加固（manifest / resume / rollback / provider / 磁盘） | 3-5 天 | 0（进入 PoC 前） |
| **总计** | — | **18-25 天** | — |

---

## 任务架构总览

| Task | 名称 | 输入 | 输出 | 验收 |
|---|---|---|---|---|
| **T0** | 清单与运行状态 | v2 绝对路径 + project UUID | manifest + hash + checkpoint | 所有输入 exactly one disposition |
| **T1** | 转换器核心模块 | v2 .md | WikiPage dict + 验证报告 | 单测覆盖 frontmatter 转换 |
| **T2** | wikilink 解析器 | v2 body 文本 | relations list | 单测覆盖所有 5 种 wikilink 形态 |
| **T3** | 实体别名导出器 | v2 entities/*.md | slug_aliases.json | 单测覆盖 aliases 列表 |
| **T4** | invalid_*.md quarantine 处理器 | v2 根 invalid_*.md | .index/quarantine/*.md + judgments.jsonl | 单测覆盖全部自定义字段保留 |
| **T5** | raw 文件搬运器 | v2 10_raw/ | ruflo-kb raw/sources/ + 命名映射 | 单测覆盖 3 平台 + 3 特殊目录 |
| **T6** | _to_recompile 决策器 | v2 _to_recompile/*.md | 报告 + 不写入主树 | 单测覆盖冲突检测 |
| **T7** | CLI 集成 + dry-run | 上述全部模块 | `python -m src.cli migrate-v2` 子命令 | 端到端冒烟测试 |
| **T8** | 全量迁移 + 原子 promotion | T0-T7 | staging + manifest + migration_report.csv | disposition 闭包、可 resume、可 rollback |
| **T9** | 健康度 + 自定义验证 | T8 输出 | 验证报告 + 修复 | H1-H10 全通过 |
| **T10** | LanceDB 重建 + 服务冒烟 | T9 输出 | 可用 ruflo-kb serve | chunk 对账、维度一致、检索通过 |

---

## 决策锁定 SSOT（2026-09-06 · 用户确认）

> **完整决策记录**：`docs/research/2026-09-06-v2-to-ruflo-migration-survey.md` §12（D1-D9a）
> **本章节作用**：把 D1-D9a 决策直接固化到实施方案，每个 Task 必须遵守。如发现决策需调整，必须先修改调研报告 §12 + 本章节，再修改代码。

| # | 决策 | 实施约束 | 对应 Task |
|---|---|---|---|
| **D1** | `_to_recompile/` 155 草稿 → `wiki/_pending/` 子目录 | main 版本胜出；草稿路径含 `_to_recompile/` 来源标识；写 `pending_decisions.csv` 报告 | T6 |
| **D2** | `_archive/` 637 文件 → `raw/_archive/` | 保留目录结构；SHA-256 校验一致 | T5 |
| **D3** | v2 业务字段 → V6 顶层 + `_ko_extra` | 按 `docs/architecture/v2-to-v6-field-mapping.md` 映射；写 `v2_origin: true`；未知字段不得丢失 | T1 |
| **D4** | raw 文件名不加平台前缀 | 默认保守；`--add-platform-prefix` flag 仅用户显式开启；撞名时 `--on-collision fail`（②-2 修复）| T5 |
| **D5** | entity aliases → `.llm-wiki/slug_aliases.json` | 仅 entity 卡；canonical = file stem；**正向格式** `{alias: canonical}`（②-1 修复）| T3 |
| **D6** | invalid_*.md → `.index/quarantine/` + judgments.jsonl | 全字段保留 | T4 |
| **D7** | v2 vault 迁移后冻结 | 迁移器不写 v2；验收通过后由项目所有者单独执行冻结标记并保留备份 | 文档（非代码） |
| **D8** | 单次全量迁移 | 一次 run-id 管理全流程；允许从 checkpoint resume；promotion 前失败不触碰 live target；rollback 按 manifest 精确恢复 | T8 |
| **D9a** | v2 概念卡 → `type: concept` 落 `wiki/concepts/` | 视频回溯走 `_ko_extra.video_id`；body 顶部插入 `<!-- capture-type: video-transcript -->` marker；设置 `capture_type = "video-transcript"` | T1 |

---

## Global Constraints

- **TDD**：每个 Task 先写测试（pytest），跑失败，再实现，跑通过，再 commit
- **Commit 粒度**：每 Task 一提交（feat/fix/refactor/test/docs 类型）
- **Dry-run 优先**：每个 Task 必须先 `--dry-run` 输出预期，再 `--apply`
- **v2 不可变**：所有脚本只读 v2；迁移器绝不写 v2，冻结标记是验收后的独立人工动作
- **路径显式**：`--project <uuid>` 与 `--v2-path <绝对路径>` 必填，不依赖 CWD；单进程运行，不支持并行迁移
- **运行可恢复**：每个 run 必须有 `migration-manifest.json`、`migration_progress.jsonl`、`raw_progress.jsonl`、`rebuild_progress.jsonl`
- **目标不覆盖**：`--apply` 只能写 staging；发现非初始化内容或非本 run 的页面时 abort，不得覆盖
- **失败不静默**：损坏卡、tag、断链、collision、provider 错误都必须进入报告并按策略终止或 quarantine
- **源一致性**：apply 开始和 promotion 前重新核对源文件 hash；源发生变化则 abort
- **审核节奏**：每个 Task 提交后 → reviewer subagent review → 修 Critical/Important → 下一 Task
- **branch**：`feature/2026-09-06-v2-to-ruflo-migration`，合并到 main 前先 PR
- **plan-audit**：本计划在进入编码前必须完成两轮审查

---

## Phase 0：PoC（前置，必须先完成）

### P0 加固门（未全部通过不得进入 PoC）

- [ ] **G0 清单闭包**：生成当前基线 manifest；3056 个 raw 文件、2082 个 wiki/support 文件全部有 disposition
- [ ] **G1 V6 持久化**：V6 顶层字段和 `_ko_extra` 通过 read → write → read；现有 V5 页面回归通过
- [ ] **G2 字段/标签映射**：按 `docs/architecture/v2-to-v6-field-mapping.md` 执行；tag 失败 fail-soft，原 tag 保留
- [ ] **G3 checkpoint/resume**：raw、wiki、vector 分层 checkpoint；重复执行不重复写、不漏写
- [ ] **G4 精确回滚**：rollback 强制 project UUID + run-id，只删除本 run 产物；通过故障注入演练
- [ ] **G5 目标冲突保护**：非初始化目标页面拒绝覆盖；collision 输出报告
- [ ] **G6 provider 预检**：真实调用一次 embedding，确认 dimension、配额、超时、429 重试策略
- [ ] **G7 向量原子替换**：新 LanceDB 在临时目录构建完成并校验后再替换 live table
- [ ] **G8 磁盘预检**：按实际源大小 + 临时空间 + 5 GB 安全余量计算，空间不足直接 abort

### PoC 任务

- [ ] **P0.1**：手选 5 张代表性 v2 卡（含 1 张概念、1 张实体、1 张 invalid、1 张 _to_recompile、1 张纯文本无 frontmatter）
- [ ] **P0.2**：使用正式 CLI：`python -m src.cli migrate-v2 --project e3a0472c-06af-41e4-8d06-083146f195f7 --v2-path <绝对路径> --dry-run`
- [ ] **P0.3**：样本除 5 类 Wiki 卡外，再验证 1 个文本 raw、1 个 `.batch`、1 个二进制 raw 的 disposition 和 hash
- [ ] **P0.4**：人工审查 V6 顶层字段、`_ko_extra`、wikilink、aliases、pending、quarantine 与 manifest
- [ ] **P0.5**：对 PoC 注入一次中断和一次 provider 失败，验证 resume/rollback
- [ ] **P0.6**：若任一 P0 门或 PoC 断言失败，禁止进入全量；修复后重新跑 Round 2.5

**PoC 完成标准**：5/5 张卡转换结果与人工审查一致，方可进入 Phase 1。

---

## Phase 1：核心转换器（T0-T7）

### Task 0: Manifest 与运行状态（`src/wiki/migrate/v2_manifest.py` / `v2_run_state.py`）

**Files:**
- Create: `src/wiki/migrate/v2_manifest.py`
- Create: `src/wiki/migrate/v2_run_state.py`
- Create: `tests/test_wiki_migrate/test_v2_manifest.py`
- Create: `tests/test_wiki_migrate/test_v2_run_state.py`
- Create: `docs/architecture/v2-to-v6-field-mapping.md`

**Interfaces:**
- `build_manifest(v2_root: Path, project_root: Path, run_id: str) -> MigrationManifest`
- `write_checkpoint(path: Path, item: CheckpointItem) -> None`
- `load_checkpoint(path: Path, run_id: str) -> set[str]`
- `rollback_run(project_root: Path, run_id: str, *, dry_run: bool) -> RollbackReport`

`ALLOWED_DISPOSITIONS = {"migrated", "archived", "skipped", "quarantined", "support-artifact", "metadata-only", "collision", "failed"}`；seed 文件使用 `disposition=migrated` 和 `kind=seed`，不得新增未定义 disposition。

**Rules:**
- Manifest 每行记录 `source_path`、`sha256`、`size`、`kind`、`disposition`、`target_path`、`reason`。
- checkpoint 使用追加式 JSONL；重复记录按 `(run_id, source_path)` 幂等去重。
- rollback 只能作用于指定 project UUID 和 run-id 的 staging/promotion 产物。
- 源 hash 在 apply 开始和 promotion 前各核对一次；不一致直接 abort。

**Acceptance:**
- 真实源目录 3056 个 raw 文件、2082 个 wiki/support 文件均能生成 manifest 条目。
- manifest 不允许无 disposition、重复 source path 或未解释的 failed。
- 注入中断后 resume 只处理未完成条目；rollback dry-run 只列出本 run 产物。

### Task 1: Frontmatter 转换器（`src/wiki/migrate/v2_frontmatter.py`）

**Files:**
- Create: `src/wiki/migrate/__init__.py`
- Create: `src/wiki/migrate/v2_frontmatter.py`
- Create: `tests/test_wiki_migrate/__init__.py`
- Create: `tests/test_wiki_migrate/test_v2_frontmatter.py`
- Create: `tests/test_wiki_migrate/conftest.py`

**Test:**
```python
# test_v2_frontmatter.py
import pytest
from src.wiki.migrate.v2_frontmatter import convert_frontmatter

def test_concept_card_full():
    """完整 v2 概念卡 → 完整 V5 + _ko_extra"""
    v2 = {
        "title": "测试",
        "version": "v2.1",
        "tags": ["a", "b"],
        "processing_depth": "concept",
        "source_grade": "A",
        "platform": "B站",
        "url": "https://...",
        "author": "N/A",
        "category": "AI技术",
        "maturity": "A级-可借鉴",
        "taxonomy_sub": "AI编程",
        "created": "2026-06-18",
        "updated": "2026-06-18",
        "use_context": "build",
        "workflow_state": "ready",
        "summary": "测试摘要",
    }
    out = convert_frontmatter(v2, file_stem="BVxxx")
    assert out["title"] == "测试"
    assert out["id"] == "BVxxx"
    assert out["type"] == "concept"
    assert out["sources"] == ["https://..."]
    assert "created_at" in out
    assert "tags" in out
    assert out["tags"] == ["a", "b"]
    # V6 canonical fields are top-level; non-core fields remain in _ko_extra.
    assert out["_ko_extra"]["version"] == "v2.1"
    assert out["processing_depth"] == "concept"
    assert out["use_context"] == "build"
    assert out["v2_origin"] is True  # 标记 v2 来源

def test_entity_card_with_aliases():
    """实体卡额外字段"""
    v2 = {"title": "Claude Code", "type": "entity",
          "aliases": ["claude-code", "ClaudeCode"], "instance_of": "工具"}
    out = convert_frontmatter(v2, file_stem="Claude Code")
    assert out["type"] == "entity"
    assert out["_ko_extra"]["aliases"] == ["claude-code", "ClaudeCode"]
    assert out["_ko_extra"]["custom_type"] == "工具"

def test_mini_wiki_version():
    """v2.1-mini 不应改变 type"""
    v2 = {"title": "碎片", "version": "v2.1-mini", "processing_depth": "memory"}
    out = convert_frontmatter(v2, file_stem="memo")
    assert out["_ko_extra"]["version"] == "v2.1-mini"
    assert out["processing_depth"] == "memory"

def test_iso_date_to_ms():
    """created/updated ISO → ms int"""
    v2 = {"created": "2026-06-18", "updated": "2026-06-18T12:34:56"}
    out = convert_frontmatter(v2, file_stem="x")
    assert out["created_at"] > 0
    # 接受 datetime / ms int 两种（ruflo-kb 的 _coerce_ts_ms 双兼容）

def test_invalid_card_quarantine():
    """invalid_*.md 的非标准字段保留到 _ko_extra"""
    v2 = {
        "uid": "20260403-D2A1",
        "title": "（无效素材）",
        "bv": "BV1tdPDzQEpa",
        "source": "10_raw/...",
        "invalid_reason": "content_too_sparse",
        "uploader": "AI靓匠",
        "video_published_at": "2026-03-09",
    }
    out = convert_frontmatter(v2, file_stem="invalid_BV1tdPDzQEpa")
    assert out["_ko_extra"]["uid"] == "20260403-D2A1"
    assert out["_ko_extra"]["invalid_reason"] == "content_too_sparse"
    # invalid 卡不打入主 wiki 树，调用方处理

def test_d9a_concept_card_with_capture_marker():
    """D9a: v2 concepts/*.md → type=concept + body 顶部 capture marker"""
    v2 = {
        "title": "测试概念",
        "tags": ["网文创作", "读者视角"],
        "processing_depth": "concept",
        "source_grade": "A",
        "platform": "B站",
        "url": "https://...",
        "author": "N/A",
        "category": "AI技术",
        "taxonomy_sub": "AI编程",
    }
    fm, body = convert_frontmatter_and_body(v2, file_stem="BV1xxx", body="## 核心观点\n...")
    # D9a: type 必须 concept
    assert fm["type"] == "concept"
    # D9a: capture_type 字段（V6 schema）
    assert fm["capture_type"] == "video-transcript"
    # D9a: v2_origin 必须 True
    assert fm["v2_origin"] is True
    # D9a: body 顶部插入 capture marker（如果不存在）
    assert body.startswith("<!-- capture-type: video-transcript -->")

def test_d9a_entity_card_uses_inspiration_marker():
    """D9a: entity 卡根据 source 判断 capture marker（保守：默认 video-transcript）"""
    v2 = {"title": "Claude Code", "type": "entity"}
    fm, body = convert_frontmatter_and_body(v2, file_stem="Claude Code", body="## 基本信息\n...")
    # D9a: entity 卡 type 仍是 entity
    assert fm["type"] == "entity"
    # entity 卡是否要 marker 留给调用方决策（默认不加，避免与 v2 内容冲突）
```

**Acceptance:**
- 5+ 测试覆盖 4 种典型卡片（D9a 加 2 个新测试）
- 100% v2 字段在输出 dict 中可访问（核心 8 项直接，扩展项经 `_ko_extra`）
- `test_iso_date_to_ms` 接受 YYYY-MM-DD 与 YYYY-MM-DDTHH:MM:SS 两种格式
- D9a 测试通过：`type == concept`、`capture_type == "video-transcript"`、`v2_origin is True`、body 顶部含 capture marker
- **提交**：`feat(migrate): v2 frontmatter 转换器（核心 8-key + _ko_extra 逃生口 + D9a type=concept + capture marker）`

---

### Task 2: wikilink 解析器（`src/wiki/migrate/v2_wikilinks.py`）

**Files:**
- Create: `src/wiki/migrate/v2_wikilinks.py`
- Create: `tests/test_wiki_migrate/test_v2_wikilinks.py`

**Test:**
```python
from src.wiki.migrate.v2_wikilinks import extract_relations

def test_bvid_wikilink():
    """[[BV1AtwLzTEtB]] → references"""
    body = "参考 [[BV1AtwLzTEtB]] 与 [[BV1234567890]]"
    rels = extract_relations(body, current_page_id="BVcur")
    assert {"target": "BV1AtwLzTEtB", "type": "references"} in rels
    assert {"target": "BV1234567890", "type": "references"} in rels

def test_chinese_title_wikilink():
    """[[Claude Code]] → references (slug 由 slugify 处理)"""
    body = "相关 [[Claude Code]] [[Obsidian]]"
    rels = extract_relations(body, current_page_id="x")
    targets = [r["target"] for r in rels]
    assert "claude-code" in targets  # slugify 转换

def test_douyin_id_wikilink():
    """[[7512800963258797321]] → references"""
    body = "抖音源 [[7512800963258797321]]"
    rels = extract_relations(body, current_page_id="x")
    assert rels[0]["target"] == "7512800963258797321"

def test_self_reference_skip():
    """[[self]] 应该被剔除"""
    body = "指向 [[self_page]] 又被 [[self_page]] 引用"
    rels = extract_relations(body, current_page_id="self_page")
    assert rels == []  # 两个都是 self

def test_aliased_wikilink():
    """[[ClaudeCode|claude code]] → 仅 target 部分进 relations"""
    body = "见 [[ClaudeCode|claude code]]"
    rels = extract_relations(body, current_page_id="x")
    assert rels[0]["target"] == "claudecode"  # slugify('ClaudeCode')

def test_markdown_link_not_wikilink():
    """[text](url) 不应被识别为 wikilink"""
    body = "看 [B 站](https://bilibili.com) 和 [[BV1xxx]]"
    rels = extract_relations(body, current_page_id="x")
    assert len(rels) == 1
    assert rels[0]["target"] == "BV1xxx"
```

**Acceptance:**
- 6+ 测试覆盖 5 种 wikilink 形态 + 1 个否定案例
- `extract_relations` 返回 `[{target, type, weight, context}]` 列表（ruflo-kb Relation 格式）
- self-reference 自动剔除
- **提交**：`feat(migrate): v2 wikilink → relations 转换器`

---

### Task 3: 实体别名导出器（`src/wiki/migrate/v2_aliases.py`）

**Files:**
- Create: `src/wiki/migrate/v2_aliases.py`
- Create: `tests/test_wiki_migrate/test_v2_aliases.py`

**Test:**
```python
def test_extract_aliases_from_entity_card():
    """②-1 修复：返回正向 {alias: canonical} 格式（与 SlugAliasRegistry 一致）"""
    from src.wiki.migrate.v2_aliases import extract_aliases
    fm = {"type": "entity", "aliases": ["claude-code", "ClaudeCode"]}
    aliases = extract_aliases(file_stem="Claude Code", frontmatter=fm)
    # 正向格式：alias → canonical
    assert aliases == {
        "claude-code": "Claude Code",
        "ClaudeCode": "Claude Code",
    }

def test_skip_non_entity_card():
    """非 entity 卡的 aliases 忽略"""
    fm = {"type": "concept", "aliases": ["foo"]}
    aliases = extract_aliases(file_stem="x", frontmatter=fm)
    assert aliases == {}

def test_canonical_slug_generation():
    """②-1 修复：canonical = file stem（带空格），非 slugify 后版本"""
    fm = {"type": "entity", "title": "Obsidian"}
    aliases = extract_aliases(file_stem="Obsidian", frontmatter=fm)
    # alias "OB" → canonical "Obsidian"（文件 stem）
    assert aliases == {"OB": "Obsidian"}

def test_write_aliases_to_registry():
    """②-1 修复：写入正向格式 JSON"""
    from src.wiki.migrate.v2_aliases import write_alias_registry
    import json, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        registry_path = Path(tmp) / "slug_aliases.json"
        # 正向格式：{alias: canonical}
        registry = {
            "claude-code": "Claude Code",
            "ClaudeCode": "Claude Code",
            "OB": "Obsidian",
        }
        write_alias_registry(registry, registry_path)
        data = json.loads(registry_path.read_text())
        # 反向索引由 SlugAliasRegistry._load() 重建
        assert data["claude-code"] == "Claude Code"
        assert data["ClaudeCode"] == "Claude Code"
        assert data["OB"] == "Obsidian"

def test_alias_resolves_after_registry_load():
    """②-1 修复：写入后 SlugAliasRegistry 能正确解析"""
    from src.wiki.features.slug_aliases import SlugAliasRegistry
    from src.wiki.migrate.v2_aliases import write_alias_registry
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        registry = {
            "claude-code": "Claude Code",
            "ClaudeCode": "Claude Code",
        }
        write_alias_registry(registry, root / ".llm-wiki" / "slug_aliases.json")
        reg = SlugAliasRegistry(root)
        assert reg.get_canonical("ClaudeCode") == "Claude Code"
        assert reg.get_canonical("claude-code") == "Claude Code"
        assert reg.has_aliases_for("Claude Code") == ["claude-code", "ClaudeCode"]
```

**Acceptance:**
- 5+ 测试覆盖 entity 卡识别、aliases 提取、canonical slug、JSON 写入、registry 加载后解析
- 输出格式与 ruflo-kb `SlugAliasRegistry` 兼容：**正向 `{alias: canonical}`**（修正自 ②-1 重大隐患）
- 反向索引由 `SlugAliasRegistry._load()` 自动重建（ruflo-kb 内置机制）
- canonical = file stem（带空格），非 slugify 后版本（因为 `resolve_wikilink` Step 1 用 `path.stem` 匹配）
- **提交**：`feat(migrate): 实体别名 → slug_aliases.json 导出器（正向格式）`

---

### Task 4: invalid_*.md quarantine 处理器（`src/wiki/migrate/v2_quarantine.py`）

**Files:**
- Create: `src/wiki/migrate/v2_quarantine.py`
- Create: `tests/test_wiki_migrate/test_v2_quarantine.py`

**Test:**
```python
def test_detect_invalid_card():
    """文件名 invalid_*.md 触发 quarantine"""
    from src.wiki.migrate.v2_quarantine import is_invalid_card
    assert is_invalid_card("invalid_BV1tdPDzQEpa.md")
    assert not is_invalid_card("BV1tdPDzQEpa.md")

def test_extract_invalid_metadata():
    fm = {
        "uid": "20260403-D2A1",
        "bv": "BV1tdPDzQEpa",
        "invalid_reason": "content_too_sparse",
        "uploader": "AI靓匠",
        "video_published_at": "2026-03-09",
    }
    from src.wiki.migrate.v2_quarantine import extract_quarantine_metadata
    meta = extract_quarantine_metadata(fm)
    assert meta["reason"] == "content_too_sparse"
    assert meta["uploader"] == "AI靓匠"
    assert meta["bv"] == "BV1tdPDzQEpa"

def test_write_to_quarantine_index():
    """写入 .index/quarantine/<slug>.md + judgments.jsonl"""
    from src.wiki.migrate.v2_quarantine import write_quarantine
    import json, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_quarantine(
            slug="invalid_BV1tdPDzQEpa",
            metadata={"reason": "content_too_sparse", "bv": "BV1tdPDzQEpa"},
            body="原始 body 内容...",
            target_root=root,
        )
        qdir = root / ".index" / "quarantine"
        assert (qdir / "invalid_BV1tdPDzQEpa.md").exists()
        judgments = json.loads((qdir / "judgments.jsonl").read_text().strip().split("\n")[-1])
        assert judgments["slug"] == "invalid_BV1tdPDzQEpa"
        assert judgments["reason"] == "content_too_sparse"

def test_quarantine_not_in_main_wiki():
    """quarantine 卡不写入主 wiki/concepts/ 树"""
    from src.wiki.migrate.v2_quarantine import write_quarantine
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_quarantine("invalid_x", {}, "", root)
        assert not (root / "wiki" / "concepts" / "invalid_x.md").exists()
        assert not (root / "wiki" / "sources" / "invalid_x.md").exists()
```

**Acceptance:**
- 4+ 测试覆盖检测、metadata 提取、写入、不污染主树
- quarantine 元数据完整保留（uid/bv/source/uploader/invalid_reason/video_published_at/...）
- **提交**：`feat(migrate): invalid_*.md → .index/quarantine 处理器`

---

### Task 5: raw 文件搬运器（`src/wiki/migrate/v2_raw.py`）

**Files:**
- Create: `src/wiki/migrate/v2_raw.py`
- Create: `tests/test_wiki_migrate/test_v2_raw.py`

**Test:**
```python
def test_bilibili_path_mapping():
    """01_B站视频转录/X.txt → raw/sources/X.txt"""
    from src.wiki.migrate.v2_raw import map_raw_path
    v2_path = Path("10_raw/01_B站视频转录/BV113411K7tu.txt")
    target = map_raw_path(v2_path, target_root=Path("/dest"))
    assert str(target).endswith("raw/sources/BV113411K7tu.txt")

def test_douyin_path_mapping():
    v2_path = Path("10_raw/02_抖音视频笔记/7512xxx.md")
    target = map_raw_path(v2_path, target_root=Path("/dest"))
    assert "7512xxx.md" in str(target)

def test_xhs_path_mapping():
    v2_path = Path("10_raw/03_小红书收藏夹/Nano-Banana.md")
    target = map_raw_path(v2_path, target_root=Path("/dest"))
    assert "Nano-Banana.md" in str(target)

def test_archive_path_preserved():
    """_archive/X.txt → raw/_archive/X.txt"""
    v2_path = Path("10_raw/_archive/old.txt")
    target = map_raw_path(v2_path, target_root=Path("/dest"))
    assert "_archive" in str(target)

def test_skip_path_excluded():
    """_skip/ 默认排除"""
    from src.wiki.migrate.v2_raw import collect_raw_files
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for sub in ["01_B站视频转录", "_skip", "_seed", "_archive"]:
            (Path(tmp) / sub).mkdir()
            (Path(tmp) / sub / "f1.txt").write_text("x")
        files = collect_raw_files(Path(tmp))
        names = [f.name for f in files]
        assert "f1.txt" in names  # at least one
        # _skip files NOT included by default
        # (write f1.txt to _skip and assert absent)
        (Path(tmp) / "_skip" / "skip_me.txt").write_text("y")
        files = collect_raw_files(Path(tmp), include_skip=False)
        skip_files = [f for f in files if "skip" in str(f)]
        assert len(skip_files) == 0

def test_collision_detection():
    """两个 v2 文件映射到同一目标时报告冲突"""
    from src.wiki.migrate.v2_raw import detect_collisions
    src = [
        Path("10_raw/01_B站视频转录/123.txt"),
        Path("10_raw/02_抖音视频笔记/123.txt"),  # 同名！
    ]
    collisions = detect_collisions(src, target_root=Path("/dest"))
    assert len(collisions) >= 1
```

**Acceptance:**
- 6+ 测试覆盖 3 平台 + archive + skip 排除 + 撞名检测
- 默认保守（不加平台前缀），仅在 `--add-platform-prefix` 时加重命名
- 撞名时输出报告（不自动解决，交给用户决策）
- **提交**：`feat(migrate): v2 raw → ruflo-kb raw/sources 搬运器`

---

### Task 6: _to_recompile 决策器（`src/wiki/migrate/v2_pending.py`）

**Files:**
- Create: `src/wiki/migrate/v2_pending.py`
- Create: `tests/test_wiki_migrate/test_v2_pending.py`

**Test:**
```python
def test_detect_pending_cards():
    """_to_recompile/*.md 标记为 pending"""
    from src.wiki.migrate.v2_pending import classify_pending
    pending_files = [Path("20_wiki/concepts/_to_recompile/BV1xxx.md")]
    report = classify_pending(pending_files, main_files=[])
    assert report["BV1xxx.md"]["status"] == "pending"
    assert report["BV1xxx.md"]["reason"] == "_to_recompile"

def test_pending_does_not_overwrite_main():
    """_to_recompile 与顶层同名时，主版本胜出"""
    from src.wiki.migrate.v2_pending import classify_pending
    files = [Path("20_wiki/concepts/_to_recompile/BV1xxx.md")]
    main = [Path("20_wiki/concepts/BV1xxx.md")]
    report = classify_pending(files, main_files=main)
    assert report["BV1xxx.md"]["status"] == "main_wins"
    assert "BV1xxx.md" in report["BV1xxx.md"]["skipped_paths"]

def test_unique_pending_kept():
    """_to_recompile 独有文件保留为 pending"""
    from src.wiki.migrate.v2_pending import classify_pending
    files = [Path("20_wiki/concepts/_to_recompile/BVonly_pending.md")]
    report = classify_pending(files, main_files=[])
    assert report["BVonly_pending.md"]["status"] == "pending"

def test_write_pending_to_subdir():
    """pending 卡写入 wiki/_pending/ 子目录"""
    from src.wiki.migrate.v2_pending import write_pending_cards
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending_cards(
            [{"slug": "BVonly_pending", "body": "...", "fm": {}}],
            target_root=root,
        )
        assert (root / "wiki" / "_pending" / "BVonly_pending.md").exists()

def test_pending_metadata_merged_into_main_ko_extra():
    """②-4 修复：pending 富元数据合并到 main _ko_extra"""
    from src.wiki.migrate.v2_pending import merge_pending_metadata
    main_fm = {
        "title": "测试",
        "version": "v2.1",
        "platform": "B站",
        "v2_origin": True,
        "_ko_extra": {}
    }
    pending_fm = {
        "bv": "BV1xxx",
        "uploader": "AI靓匠",
        "view_count": 30726,
        "like_count": 1026,
        "favorite_count": 877,
        "video_published_at": "2026-03-16",
    }
    merged = merge_pending_metadata(main_fm, pending_fm)
    # pending 的字段追加到 main 的 _ko_extra
    assert merged["_ko_extra"]["bv"] == "BV1xxx"
    assert merged["_ko_extra"]["uploader"] == "AI靓匠"
    assert merged["_ko_extra"]["view_count"] == 30726
    assert merged["_ko_extra"]["like_count"] == 1026
    assert merged["_ko_extra"]["favorite_count"] == 877
    assert merged["_ko_extra"]["video_published_at"] == "2026-03-16"
    # main 原有字段保留
    assert merged["platform"] == "B站"
    assert merged["v2_origin"] is True

def test_pending_metadata_no_conflict_overwrite():
    """②-4 修复：main 已有字段不被 pending 覆盖"""
    main_fm = {"_ko_extra": {"uploader": "原UP主", "view_count": 100}}
    pending_fm = {"uploader": "新UP主", "view_count": 200, "like_count": 50}
    merged = merge_pending_metadata(main_fm, pending_fm)
    # main 胜出（保留原值），pending 的新字段追加
    assert merged["_ko_extra"]["uploader"] == "原UP主"
    assert merged["_ko_extra"]["view_count"] == 100
    assert merged["_ko_extra"]["like_count"] == 50  # 新字段追加
```

**Acceptance:**
- 4+ 测试覆盖检测、主版本冲突、unique pending 保留、写入 _pending 子目录
- 冲突时 main 胜出，pending 版本进入 `_pending/` 子目录（不污染主树）
- 输出 `pending_decisions.csv` 报告
- **提交**：`feat(migrate): _to_recompile/ → wiki/_pending/ 决策器`

---

### Task 7: CLI 集成（`src/cli_ext/migrate_v2_cmd.py`）

**Files:**
- Create: `src/cli_ext/migrate_v2_cmd.py`
- Modify: `src/cli.py`（注册子命令）
- Create: `tests/test_wiki_migrate/test_migrate_v2_cmd.py`

**Test:**
```python
def test_dry_run_outputs_plan():
    """--dry-run 打印转换计划但不写盘"""
    from click.testing import CliRunner
    # ... invoke `python -m src.cli migrate-v2 --dry-run`
    # expect: stdout 包含 "DRY RUN", 不创建任何 wiki 文件

def test_apply_writes_files(tmp_path):
    """--apply 实际写盘"""
    # ... 用 5 张样本卡 + tmp_path 跑 --apply
    # expect: <tmp>/wiki/concepts/X.md 存在

def test_skip_quarantine_flag():
    """--skip-quarantine 时 invalid_*.md 不处理"""
    # ... 验证 .index/quarantine/ 为空

def test_skip_raw_flag():
    """--skip-raw 只迁 wiki 不迁 raw"""

def test_skip_pending_flag():
    """--skip-pending 不处理 _to_recompile"""
```

**Acceptance:**
- CLI 子命令 `python -m src.cli migrate-v2` 注册成功
- 参数 `--project <uuid> --v2-path <绝对路径>` 必填；不得依赖 CWD 或模糊 target 名称
- 支持 `--dry-run`、`--apply`、`--resume`、`--rollback --run-id <id>`；rollback 不接受无 project 的默认值
- 5+ 测试覆盖 dry-run / apply / resume / rollback / collision / 各种 skip 标志
- 输出格式：`migration-manifest.json`、`migration_report.csv`、`migration_warnings.csv`
- dry-run 不写 live target；apply 只写 staging，promotion 单独执行且有 run-id
- **提交**：`feat(cli): migrate-v2 子命令 + dry-run 报告`

---

## Phase 2：全量迁移（T8）

### Task 8: 全量迁移执行

**Files:**
- Create: `scripts/run_v2_migration.sh`（幂等启动脚本）
- Create: `docs/migration/2026-09-06-v2-migration-log.md`（执行日志）

**步骤**：
1. [x] ~~创建目标 ruflo-kb 项目：`python -m src.cli project init migration_target`~~ **已完成**（2026-09-06）：项目 `video-notes-wiki` UUID `e3a0472c-06af-41e4-8d06-083146f195f7`，capture 模板
2. [ ] T0 生成 manifest，记录源文件 hash、大小、mtime、kind、disposition；确认目标只有初始化 skeleton
3. [ ] 磁盘和 provider 预检；源 hash 快照写入 run state
4. [ ] Dry-run：`python -m src.cli migrate-v2 --project e3a0472c-06af-41e4-8d06-083146f195f7 --v2-path <绝对路径> --dry-run`
5. [ ] 人工审查 manifest、collision、warning 和 disposition 汇总
6. [ ] Apply 到 `.staging/video-notes-wiki/<run-id>/`；每个 raw/wiki 文件成功后追加对应 checkpoint
7. [ ] 对 staging 完整执行 T9 验证；未通过不得 promotion
8. [ ] 在 promotion 前重新核对源 hash；变更则 abort
9. [ ] 同卷原子替换 live target，并保留 promotion 前快照；写入 promotion marker
10. [ ] compile_db.sqlite 若存在则导出 CSV；不存在时记录 `support-artifact`，不伪造行数

**Acceptance:**
- manifest 中 3056 个 raw 文件、2082 个 wiki/support 文件均有 exactly one disposition
- 1919 张 concepts、155 张 pending、5 张 entities、1 张 invalid 按映射落位；`links.md` / `overview.md` 仅作为 support artifact
- 5 张 entity 卡 aliases 写入 `.llm-wiki/slug_aliases.json`，JSON 为 `{alias: canonical}`
- 全部 migrated/archived 文件 SHA-256 与源一致；`_skip` 保留但默认不索引
- 无未解释的 collision、failed、tag 丢失、未知字段丢失或损坏卡静默跳过
- 中断后 `--resume` 可继续；重复运行不重复 append index/log/alias
- promotion 前失败不改变 live target；rollback 只恢复当前 run 的目标快照
- **提交**：`chore(migration): 全量迁移 v2 → video-notes-wiki 项目 (UUID e3a0472c)`

---

## Phase 3：验证（T9）

### Task 9: 健康度 + 自定义验证

**Files:**
- Create: `tests/test_wiki_migrate/test_post_migration_validation.py`
- Create: `docs/migration/2026-09-06-v2-validation-report.md`

**测试清单**：

```python
# 1. disposition 闭包与文件 hash
def test_all_v2_files_present():
    """每个源文件恰有一个 disposition，已迁移文件 hash 一致。"""
    manifest = load_manifest()
    assert all(item["disposition"] in ALLOWED_DISPOSITIONS for item in manifest)
    assert not [item for item in manifest if item["disposition"] == "failed"]
    assert hashes_match_for_migrated_files(manifest)

# 2. frontmatter 完整性
def test_all_pages_have_required_v5_keys():
    """每张 wiki 卡必须有 id/title/type/sources/created_at/updated_at/relations/tags"""
    for page_path in glob("**/wiki/**/*.md"):
        fm = parse_frontmatter(page_path)
        for key in ["id", "title", "type"]:
            assert key in fm, f"{page_path} missing {key}"

# 3. wikilink 全量账本
def test_relations_field_populated():
    """每个可解析 wikilink 必须是 relation、knowledge-gap 或 self-reference。"""
    report = load_wikilink_report()
    assert report["parse_error"] == 0
    assert report["input_total"] == report["resolved"] + report["gap"] + report["self_reference"]

# 4. aliases 注册
def test_entity_aliases_registered():
    """5 张 entity 卡的 aliases 全部在 slug_aliases.json"""

# 5. quarantine 完整
def test_quarantine_preserved():
    """1 张 invalid_*.md → .index/quarantine/<slug>.md"""

# 6. raw 文件存在与分类
def test_raw_files_preserved():
    """raw disposition 完整；skip 也保留，只是不进入索引。"""
    assert raw_disposition_counts() == {
        "migrated": 2398,
        "metadata-only": 5,
        "archived": 637,
        "skipped": 16,
    }

# 7. compile_db 快照
def test_compile_db_snapshot_exists():
    """若 v2 有 compile_db.sqlite，则 snapshot 行数与 records 表一致；没有则有 support disposition。"""

# 8. ruflo-kb 原生健康度
def test_ruflo_kb_health_check_passes():
    """python -m src.cli health --project <id> H1-H10 全部 PASS"""
```

**Acceptance:**
- 10+ 测试覆盖 manifest、hash、frontmatter、tags、wikilinks、aliases、quarantine、健康度、冲突和恢复
- `validation_report.md` 输出每项的 PASS/FAIL + 详情
- 失败项必须修复（不允许“已知问题跳过”）；WARN 只能用于明确列出的非阻断信息
- 测试目标必须是 staging 或临时项目，不能用 live target 做破坏性验证
- **提交**：`test(migration): 8 项迁移验证测试`

---

## Phase 4：LanceDB + 服务（T10）

### Task 10: LanceDB 重建 + 服务冒烟

**Files:**
- Modify: `scripts/run_v2_migration.sh`（追加向量重建步骤）
- Create: `docs/migration/2026-09-06-v2-vector-rebuild-log.md`

**步骤**：
1. [ ] provider 预检：真实 embed 一次，记录 provider、dimension、超时和预计 token/cost
2. [ ] 新 LanceDB 在 `.staging/<run-id>/index/` 构建；每 100 张页面写 `rebuild_progress.jsonl`
3. [ ] 对 429/500/502/503 做最多 5 次指数退避；失败可从 checkpoint resume
4. [ ] 只对可索引页面生成向量；按 chunk manifest 验证向量行数与 chunk 数一致
5. [ ] 校验完成后再原子替换 live LanceDB；失败不得污染旧表
6. [ ] 启动 ruflo-kb 服务：`python -m src.cli serve --host 127.0.0.1 --port 19828`
7. [ ] 验证 `/health` 返回 200、项目隔离、全文检索和向量检索
8. [ ] WebUI smoke test 为非阻断项：页面无法打开不影响核心迁移验收

**Acceptance:**
- `/health` 200
- 5 个关键词全部命中 ≥3 结果
- `actual_embedding_dimension == provider_dimension`
- `vector_row_count == indexed_chunk_count`，而非 wiki 页面数
- 向量构建中断后 resume 结果与一次性构建结果一致
- **提交**：`feat(migration): LanceDB 重建 + 服务冒烟通过`

---

## Audit

- **Round 1（全面漏洞审计）**：已完成；发现 3 个致命、7 个重大问题
- **Round 1.5（整改复审）**：已完成；确认 V6/tag/acceptance 仍需落到真实代码和统一映射文档
- **Round 2（压力测试推演）**：已完成；发现中断恢复、向量限流、磁盘、冲突和回滚等 P0 风险
- **当前结论**：P0 加固完成前 NO-GO；Round 2.5 必须验证 G0-G8 后才能进入 PoC
- **Open risks**：仅保留实现阶段新增风险；任何未进入 `migration_warnings.csv` 的异常均视为失败
- **Rollback**：
  - PR 1/2/3 代码回滚使用独立 commit，禁止用数据删除代替代码回滚
  - 数据迁移只在 `.staging/<run-id>/` 进行；promotion 前失败直接删除该 staging
  - promotion 后回滚必须指定 `--project e3a0472c-06af-41e4-8d06-083146f195f7 --run-id <id>`，恢复 promotion 前快照
  - rollback 默认 dry-run，显示 project UUID、run-id、文件数和向量目录；确认后才执行
  - 禁止无 project、无 run-id 的递归删除；不得删除 v2 来源

---

## Completion evidence

- **Final commit**: Phase 4 完成后填写实际 commit hash
- **Tests**: pytest `tests/test_wiki_migrate/` 全 PASS（≥30 用例）
- **Static checks**: 无（ruflo-kb 未配 ruff/mypy）
- **Documentation updated**:
  - `docs/research/2026-09-06-v2-to-ruflo-migration-survey.md`（调研）
  - `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md`（本计划）
  - `docs/migration/2026-09-06-v2-acceptance.md`（验收清单）
  - `docs/architecture/v2-to-v6-field-mapping.md`（唯一字段映射）
  - `docs/migration/2026-09-06-v2-migration-log.md`（执行日志）
  - `docs/migration/2026-09-06-v2-validation-report.md`（验证报告）
- **Progress ledger updated**: yes
- **Knowledge memory captured**: `feedback-v2-migration.md`（沉淀迁移经验到 `.memory/`）

---

## 下一步（进入编码前必做）

1. 完成 G0-G8 P0 加固并补齐对应测试
2. 对主计划和 ADR-0008 做 Round 2.5 复审，确认“设计项”已变成“可执行项”
3. 运行 Phase 0 PoC；失败时只修复后重跑，不进入全量
4. PoC 通过后按 T0 → T10 执行，每个 Task 独立测试和提交
5. 全量 promotion 后再执行一次故障恢复演练和最终验收签字
6. 所有验收通过后，由项目所有者单独决定是否给 v2 加冻结标记；迁移器本身不修改 v2
