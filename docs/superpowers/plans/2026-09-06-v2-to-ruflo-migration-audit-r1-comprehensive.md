# Plan-Audit Round 1 综合报告：v2 → ruflo-kb 数据迁移

> **审计人**：独立第三方 subagent（含事实核查）
> **审计日期**：2026-09-06
> **待审方案**：v2 → ruflo-kb 数据迁移（status: ready-for-audit → ❌ 拒绝）
> **审计范围**：调研报告 + 实施方案 + 验收清单（约 1700 行）
> **总体判定**：❌ **必须整改后复审**

## 数据升级

| 维度 | 初版报告 | 综合报告 |
|---|---|---|
| 致命缺陷 | 3 | **4** |
| 重大隐患 | 7 | **8** |
| 优化疏漏 | 9 | **9** |
| 总问题数 | 19 | **21** |

## 新增发现（综合 subagent 深入审核后）

| 编号 | 级别 | 问题 |
|---|---|---|
| **①-2** | 致命 | `capture._TYPE_MAP` 把 `video-transcript → source`，与 v2 concepts 路径硬冲突（需用户拍板 D9）|
| **①-4** | 致命 | LanceDB `DEFAULT_EMBEDDING_DIM=384` 不是 1536；video-notes-wiki 没配 LLM provider |
| **②-1** | 重大 | `slug_aliases.json` 实际是正向 `{alias: canonical}`，方案假设反向格式 `{canonical: [aliases]}` 错 |
| **②-3** | 重大 | `write_page` 内部调 `rewrite_wikilinks` 静默改 body |
| **②-4** | 重大 | `_to_recompile/` pending 富元数据（uploader/view_count/like_count）迁移后永久丢失 |
| **②-5** | 重大 | Phase 4 失败时 Phase 1-3 已写入无回滚 |
| **②-7** | 重大 | `<!-- capture-type: video-transcript -->` marker 注入在 T1-T7 没实现 |

---

## 致命缺陷 ①（4 项 · 必须修复才能进入编码）

### ①-1 `_ko_extra` 字段不会持久化到磁盘（与初版报告一致）

- **漏洞位置**：调研报告 §4.2/§5 + 实施方案 D3 决策 + T1 测试 `assert out["_ko_extra"]["version"] == "v2.1"`
- **事实核查**：
  - `src/wiki/core/types.py:215-224` `to_frontmatter_dict()` 只输出 8-key V5 白名单
  - `src/wiki/storage/page_writer.py:125-132` `yaml.dump(page.to_frontmatter_dict(), ...)` 写盘不包含 `_ko_extra`
  - `src/wiki/core/types.py:263` `from_dict()` 读 `_ko_extra` 前提是该字段真在磁盘 frontmatter
- **风险后果**：1919 张卡的 processing_depth / source_grade / use_context / workflow_state / platform / category / taxonomy_sub / maturity / version / summary / instance_of **全部丢失**
- **真实案例**：T1 把 v2 frontmatter 转 WikiPage → 写盘 → 12+ 字段全无 → 验收 B2 FAIL
- **整改**：路径 X（ADR-0008）—— V6 schema 把 9 字段直接写盘

### ①-2 capture 模板 type 映射与 v2 concepts 路径硬冲突（**新发现**）

- **漏洞位置**：调研报告 §4.3/§15 + 实施方案 T1 `assert out["type"] == "concept"` + 验收 §D2
- **事实核查**：`src/services/capture.py:118-122` `_TYPE_MAP` 写死：`video-transcript → source`、`article → source`、`inspiration → concept`
- **冲突分析**：
  - 方案要求：v2 卡是 concept → 落 `wiki/concepts/`
  - capture 语义：video-transcript → 落 `wiki/sources/`
  - **二者互斥**：`write_page` 根据 PageType 决定落盘目录
- **真实案例**：迁移后用户找 `BV1xxx`，可能在 `concepts/`（v2 路径）找到"方法论"，但 capture video-transcript 视图过滤 type=source，**看不到 v2 内容**
- **整改**：**必须新增 D9 决策由用户拍板**：
  - **D9a**：`type: concept`（与 v2 文件位置一致；视频回溯走 `_ko_extra.video_id`）— **推荐**
  - **D9b**：`type: source`（应用 capture video-transcript 语义；loss 编译信息）

### ①-3 v2 tag 与 ruflo-kb 强制校验冲突（与初版报告一致）

- **漏洞位置**：调研报告 §5 `tags` 直映 + §9 R4（标"中"但实际"高"）+ 验收 §D3
- **事实核查**：
  - `src/wiki/features/tag_namespace.py:18-31` TAG_PREFIXES 仅 12 个中文前缀，无 `tool/scene/status/AI编程`
  - `MANDATORY_PAIRS = [("素材", "ugc"), ("可信度", "ugc")]` 强制要求
  - v2 1919 张卡的 tags 是无斜杠中文（`[网文创作, 读者视角, 自审方法, 写作技巧]`）
- **风险后果**：`is_valid()` 返回 False → `validate_tag_compliance()` raise TagValidationError → **第 1 张卡就中断**
- **整改**：V6 tag 命名空间（ADR-0008 PR 2）+ 迁移器主动 `normalize_tags()` + 补 mandatory pairs + 保留原 tag 到 `_ko_extra.original_tags`

### ①-4 LanceDB 维度与 provider 配置在 Phase 4 完全未规划（**新发现**）

- **漏洞位置**：实施方案 T10 步骤 3 + 验收 §E1 "向量维度 1536"
- **事实核查**：
  - `src/vector/store.py:39` `DEFAULT_EMBEDDING_DIM = 384`（不是 1536）
  - `src/cli_ext/vector_cmd.py` 只注册 `status` + `reconcile`，**无 `rebuild`**
  - video-notes-wiki 项目**没有 LLM provider 配置**（`~/.config/ruflo-kb/llm-providers.json` 不存在）
  - `embedding_runtime.get_embedding_provider()` 抛 RuntimeError
- **风险后果**：
  - `vector reconcile` 调 `_embed_and_upsert()` → provider is None → "no embedding provider configured" → 返回 False → 0 卡处理
  - 即便 reconcile 工作，1924 张卡的 `mark_pending` 在手工 dump 路径下不会被调用（因为绕过 `write_page`）
  - 验收 §E1 "lancedb 行数 == wiki 卡数" → 0 vs 2079 → FAIL
  - 验收 §E2 5 个关键词检索 → 0 命中 → FAIL
- **整改**：
  - T10 前置新增 `python -m src.cli vector rebuild-all --project <id>` 子命令
  - 维度用 `expected_dim=embedding_provider.dim()` 而非写死
  - Phase 0 PoC 之前要求用户**预先配置 embedding provider**（`python -m src.cli llm-providers add ...`）
  - 迁移器**显式调** `mark_pending(paths, pages)`

---

## 重大隐患 ②（8 项 · 应该修复）

### ②-1 `slug_aliases.json` 写入格式与 ruflo-kb schema 不一致（**新发现**）

- **漏洞位置**：决策 D5 + 验收 §K-D5 + 实施方案 T3 测试
- **事实核查**：`src/wiki/features/slug_aliases.py:57` `self.aliases: dict[str, str]` 正向 `{alias: canonical}`，**不是反向**
- **风险后果**：
  - 方案 T3 写出 `{"Claude Code": ["claude-code", "ClaudeCode"]}` → 反向格式
  - `_load()` 第 71 行重建 `aliases_rev` 但基于正向 map 创建 → `get_canonical("ClaudeCode")` 返回 None（正向 map 无此 key）
  - wikilink `[[ClaudeCode]]` 解析失败 → 断链入 `KnowledgeGapStore`
- **真实案例**：T7 dry-run 时 alias chain 解析失败 → C3 FAIL
- **整改**：
  - T3 改用正向格式：`{"claude-code": "Claude Code", "ClaudeCode": "Claude Code"}`
  - canonical 应该是 v2 文件名 stem（带空格）而非 slugify 后版本

### ②-2 raw 文件实际撞名 126 个（**新发现 · 数据已实测**）

- **漏洞位置**：调研报告 §7.2 + 决策 D4 + 验收 §K-D4
- **实测数据**：v2 全部 2402 raw 文件中 126 个撞名（跨平台）
- **风险后果**：
  - D4 默认行为未定义（覆盖？跳过？报错？）
  - 验收 §K-D4 要求"撞名报告 0 行" → 实际 126 行 → FAIL
  - 真实迁移时后遍历的覆盖先遍历的 → **至少一个平台文件数据丢失**
- **整改**：
  - 默认行为定义：`--on-collision {skip, overwrite, fail}`（推荐默认 `fail`）
  - dry-run 强制输出撞名报告（即使期望 0 行）
  - 验收 §K-D4 改为"撞名报告 ≤ 126 行；每行含 src_path / dst_path / suggested_resolution"

### ②-3 wikilink 形态被 `rewrite_wikilinks` 静默修改（**新发现**）

- **漏洞位置**：调研报告 §6 + 实施方案 T2
- **事实核查**：`src/wiki/storage/page_writer.py:120-122` `page.body = materialize_relations(rewrite_wikilinks(page.body, target_slugs), ...)`
- **风险后果**：
  - 1919 张卡的 `[[xxx]]` 大部分被改写为 `[[dir/xxx]]` 形式 → v2 原 body 形态被破坏
  - `target_slugs` 是动态构建 → 同一项目 body 形态混杂
- **整改**：
  - 方案 A：接受 rewrite，迁移后统一 body 形态
  - **方案 B（推荐）**：迁移器手工 `yaml.dump + safe_write`，完全绕过 `write_page`

### ②-4 `_to_recompile/` 草稿富元数据丢失（**新发现**）

- **漏洞位置**：决策 D1 + 实施方案 T6
- **实测对比**：
  - main `BV1AtwLzTEtB.md` 3498 字节，frontmatter 含 `version/processing_depth/workflow_state/summary`
  - pending `_to_recompile/BV1AtwLzTEtB.md` 925 字节，frontmatter 含 **`bv/uploader/view_count/like_count/favorite_count/video_published_at`**
- **风险后果**：pending 的 view_count/uploader 等数据对评估视频热度、UP 主识别很重要；方案 D1 把 pending 移到 `wiki/_pending/`，**永久归档**这些字段
- **整改**：
  - pending 的 `_ko_extra.view_count/uploader/video_published_at` 等**追加到 main 的 `_ko_extra`**
  - 或：pending 不入 `_pending/`，原始 frontmatter 完整迁移到 `<slug>.md.bak.json`（JSON 备份）

### ②-5 Phase 4 全部失败但 Phase 1-3 数据已写入无回滚（**新发现**）

- **漏洞位置**：实施方案 Phase 1-4 线性 + 验收 §H 故障矩阵
- **风险后果**：
  - Phase 1-3 完成 → 1924 张 wiki 卡 + 2180 raw + 5 entity aliases + 1 quarantine 已写入
  - Phase 4 步骤 3 `vector rebuild` 命令不存在 → Phase 4 FAIL
  - 验收 §H 故障矩阵只对最终结果判定，Phase 4 FAIL 但数据半残 → 用户体验差
- **整改**：
  - Phase 4 必须有**回滚触发器**：步骤 3 命令不存在时立即终止整个 migration，**回滚 Phase 1-3 已写入的数据**
  - 或：Phase 4 改为**前置步骤**（在 Phase 3 之前验证 vector 命令可用 + provider 可配）
  - 验收 §H 增加新场景："Phase 4 任一步骤 FAIL → NO-GO，触发全量回滚"

### ②-6 迁移器假设 `python -m src.cli` 在正确 CWD 下能找到 video-notes-wiki（**新发现**）

- **漏洞位置**：实施方案 T7 + T8 `--target <target>` 参数化
- **事实核查**：`src/lib/project.py:31` `ProjectContext.resolve()` 依赖全局注册表 + CWD `.llm-wiki/project.json` 探测
- **风险后果**：
  - `--target` 参数语义在方案中没定义（项目名？UUID？路径？）
  - PowerShell 的 `Set-Location "D:\5- 项目\..."` 切换 CWD 后相对路径解析错误
  - 中文+空格路径在 PowerShell 下不稳定
- **整改**：
  - 实施方案明确定义 `--target` 参数语义
  - 迁移脚本开头显式 `cd knowledge/video-notes-wiki` 或用绝对路径
  - PowerShell 脚本用 `pathlib.Path` 而非 shell 字符串拼接

### ②-7 capture 子类型 marker 注入未在任何 Task 实现（**新发现**）

- **漏洞位置**：调研报告 §15 承诺
- **事实核查**：`src/services/capture.py:226` `body = f"<!-- capture-type: {type} -->\n\n{body}"` 是 capture 服务固定行为
- **风险后果**：
  - T1-T7 没有任何 Task 负责"在 v2 body 顶部插入 `<!-- capture-type: video-transcript -->`"
  - WebUI 的"按捕获类型筛选"功能依赖 body 含 marker → 1919 张迁移卡全部不被识别为 video-transcript
  - 调研报告 §15 承诺的"capture 子类型与 v2 天然匹配"在交付时**完全不兑现**
- **整改**：
  - T1 必须在 body 顶部插入 marker（无论 D9 选哪个）
  - 或：调研报告 §15 必须删除"capture 子类型与 v2 天然匹配"承诺

### ②-8 `migration_target` 字样残留多处文本不一致（**新发现**）

- **漏洞位置**：实施方案 T7/T10 + Audit Rollback 第 2 条
- **风险后果**：误删错目录（如果脚本把 `migration_target` 创建为字面目录）
- **整改**：全文替换 `migration_target` → `video-notes-wiki` 或 UUID

---

## 优化疏漏 ③（9 项 · 建议修复）

- **③-1** v2 SQLite `wiki_pages.confidence` 字段未迁移（LLM 自评置信度）
- **③-2** `wiki/index.md` + `wiki/log.md` 自动重生成步骤缺失
- **③-3** F1 "60 秒迁移" 假设过乐观（snapshot + I/O）
- **③-4** H5 密度检查必然 FAIL（v2 1919 张卡集中 taxonomy_sub）
- **③-5** `_v2_origin` 用 `is True` 严格断言（容错性差）
- **③-6** `tests/test_wiki_migrate/` 新目录需要复制 conftest.py 但方案未提及
- **③-7** dry-run 输出格式未定义
- **③-8** v2 Changelog 追加无自动化机制
- **③-9** Phase 4 WebUI smoke test 可选 vs F-bis-5 必填 矛盾

---

## 整改优先级矩阵（更新版 · 含综合报告新增项）

| 优先级 | 整改项 | 影响 | 工作量 |
|---|---|---|---|
| **P0-①-2** | **新增 D9 决策**（type=concept 或 source）+ T1 测试 + 验收 §D2 + capture marker 注入（②-7） | 用户拍板；方案根本走向 | 0.5 天 |
| **P0-①-1** | D3 决策 V6 schema 改造（ADR-0008 PR 1+2） | 12+ 字段持久化 | 2-3 天 |
| **P0-①-3** | D3 决策 tag normalize 适配（V6 PR 2 + T1 normalize_tags） | 第 1 张卡不中断 | 1 天 |
| **P0-①-4** | Phase 4 vector rebuild-all 子命令 + provider 自检 + mark_pending 显式调用 | Phase 4 不崩 | 1-2 天 |
| **P0-②-1** | slug_aliases 写入格式改正（正向 dict） | 5 张 entity 卡 alias 可用 | 0.5 天 |
| **P0-②-3** | 迁移器绕过 write_page，手工 yaml.dump + safe_write | body 形态 + `_ko_extra` 持久化 | 1 天 |
| **P1-②-2** | raw 撞名策略（默认 fail + dry-run 报告 + 验收 §K-D4 改 ≤ 126） | 126 个文件不丢 | 0.5 天 |
| **P1-②-4** | `_to_recompile/` pending 富元数据追加到 main `_ko_extra` | 视频热度/UP 主数据保留 | 0.5 天 |
| **P1-②-5** | Phase 4 失败回滚触发器 + 验收 §H 增新场景 | 不留数据半残 | 0.5 天 |
| **P2** | ②-6/②-8/③-1~③-9 | 一致性 + 文档 | 1 天 |
| **总计** | P0+P1+P2 全部 | — | **~10 天** |

---

## 总判定

❌ **方案当前不能进入编码阶段**

**整改流程**：

```
Phase 1 整改（10 天）:
├── D9 用户拍板（type=concept 或 source）
├── ADR-0008 PR 1（V6 schema 字段 + 17-key 写盘）
├── ADR-0008 PR 2（V6 tag 命名空间 + mandatory pair 条件化）
├── ADR-0008 PR 3（migration tools 完整版）
├── ①-1 ①-2 ①-3 ①-4 致命缺陷全部修复
├── ②-1 ②-2 ②-3 ②-4 ②-5 重大隐患修复
└── ②-6 ②-7 ②-8 ③-x 优化疏漏修复
↓
Plan-Audit Round 1.5 复审（独立 subagent 再跑漏洞审计）
↓
Plan-Audit Round 2 压力测试（独立 subagent 跑）
↓
人工复核 + 用户最终拍板
↓
Phase 0 PoC（5 张样本卡）
↓
Phase 1-4 TDD 实施
```

**报告结束 · 21 个问题点（4 致命 + 8 重大 + 9 优化）**

---

## 关键根因总结

**3 大类根因**：

1. **ruflo-kb 主线 V5 schema 与 v2 数据模型不兼容**
   - V5 8-key 严格白名单不写 v2 业务字段 → ①-1
   - 中文 tag 前缀不兼容 v2 free-form → ①-3
   - `_TYPE_MAP` 把 video-transcript 映射到 source，与 v2 concepts 路径冲突 → ①-2
   - slug_aliases 正向格式与方案反向假设不符 → ②-1

2. **ruflo-kb 主线能力与外部 KB 迁移需求不匹配**
   - 无 `vector rebuild` 命令 → ①-4
   - 默认 embedding 维度 384 而非 1536 → ①-4
   - capture 子类型 marker 仅在 capture 服务注入，迁移路径不触发 → ②-7
   - `_to_recompile/` 这种"未编译草稿"概念不存在于 ruflo-kb → ②-4

3. **方案文档自身的工程细节疏漏**
   - raw 撞名策略未定义 → ②-2
   - Phase 4 失败回滚缺失 → ②-5
   - `--target` 参数语义 + PowerShell 中文路径不稳定 → ②-6
   - dry-run 输出格式 / WebUI 测试态度 / `migration_target` 字样残留 → ③-x
