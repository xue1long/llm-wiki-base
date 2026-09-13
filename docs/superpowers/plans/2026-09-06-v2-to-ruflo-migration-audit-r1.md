# Plan-Audit Round 1 报告：v2 → ruflo-kb 数据迁移方案

> **审计人**：独立第三方（subagent）+ 主对话事实核查
> **审计日期**：2026-09-06
> **待审方案**：v2 → ruflo-kb 数据迁移（status: ready-for-audit）
> **审计范围**：调研报告 + 实施方案 + 验收清单，约 1700 行
> **总体判定**：❌ **必须整改后复审**（3 致命 + 7 重大 + 9 优化）

---

## 致命缺陷 ①（必须修复才能进入编码）

### ①-1 `_ko_extra` 字段不会持久化到磁盘 —— D3 决策"无效化"

- **漏洞位置**：调研报告 §4.2 第 117 行 + §5 字段差异矩阵 + 实施方案 T1 frontmatter 转换器
- **隐含假设**：方案假设 `_ko_extra` 字段写入文件后，下次 read 还能解析回来
- **事实核查**：
  - `src/wiki/storage/page_writer.py` 第 125-130 行 `yaml.dump(page.to_frontmatter_dict(), ...)`
  - `src/wiki/core/types.py` 第 194-224 行 `to_frontmatter_dict()` 只返回 **8-key 严格白名单**
  - `src/wiki/core/types.py` 第 263 行 `from_dict()` 会读 `_ko_extra`，**但前提是这个 dict 真的被写到了 frontmatter**
  - 矛盾点：write 时不写 `_ko_extra`，read 时却读 `_ko_extra` → **数据不会持久化**
- **风险后果**：T1 跑完写 1919 张概念卡，每张卡的 `processing_depth` / `source_grade` / `use_context` / `workflow_state` / `platform` / `category` / `taxonomy_sub` / `maturity` 等 12+ 字段全部丢失 → **B2 验收必失败**
- **真实案例**：T1 把 `BV113411K7tu.md` 的 v2 frontmatter 转成 WikiPage，设置 `page._ko_extra = {processing_depth: "concept", platform: "B站", ...}`。调 `write_page()` 写盘 → yaml.dump 只输出 8-key → 磁盘 frontmatter 不含 `_ko_extra`。第二天 read → `from_dict()` 取不到 `_ko_extra` → 字段丢失
- **整改建议**：**D3 决策必须根本修改**，三个备选：
  - **方案 A**：改 ruflo-kb 主线 `WikiPage.to_frontmatter_dict()` 把 `_ko_extra` 写盘（重大阻塞项，需 PR review）
  - **方案 B**：T1 自己手写 frontmatter（不用 `write_page`），绕过 V5 严格白名单
  - **方案 C**：接受 v2 业务字段丢失（最简单，但违背 D3 决策本身）

### ①-2 ruflo-kb tag 强校验 + v2 tags 完全不兼容 —— 全部 v2 卡片无法写入

- **漏洞位置**：实施方案 T1 + 验收清单 §D3 标签校验 + 调研报告 R4
- **隐含假设**：方案 R4 标"🟡 中"，暗示"小事，事后改"
- **事实核查**：
  - `src/wiki/features/tag_namespace.py` 第 86-89 行 `MANDATORY_PAIRS = [("素材", "ugc"), ("可信度", "ugc")]`
  - 第 230-250 行 `validate_tag_compliance()` 在 `tags` 非空时强制要求 mandatory pair
  - 第 18-31 行 `TAG_PREFIXES` 全部是**中文前缀**（题材/功能/角色/...），要求 tag 必须是 `prefix/value` 格式
  - v2 的 tag 例子：`[网文创作, 读者视角, 自审方法, 写作技巧, AI编程, tool/python, ...]` — **既无 `素材/ugc` 也无 `可信度/ugc`**，且不符合 `prefix/value` 格式
  - 第 246 行 `raise TagValidationError(...)`
- **风险后果**：**写第一张卡就 raise**，1919 张全部写不进
- **真实案例**：`BV113411K7tu.md` tags = `[网文创作, 读者视角, 自审方法, 写作技巧]`。校验时：① `网文创作` 不是 `prefix/value` 格式 → invalid_values；② tags 非空但缺 `素材/ugc` + `可信度/ugc` → missing_mandatory。`raise TagValidationError("invalid tag values: [...]; missing mandatory tags: [...]")` → T1 中断
- **整改建议**：T1 必须先做 **tag 适配层**：
  - v2 free-form tag → ruflo-kb `prefix/value` 转换表（如 `网文创作` → `功能/教程`）
  - 自动注入 mandatory pair `素材/ugc` + `可信度/ugc`（所有 v2 卡都是 UGC）
  - 或扩展 ruflo-kb `TAG_PREFIXES` 加入 v2 既有前缀（阻塞 ruflo-kb 主线）

### ①-3 T10 引用的 `python -m src.cli vector rebuild` 子命令根本不存在

- **漏洞位置**：实施方案 §Phase 4 Task 10 第 3 步 + 调研报告 §10 高层架构图
- **隐含假设**：方案假设 ruflo-kb 有 `vector rebuild` 子命令
- **事实核查**：`src/cli_ext/vector_cmd.py` 第 110-116 行注册了 `status` 和 `reconcile` 两个子命令，**没有 `rebuild`**
- **风险后果**：Phase 4 第 3 步 `python -m src.cli vector rebuild --project <id>` 直接报 `unrecognized arguments`
- **整改建议**：T10 前置补一个 Task T10.0：写 `scripts/rebuild_vectors.py`（调用 `init_vector_store_for_paths` + `vector_upsert_chunks`），或在 T10 直接用 `vector reconcile` + provider 自检脚本

---

## 重大隐患 ②（应该修复）

### ②-1 _to_recompile 撞名率 100%，方案默认值数学不自洽

- **漏洞位置**：验收清单 §A1 Wiki 卡片数对账 + §K D1-D8 决策合规性 + 调研报告 R2
- **风险场景**：`_to_recompile/` 子目录的 155 张草稿 BV 号**几乎全部**与顶层 `concepts/` 撞名（实测抽样 10/10 撞名），按 D1"主版本胜出"决策：
  - 主 wiki 树 = 1919 - 155 = **1764**（不是方案写的 1919）
  - `_pending/` = 155 - 155 = **0**（不是方案写的 ≥ 0）
  - 总计 = 1764 + 5 + 0 = **1769**（不是方案 A1 写的 `≥ 2079`）
- **影响范围**：A1 行 23 + 27、K 行 358 + 359 数字全部算错
- **整改建议**：A1 数字重算；或 D1 改为"pending 草稿存为 `<slug>.from-recompile.md`" 保留差异

### ②-2 KnowledgeGapStore 默认 cap=3 → 1919 张卡的断链只记录少量，R1 兜底失效

- **漏洞位置**：`src/wiki/features/knowledge_gaps.py` 第 140 行 + 调研报告 R1 + 验收清单 §C2
- **风险场景**：`add_many(max_entries=3)` 单次最多加 3 条。1919 张卡的断链大量触发 add_many → 实际累加记录数远少于 v2 自身断链（v2 有 576+ 条）
- **整改建议**：T2 调用 `add_many(max_entries=10000)` 临时提高 cap，或 T9 验证脚本**不依赖 knowledge_gaps.json** 而是自己扫 wiki/ 目录检测

### ②-3 LanceDB 重建依赖 LLM Embedding API —— 服务不可用即 Phase 4 全失败

- **漏洞位置**：实施方案 §Phase 4 步骤 1-4
- **风险场景**：重建向量需要 LLM provider 在线 + Embedding provider 在线 + 联网 + 余额/配额足够（1919 张卡的 embedding API 费用未估算）
- **影响范围**：方案 F1 第 312 行说"≤ 30 分钟（依赖 LLM 服务）" 但**完全没提服务不可用怎么办**
- **整改建议**：T10 前置 provider 自检脚本（`python -m src.cli llm-providers list` + health check），缺失则 abort with clear error；F1 加一条「LLM provider 不可用 → NO-GO」

### ②-4 `raw/_archive/` 不是 ruflo-kb 默认目录，搬过去后变成孤儿

- **漏洞位置**：调研报告 §10 + 实施方案 D2 + T5
- **风险场景**：
  - `src/wiki/storage/ensure.py` 第 19-31 行只 mkdir `raw_sources`（单一目录），不包含 `raw/_archive/`
  - `paths.raw_sources = root/raw/sources`（不递归）
  - `src/agent/tools.py` 第 72 行 `SourceSearchTool.execute` 用 `paths.raw_sources.glob("*")` 扫 raw，**不递归** → `raw/_archive/` 里的文件**永远不会被检索到**
- **整改建议**：D2 决策改为「_archive 不搬」（与 D7「v2 冻结」一致），或扩展 ruflo-kb `WikiPaths` 加 `raw_archive` 属性

### ②-5 实施文件路径两套矛盾：`tools/migrate_v2.py` vs `src/cli_ext/migrate_v2_cmd.py`

- **漏洞位置**：调研报告 §10 高层架构图 vs 实施方案 T7 第 527 行
- **风险场景**：两个文件职责不同但没说哪个是主入口
- **整改建议**：明确 `src/wiki/migrate/v2_*.py` 是核心库（被两边共用），`src/cli_ext/migrate_v2_cmd.py` 是 CLI 入口，**删除架构图里的 `tools/migrate_v2.py`**

### ②-6 `--import-from-v2` 伪命令（架构图错误）

- **漏洞位置**：调研报告 §10 高层架构图最后一行
- **风险场景**：`src/cli.py` `add_parser("init")` 没注册 `--import-from-v2` flag，运行会报错
- **整改建议**：修正架构图：`python -m src.cli migrate-v2 --v2-path <v2> --target video-notes-wiki --apply`

### ②-7 v2 字段 `summary` / `use_context` / `workflow_state` 在 frontmatter，但 V5 write 不写盘 → B2 验收方法本身有 bug

- **漏洞位置**：调研报告 §5 + 验收清单 B2 第 1 行
- **风险后果**：即使 T1 把 summary 塞进 `_ko_extra`，由于 `to_frontmatter_dict()` 返回值再被 `yaml.dump` → frontmatter 里**根本没有 `_ko_extra` 键**
- **影响范围**：B2 全行失败；K 节 D3 验收「100% 非空」必然失败
- **整改建议**：要么修改 `WikiPage.to_frontmatter_dict()` 把 `_ko_extra` 写盘（改主线，重大阻塞），要么验收方法改为"在 yaml 解析阶段识别全部字段"

---

## 优化疏漏 ③（建议修复）

### ③-1 5 张 entity 卡 aliases 总数应为 8 项
- **位置**：验收清单 §C3 第 127 行
- **建议**：明确"5 张卡合计 8 项 aliases"（实测：`Claude Code: 3` + `Obsidian: 1` + `Karpathy: 2` + `OpenClaw: 1` + `潇逸HR: 1` = 8）

### ③-2 D3 第 363 行验收"含 use_context 全部非空" 但 v2 早期卡无 use_context
- **位置**：验收清单 §K 行 363
- **建议**：改为"有 use_context 字段的卡 → 必须保留；无 use_context 的卡 → 缺字段不算失败"

### ③-3 raw 文件存在 `.batch/` / `boards/` 隐藏工作目录（实测 6 个文件），D4 没提是否排除
- **位置**：调研报告 §7.1
- **建议**：T5 `collect_raw_files` 显式 skip 任何 `.` 开头的隐藏目录

### ③-4 F-bis-2 要求 HEAD 请求批量验证 URL 但没设计限速
- **位置**：验收清单 §F-bis-2 行 237
- **建议**：用 aiohttp 异步 + 5 req/s 限速；或改 F-bis-2 为"URL 模板可生成（不实际请求）"

### ③-5 调研报告 §2 第 30 行说"3.2 GB"，但实际 raw 6.2 MB
- **位置**：调研报告 §2
- **建议**：核对数据；初版 ls 输出的 3,217.1 MB 可能误读（含隐藏工作文件）；D2 校验统一用 `find raw -type f -exec md5sum`

### ③-6 T8 第 580 行写"1924 张全部成功"，但没提异常处理策略
- **位置**：实施方案 §Phase 2 T8
- **建议**：T8 步骤 4 增加 `--continue-on-error` flag + 错误日志输出到 `migration_errors.csv`

### ③-7 Phase 4 第 658-660 行步骤缺序号
- **位置**：实施方案 §Phase 4
- **建议**：补 `- [ ]` checkbox

### ③-8 v2 的 `00_inbox/` 不在迁移范围，但 entity 卡 body 引用 `[[00_inbox/wiki-标签-openclaw.base]]`
- **位置**：调研报告 §2 + 实施方案 Non-goals
- **建议**：T2 加预处理跳过 `[[00_inbox/*]]` 和 `[[Clippings/*]]` 这类 v2 内部目录引用

### ③-9 C2 验收说"断链数 ≤ v2 自身"，实际会显著增加（_to_recompile 丢弃 + inbox 引用 + cap=3）
- **位置**：验收清单 §C2 行 120
- **建议**：改为"断链数 - v2 自身断链数 ≤ 161（_to_recompile 155 + 隐藏目录 6）"

---

## 额外发现（11 项 · 用户/作者确认）

1. D7「v2 冻结」执行时机未明：建议 T8 验收后立即追加 v2 Changelog，作为 Phase 4 的 gate
2. R3 风险等级不准确：方案标"🟠 高"，实际影响**致命**，应升级为"致命"
3. `scripts/run_v2_migration.sh` 幂等启动脚本：1919 张卡 + 3.2 GB raw 场景下做不到真幂等（每次 upsert 重复），需明确"幂等 = 跳过已完成页" + `--force-reingest`
4. `compile_db.sqlite` CSV 导出 schema 不全：缺 `wiki_pages.confidence` 列
5. `--skip-pending` 等 skip flags 实现位置不明确：应该在 `cli_ext/migrate_v2_cmd.py` 而不是 `v2_*.py` 库代码
6. WebUI smoke test 态度不一致：验收清单 E3 说"（可选）"但实施方案 T10 说"如果时间允许"
7. PoC 与 Phase 1 commit 边界不清晰：PoC 不提交（dry-run only），但 Global Constraints 说"每 Task 一提交"
8. 3.2 GB raw IO 时间窗紧：Windows HDD 约 60 MB/s → 3.2 GB md5 + copy 约 107 秒；NVMe 应该够
9. capture 模板的 inspiration 子类型用不上：v2 1924 张卡几乎全外部素材
10. WebUI"原视频"按钮存在性未验证：F-bis-5 假设按钮存在
11. `<!-- capture-type: video-transcript -->` body 注释只是文本标记，ruflo-kb 无代码读取

---

## 整改优先级矩阵

| 优先级 | 整改项 | 阻塞代码层 | 工作量 |
|---|---|---|---|
| **P0** | ①-1 D3 决策根本修改（V6 schema / 手写 frontmatter / 接受丢失） | T1 frontmatter | 半天 |
| **P0** | ①-2 T1 加 tag 适配层 + 自动注入 mandatory pair | T1 | 半天 |
| **P0** | ②-7 B2/K D3 验收方法重写 | T9 | 1 小时 |
| **P1** | ①-3 T10 前置写 `scripts/rebuild_vectors.py` | T10 | 2 小时 |
| **P1** | ②-1 A1/K 撞名率 100% 重新计算 | T6 / 文档 | 30 分钟 |
| **P1** | ②-2 KnowledgeGapStore cap 调整 | T2 | 1 小时 |
| **P1** | ②-3 T10 前置 provider 自检 | T10 | 1 小时 |
| **P1** | ②-4 D2 决策改为"不搬 _archive" | 文档 + T5 | 30 分钟 |
| **P2** | ②-5 统一架构图与 Task 列表的文件路径 | 文档 + T7 | 1 小时 |
| **P2** | ②-6 删除架构图里的 `--import-from-v2` 伪命令 | 文档 | 10 分钟 |
| **P3** | ③-1 ~ ③-9 + 11 项额外 | 文档 / 验收 | 2 小时 |

**总计**：P0 必改 1.5 天 + P1 建议改 1 天 + P2/P3 半天 ≈ **3 天整改**

---

## 关键根因（一条说清）

**方案与 ruflo-kb 主线（V5 严格白名单 + tag 强校验）的两个硬冲突**：

1. D3 决策假设 `_ko_extra` 能持久化，但 V5 严格白名单不会写入
2. D3 决策假设 v2 tag 能保留，但 ruflo-kb 中文前缀 + mandatory pair 不兼容 v2 free-form tag

**这两条**是所有致命/重大问题的源头。其他 ①-3、②-x、③-x 都可以靠文档修订或补丁脚本解决。

**根因解决路径（三选一）**：
- 路径 X：先 PR 给 ruflo-kb 加 V6 扩展字段 + 调整 TAG_PREFIXES / mandatory pair，再迁
- 路径 Y：T1 完全不走 `write_page`/`validate_tag_compliance`，自己手写 frontmatter + 跳过 tag 校验（脏数据但能迁）
- 路径 Z：接受 v2 业务字段丢失（只迁 8-key 核心 + platform/url/tags 丢弃）

---

## 总体判定

❌ **方案当前不能进入编码阶段**

**整改流程**：

```
P0 整改 (1.5 天) → 复审 Round 1.5 → 通过 → 整改确认
P1 整改 (1 天) → 同步进 Round 2
P2/P3 整改 (半天) → 文档定稿
↓
复审 Round 1（再跑一次漏洞审计，确认所有问题修复）
↓
Round 2 压力测试（独立 subagent 跑）
↓
人工复核 + 用户最终拍板
↓
Phase 0 PoC
```

**报告结束 · 19 个问题点（3 致命 + 7 重大 + 9 优化）· 11 项额外确认**
