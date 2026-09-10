# 验收清单：LLM_Knowledge_base_v2 → ruflo-kb 数据迁移

> **配套文档**：
> - 调研报告：`docs/research/2026-09-06-v2-to-ruflo-migration-survey.md`
> - 实施方案：`docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md`
>
> **目标项目**（已创建）：
> - 路径：`D:\5-Project\20260903\llm-wiki-base\knowledge\video-notes-wiki`
> - UUID：`e3a0472c-06af-41e4-8d06-083146f195f7`
> - 模板：`capture`
>
> **日期**：2026-09-09（按 Round 1/1.5/2 审计整改）
> **使用方式**：每完成一项验收，在 `[ ]` 中填入 `[x]` 并记录实际值；任何 ❌ 必须有对应的修复 PR

---

## A. 数据完整性（量化指标）

### A1. Wiki 与 support disposition 对账

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| 主 wiki 树概念卡（concepts/）| 1919 - collision 数 | ___ | [ ] |
| 主 wiki 树实体卡（entities/）| 5 | ___ | [ ] |
| `_pending/` 子目录草稿 | 155 - 撞名数 | ___ | [ ] |
| `migration/support/`（links + overview）| 2 | ___ | [ ] |
| `_archive/` 不进 wiki 树 | 0 | ___ | [ ] |
| 总计 = concepts + entities + pending + support | 与 manifest 一致 | ___ | [ ] |

> **判定**：manifest 中每个来源文件必须 exactly one disposition；数量不能用“≥”放宽。

### A2. raw 文件数对账

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| `raw/sources/` 平台文件 | 2397（当前清单基线）| ___ | [ ] |
| `migration/legacy/` `.batch` 元数据 | 5 | ___ | [ ] |
| `raw/_archive/` 已消化归档 | 637 | ___ | [ ] |
| `raw/_seed/` 种子 | 1 | ___ | [ ] |
| `raw/_skip/` 跳过文件 | 16（保留但默认不索引）| ___ | [ ] |
| 总计 raw | 3056 | ___ | [ ] |

> **判定**：全部 migrated/archived/skipped 文件 SHA-256 与源一致；不能只验文件名或抽样数量。

### A3. SQLite 状态库快照

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| `compile_db_snapshot.csv` 行数 | 若存在 `compile_db.sqlite`，== v2 `records` 表行数；否则记录 support disposition | ___ | [ ] |
| 快照包含字段 | record_id, source_file, status, invalid_reason, compiled_at | ___ | [ ] |
| 快照存放路径 | `docs/migration/compile_db_snapshot_2026-09-06.csv` | ___ | [ ] |

---

## B. Frontmatter 转换正确性

### B1. V6 页面契约与 V5 兼容

| 字段 | 必填？ | 检查方法 | 通过 |
|---|---|---|---|
| `id` | ✅ | 每张 wiki 卡的 `id` == 文件名 stem | [ ] |
| `title` | ✅ | 抽样 50 张，title 与 v2 一致 | [ ] |
| `type` | ✅ | concepts/ → concept；entities/ → entity；无 source/synthesis | [ ] |
| `sources` | ✅（可空 list）| 1919 张概念卡中带 url 的有对应 sources 列表 | [ ] |
| `created_at` | ✅ | 抽样 20 张，created_at 是 ISO 8601 或 ms int | [ ] |
| `updated_at` | ✅ | 抽样 20 张，updated_at 是 ISO 8601 或 ms int | [ ] |
| `relations` | ✅（可空 list）| 含 wikilink 的卡有 relations | [ ] |
| `tags` | ✅（可空 list）| 规范化 tag + legacy tag 总和与 v2 原始 tag 数一致 | [ ] |
| V6 字段 | ✅ | 9 个 V6 字段真实写入 frontmatter | [ ] |

### B2. V6 顶层字段与 `_ko_extra` 保留

| 字段类别 | 抽样检查（每类抽 5 张）| 通过 |
|---|---|---|
| `version` (v2.1 / v2.1-mini) | ___ | [ ] |
| `processing_depth`（V6 顶层） | ___ | [ ] |
| `source_grade` (A/B/C，V6 顶层) | ___ | [ ] |
| `platform` (B站/抖音/...，V6 顶层） | ___ | [ ] |
| `url` | ___ | [ ] |
| `author` | ___ | [ ] |
| `category`（V6 顶层） | ___ | [ ] |
| `maturity`（`_ko_extra`） | ___ | [ ] |
| `taxonomy_sub`（V6 顶层） | ___ | [ ] |
| `use_context` (build/ops/...，V6 顶层) | ___ | [ ] |
| `workflow_state` (draft/ready/...，V6 顶层) | ___ | [ ] |
| `summary` | ___ | [ ] |
| `aliases`（仅 entity）| ___ | [ ] |
| `custom_type`（仅 entity，`instance_of` 映射）| ___ | [ ] |
| 标记 `v2_origin: true`（V6 顶层） | ___ | [ ] |

> **判定**：每个 v2 字段按字段映射表进入唯一 canonical home；V6 顶层字段和 `_ko_extra` 非核心字段均能回读，未知字段不得静默丢失。

### B3. invalid_*.md quarantine 元数据保留

| 字段 | 检查方法 | 通过 |
|---|---|---|
| `uid` | `extract_quarantine_metadata` 输出含 uid | [ ] |
| `bv` | 同上 | [ ] |
| `source` | 同上 | [ ] |
| `invalid_reason` | 同上 | [ ] |
| `uploader` | 同上 | [ ] |
| `video_published_at` | 同上 | [ ] |
| `judgments.jsonl` 一致 | 每张 quarantine 卡 1 行记录 | [ ] |

---

## C. wikilink 网络保留

### C1. wikilink 解析覆盖率

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| 总 wikilink 数（v2 wiki 体）| 全量扫描 | ___ | [ ] |
| 已解析或进入 knowledge-gap 的 wikilink 数 | == 总数 | ___ | [ ] |
| self-reference 已剔除 | 100% | ___ | [ ] |
| 不同形态 wikilink 都被支持 | BV 号 / 抖音 ID / 中文标题 / 别名 | [ ] |

### C2. 断链报告

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| v2 自身断链数 | 全量扫描 | ___ | [ ] |
| 迁移后断链数 | 不新增；原有断链逐条可追溯 | ___ | [ ] |
| 断链处理 | relation 或 `.index/knowledge_gaps.json` 均有记录，保留原始文本 | ___ | [ ] |

### C3. aliases 解析

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| 5 张 entity 卡 aliases 数量 | `Obsidian: [OB]` 1 项；`Claude Code: 2 项`；其他合计 | ___ | [ ] |
| `slug_aliases.json` 文件存在 | `.llm-wiki/slug_aliases.json` | ___ | [ ] |
| `[[ClaudeCode]]` 链接可解析 | 通过 `SlugAliasRegistry.get_canonical` 找到 "claude-code" | [ ] |

---

## D. ruflo-kb 原生健康度

### D1. 健康检查 10 项

执行：`python -m src.cli health --project <id>`

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| H1 DB 一致性 | PASS | ___ | [ ] |
| H2 文件存在 | PASS | ___ | [ ] |
| H2.5 wiki_pages 存在 | PASS | ___ | [ ] |
| H3 断链 | PASS（断链数 ≤ v2 自身）| ___ | [ ] |
| H4 done 比例 | PASS | ___ | [ ] |
| H5 密度（单 taxonomy_sub ≤ 150）| WARN 或 PASS | ___ | [ ] |
| H6 漂移 | PASS | ___ | [ ] |
| H7 标签命名空间 | PASS 或 WARN（v2 标签前缀需要适配）| ___ | [ ] |
| H8 use_context 覆盖率 | PASS（v2 缺 use_context → WARN）| ___ | [ ] |
| H9 workflow_state 分布 | PASS（v2 缺 workflow_state → WARN）| ___ | [ ] |
| H10 verified 超期 | PASS | ___ | [ ] |

> **判定**：PASS 视为通过；WARN 视为已知可接受；FAIL 必须修复。

### D2. schema-routing 一致性

执行：`python -m src.cli fields validate --all --project <id>`

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| 概念卡全在 `wiki/concepts/` | 100% | ___ | [ ] |
| 实体卡全在 `wiki/entities/` | 100% | ___ | [ ] |
| 无 source/synthesis 类型混在 | 100% | ___ | [ ] |

### D3. tag 命名空间校验

执行：`python -m src.cli tags validate --all --project <id>`

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| v2 标签 `tool/AI编程` 等通过 | 是（v2 已在白名单中）| ___ | [ ] |
| 不合规标签数 | 0 | ___ | [ ] |

---

## E. LanceDB 向量重建

### E1. 向量索引完整性

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| `init_vector_store_for_paths(WikiPaths)` 成功 | yes | ___ | [ ] |
| 全量 upsert 成功 | yes | ___ | [ ] |
| lancedb 行数 == indexed chunk 数 | 以 `rebuild_progress.jsonl` manifest 为准 | ___ | [ ] |
| 向量维度 | == provider 实际返回维度 | ___ | [ ] |
| provider 预检 | embed 成功 + dimension 已记录 | ___ | [ ] |
| 中断恢复 | resume 后结果与一次性构建一致 | ___ | [ ] |

### E2. 检索冒烟

执行：`python -m src.cli search --project <id> --query "<关键词>"`

| 关键词 | 预期命中数 | 实际 | 通过 |
|---|---|---|---|
| Claude Code | ≥ 5（含 entities 卡）| ___ | [ ] |
| Obsidian | ≥ 3 | ___ | [ ] |
| 网文创作 | ≥ 5 | ___ | [ ] |
| AI 编程 | ≥ 5 | ___ | [ ] |
| Prompt 工程 | ≥ 3 | ___ | [ ] |

### E3. 服务冒烟

执行：`python -m src.cli serve --host 127.0.0.1 --port 19828`

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| 服务启动 | 无 error | ___ | [ ] |
| `GET /health` | 200 | ___ | [ ] |
| `GET /api/v1/projects/<id>/search?q=...` | 返回 ≥ 1 命中 | ___ | [ ] |
| WebUI `http://127.0.0.1:19828/web/` | 页面加载（可选） | ___ | [ ] |

---

## F-bis. 平台+视频 ID 追溯能力（关键 · 用户决策）

### F-bis-1. 5 重追溯链路完整性

**检查方法**：每张适用的 wiki 卡必须通过全部可用追溯通道；缺失原始字段只能标记为 source-data-missing，不得伪造或静默跳过：

| 通道 | 字段 | 检查方式 | 通过 |
|---|---|---|---|
| 1. WikiPage.id | 文件名 | 与 v2 文件 stem 完全一致 | [ ] |
| 2. sources[0] | 原始 URL | URL 模板能解析出 platform + video_id | [ ] |
| 3. `platform` | 平台标识 | 值 ∈ {B站, 抖音, 小红书, 公众号, 知乎, 播客, ...} | [ ] |
| 4. `_ko_extra.video_id` | 平台视频 ID | 非空 OR 标记 `_v2_needs_manual_url_review=true` | [ ] |
| 5. raw/sources/ 同名文件 | 转录稿正文 | 文件存在且 size > 0 | [ ] |

### F-bis-2. B 站 BV 号追溯

抽样 50 张 B 站卡，验证：

| 检查项 | 预期 | 通过 |
|---|---|---|
| `id` 以 `BV` 开头 | 100% | [ ] |
| `platform == "B站"` | 100% | [ ] |
| `_ko_extra.bv` 与 id 一致 | 100% | [ ] |
| `sources[0]` URL 含 `bilibili.com/video/` | 100% | [ ] |
| URL 末尾 = bv 值 | 100% | [ ] |
| **URL 真实可访问（HEAD 请求）** | ≥ 95% | [ ] |

### F-bis-3. 抖音 ID 追溯

抽样 30 张抖音卡：

| 检查项 | 预期 | 通过 |
|---|---|---|
| `id` 是 19 位纯数字 | 100% | [ ] |
| `platform == "抖音"` | 100% | [ ] |
| `_ko_extra.video_id` 是 19 位数字 | 100% | [ ] |
| `sources[0]` URL 含 `douyin.com/video/` | 100% | [ ] |

### F-bis-4. 小红书追溯

抽样 20 张小红书卡：

| 检查项 | 预期 | 通过 |
|---|---|---|
| `platform == "小红书"` | 100% | [ ] |
| URL 模板 `xiaohongshu.com/explore/<id>` 可生成 | ≥ 80% | [ ] |
| CJK 标题文件标记 `_v2_needs_manual_url_review` | 100% | [ ] |

### F-bis-5. WebUI 一键回溯

执行 `python -m src.cli serve`，访问 WebUI：

| 检查项 | 预期 | 通过 |
|---|---|---|
| 卡片详情页有"原视频"按钮 | 是 | [ ] |
| 按钮点击跳转到 sources[0] URL | 是 | [ ] |
| 缺 URL 的卡显示 ⚠️ 待补 URL 标记 | 是 | [ ] |

### F-bis-6. 追溯批量验证脚本

```python
# scripts/verify_video_traceability.py
def verify_all_video_ids():
    """批量验证 5 重追溯链路"""
    from src.lib.project import resolve_project
    from src.wiki.storage.page_writer import read_page
    from pathlib import Path
    
    ctx, paths = resolve_project("video-notes-wiki")
    issues = {"missing_url": [], "missing_bv": [], "missing_raw": [], "missing_video_id": []}
    
    for md in paths.wiki_sources.rglob("*.md"):
        page = read_page(md)
        fm = page.to_frontmatter_dict()
        ko = fm.get("_ko_extra", {})
        
        if not fm.get("sources"):
            issues["missing_url"].append(md.name)
        if ko.get("platform") == "B站" and not ko.get("bv"):
            issues["missing_bv"].append(md.name)
        if ko.get("platform") in {"抖音", "小红书"} and not ko.get("video_id") and not ko.get("_v2_needs_manual_url_review"):
            issues["missing_video_id"].append(md.name)
        if not (paths.raw_sources / md.name).exists():
            issues["missing_raw"].append(md.name)
    
    return issues
```

**Acceptance**：执行后每个 issue 都能在 manifest 或 source-data-missing 报告中解释；迁移新增 issue 必须为 0。

---

## F. 性能与规模

### F1. 迁移脚本性能

| 检查项 | 预期 | 实际 | 通过 |
|---|---|---|---|
| 全量迁移 2079 张页面（不含 support）耗时 | 记录基线；不得以 60 秒作为硬门 | ___ | [ ] |
| raw 3056 文件处理耗时 | 记录基线；不得以固定机器时间作为硬门 | ___ | [ ] |
| LanceDB 全量 upsert 耗时 | ≤ 30 分钟（依赖 LLM 服务） | ___ | [ ] |
| 内存峰值 | ≤ 1 GB | ___ | [ ] |

### F2. 检索响应时间

| 查询类型 | 预期 P95 | 实际 | 通过 |
|---|---|---|---|
| 关键词搜索 | ≤ 200 ms | ___ | [ ] |
| 语义搜索（top 10）| ≤ 500 ms | ___ | [ ] |
| RRF 混合搜索 | ≤ 800 ms | ___ | [ ] |

---

## G. 文档与可追溯性

### G1. 文档完整性

| 文档 | 路径 | 检查 | 通过 |
|---|---|---|---|
| 调研报告 | `docs/research/2026-09-06-v2-to-ruflo-migration-survey.md` | 存在 + 完整 | [ ] |
| 实施方案 | `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md` | 存在 + 完整 | [ ] |
| 验收清单（本文件）| `docs/migration/2026-09-06-v2-acceptance.md` | 存在 + 全部勾选 | [ ] |
| 执行日志 | `docs/migration/2026-09-06-v2-migration-log.md` | 存在 + 时间戳完整 | [ ] |
| 验证报告 | `docs/migration/2026-09-06-v2-validation-report.md` | 存在 + 全项 PASS | [ ] |
| 向量重建日志 | `docs/migration/2026-09-06-v2-vector-rebuild-log.md` | 存在 | [ ] |
| compile_db 快照 | `docs/migration/compile_db_snapshot_2026-09-06.csv` | 存在 + 行数匹配 | [ ] |
| migration_report.csv | 迁移输出目录 | 存在 + 行数 == 2079+ | [ ] |
| feedback 经验沉淀 | `.memory/feedback-v2-migration.md` | 存在 | [ ] |

### G2. ADR 提案（可选）

如 `_ko_extra` 字段对未来 V6 风险成立，建议追加：

| 提案 | 路径 | 检查 | 通过 |
|---|---|---|---|
| ADR：v2 → ruflo-kb 字段迁移策略 | `docs/adr/2026-09-06-v2-to-ruflo-migration-strategy.md` | 存在 + 经审 | [ ] |

---

## V. V6 Schema 扩展合规性（ADR-0008 · 2026-09-06 用户选定路径 X）

> **完整决策记录**：`docs/adr/0008-v6-wiki-schema-extension-for-v2-migration.md`
> **目的**：修复 Plan-Audit Round 1 致命缺陷 ①-1（`_ko_extra` 不持久化）+ ①-2（v2 tag 不兼容）+ ②-7（验收方法 bug）

### V-1. PR 1 验收：V6 WikiPage dataclass + 17-key 写盘

| 检查项 | 期望 | 实际 | 通过 |
|---|---|---|---|
| WikiPage 字段数 | 18 → 27 | ___ | [ ] |
| `to_frontmatter_dict()` 输出 key 数 | 8 → 17 | ___ | [ ] |
| V5 8-key frontmatter round-trip 字节级一致 | 是（novel-wiki 抽样 50 张）| ___ | [ ] |
| V6 17-key frontmatter round-trip 字节级一致 | 是（v2 抽样 50 张）| ___ | [ ] |
| V6 字段缺失填默认值（不报错） | 是 | ___ | [ ] |
| `_ko_extra` 逃生口保留 | 是 | ___ | [ ] |
| 测试用例数（PR 1 新增）| ≥ 5 | ___ | [ ] |

### V-2. PR 2 验收：V6 Tag Namespace 扩展

| 检查项 | 期望 | 实际 | 通过 |
|---|---|---|---|
| TAG_PREFIXES 新增前缀 | 5（tool/scene/status/media/author）| ___ | [ ] |
| `validate_tag_compliance` 新参数 | `page_type=None, platform=None` | ___ | [ ] |
| v2 free-form tag 不 raise | 是（抽样 50 个 v2 tag）| ___ | [ ] |
| source 卡 + video platform 仍需 mandatory pair | 是 | ___ | [ ] |
| concept / entity / synthesis 卡不强制 mandatory | 是 | ___ | [ ] |
| 测试用例数（PR 2 新增）| ≥ 4 | ___ | [ ] |

### V-3. PR 3 验收：V6 Migration Tools 全套

| 检查项 | 期望 | 实际 | 通过 |
|---|---|---|---|
| T0-T10 + T10.0 Task 全部提交 | 是（12 个 commit）| ___ | [ ] |
| 1919 张 v2 概念卡成功迁移 | 是 | ___ | [ ] |
| 5 张 v2 entity 卡成功迁移 + aliases 注册 | 是 | ___ | [ ] |
| 1 张 v2 invalid 卡进 quarantine + 全字段保留 | 是 | ___ | [ ] |
| 3056 raw 文件均有 disposition + SHA-256 对账 | 是 | ___ | [ ] |
| 12+ v2 业务字段 round-trip 一致 | 100% | ___ | [ ] |
| LanceDB 全量重建 | indexed chunk manifest 全部完成 | ___ | [ ] |
| 5 个关键词检索全部 ≥3 命中 | 是 | ___ | [ ] |

### V-4. V6 Backward Compatibility（不破坏现有 KB）

| 检查项 | 期望 | 实际 | 通过 |
|---|---|---|---|
| novel-wiki 现有卡字段语义不变 | 是；不要求 V6 YAML byte-level 不变 | ___ | [ ] |
| novel-wiki V5 8-key frontmatter 仍可读 | 是 | ___ | [ ] |
| novel-wiki `python -m src.cli health --project novel-wiki-id` H1-H10 全 PASS | 是 | ___ | [ ] |
| `python -m src.cli project list` 含 novel-wiki + video-notes-wiki | 是 | ___ | [ ] |

### V-5. V6 字段在磁盘的真实持久化（关键 · 修复 ①-1）

> 这是原 Plan-Audit 致命缺陷 ①-1 的根本修复验证

```python
# scripts/verify_v6_persistence.py
def verify_v6_fields_persisted():
    """V6 字段必须真实写入磁盘，不只是内存"""
    from src.lib.project import resolve_project
    from src.wiki.storage.page_writer import read_page
    import yaml
    
    ctx, paths = resolve_project("video-notes-wiki")
    
    # 抽样 50 张迁移后的卡
    for md in list(paths.wiki_concepts.glob("*.md"))[:50]:
        text = md.read_text(encoding="utf-8")
        # 提取 frontmatter
        end = text.find("\n---", 4)
        fm_text = text[4:end]
        fm = yaml.safe_load(fm_text) or {}
        
        # V6 关键字段必须在 frontmatter（新-5 修复：增 capture_type）
        for v6_key in ["processing_depth", "source_grade", "platform",
                       "category", "taxonomy_sub", "use_context",
                       "workflow_state", "v2_origin", "capture_type"]:
            assert v6_key in fm, f"{md.name}: missing {v6_key} in frontmatter"
        
        # platform 必须是 B站/抖音/小红书 之一（v2 数据特征）
        assert fm["platform"] in {"B站", "抖音", "小红书", "公众号", "知乎", "其他", ""}
        
        # v2_origin 必须 True（v2 迁移标记）
        assert fm["v2_origin"] is True, f"{md.name}: v2_origin not True"
```

**Acceptance:** 50/50 张卡全部通过 → V6 schema 升级成功修复 ①-1。

---

## K. D1-D9 决策合规性（用户确认 · 2026-09-06）

> 完整决策记录：`docs/research/2026-09-06-v2-to-ruflo-migration-survey.md` §12
> 本章把决策转成可执行验收项；任何 ❌ 表示决策未被落地。

| # | 决策 | 验收方法 | 期望 | 实际 | 通过 |
|---|---|---|---|---|---|
| **D1** | `_to_recompile/` 155 草稿 → `wiki/_pending/` 子目录 | manifest + 目录扫描 | 1919 - concepts collision 数（无草稿混进主树）| ___ | [ ] |
| **D1** | 主版本胜出，pending 标识 | manifest + 目录扫描 | 155 - pending collision 数 | ___ | [ ] |
| **D1** | pending_decisions.csv 存在 | `ls docs/migration/pending_decisions.csv` | 存在 | ___ | [ ] |
| **D2** | `_archive/` 637 → `raw/_archive/` | `find raw/_archive -type f \| wc -l` | 637 | ___ | [ ] |
| **D2** | SHA-256 校验一致 | PowerShell `Get-FileHash -Algorithm SHA256` 比对 v2 与目标 | 全部一致 | ___ | [ ] |
| **D3** | V6 + `_ko_extra` 字段保留 | 按 `docs/architecture/v2-to-v6-field-mapping.md` 抽样 50 张卡，字段 read → write → read 一致 | 100% | ___ | [ ] |
| **D3** | `v2_origin: true` 标记 | 抽样 20 张卡 → 顶层 `v2_origin == True` | 100% | ___ | [ ] |
| **D3** | `confidence` 字段保留（③-1 修复）| 抽样 50 张卡 → 按字段映射表回读，来源值一致 | 100% | ___ | [ ] |
| **D4** | raw 文件名不加平台前缀 | `ls raw/sources/` 无 `bilibili__` / `douyin__` / `xiaohongshu__` 前缀 | 无前缀 | ___ | [ ] |
| **D4** | 撞名报告 | `docs/migration/raw_filename_collisions.csv` | 行数 == manifest collision 数 | ___ | [ ] |
| **D4** | `--on-collision` 默认 fail | 撞名时迁移器 abort | 是 | ___ | [ ] |
| **D5** | entity aliases 写入 slug_aliases.json | `cat .llm-wiki/slug_aliases.json` | 含 5 张 entity 卡 | ___ | [ ] |
| **D5** | **正向格式**（②-1 修复）| JSON 结构是 `{"alias": "canonical"}` 不是 `{"canonical": [aliases]}` | 正向 | ___ | [ ] |
| **D5** | canonical = file stem | "Claude Code" → "Claude Code"，"Obsidian" → "Obsidian" | 全部一致 | ___ | [ ] |
| **D6** | invalid_*.md 进 quarantine | `find .index/quarantine -name "*.md" \| wc -l` | 1 | ___ | [ ] |
| **D6** | judgments.jsonl 1 行 | `cat .index/quarantine/judgments.jsonl \| wc -l` | 1 | ___ | [ ] |
| **D6** | 元数据全保留 | 读 quarantine 卡 → 含 uid/bv/source/uploader/video_published_at/invalid_reason | 全部 | ___ | [ ] |
| **D7** | v2 Changelog 追加条目 | 验收通过后由项目所有者单独执行；迁移器不得写 v2 | 人工确认 | ___ | [ ] |
| **D7** | v2 标注冻结 | 同上动作含“冻结 / 停止维护”，且迁移前备份存在 | 含 | ___ | [ ] |
| **D8** | 单次全量迁移 | 一次 `python -m src.cli migrate-v2 --project <uuid> --v2-path <绝对路径> --apply` 完成 | 1 次执行 | ___ | [ ] |
| **D8** | checkpoint/resume | 注入中断后 `--resume` 不重复、不漏数据 | 工作 | ___ | [ ] |
| **D8** | 精确回滚 | `--rollback --project <uuid> --run-id <id>` 只恢复本 run | 工作 | ___ | [ ] |
| **D9a** | 概念卡 `type == "concept"` | 抽样 50 张卡 → 100% 在 `wiki/concepts/` 且 frontmatter `type: concept` | 100% | ___ | [ ] |
| **D9a** | body 顶部 capture marker | 抽样 50 张卡 → 100% 以 `<!-- capture-type: video-transcript -->` 开头 | 100% | ___ | [ ] |
| **D9a** | `capture_type` 字段写入 frontmatter | 抽样 50 张卡 → 100% 含 `capture_type: video-transcript` | 100% | ___ | [ ] |
| **D9a** | 视频回溯走 `_ko_extra.video_id` | 50 张 B 站/抖音卡 → `_ko_extra.video_id` 非空 | 100% | ___ | [ ] |

**D1-D9、G0-G8 全部通过才能进入 Phase 4（向量重建）**。

> **Round 1.5 复审修复（2026-09-06）**：
> - ③-1 wiki_pages.confidence 字段保留（验收项已加 `_ko_extra.confidence`）
> - ②-1 slug_aliases 正向格式（验收项已加 "JSON 结构是 `{alias: canonical}`"）
> - 新-4 删除旧版 D1-D8 重复段落（上方已合并到新版 §K D1-D9 表）

> 完整决策记录：`docs/research/2026-09-06-v2-to-ruflo-migration-survey.md` §12
> 本章把决策转成可执行验收项；任何 ❌ 表示决策未被落地。

---

## G. P0 运行安全门（Round 2 整改）

| 门 | 验收方法 | 期望 | 实际 | 通过 |
|---|---|---|---|---|
| G0 manifest 闭包 | manifest 汇总 | 3056 raw + 2082 wiki/support 全部 exactly one disposition | ___ | [ ] |
| G1 V6 持久化 | read → write → read | V6 顶层字段与 `_ko_extra` 100% 可回读 | ___ | [ ] |
| G2 标签与未知字段 | 对账原始 tags / legacy tags / unknown fields | 无静默丢失 | ___ | [ ] |
| G3 checkpoint/resume | 中断后重新执行 | 不重复、不漏数据 | ___ | [ ] |
| G4 精确回滚 | 注入 promotion 前后失败 | 只影响指定 project + run-id | ___ | [ ] |
| G5 冲突保护 | 目标放入非本 run 页面 | abort，不覆盖 | ___ | [ ] |
| G6 provider 预检 | 实际 embed 一次 | provider、维度、限流策略均记录 | ___ | [ ] |
| G7 向量原子替换 | 新旧 LanceDB 切换演练 | 新表未完成时旧表可用 | ___ | [ ] |
| G8 磁盘预检 | apply 前计算空间 | 源大小 + 临时空间 + 5 GB 余量 | ___ | [ ] |

**G0-G8 任一失败即 NO-GO。**

---

## H. 故障判定矩阵（Go/No-Go）


| 场景 | 判定 |
|---|---|
| A1/A2 文件数对账偏差 > 0 | **NO-GO**，需修复 |
| G0-G8 任一 P0 安全门失败 | **NO-GO** |
| B1 任一 V5 8-key 缺失 | **NO-GO** |
| B2 任一 V6/_ko_extra 字段不可回读 | **NO-GO** |
| C1 存在未进入 relation/gap 的 wikilink | **NO-GO** |
| C2 断链数 > v2 自身断链数 | **NO-GO** |
| D1 任一 H 状态 FAIL | **NO-GO** |
| D3 任一原始 tag 无规范化结果或 legacy 记录 | **NO-GO** |
| E1 向量行数不匹配 | **NO-GO** |
| E1 向量维度不等于 provider 实际维度 | **NO-GO** |
| E2 任一关键词 0 命中 | **NO-GO** |
| E3 /health 非 200 | **NO-GO** |
| F1 任一耗时超阈值 2x | **WARN** |
| G1 任一文档缺失 | **NO-GO** |

---

## I. 验收签字

| 角色 | 姓名 | 日期 | 签字 |
|---|---|---|---|
| 执行者 | ___ | ___ | __________ |
| 审查者 | ___ | ___ | __________ |
| 项目所有者 | ___ | ___ | __________ |

---

## J. 验收后动作（Post-acceptance）

1. [ ] **v2 vault 冻结**：验收通过后由项目所有者单独追加「v2 已迁出」条目；迁移器不得写 v2
2. [ ] **ruflo-kb 端启用迁移项目**：`python -m src.cli project select <id>`
3. [ ] **保留 v2 原始库**：至少保留迁移前备份和原始 hash；删除源文件属于另行授权的破坏性操作，不属于迁移流程
4. [ ] **更新 user-preferences**：v2 vault 不再维护
5. [ ] **MEMORY.md 更新**：追加迁移经验索引

---

**验收清单结束 · 总计 13 大类 · 60+ 检查项**
