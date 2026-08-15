# 编译流程与编译质量审计报告（novel-wiki raw 随机 5 篇）

> 日期：2026-08-15
> 审计项目：`knowledge/_compile-audit-20260814`（隔离测试项目，id `8740e8d3-6db2-4043-b2de-8b67a2e2baa6`，审计完可整体删除）
> 源池：`knowledge/novel-wiki/raw/sources`（13 个 .md；排除 3 个 236–282B 测试桩后 10 个候选）
> 抽样：固定种子 `20260814` 随机抽 5 篇（含 11KB 大文档），结果可复现
> Provider：glm-5.2（sfkey.cn 中转，聊天）+ 本地 sentence-transformers all-MiniLM-L6-v2（384 维，离线）
> 摄取路径：HTTP API `POST /api/v1/projects/{id}/ingest` → 异步队列（JSON 持久化）→ Collector → unified Generator → 质量门 → 原子 Writer → Indexer

---

## 0. 抽样清单与最终结果

| # | 源文档 | 大小 | 成功任务 | 产出页数 | 状态 |
|---|---|---|---|---|---|
| 1 | 必备资料20个签约条件新人必看2.md | 11,117 B | kb-…-f0034f93 | 9 | approved ✓ |
| 2 | 补充教程写作经验如何加强书的情节.md | 5,998 B | kb-…-d3abd13d | 5（+旧轮 10） | approved ✓ |
| 3 | 补充教程小说写作新人网络小说的成神宝典精装版.md | 4,773 B | kb-…-53211317 | 6 | approved ✓ |
| 4 | 补充教程写穿越小说角色前要注意的十个问题.md | 3,511 B | kb-…-02e6b445 | 6 | approved ✓ |
| 5 | 必备资料15顺眼谈文章的画面感.md | 3,501 B | kb-…-38471bff | 7 | approved ✓ |

最终 wiki 规模：**5 sources + 16 entities + 24 concepts = 45 页**（含两轮摄取造成的重复页，见 F11）。

---

## 1. 流程层验证

### 1.1 摄取路径实测链路
`POST /ingest`（UTF-8 必须）→ 入队（.kb-queue.json 持久化）→ `collector:start` 事件 → PipelineService（信号量限流 6 并发）→ CollectorStage 读文件 → `run_ingest`：sanitizer 预检 → unified_generate 单趟 LLM（失败降级 two-step）→ 标签清洗 → quality gate → AtomicContext 原子提交（write_page + index.md + log.md）→ APPROVED。**全程无向量/图/生命周期阶段被实际调用**（IndexerStage 未挂在 service 链上，`src/pipeline/service.py` 只跑 `stages[:1]`），向量索引仅在启动时初始化、未随摄取 upsert——见 F8。

### 1.2 各篇任务时间线（本地时间）

| 文档 | 入队 | 首次提交 | 终态 | 处理耗时 |
|---|---|---|---|---|
| 成神宝典 | 19:03:54 | 19:09:08（含熔断等待 ~19:04:59–19:06:39） | approved | ~2.5 min（实际处理） |
| 签约条件 | 19:14:26 | 19:17:13 | approved | 2 min 47 s |
| 加强情节 | 19:14:28 | 19:19:20（unified 3 次解析失败 → two-step 降级） | approved | 4 min 52 s |
| 穿越 | 19:14:29 | 19:15:07 | approved | 38 s |
| 画面感 | 19:14:30 | 19:15:28 | approved | 58 s |

- LLM 调用成功率：多数一次成功（HTTP 200），但约 1/3 输出不可解析（空内容 / 非 dict / 非 JSON），触发内部 3 次重试 + two-step 降级。
- 队列重试：任务级 MAX_RETRIES=3，超限进死信。

### 1.3 重试与熔断
- 任务失败 → FAILED → 重试策略回置 PENDING → 重新派发；3 次后 DEAD_LETTER。
- 熔断器 `task_queue`：连续失败后 OPEN（60s 恢复窗口，半开放行 1 个，成功 2 次后关闭）。
- 启动恢复：服务器重启后自动重派 PENDING 任务（实测 5 个全部恢复）。

---

## 2. 结构层验证

### 2.1 健康检查（`python -m src.cli health`）
| 检查 | 结果 |
|---|---|
| H1 文件存在性 | ✅ OK（35 页检查，32 sources 引用，0 问题） |
| H2 链接完整性 | ✅ OK（35 页，151 个 wikilink/relation，0 断裂） |
| H4 id 格式 | ⚠️ 1 个非法：`《-俄狄浦斯王-》`（含书名号 `《》`，不在 id 字符集；H4 判定 UUID v7/slug 均不符） |
| H5 缓存健康 | ✅ OK |

### 2.2 Frontmatter 合规（全量 41 页）
- 40/41 页 id/title/type 齐全且 id 格式合规；1 页 id 非法（同上 H4）。
- grade 分布、frontmatter 可回读（YAML round-trip 正常）。
- **标签全部为空**（41 页 tags=[]）——LLM 输出的标签基本全落在值域外被清洗，强制标签补齐分支未触发（F7）。

---

## 3. 内容层验证（源文档 vs 产出页面）

5 篇 reviewer 子代理逐篇对比，四维打分（覆盖度/准确性/结构化/类型合理性）：

| 文档 | 覆盖度 | 准确性 | 结构化 | 类型合理性 | 一句话结论 |
|---|---|---|---|---|---|
| 签约条件（20 条） | 3/5 | 4/5 | 4/5 | 3/5 | 16/20 条核心覆盖、数字零错误；条件 10（异性角色）与 11（七分铺垫三分打斗）完全丢失，source 关键观点只列 5/20 |
| 加强情节 | 3/5 | 3/5 | 4/5 | 3/5 | 六大技法五个有页，时空交错整段缺失；两处例子归属编造 |
| 成神宝典 | 3/5 | 5/5 | 4/5 | 4/5 | 55%/35%/10% 比例零编造，引言/写作建议/VIP 结论推导缺失 |
| 穿越十问 | 2/5 | 4/5 | 3/5 | 3/5 | 10 问只落实 3 问，JJ/女人属性/朋友/敌人/理想 5 问全丢 |
| 画面感 | 4/5 | 3/5 | 3/5 | 3/5 | 覆盖好但「顺眼」被幻觉成培训讲师、源文档被重复生成为 stub 实体 |

### 3.1 各篇缺失要点摘录
- **签约条件**：20 条中 16 条完整、2 条部分（条件 3 功法体系/卖点、条件 8 要素不可重复）、**2 条完全缺失（条件 10 异性角色至少 3 个、条件 11 七分铺垫三分打斗）**；source 页「关键观点」仅列 5/20 条；存在一个文档标题型 entity stub 空壳页（`必备资料-20-…`，无页面引用它）。
- **加强情节**：时空交错/意识流整段缺失；《斗破》延宕例子丢失；悬念页把《俄狄浦斯王》错标为期望式例子（源文该例属于"发现/突转"）；source 页「抽取的概念」漏列 [[延宕]]、[[巧合]]。
- **成神宝典**：引言（两种失败作者心态、写作前需研究准备）、写作建议（内容比例、新奇特、快慢有致）无产出；"VIP 目标受众=都市上班族"的推导链丢失；作者心态细节（更新慢/太监风险/喜新厌旧）仅两句话。
- **穿越十问**：第 3/5/7/9 问（JJ、朋友、敌人、理想）完全缺失；第 4 问 a–o 十五项属性清单全缺；第 8 问 4 部例书只建了 2 个实体页；两个实体页含源文没有的情节推断（轻度编造）。
- **画面感**：`entities/顺眼.md` 把概念幻觉成"培训讲师顺眼"（源文无此人）；`entities/必备资料-15-….md` 把源文档自身生成为 stub 实体（id 连字符变体引用所致）；顺眼/网络文学同时存在 entity+concept 双类型；「基础 vs 能力」观点缺失。

### 3.2 跨篇共性质量结论
- **source 页是质量标杆**：元数据 + 摘要 + 关键观点 + 抽取概念 + relations 结构完整（500–650 字）。
- **concept 页**：五章节模板（定义/特点/例子/相关/参考）齐备但偏短（300–600 字），「例子」节常填"来源未提供具体例子"（实则有例）。
- **entity 页**：偏薄（170–290 字），部分接近半空壳，且存在把概念/文档当实体、编造细节的问题。
- **普遍问题**：LLM 对"例子/数字/清单类"细节提取弱；对显式编号清单（20 条/10 问）覆盖不稳定。

---

## 4. 发现的问题清单（按严重度）

### F1 [Critical-已修复] 标签命名空间质量门拒绝 LLM 产出 → 编译非确定性失败
- **现象**：`write_page` 对带标签的新页面执行 `validate_tag_compliance`（值域 + 强制对 `素材/ugc`、`可信度/ugc`），而 LLM 输出常含值域外标签（`题材/穿越`、`题材/写作`）或缺强制对 → TagValidationError → commit 原子回滚 → 任务重试 → 死信。任务成败取决于 LLM 是否恰好不输出标签，**非确定性**。
- **根因**：`generator.py::_resolve_page_tags_unified/_resolve_page_tags` 只按前缀过滤（`is_valid_tag`），注释声称"结果总是通过校验"但实际门是 `validate_tag_compliance`（前缀+值域+强制对），三者只覆盖了前者。
- **修复**（本审计执行）：新增 `_normalize_tags()`——过滤值域非法标签 + 有有效标签时补齐强制对；两个解析函数共用。TDD：新增 5 个测试（红→绿），`tests/test_pipeline/test_generator.py` 全绿（58 passed 无回归）。
- **实测效果**：修复后 4 篇重跑全部提交成功，不再出现 TagValidationError。
- **遗留**：LLM 标签输出质量差导致页面标签为空（F7），建议后续让 Analyzer/Generator 提示词更强调标签命名空间，或按 `素材` 值域自动归类。

### F2 [Critical] HTTP 非 UTF-8 客户端提交中文路径 → 全队列熔断
- **现象**：PowerShell `Invoke-RestMethod` 字符串 body 默认非 UTF-8，中文文件名在 HTTP 层被替换为 `?`；Collector 检测 `?` 报 "encoding corruption" 并拒绝 → 4 个任务 3 次重试后全部死信 → 熔断器打开 → 队列整体暂停 65s+。
- **影响**：中文文件名是网文库的常态，任何非 UTF-8 客户端（旧 curl/Postman/脚本）都会踩中。
- **规避**：body 必须 UTF-8 字节 + `charset=utf-8`；错误信息已提示 "Re-submit using a UTF-8 capable client"。
- **建议**：Collector 对 `?` 的判定是防御性的，但应区分"客户端编码错误"与"文件名真的含 ?"；可考虑接受 URL 编码或 base64 路径。

### F3 [High] 熔断恢复后陈旧坏任务被优先调度 → 队列死锁
- **现象**：熔断半开后 `select_next_task` 总是先挑最旧的 PENDING 任务——坏路径僵尸（永远失败）排在我的新任务前面，每次半开放行都被它耗尽并重新熔断，形成 65s 循环死锁，新任务永远轮不到。
- **根因**：调度器按创建时间/优先级取旧任务，无"连续失败冷却/跳过"机制；且队列清理需停机改文件（无任务删除 API）。
- **建议**：调度器跳过最近 N 次失败的 PENDING 任务，或提供任务级 cancel/delete API；熔断半开时应优先派发新任务。

### F4 [High] glm-5.2/sfkey 拒绝 response_format → JSON 降级 + 偶发空/非 JSON 输出
- **现象**：sfkey 中转对 `response_format` 返回 400（启动探测缓存 `_response_format_ok=False`），Analyzer/Generator 自动降级为 prompt 内嵌 JSON 约束；但 GLM 无约束时约 1/3 输出为空内容 / 数组 / markdown 包裹，触发内部 3 次重试 + unified→two-step 降级，严重拖慢编译（加强情节 unified 3 次失败后 two-step 才成功，耗时 4 min 52 s；期间偶发"All connection attempts failed"瞬时网络失败）。
- **建议**：sfkey 侧确认 glm-5.2 是否支持 OpenAI 标准 `response_format`（或 GLM 的 `json_mode` 参数）；若支持，修正 provider 探测逻辑；否则增强 JSON 提取容错（从 markdown fence 中剥离）。

### F5 [Medium] 文档与实现脱节：AGENTS.md 声称 candidate 流水线默认，实际走 unified 单趟
- `AGENTS.md`/`CLAUDE.md` 描述 Collector→Analyzer(JSON)→Reviewer→Promoter→Generator(candidate) 为默认；但本仓库 `run_ingest` 直接调用 `unified_generate`（单趟），`RUFLO_PIPELINE_MODE` 环境变量在代码中无读取点（仅 shadow.py 引用）。stages/ 包（AnalyzerStage/ReviewerStage 等）未被 service 链使用（`stages[:1]` 只跑 Collector）。
- **建议**：要么让 candidate 路径真正接线并成为默认，要么更新文档为 unified 单趟现实，消除误导。

### F6 [Medium] 任务状态更新与竞态噪音
- 观察：任务状态可长时间停留在 RUNNING（如 d3abd13d 在 two-step 阶段 `updated_at` 未随阶段更新，终态前持续 4.5 min）；旧轮出现 `InvalidTransition('…','running','running')` 双标记竞态日志（重派时二次标记 RUNNING）。
- **建议**：`update_status(RUNNING)` 幂等化（RUNNING→RUNNING 允许）；增加任务级超时（如 10 min）自动 FAILED，避免异常时永久 RUNNING。

### F7 [Medium] LLM 标签产出与清洗导致页面标签全部为空
- 41 页全部 tags=[]。LLM 输出的标签基本落在值域外（`题材/穿越`、`题材/写作`、`素材/写作`），清洗后无有效标签幸存 → 强制对补齐分支未触发 → 页面无标签，检索/过滤能力受损。
- 这是 F1 修复的"副作用面"：修复保证不失败，但暴露了 LLM 标签能力弱这一层。

### F8 [Low] 摄取流水线实际不执行向量索引（Indexer 未接线）
- `src/pipeline/service.py` 只运行 `stages[:1]`（CollectorStage），run_ingest 内部也无 IndexerStage 调用；启动时 vector store 初始化（384 维）但摄取后无 upsert——本审计项目 `.index/lancedb` 无新增向量。与 AGENTS.md 描述的"1536-dim LanceDB 向量存档"不符。
- **建议**：确认 IndexerStage 的接入点（可能是 batch 路径才挂）并补文档或接线。

### F9 [Info] sanitizer high_repetition 告警
- 5 篇全部触发 `['high_repetition'] score=0.70`——飞书导出文件的重复页眉/页脚（"飞书云文档/北京圣东方国信科技有限公司/登录/注册"）被检出。源文件预清洗可消除（`sanitizer` 只告警未去除）。

### F10 [Info] 重启后 /ingest/tasks 端点清空
- ingest_tracker 为内存态，服务器重启后旧任务列表消失（新任务正常追踪），WebUI 任务历史跨重启丢失。建议持久化或从队列文件回放。

### F11 [Info] 审计过程伪影：两轮摄取的重复页面
- 本审计因修复流程重跑了文档，且旧轮任务的流水线在队列清理后仍继续提交（清理只删队列文件、不停进程内协程），导致画面感被摄入 3 次、加强情节 2 次、穿越 2 次，wiki 存在同 id 双类型（entity+concept）与重复实体页（俄狄浦斯王 ×2、延宕 entity 游离页）。**这是审计操作造成的，不是生产缺陷**，但暴露了"任务取消不传播到运行中流水线"的运维缺口。

---

## 5. 结论与建议

### 编译流程
- **链路完整可用**：HTTP 入队 → 持久化队列 → 流水线 → 原子提交 → 状态回写，全链路跑通；重启恢复、熔断、重试机制均真实生效。
- **但生产路径存在 2 个 Critical 缺陷**：标签质量门（F1，本次已修复+测试）与编码/熔断链路（F2/F3）。修复 F1 前，带标签页面 100% 被拒、无标签页面 100% 通过——编译成功与否由 LLM 标签行为掷骰子。
- **当前 provider 组合（glm-5.2/sfkey + 本地 embedding）可完成编译**，但 JSON 可靠性（F4）导致大文档耗时 3–5 倍。

### 编译质量（内容层）
- 结构模板（source/concept 页）执行良好，无空壳概念页；**source 页质量最高**。
- **覆盖度普遍不足**：5 篇覆盖度 2–4/5，显式清单（20 条件/10 问题）与细节例子丢失严重；**准确性 3–5/5**：存在"顺眼被幻觉成讲师""例子归属编造"等幻觉，需人工修正。
- 页面类型拆分方向基本合理，但 entity 页偏薄、偶发概念/文档被误当实体。

### 建议优先级
1. 修复 F2/F3（编码与熔断死锁）——生产环境最先踩到。
2. 解决 F4（sfkey response_format/JSON 可靠性）——直接影响编译速度与成功率。
3. 推进 F5/F8（文档与实现对齐、Indexer 接线）。
4. 标签体系（F1 遗留/F7）：要么让 LLM 输出合规标签（提示词强化），要么放宽值域或按文档类型自动归类。
5. 人工修正评审标记的幻觉页（顺眼讲师实体、必备资料 stub 实体、俄狄浦斯王重复页）。

---
*附：修复变更 — `src/pipeline/generator.py`（新增 `_normalize_tags`，`_resolve_page_tags`/`_resolve_page_tags_unified` 改用之）+ `tests/test_pipeline/test_generator.py`（+5 测试）。临时脚本 `_tmp_*.py` 为审计工具，未纳入源码。*
