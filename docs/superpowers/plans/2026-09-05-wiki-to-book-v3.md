# Wiki-to-Book V3.2 安全整改实施计划

> 状态：安全整改实施完成（V3.2）；验收证据见 [`docs/reports/2026-09-05-book-wiki-v4-acceptance.md`](../../reports/2026-09-05-book-wiki-v4-acceptance.md)。`knowledge/novel-wiki` 已通过关系阈值并完成一次真实 `--apply` 发布。
>
> **V3.2 + V4 关系**：V3.2 是 P0（安全基线），P1（阅读体验）+ P2（质量门 + 读者任务 + 跨页面融合）见 [`docs/superpowers/plans/2026-09-05-wiki-to-book-v4.md`](2026-09-05-wiki-to-book-v4.md)。V4 一体化整合 V3.2 + 阅读体验 + 验收，按 P0/P1/P2 三级排序。
>
> **V3.2 → V4 exit code 演进**：V3.2 的 exit 7（unresolved-relation-over-threshold）在 V4 中保留；V4 新增 exit 9（其它 quality-gate rule blocker）和 exit 10（reader-task-rubric < 80%，警告非阻断）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal（范围与边界）：** 将项目 wiki 中的 concepts、entities、synthesis 页面编译为**可审计的结构化 Wiki 拼装器**。本版本严格收敛于：
- 稳定 `page_id` + block 守恒；
- 确定性分区 + 规则聚合；
- 可恢复原子发布；
- 显式 reader 入口与可追溯来源；
- 章节级阅读体感三件套（过渡与导读、术语表与索引、章节内语义排序）。

V3.2 **不**承诺：跨页面知识融合、读者任务验收 (acceptance rubric)、"网文写作百科全书"重定义。如果业务目标要扩展为百科全书，必须新立 V4 计划，并补齐 schema/quality gate/**读者任务验收**三项必修。详见 [`docs/superpowers/plans/2026-09-05-wiki-to-book-v4.md`](2026-09-05-wiki-to-book-v4.md)（v0.2 草案，已通过 Round 1/2 自审）。

> 阅读体感三件套的落地模式：
> - **全文术语表与索引**：纯规则可达；自动从 wikilink、page_type、`primary_taxonomy`、`grade` 提取 glossary + index。
> - **章节间过渡与导读 / 章节内语义排序**：依赖 LLM；纯规则路径给出占位文本与 page_id 字典序默认排序，**不**声称满足阅读体感。

**目标产物与读者入口（必定义）：**
- 目标产物：`book-wiki/` 目录下**结构化编译产物**，由 `<project_root>/book-wiki/CURRENT.json` 指针指向当前激活版本目录。
- 指针协议：`CURRENT.json = {"version": "<run_id>", "manifest_sha256": "<sha256>"}`，UTF-8 JSON，确定键序。
- 读者入口：`resolve_active_version(<project_root>) -> Path | None` 必须存在并被 reader 调用方（CLI/MCP/HTTP）使用；当指针缺失、解析失败或 `manifest_sha256` 不匹配时返回 `None`，**不**静默回退到任何目录；reader 在缺指针时返回显式错误（不存在结构化 Book）。
- 版本目录由 `compiler.py` 写入 `<project_root>/.index/book-wiki/versions/<run_id>/`（命名空间隔离，不与 `book/` 共用）；指针位置在 `<project_root>/book-wiki/CURRENT.json`。
- 与 KC book 的关系：互不感知；KC `book/manifest.json` 与 wiki `book-wiki/CURRENT.json` 是两套独立发布协议，互不覆盖。

**Architecture:** 先完成项目与输入 preflight，再以 fail-closed 方式读取一次 Wiki 快照，生成稳定页面记录、摘要和 token 计数。页面先按确定性规则分区并形成最终 chapter chunks；LLM 只负责固定 chunk 的标题和受限 overview（默认关闭，可选启用），规则引擎负责内容搬运、链接解析和完整性校验。构建结果写入版本目录，最终只原子替换一个指针文件，避免 Windows 非空目录交换的不确定性。

**Tech Stack:** Python 3.11+、现有 `WikiPage`、现有 `LLMProvider.complete`、标准库 `json`/`hashlib`/`pathlib`/`tempfile`/`os`，pytest。

**Spec:** 本文件；业务目标沿用 `docs/superpowers/plans/2026-09-05-wiki-to-book.md`，其 V2 实施细节不作为 V3 契约。

## 审计整改闭环

> 命名对照：V3.x 表示 `docs/superpowers/plans/2026-09-05-wiki-to-book.md` 各轮迭代；V3.2 即本计划。

- **致命缺陷｜发布边界（V3.1 Task 6）**：Windows 非空目录替换不具备可证明的原子性，可能留下半套 Book 或破坏旧版本。**整改**：版本目录先完整落盘并校验，只原子替换 `CURRENT.json` 指针；指针损坏时读者拒绝加载并保留旧版本。
- **致命缺陷｜项目与输入前置条件（V3.1 全局约束）**：未初始化项目、坏 frontmatter、越界输出路径可能被当作正常输入，导致误写或静默丢页。**整改**：Task 0 fail-closed preflight，Task 1 严格扫描；任一前置条件失败不得扫描、调用 LLM 或创建项目文件。
- **重大隐患｜全局 LLM 分配（V3.1 Task 3）**：一次性让模型分配全部页面，容易超上下文、重复归类、漏页且难以重现。**整改**：先按页面类型/主 taxonomy 做确定性分区，再对固定 chapter chunk 做受限命名和 overview；最终以 ID 多重集校验。
- **重大隐患｜标题与正文完整性（V3.1 Task 2/4/5）**：标题重复或润色改写会破坏身份与可追溯性。**整改**：全链路只用稳定 `page_id`；正文按不可变 `ContentBlock` 搬运，润色只产生编辑文本，并校验 block-ID 多重集、正文哈希和链接。
- **重大隐患｜重跑与预算（V3.1 Task 3/7）**：部分状态续跑可能混入旧快照或旧提示词，预算耗尽时还可能留下不完整结果。**整改**：指纹覆盖快照、schema、提示词、渲染器、provider/model 和选项；失败运行不续跑，只复用完整且哈希一致的缓存；预算耗尽返回完整规则版并停止 LLM。
- **优化疏漏｜运行审计与合规（V3.1 全文）**：缺少 provider 用量、锁归属、关系解析和正文外发边界，故障难定位且可能违规传输内容。**整改**：manifest 固化实际用量、错误、缓存命中、关系解析和锁审计；默认不外发正文，`--polish` 需显式授权和策略检查。

追加整改：

- **致命缺陷｜目标与产物定义（V3.1 Goal/Task 4）**：仅拼接页面却宣称"结构化百科全书"，验收标准无法证明知识层级、关系和章节摘要成立。**整改**：V3.2 将目标收敛为"**可审计的 Wiki 拼装器**（safety-first structured compiler）"；每章固定输出 overview、taxonomy、role、关系索引和来源页清单，跨页面语义融合明确排除在本版本之外。如需"百科全书"级语义融合，必须新立 V4 计划补齐 schema/quality gate/读者任务验证，详见 [`docs/superpowers/plans/2026-09-05-wiki-to-book-v4.md`](2026-09-05-wiki-to-book-v4.md)。
- **重大隐患｜分类输入（V3.1 Task 1/3）**：依赖未生成的 `taxonomy_summary.txt` 会让分类流程在真实项目中断。**整改**：分类只读取快照中的 `primary_taxonomy` 和 `page_type`；缺失 taxonomy 进入显式 fallback，并在 manifest 记录数量，不再假设外部汇总文件。
- **重大隐患｜交付位置语义（V3.1 全局）**：`.index/` 在 `src/wiki/core/paths.py` 被定义为运行数据、默认不导出；把 book 正文放进 `.index/book-wiki/runs/<fp>/versions/<run_id>/` 会让最终交付物隐藏在运行目录中。**整改**：将 **staging** 留在 `.index/book-wiki/versions/<run_id>/`，但 **激活内容** 必须通过 `<project_root>/book-wiki/CURRENT.json` 指针对外暴露，读者只读指针解析路径；运行目录可清理但不影响已激活内容。
- **重大隐患｜发布协议二重化（V3.1 Task 6）**：现有 `src/kc/views/book/rebuild.py` 已有 `.releases/<run_id>/` + manifest.json 原子替换 + 旧版本保留；新建独立 publisher 会导致两套互不感知的发布协议。**整改**：V3.2 必须复用现有 `BookRebuildReport` / `_commit_stage` 风格的 release 模式（`book-wiki/.releases/<run_id>/` + manifest.json + atomic pointer swap），不再单独设计 publisher 模块；保留指针文件是当前版本元数据 + 旧 release 仍然可读。
- **重大隐患｜写锁 3600 秒自动抢占**：按时间自动接管锁会误杀长任务，破坏并发安全。**整改**：过期判断必须同时满足 (a) 锁文件 age > `stale_after_seconds` 且 (b) 持有 PID 已退出（POSIX `kill(pid, 0)` / Windows `OpenProcess`）；仅任一条件成立均不得抢占。锁 release 必须有契约（try/finally）、有审计日志。

## 实施分级

> 判定原则：按"安全 → 可落地 → 最小闭环"的三段优先级整理；安全底线必修，质量增强可选，未经验证的复杂度可砍。

### 必修基线（安全底线）

任何一项缺失都不得进入 `--apply` 发布或接入真实项目：

- **目标/读者入口**：明确产物是"可审计的 Wiki 拼装器"还是"百科全书"；`CURRENT.json` 指针协议 + `resolve_active_version()` reader 契约 + reader 在缺指针时返回显式错误。
- **项目与输入 preflight**：检查项目初始化（`.llm-wiki/project.json` 存在且 schema 版本匹配）、输入目录存在、schema 版本、输出路径 containment（不在 `wiki/` / `.git/` / 项目根之外）、provider/model 配置按运行模式条件启用。
- **严格扫描和快照**：阻断坏 frontmatter、重复 ID、非法编码、越界链接、扫描期间文件变化；不静默跳过。
- **稳定 ID 和覆盖校验**：`page_id` 是身份唯一；页面在最终 outline 中恰好出现一次；未知 ID、缺失 ID、重复 ID 都是阻断错误；标题只用于展示。
- **规则化正文聚合和内容守恒**：保留每个正文块、heading、关系、来源；使用 block-ID 多重集校验；`Counter(draft.block_ids) == Counter(all_source_block_ids)`。
- **发布完整性和旧版本保护**：先生成完整版本目录、再原子切换 `CURRENT.json` 指针；旧版本必须可读；优先复用 `src/kc/views/book/rebuild.py` 的 release 机制（`.releases/<run_id>/` + manifest + staged commit），不新建独立 publisher。
- **并发锁和异常释放**：锁获取用 `O_CREAT | O_EXCL`；release 必须有 try/finally 契约；过期判断需"age + 持有 PID 已退出"双条件，不得按时间自动抢占；含并发测试。
- **关系和来源策略**：excluded source（来自 `wiki/sources/`、`wiki/_stubs/`、`wiki/_archive/`）的关系处理策略；unresolved relation 的发布阈值（默认禁止发布，或 manifest 明确标注）；reader 追溯来源。
- **LLM 边界控制**：纯规则路径不得被 provider/tokenizer/response_format 阻断；LLM 路径限制输入范围（仅元数据 + 安全摘要）、输出 schema 校验、重试分类（429/5xx 重试，401/不支持格式不重试）、预算超时、正文不可改写；正文外发授权仅在 `--polish` 开启时强制。
- **阅读体感三件套**：每章含 (a) `transition_in` + `transition_out` + `overview`、(b) 全文 `glossary.md` 与 `index.md`（page_id → 标题/类型/taxonomy）、(c) 章节内 page 排序输出。
  - 纯规则路径下：(b) **必须**自动生成；(a)/(c) 给占位文本与 page_id 字典序默认排序，并在 manifest 中标注 `reading_experience_mode = "rule_only"`，**不**声称满足阅读体感。
  - LLM 启用路径下：(a)/(c) 由 LLM 在 token 预算内生成，(b) 规则版基线 + LLM 增补，标注 `reading_experience_mode = "llm_enhanced"`。
  - V3.2 提供"基础机械可达"；V4 计划（Task 9–14）升级为"完整增强"，并加入 quality gate 与 reader task 验收。
- **发布前失败演练和 CLI 验证**：覆盖项目未初始化、坏页、重复 ID、provider 失败、锁冲突、磁盘失败、指针失败、旧版本保留。
- **磁盘和版本保留策略**：版本目录数量上限、staging 清理规则、空间监控；否则长期运行会耗尽磁盘。

### 可选增强（质量层，可后置）

不阻塞最小安全版本；必修基线全部通过验收后才能启用：

- LLM 生成章节标题与 overview（Task 3 中的固定 chunk 命名和摘要作为增强层；规则版可先产出可审计 Book）。
- LLM 润色（Task 5 默认关闭；正文守恒验证本身是必修，LLM 润色不是）。
- 缓存与完整 BuildFingerprint 命中（首版可完整重建，仅保留 snapshot hash 与结果 manifest）。
- provider 用量、缓存命中、错误统计（成本控制价值，不阻塞纯规则构建）。
- `--json` 输出、可调 retry/token 参数（运维友好，CLI 稳定后增加）。
- `confidence` 字段（若不参与分区/排序/门禁，则延后）。
- 模糊 heading 匹配（未匹配内容必须保留；模糊匹配本身可后置）。
- 广泛故障注入（先覆盖发布/锁/快照/磁盘四类关键故障；provider 细分故障可追加）。
- fsync 细节验证（若部署环境要求断电级持久性；普通本地构建可先完成原子指针和旧版本保护）。

### 删除/下沉项（不必要的复杂度）

以下内容已被本次复审判定为"增加复杂度但不增加可证明的结果"，必须删除、下沉或转为可选：

- 固定"4–8 卷"限制（卷数由内容规模和阅读结构决定，不得硬编码）。
- 无未分类页面时强制生成空兜底卷（无内容时不要空目录噪声）。
- 只展示不参与决策的 confidence 字段。
- 新建独立 publisher + `.index/book-wiki/runs/.../versions/...`（重复建设导致两套发布协议）。
- 把激活内容放进 `.index/`（`.index/` 是运行数据，不适合作为最终交付位置；staging 可以放 `.index/`，激活内容必须经 `book-wiki/CURRENT.json` 对外）。
- 无条件要求 provider-compatible tokenizer（纯规则路径不得被 tokenizer 缺失阻断）。
- 无条件要求 `response_format={"type":"json_object"}`（不同 provider 支持不一致；真正必要的是可靠解析、schema 验证、失败降级）。
- 扫描期间 mtime/size/hash 双重判定（读取正文并保存快照后 mtime 不提供额外可靠性；保留内容哈希 + 必要的读取一致性检查即可）。
- 按 3600 秒自动判定锁过期（误杀长任务；按时间接管无必要且破坏并发安全）。
- `BuildArtifact.files: dict[str, bytes]` 全量驻留内存（不适合扩大规模；直接流式写入 staging）。
- 把 1255 / 463 写进验收条件（仅是当前观测值，不能作为实现契约）。
- 同时保存所有 LLM 原始响应（可能带来敏感信息、版权内容和磁盘膨胀；只保存摘要、哈希、错误分类即可）。

## Global Constraints

### 输入与基础安全

- 输入范围固定为 `wiki/concepts/`、`wiki/entities/`、`wiki/synthesis/`；`sources/`、`_stubs/`、`_archive/` 不进入 Book。`sources/` 仍可作为关系来源出现在 manifest 的 source provenance 列表中，但不直接迁移正文。
- 页面数量从快照动态计算；当前基线为 924 + 316 + 15 = 1255（仅为当前观测值，不写进验收条件、不在代码中硬编码）。
- 编译前必须确认 project manifest、输入目录、schema 版本、输出目录；项目未初始化时 fail closed，不自动初始化。
- 页面身份只能使用稳定唯一 `page_id`；标题只用于展示，不能用于查找或去重。
- 每个输入页面必须在最终 outline 中恰好出现一次；未知 ID、缺失 ID、重复 ID 都是阻断错误。
- 启用 LLM 章节规划或润色时，才按实际 provider/model 上下文上限预检；超限章节必须拆分或降级为规则版。纯规则路径不依赖 tokenizer。
- 每章必须包含固定的 `overview`、taxonomy、role、关系索引和来源页清单；这些字段没有证据时写明"未提供"，不得由模型补造事实。
- 页面正文块不可由 LLM 改写；LLM 只能生成 overview、排序和编辑性过渡文本。
- 默认 dry-run；只有 `--apply` 才能发布，发布失败不得破坏上一份有效 Book。
- 每次运行绑定同一个 Wiki 快照；快照变化时禁止复用旧规划或旧润色结果。
- 仅启用缓存时计算完整 BuildFingerprint；至少包含 snapshot、schema、分区规则、已启用的 prompt/renderer、provider/model 和命令选项，任一变化都使对应缓存失效。

### 输出与发布安全

- 激活内容位于 `<project_root>/book-wiki/CURRENT.json` 指针；指针损坏或缺失时 reader 返回显式错误，不静默回退。
- 版本目录位于 `.index/book-wiki/versions/<run_id>/`（命名空间隔离，不与 KC `book/` 共用）；完成后原子切换指针。
- 优先复用现有 Book release 模式（参考 `src/kc/views/book/rebuild.py::rebuild_book` 与 `_commit_stage`），不新建独立 publisher。
- 旧版本必须可读；指针替换前不删除旧 release。

### LLM 边界（按运行模式条件启用）

- 纯规则路径（未传 `--use-llm` / 默认）不得被 provider、tokenizer、`response_format` 缺失阻断；规则版可直接产出可审计 Book。
- LLM 路径必须：限制输入范围（仅元数据 + 章节安全摘要，禁止外发正文，除非 `--polish` 开启）、输出 schema 校验、重试分类（429/5xx 重试，401/不支持格式不重试）、预算超时、正文不可改写。
- 正文外发授权仅在 `--polish` 开启时强制；并需通过外发策略检查。
- 仅在启用 LLM 时记录 provider、模型、请求次数、token 用量、错误类别和缓存命中情况；提供显式 attempt/input/output-token 预算，达到预算即停止 LLM 阶段并保留规则版，不依据未定义的价格表计算 cost。
- 默认不向外部 LLM 发送正文；`--polish` 必须通过内容外发检查，并只发送已获授权的正文块。
- LLM 原始响应**不**保存，只保存摘要 + 哈希 + 错误分类（避免敏感信息、版权内容和磁盘膨胀）。

### 并发与锁

- 同一项目和输出目标一次只允许一个运行；锁文件包含 owner token、PID 和启动时间。
- 锁获取用 `O_CREAT | O_EXCL`；release 必须有 try/finally 契约。
- 过期接管必须**同时**满足 (a) 锁文件 age > `stale_after_seconds` 且 (b) 持有 PID 已退出（POSIX `kill(pid, 0)` / Windows `OpenProcess`）；任一条件不满足均拒绝抢占。
- 包含并发测试（同一项目并发两次 run，第二次必须被锁阻断）。

### 内容守恒

- 所有 LLM 调用必须保证 block-ID 多重集守恒：`Counter(draft.block_ids) == Counter(all_source_block_ids)`。
- 章节正文 hash 必须等于所有源块拼接后的内容 hash。
- 未匹配 heading 必须保留（不得静默丢弃）；可进入"未分类"桶，并在 manifest 标注数量。

### 故障阻断

- frontmatter 存在但解析失败时必须阻断扫描；不得把坏页降级成普通 Markdown。
- 坏 frontmatter、重复 ID、非法编码、越界链接、扫描期间文件变化任一情况出现，扫描阶段返回非零退出，不得进入后续阶段。

## Data Contract

Step 0 产出的记录使用稳定 ID，后续所有模块只消费这些类型：

```python
@dataclass(frozen=True)
class PageRecord:
    page_id: str
    title: str
    page_type: Literal["concept", "entity", "synthesis"]
    path: str                  # path relative to wiki_root; never an absolute path
    primary_taxonomy: str | None
    summary: str                 # first non-empty body block, normalized to <= 800 chars
    content_blocks: tuple["ContentBlock", ...]
    relation_targets: tuple[tuple[str, str], ...]  # (relation_type, target_id)
    content_sha256: str
    char_count: int
    token_count: int | None     # LLM 路径可用 tokenizer 或保守估算；纯规则路径允许为 None

@dataclass(frozen=True)
class ContentBlock:
    block_id: str                 # f"{page_id}:{ordinal}"
    page_id: str
    heading: str | None
    body: str
    ordinal: int

@dataclass(frozen=True)
class WikiSnapshot:
    snapshot_id: str              # sha256 of canonical records (内容哈希 + 必要读取一致性检查)
    wiki_root: str
    schema_version: str
    pages: tuple[PageRecord, ...]
    excluded_sources: tuple[str, ...]   # 来自 sources/、_stubs/、_archive/ 的页面 ID

@dataclass(frozen=True)
class PageAssignment:
    page_id: str
    volume_id: str
    chapter_id: str
    confidence: float | None
    role: str

@dataclass(frozen=True)
class BuildFingerprint:
    snapshot_id: str
    schema_version: str
    partition_sha256: str
    outline_prompt_sha256: str | None   # 仅启用 LLM 章节规划时填写
    polish_prompt_sha256: str | None    # 仅启用 LLM 润色时填写
    renderer_sha256: str                # 启用缓存时填写；否则不作为门禁
    provider: str | None       # 纯规则路径为 None
    model: str | None          # 纯规则路径为 None
    options_sha256: str

@dataclass(frozen=True)
class UsageReport:
    provider: str
    model: str
    attempts: int
    input_tokens: int
    output_tokens: int
    cache_hits: int
    errors: tuple[str, ...]

@dataclass(frozen=True)
class ValidationError:
    code: str
    stage: str
    message: str
    context: dict[str, str]

@dataclass(frozen=True)
class BuildArtifact:
    """版本目录的逻辑抽象；落盘时**流式**写入 staging，不全量驻留内存。

    `version_dir: Path` 指向 `.index/book-wiki/versions/<run_id>/`；文件清单与 hash
    在落盘过程中累积到 `manifest`，最终用于发布前的完整性校验。
    """
    snapshot_id: str
    fingerprint: BuildFingerprint
    manifest: dict[str, object]   # 含文件 hash、计数、关系解析、用量摘要等
    version_dir: Path             # 流式落盘位置
    validation_errors: tuple[ValidationError, ...]

@dataclass(frozen=True)
class PublishReport:
    status: str                   # "published" | "failed" | "rolled_back" | "noop"
    active_version: str | None    # run_id
    previous_version: str | None  # 上一指针 run_id
    error: str | None

@dataclass(frozen=True)
class PreflightReport:
    project_root: str
    output_dir: str               # 激活内容路径：book-wiki/
    staging_root: str             # staging 路径：.index/book-wiki/versions/
    provider: str | None          # 纯规则路径为 None
    model: str | None             # 纯规则路径为 None
    tokenizer: str | None         # 仅在 LLM 路径有效
    eligible_page_count: int
    errors: tuple[ValidationError, ...]

@dataclass(frozen=True)
class RunLock:
    path: str
    owner_token: str
    pid: int
    started_at: int
    stale_after_seconds: int      # 显式声明，过期需 age + pid-dead 双条件

@dataclass(frozen=True)
class ChapterDraft:
    chapter_id: str
    page_ids: tuple[str, ...]
    blocks: tuple[ContentBlock, ...]
    block_ids: tuple[str, ...]
    bucket_index: dict[str, tuple[str, ...]]

@dataclass(frozen=True)
class PolishedChapter:
    chapter_id: str
    block_order: tuple[str, ...]
    editorial_sections: tuple[str, ...]
    polished: bool
    failure_reason: str | None
```

`token_count` 仅在 LLM 路径下计算（优先使用 tokenizer；不可用时使用项目已有的保守估算器）；纯规则路径不要求 token 计数，preflight 不会因 tokenizer 缺失而 fail closed。若 LLM provider 未提供可靠上下文上限且无法配置，则仅禁用 LLM 增强，不阻断规则构建。`PageRecord.path` 始终是仓库相对路径。Relation 记录保留 `relation_type` 与 `target_id` 两字段；未解析目标必须在 manifest 中报告，**不得**静默移除；unresolved 比例超过 manifest 声明阈值时禁止发布。

Outline JSON 使用 `page_ids`，不使用 `page_titles`：

```json
{
  "schema_version": "book-wiki-outline-v2",
  "snapshot_id": "sha256...",
  "volume_id": "v1",
  "title": "写作基础",
  "is_fallback": false,
  "chapters": [
    {
      "chapter_id": "v1-ch01",
      "title": "选题与立意",
      "overview": "...",
      "overview_refs": ["card_..."],
      "assignments": [
        {"page_id": "card_...", "confidence": 0.92, "role": "core"}
      ]
    }
  ]
}
```

## Tasks

### Task 0: Fail-closed project and runtime preflight

**Files:**
- Create: `src/kc/views/book/wiki/preflight.py`
- Test: `tests/test_kc/test_book_wiki_preflight.py`

**Interfaces:**
- `run_preflight(project_arg: str, *, output_dir: Path, use_llm: bool, provider_name: str | None, polish: bool) -> PreflightReport`
- `acquire_run_lock(lock_path: Path, *, stale_after_seconds: int) -> RunLock` — `stale_after_seconds` 由调用方显式传入（典型值 3600–7200，依运行模式），**不**硬编码；`RunLock` 携带 owner_token / PID / 启动时间；过期接管需 "age > stale_after_seconds" **且** "持有 PID 已退出"（POSIX `kill(pid, 0)` / Windows `OpenProcess`）；缺一不可。
- `release_run_lock(lock: RunLock) -> None` — try/finally 契约；任何异常路径都必须释放。
- `BuildFingerprint` 是唯一缓存身份；不完整运行只作为审计记录，不可续跑。

**实施要点（按必修/可选项分级）：**

- `use_llm=False` 时（默认）：不要求 provider/model/tokenizer；纯规则路径直接通过 preflight。
- `use_llm=True` 时：必须存在 provider/model 及可验证的上下文上限；tokenizer 缺失可由保守估算器替代，无法得到可靠上限时仅禁用 LLM 增强并返回可审计规则版。
- `polish=True` 时：必须存在"内容外发授权"标记；纯规则路径无需该标记。
- 锁文件用 `os.open(..., O_CREAT | O_EXCL)`；释放走 `os.close + os.unlink`；遇异常由调用方 try/finally 兜底。
- 过期接管同时校验：(a) 当前时间 - started_at > stale_after_seconds，(b) PID 已退出；任一不满足即拒绝。
- stale_after_seconds 由调用方按运行模式显式传入；不得硬编码。

- [ ] **Step 1: Write failing tests** for an uninitialized project, missing eligible directories, output paths outside the project root, output paths inside `wiki/` or `.git/`, missing project.json, schema version mismatch, missing provider/model when `use_llm=True` (and **not** required when `use_llm=False`), tokenizer absence with a configured context limit (must remain usable), unauthorized `--polish`, live lock contention, stale-lock takeover (both age-expired-but-alive and dead-but-young), lock release on exception, and a valid initialized project.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_kc/test_book_wiki_preflight.py -v`; each invalid precondition must fail before scanning or calling an LLM.
- [ ] **Step 3: Implement** project resolution through `src.lib.project.resolve_project`; require `.llm-wiki/project.json` with schema 版本匹配、eligible input directories、output path containment (must resolve inside project_root, may be the dedicated `book-wiki/` activation directory, and must not overlap `wiki/`, `.git/`, or `.index/`)。Use `os.open(..., O_CREAT | O_EXCL)` for a cross-platform single-writer lock; stale takeover requires both age-expired and PID-dead, writes an audit event.
- [ ] **Step 4: Verify** all accepted paths resolve inside the project root and that an uninitialized project returns exit code `2` without creating project files. Lock release always runs even when downstream code raises; concurrent lock test asserts second run gets lock-busy error.
- [ ] **Step 5: Commit** `feat(book-wiki): add fail-closed preflight and run lock`.

### Task 1: Freeze Wiki snapshot and parse ordered content blocks

**Files:**
- Create: `src/kc/views/book/wiki/model.py`
- Create: `src/kc/views/book/wiki/scanner.py`
- Test: `tests/test_kc/test_book_wiki_scanner.py`

**Interfaces:**
- `scan_wiki_snapshot(wiki_root: Path) -> WikiSnapshot`
- `canonical_snapshot_json(snapshot: WikiSnapshot) -> str`
- `snapshot_sha256(snapshot: WikiSnapshot) -> str`

- [ ] **Step 1: Write failing tests** for dynamic page counts, excluded directories, duplicate IDs, duplicate titles, missing frontmatter, malformed frontmatter, empty body, repeated headings, preamble text, invalid UTF-8, symlink escape, change-during-scan, and stable snapshot hash.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_kc/test_book_wiki_scanner.py -v`; malformed pages and duplicate IDs must fail explicitly.
- [ ] **Step 3: Implement** a strict raw Markdown reader in this module; do not use `read_page()` for validation because it treats YAML errors as empty metadata. Distinguish absent, valid, and invalid frontmatter; map `PageType` and `custom_type` explicitly; preserve heading order as `ContentBlock` tuples, retain preamble as `heading=None`, and reject files that change during the scan. Canonical hashing uses repository-relative paths and includes `schema_version`, page IDs, relation types, content hashes and (when available) token counts, never absolute paths.
- [ ] **Step 4: Verify** the scanner reports dynamic counts, token counts (None when tokenizer unavailable), relation types, and structured errors; changing one body changes `snapshot_id` while reordering directory iteration does not. The scanner reads file inventory and content hashes twice; any path or content-hash change aborts the snapshot and requires a new run. mtime/size is **not** part of the consistency check (it's noisy and not a content property); only inventory paths + content hashes are checked.
- [ ] **Step 5: Commit** `feat(book-wiki): freeze wiki snapshot contract`.

### Task 2: Define outline schema and exact coverage validator

**Files:**
- Create: `src/kc/views/book/wiki/outline_model.py`
- Create: `src/kc/views/book/wiki/outline_validate.py`
- Test: `tests/test_kc/test_book_wiki_outline_validate.py`

**Interfaces:**
- `validate_outline(snapshot: WikiSnapshot, outlines: list[dict]) -> ValidationReport`
- `ValidationReport.ok: bool`
- `ValidationReport.errors: tuple[ValidationError, ...]`
- `build_page_index(outlines) -> dict[str, PageAssignment]` — raises on duplicate IDs; never overwrites.
- `validate_outline_schema(payload: object) -> tuple[ValidationError, ...]`

Allowed `role` values are `core`, `method`, `pitfall`, `case`, and `reference`. `confidence` is optional and informational; when present it must be finite and in `[0, 1]`. It must not affect partition, ordering, or publish gating; fallback membership is determined by the deterministic partition.

**约束调整（来自复审）：**

- 卷数由内容决定，不得固定 4–8；fallback volume 仅在存在未分类页面时存在，无未分类页面时**不**生成空兜底卷。
- 验收用例不要硬编码 1255；使用 fixture 动态构造不同规模的快照。

- [ ] **Step 1: Write failing tests** for missing IDs, unknown IDs, duplicate assignment, duplicate volume/chapter IDs, optional fallback volume (exists only when unclassified pages exist), invalid confidence, and dynamic-size valid cases (small/medium/large).
- [ ] **Step 2: Run** the focused test file and confirm the validator rejects each invalid case.
- [ ] **Step 3: Implement** versioned schema checks and multiset coverage: `Counter(assigned_page_ids) == Counter(snapshot.page_ids)`; validate `snapshot_id`, schema types, finite confidence values when supplied, allowed roles, unique volume/chapter IDs, at-most-one `is_fallback` volume (zero when no unclassified pages), non-empty `overview_refs` that resolve to assigned page IDs, and non-overwriting page indexes.
- [ ] **Step 4: Verify** titles may repeat without affecting identity, duplicate IDs are rejected before dict construction, and every error includes page or chapter context.
- [ ] **Step 5: Commit** `feat(book-wiki): validate stable-id outline coverage`.

### Task 3: Partition pages deterministically, then plan chapters within each partition

**级别：必修（确定性分区、整页分块、规则版覆盖）；可选（LLM 标题与 overview）。**

**Files:**
- Create: `src/kc/views/book/wiki/outline_llm.py`
- Create: `src/kc/views/book/wiki/partition.py`
- Test: `tests/test_kc/test_book_wiki_outline_llm.py`

**Interfaces:**
- `partition_pages(snapshot: WikiSnapshot) -> dict[str, tuple[str, ...]]` — 卷数由内容决定（不固定 4–8）；fallback volume 仅在存在未分类页面时存在。
- `build_chapter_chunks(snapshot: WikiSnapshot, partitions: dict[str, tuple[str, ...]], *, context_window: int, output_reserve: int) -> dict[str, tuple[str, ...]]`
- `plan_outline(snapshot: WikiSnapshot, chapter_chunks: dict[str, tuple[str, ...]], provider: LLMProvider, *, context_window: int, token_budget: int) -> list[dict]`
- `load_or_plan_outline(snapshot, chapter_chunks, provider, state_dir: Path, fingerprint: BuildFingerprint, ...) -> list[dict]`
- `class OutlinePlanningError(Exception)` with `retryable: bool` and `errors`.

**约束调整（来自复审）：**

- `volume_count` 不再硬编码 7；由实际可形成的非空 taxonomy 分区数决定。
- fallback volume 仅在存在 unclassified page 时存在；不存在时**不**生成空卷。
- `response_format={"type": "json_object"}` 仅在 provider 支持时尝试；不支持时回退到 prompt 指令 + 严格 JSON 解析 + schema 校验。
- LLM 原始响应**不**持久化；只保存摘要、hash、错误分类。

- [ ] **Step 1: Write failing tests** for deterministic taxonomy/type partitioning, optional fallback (present only with unclassified pages), complete page-ID coverage, chapter chunks that never split a content block, per-chunk context limits, valid JSON, truncated output, HTTP 429/5xx retry, 401/unsupported-format no-retry, and cached fingerprint mismatch.
- [ ] **Step 2: Run** the focused tests and confirm provider calls are recorded without making network calls.
- [ ] **Step 3: Implement** `partition_pages()` locally: group by `(page_type, primary_taxonomy)`, sort groups and page IDs lexicographically; 卷数按实际非空分组数决定（无硬上限下限），fallback volume 仅在存在 unclassified page 时创建。No LLM call can move a page between partitions. Validate the partition with a page-ID multiset before any LLM call.
- [ ] **Step 4: Implement** `build_chapter_chunks()` by accumulating whole pages in stable ID order until `context_window - output_reserve` would be exceeded; a single page larger than the limit becomes a rule-only chapter and is never sent to the LLM. Each chunk gets a stable chapter ID before any LLM call. **Only when `--use-llm` is enabled**, calls may name and summarize that fixed chunk; every overview must cite `overview_refs` from that chunk, and the model never creates, moves, merges or splits assignments. 尝试 `response_format={"type":"json_object"}` when provider supports it; fall back to prompt-based JSON + schema validation otherwise. Reject responses that do not match the versioned schema.
- [ ] **Step 5: Implement** retry classification: at most two retries for transient errors or malformed/truncated responses; no retry for authentication, unsupported format after fallback, invalid schema after retry, or fingerprint mismatch. Persist only digest + hash + error category under `state_dir/<fingerprint>/outline/`（不保存原始响应体）。
- [ ] **Step 6: Run** `validate_outline` after chapter chunks are created and after the final outline; in LLM mode record actual token/attempt usage and stop at the explicit budget, returning a complete rule-only plan for uncalled chunks so coverage remains valid. Pure-rule mode skips provider accounting entirely.
- [ ] **Step 7: Commit** `feat(book-wiki): add deterministic partitions and bounded outline planner`.

### Task 4: Build rule-based chapter aggregation without content loss

**Files:**
- Create: `src/kc/views/book/wiki/aggregator.py`
- Create: `src/kc/views/book/wiki/section_buckets.py`
- Create: `src/kc/views/book/wiki/reading_aids.py`（新增：glossary/index/章节内排序）
- Test: `tests/test_kc/test_book_wiki_aggregator.py`
- Test: `tests/test_kc/test_book_wiki_reading_aids.py`

**Interfaces:**
- `aggregate_chapter(chapter: dict, pages: dict[str, PageRecord]) -> ChapterDraft`
- `ChapterDraft.blocks: tuple[ContentBlock, ...]`
- `ChapterDraft.page_ids: tuple[str, ...]`
- `ChapterDraft.bucket_index: dict[str, tuple[str, ...]]`
- `ChapterDraft.block_ids: tuple[str, ...]`
- `ChapterDraft.transition_in: str | None`     # 占位文本（纯规则）或 LLM 生成的过渡
- `ChapterDraft.transition_out: str | None`
- `ChapterDraft.intra_chapter_order: tuple[str, ...]`  # 章节内 page_id 序列
- `build_glossary(snapshot: WikiSnapshot) -> dict[str, GlossaryEntry]` — 从 wikilink + page_type + taxonomy + grade 提取
- `build_index(snapshot: WikiSnapshot, outlines: list[dict]) -> IndexManifest` — page_id → (chapter_id, page_type, title, taxonomy)
- `order_pages_within_chapter(chapter: dict, pages: dict[str, PageRecord], *, mode: Literal["rule_only", "llm_enhanced"]) -> tuple[str, ...]`
  - `rule_only`: 按 (page_type 优先级, grade 优先级, page_id) 三键排序
  - `llm_enhanced`: LLM 在 token 预算内输出 page_id 序列，仍受 ID 多重集校验保护

- [ ] **Step 1: Write failing tests** for repeated headings, unknown headings (must be retained as fallback bucket, not silently dropped), empty sections, preambles, concept/entity/synthesis templates, same page in multiple buckets, glossary deduplication, index completeness, rule-only ordering stability, and LLM ordering integrity (multiset + per-page-once)。
- [ ] **Step 2: Run** the focused tests and confirm every input block is accounted for.
- [ ] **Step 3: Implement** ordered block aggregation. Fuzzy matching may choose a display bucket, but it must never remove or merge blocks; retain original heading and `block_id`. 未匹配 heading 进入"未分类"桶，并在 manifest 中标注数量。
- [ ] **Step 4: Implement** `build_glossary` 与 `build_index` (pure rule): glossary 收录所有 inbound wikilink 目标 + 每页 title 与首句；index 收录每页到章节/卷的映射。两者**必须**基于扫描得到的 `page_id`，不得使用页面标题作为 key。
- [ ] **Step 5: Verify** `Counter(draft.block_ids) == Counter(all_source_block_ids)` and that deterministic ordering is stable across runs; retain relation type and target ID for every rendered relation. 未解析目标（unresolved relations）保留并在 manifest 标注，**不得**静默移除；unresolved 比例超过 manifest 声明阈值时禁止发布。
- [ ] **Step 6: Commit** `feat(book-wiki): aggregate ordered wiki blocks with reading aids`.

### Task 5: Make polishing editorial-only and prove block preservation

**级别：可选增强。** 正文守恒、哈希与链接校验属于必修；LLM 润色本身不属于最小可交付范围。

**Files:**
- Create: `src/kc/views/book/wiki/polish_llm.py`
- Create: `src/kc/views/book/wiki/polish_validate.py`
- Test: `tests/test_kc/test_book_wiki_polish.py`

**Interfaces:**
- `polish_chapter(draft: ChapterDraft, provider: LLMProvider, ...) -> PolishedChapter`
- `validate_polished_chapter(draft: ChapterDraft, polished: PolishedChapter) -> tuple[str, ...]`
- `PolishedChapter.block_order: tuple[str, ...]`         # 章节内 page_id 顺序（与 draft.intra_chapter_order 多重集相等）
- `PolishedChapter.transition_in: str | None`
- `PolishedChapter.transition_out: str | None`
- `PolishedChapter.editorial_sections: tuple[str, ...]`
- `PolishedChapter.polished: bool`
- `PolishedChapter.failure_reason: str | None`

- [ ] **Step 1: Write failing tests** for deleted blocks, duplicated blocks, changed body text, invented wikilinks, malformed JSON, valid editorial additions, transition_in/out 引用合法 block_ids, and intra-chapter order multiset integrity.
- [ ] **Step 2: Run** tests and confirm all body mutations are rejected.
- [ ] **Step 3: Implement** a prompt that asks only for block ordering + `transition_in`/`transition_out` + bounded overview/transitions/summary; every generated sentence must cite one or more existing block IDs, and body text is rendered locally from the original `ContentBlock` values. `transition_in/out` 也必须 cite 至少一个 chunk 内 block_id。
- [ ] **Step 4: Implement** exact block-ID multiset, canonical body hash, allowed-wikilink, editorial-token-limit, intra-chapter order multiset, and `transition_in/out` citation checks. Do not use a percentage-loss threshold or hash-string length as a content metric.
- [ ] **Step 5: On failure**, retain the unpolished `ChapterDraft`, set `polished=false`, record the reason and response hash, and continue without a second semantic rewrite. Default CLI behavior is `polish=false`.
- [ ] **Step 6: Commit** `feat(book-wiki): constrain polishing to editorial text`.

### Task 6: Compile manifest and publish through a recoverable staging boundary

**Files:**
- Create: `src/kc/views/book/wiki/compiler.py`（合并原 publisher.py；不新增独立 publisher）
- Test: `tests/test_kc/test_book_wiki_compiler.py`

**Interfaces:**
- `compile_book(snapshot, outlines, pages, *, fingerprint: BuildFingerprint, polish=False, state_dir=None) -> BuildArtifact`
- `publish_book(artifact: BuildArtifact, output_dir: Path, *, apply: bool, lock: RunLock) -> PublishReport`
- `resolve_active_version(output_dir: Path) -> Path` — reader 入口；指针缺失/解析失败/hash 不匹配时返回 `None`（**不**静默回退）。
- `BuildArtifact.snapshot_id`, `.manifest`, `.version_dir`, `.validation_errors`（流式落盘，**不**在内存中保存全量文件 bytes）

**架构调整（来自复审，避免二重发布协议）：**

- **复用** `src/kc/views/book/rebuild.py::rebuild_book` 的 staged commit、manifest 校验和旧版本保留语义；`compiler.py` 可保留为编译入口，但不得再造一套独立 publisher 状态机。
- 命名空间隔离：`book-wiki/`（激活内容，命名空间与 KC `book/` 完全分离）；`book-wiki/.releases/<run_id>/`（不可变 release 副本）；`.index/book-wiki/versions/<run_id>/`（staging）。
- 指针文件：`<project_root>/book-wiki/CURRENT.json`，结构 `{"version":"<run_id>","manifest_sha256":"<sha256>"}`，UTF-8 JSON，确定键序。
- reader 通过 `resolve_active_version(<project_root>) -> Path | None` 解析；缺指针时返回 `None`，reader 必须显式处理。
- 旧版本必须保留；指针替换前不删除旧 release；失败时回滚旧指针。

**磁盘与版本保留策略（新增）：**

- 单项目保留 release 数 ≤ 5（可通过配置调整）；超过时按 LRU 清理最旧 release，仅当 release 不再被任何指针引用时才允许清理。
- staging 目录 (`.index/book-wiki/versions/`) 视为可清理运行数据；不得作为最终交付位置。
- 每次 `--apply` 完成后输出磁盘占用与 release 数量统计（manifest 中记录）。
- 阶段任务（失败注入）必须覆盖"磁盘满/IO 错误"分支，确保 release 写入失败时旧 release 仍可读。

- [ ] **Step 1: Write failing tests** for dynamic counts, unsafe titles, Windows-reserved filenames, manifest/file mismatch, snapshot mismatch, disk-write failure, interrupted publish, missing-pointer resolve (`None`), hash-mismatched pointer resolve (`None`), release-count cap, and LRU cleanup preserving still-referenced releases.
- [ ] **Step 2: Run** focused tests and confirm failed validation never writes to the target directory.
- [ ] **Step 3: Implement** filename generation from `volume_id`/`chapter_id`, not titles; 流式写入 `.index/book-wiki/versions/<run_id>/`，完成校验后按现有 release 语义写入 `book-wiki/.releases/<run_id>/`；include `snapshot_id`, build fingerprint, source filter, actual counts, chapter hashes, block counts, polish status, relation resolution, unresolved relation 列表与比例, **reading_experience_mode** (`rule_only` | `llm_enhanced`), glossary hash, index hash, and provider usage digest in a versioned `manifest.json`. **`files` 字段不保存全量 bytes**；保存 `path -> sha256` 映射即可。
  - **V4 预留字段**（V3.2 阶段 schema 中保留但不写值）：`quality_gate_report`, `reader_task_report`, `mode_history`, `encyclopedic_outline_hash`, `cross_link_candidates`。V3.2 manifest.json 校验器允许这些字段为 null/缺失；V4 阶段补全。
- **额外产物文件**：
  - `book-wiki/.releases/<run_id>/glossary.md`（纯规则生成；LLM 启用路径可追加"作者视角说明"段，但仍以规则版为基线）
  - `book-wiki/.releases/<run_id>/index.md`（page_id → 标题/类型/taxonomy/章节）
  - 每章 Markdown 中保留 `## 本章导读`（=overview + transition_in）、`## 本章衔接`（=transition_out）；LLM 关闭时填占位"本章为规则版排序"。
- [ ] **Step 4: Write** all files to `.index/book-wiki/versions/<run_id>/` (staging); on success move/copy to `book-wiki/.releases/<run_id>/`; validate manifest, hashes, link targets and stale-file set before publish.
- [ ] **Step 5: Publish** the complete release first, then atomically replace only `book-wiki/CURRENT.json` with `{"version": "<run_id>", "manifest_sha256": "..."}`. Readers resolve the active version through this pointer. Keep the previous pointer until the new pointer is durable; on failure restore the previous pointer and leave both release directories readable. LRU cleanup of old releases happens **after** pointer swap succeeds and only for releases not referenced by any pointer.
- [ ] **Step 6: Verify** `resolve_active_version()` rejects a missing or hash-mismatched pointer (returns `None`). If cache reuse is enabled, a second build may reuse only complete deterministic stages with matching fingerprint and file hashes; otherwise it performs a clean rebuild and must produce the same chapter hashes.
- [ ] **Step 6a: Harden pointer recovery** by fsyncing version files and their parent directory before pointer replacement; an interrupted replacement must leave either the previous valid pointer or a recoverable staged release, never a partially written JSON file. Cache reuse is allowed only for a complete run whose file hashes and fingerprint match.
- Canonical pointer payload: `{"version":"<run_id>","manifest_sha256":"<sha256>"}`; serialization must be UTF-8 JSON with deterministic key order.
- [ ] **Step 7: Commit** `feat(book-wiki): compile and recoverably publish versioned output`.

### Task 7: Register CLI and expose dry-run/apply controls

**Files:**
- Modify: `src/cli.py`
- Modify: `src/cli_ext/book_cmd.py`
- Create: `tests/test_cli_ext/test_book_build_from_wiki.py`

**Interfaces:**
- Command: `python -m src.cli book build-from-wiki --project <id> [--output-dir book-wiki] [--use-llm] [--polish] [--apply] [--max-attempts N] [--max-input-tokens N] [--max-output-tokens N] [--json]`
- Exit codes: `0` success, `1` build or publish failure, `2` project unresolved, `3` no eligible pages, `4` snapshot/fingerprint mismatch, `5` lock busy, `6` budget exhausted, `7` unresolved-relation-over-threshold, `8` disk-pressure`.

**新增关键测试（必修）：**

- Reader 入口：`resolve_active_version` 缺指针返回 `None`，不静默回退；hash 不匹配返回 `None`。
- 关系与来源策略：未解析 relation 列表必须在 manifest 出现；unresolved 比例超过声明阈值时发布被阻断（exit 7）。
- excluded sources（来自 `wiki/sources/`、`wiki/_stubs/`、`wiki/_archive/`）的关系必须出现在 manifest 的 source provenance 列表中，但**不**迁移到正文。
- 磁盘上限检查：磁盘可用空间不足时返回 exit 8，不进入发布阶段。
- LLM 边界条件：未传 `--use-llm` 时不应要求 provider/tokenizer；`--polish` 需内容外发授权。

- [ ] **Step 1: Write failing CLI tests** for command registration, default dry-run, `--apply`, output-dir resolution relative to project root, stale-cache rejection, JSON report, exit codes (including 7/8), reader `resolve_active_version` 行为，unresolved 比例阻断, excluded sources 出现在 manifest, and disk-pressure exit.
- [ ] **Step 2: Run** the focused CLI tests and confirm the command is initially unavailable or fails before implementation.
- [ ] **Step 3: Implement** the parser in `src/cli.py`; keep `book build` unchanged and route the new command through the V3 compiler. Add `--use-llm` (default false) to make the LLM opt-in; do not add a redundant `--no-llm` alias.
- [ ] **Step 4: Implement** preflight checks for project resolution, eligible-page count, output path containment, lock ownership, unresolved-relation ratio, and disk space threshold. Check provider availability and token budgets only when `--use-llm`; record run states `scanned`, `partitioned`, `outlined`, `aggregated`, `polished`, `staged`, `published`; a failed run always starts a new run. Cache reuse is optional and, when enabled, requires a complete entry with matching fingerprint and file hashes.
- [ ] **Step 5: Verify** dry-run writes only run state under `.index/book-wiki/versions/` and `--apply` changes only `book-wiki/` after all gates pass.
- [ ] **Step 6: Commit** `feat(cli): add wiki-to-book v3 command`.

### Task 8: Run pilot, failure injection, and end-to-end acceptance

**Files:**
- Create: `tests/test_kc/test_book_wiki_e2e.py`
- Modify: `.superpowers/sdd/progress.md`

**故障注入范围（必修覆盖关键类别，其余故障可后置）：**

| 类别 | 必修覆盖项 |
|---|---|
| **发布安全** | 项目未初始化（exit 2）；坏页 / 重复 ID 扫描阶段阻断；指针失败（写入 `CURRENT.json` 中断）；旧版本保留（发布失败时旧 release 仍可读）；磁盘压力（exit 8）；磁盘 IO 失败（写 staging 失败） |
| **锁安全** | 锁冲突（两进程并发）；过期接管需双条件校验（age + PID-dead）；异常路径 release |
| **快照/内容守恒** | source body 变化 → snapshot 拒绝；unresolved 关系超阈值（V3.2 exit 7；V4 仍保留）；坏 frontmatter |
| **LLM 边界** | provider 失败（仅当启用 LLM）：timeout、truncated JSON、429/5xx 重试、401/不支持格式不重试 |

其余故障注入（细分 provider 错误、覆盖整链路所有阶段的瞬时错误等）作为可选增强。

- [ ] **Step 1: Build a fixture** containing duplicate titles, repeated headings, malformed pages, long pages, all three included page types, excluded source pages (must appear in source provenance only), and at least one unresolved relation.
- [ ] **Step 2: Run** the one-chapter pilot with `--dry-run --json`; require zero missing/unknown/duplicate IDs and a complete block ledger. Confirm `resolve_active_version` returns `None` (no apply yet) and reader surfaces this as "no active book-wiki".
- [ ] **Step 3: Inject** provider timeout, truncated JSON, disk-write failure, changed source body, concurrent run, unsafe output path, interrupted pointer publish, unresolved-relation-over-threshold, and disk-pressure; verify retry classification, snapshot rejection, lock behavior, old-output preservation, exit codes 7/8, and LRU cleanup not removing referenced releases.
- [ ] **Step 4: Run** the full baseline build; compare manifest counts to the scanner result rather than to a hardcoded constant.
- [ ] **Step 5: Perform** manual review against explicit criteria: every non-empty chapter has a resolvable, cited overview (no empty fallback volume when no unclassified pages exist), every page is traceable by ID, every block appears once, no body block is changed, unresolved relations are explicitly listed in manifest, excluded sources appear in source provenance only (not in book body), and failed polishing is visibly marked.
- [ ] **Step 6: Record** commands, counts, hashes, failures, rollback evidence, exit codes, and release-count-after-publish in the progress ledger; commit `test(book-wiki): verify v3 end to end`.

## Acceptance Gates

> 验收条件使用动态观测值，**不得**将当前规模数字（如 1255 / 463）固化为实现契约。

Implementation may proceed from one task to the next only when the previous task's mandatory tests pass. Full acceptance requires the **必修基线** below；**可选增强**只在对应 flag 或能力启用时验收：

- Scanner count equals the dynamically discovered eligible-page count（当前观测为 ~1255 included / ~463 excluded，仅供参考）。
- Final outline passes exact ID multiset coverage: every eligible page appears exactly once, with no unknown or duplicate ID.
- Every chapter draft has a complete block ledger using multiset equality; no parser or bucket fallback silently drops or duplicates content.
- When `--polish` is enabled, output either passes exact block/body preservation and citation checks or is replaced by the unpolished draft with `polished=false`; pure-rule builds skip this stage.
- `manifest.json` matches staged files, hashes, counts, snapshot ID, build fingerprint and relation resolution; provider usage digest is required only for LLM runs。
- Dry-run produces no `book-wiki/CURRENT.json` mutation; apply publishes a complete version before replacing the pointer; an injected pointer failure leaves the previous Book readable.
- Output-dir validation rejects paths outside the project root and paths inside `wiki/` / `.git/` / `.index/`; the dedicated `book-wiki/` activation directory is allowed. `--polish` is refused unless the configured content-export authorization and policy check pass.
- If cache is enabled, re-running with the same fingerprint is idempotent by chapter hash and changes no active content when the staged version is identical; cache is not a prerequisite for correctness.
- CLI command is registered in `src/cli.py` and passes a real subprocess smoke test.
- The run lock prevents concurrent builds, **and** stale takeover requires both age-expired AND PID-dead. In LLM mode, budget exhaustion returns a complete, explicitly marked unpolished result or a clear failure without further LLM calls.
- Reader `resolve_active_version()` returns `None` on missing/mismatched pointer; reader surfaces this as explicit "no active book-wiki" error (no silent fallback).
- Excluded sources (来自 `wiki/sources/`、`wiki/_stubs/`、`wiki/_archive/`) appear in manifest source provenance only; they do not appear in any chapter body.
- Unresolved relations listed in manifest; unresolved 比例超过 manifest 声明阈值时发布被阻断（V3.2/V4 exit 7）。其它规则质量门阻断使用 V4 exit 9。
- Disk-pressure detected pre-commit; release count does not exceed cap; LRU cleanup never removes still-referenced releases.
- Pure-rule path (未传 `--use-llm`) succeeds end-to-end without any provider/tokenizer/`response_format` requirement.
- **阅读体感（必须）**：
  - **全文术语表与索引**：`glossary.md` 与 `index.md` 在纯规则路径下也**必须**生成；glossary 至少包含每个页面 title 与首句；index 覆盖所有 eligible page_id，page_id → (chapter_id, page_type, taxonomy) 映射完整。
  - **章节内排序**：`intra_chapter_order` 与 `ChapterDraft.page_ids` 多重集相等；纯规则路径按 (page_type 优先级, grade 优先级, page_id) 排序且跨运行稳定；LLM 路径在保留多重集的前提下允许 LLM 重排，校验 `Counter(order) == Counter(draft.page_ids)`。
  - **章节间过渡与导读**：LLM 路径下 `transition_in` / `transition_out` / `overview` 必须存在并 cite 至少一个 chunk 内 block_id；纯规则路径下占位文本与 `reading_experience_mode = "rule_only"` 标注必须出现，**不**声称满足阅读体感。
- **不声称**：本版本**不**承诺"读者任务验收"（如"新手读完能写出 3 类钩子"）。这是 V4 计划范畴。

## Audit Gates Before Coding

### Round 1: defect closure

The V2 blockers are closed by explicit V3.2 changes: fail-closed preflight and scanning (Tasks 0–1), stable IDs and one versioned schema (Task 2), deterministic partitioning before bounded LLM calls (Task 3), multiset block coverage (Task 4), immutable content blocks (Task 5), pointer-based publication reusing existing release mechanism (Task 6), CLI registration with complete-cache reuse only (Task 7), and failure injection (Task 8).

### Round 2: pressure-test boundary

The plan is blocked if any of these conditions is unresolved: uninitialized project; missing `.llm-wiki/project.json`; duplicate or missing page IDs; a partition with no valid chapter plan; input or output exceeding provider limits without a split (LLM path only); provider authentication failure (LLM path only); fingerprint or snapshot mismatch; lock contention; lock auto-takeover without PID-dead check; disk failure during staging or pointer publish; unresolved relation over threshold; or an absent human reviewer for the pilot. Each condition must stop before publication or restore the previous pointer.

> **V4 增量**（见 [`docs/superpowers/plans/2026-09-05-wiki-to-book-v4.md`](2026-09-05-wiki-to-book-v4.md)）：quality gate 4 维规则硬限（block 多重集 / unresolved 比例 / 未匹配 heading / glossary 覆盖率）任一超阈值 → exit 9；reader task RubricSpec 通过率 < 80% → exit 10（警告非阻断）；LLM provider 不可用（`truncated=True` / `content_length=0` / `finish_reason=length` 三态任一）→ exit 6；encyclopedic 模式 LLM 不可用**不**回退。

## Rollback

Rollback means releasing the run lock, retaining the failed run's manifest and error log for audit, and restoring the previous `book-wiki/CURRENT.json` pointer. Release directories under `book-wiki/.releases/` are immutable during recovery and are never deleted by the publisher; only the LRU cleanup (separate, post-publish, never blocks a release in active use) may prune old releases. Wiki pages, KC `book/`, and existing KC state are never modified by this plan. If the previous pointer is missing or cannot be restored, publication stops before pointer replacement and reports exit code 1.

首次发布是例外：不存在旧指针时，只有在完整 release 目录、manifest 和文件哈希全部验证通过后才允许创建首个 `CURRENT.json`；只有"原先存在但损坏或无法恢复"的旧指针才构成回滚阻断。

## Open Preconditions

Before Task 0 begins, the implementer must explicitly:

- Initialize/register the project (`python -m src.cli project init <path>` or import existing) so `.llm-wiki/project.json` exists with matching schema version.
- Decide the **LLM mode**: pure-rule (未传 `--use-llm`, default) or LLM-enabled (`--use-llm`). Only for LLM mode: provider/model and a verifiable context/output limit; tokenizer is optional when the conservative estimator is used.
- Define the **reader/Markdown renderer** that will consume `book-wiki/CURRENT.json`.
- Define the **source-to-relation policy** for excluded pages (sources/、_stubs/、_archive/): how relations are preserved in manifest without leaking into chapter body.
- Define the **legal/PII policy** for any content sent to an external provider (only relevant when LLM mode is enabled AND `--polish` is on).
- Define the **content-export authorization** required by `--polish` (only relevant when LLM mode is enabled).
- Decide whether `book-wiki/` is **distributed together with the source wiki** (impacts output path containment and `.gitignore`).
- Decide the **release cap** and **disk-pressure threshold** for cleanup policy.

These are execution inputs; they must not be inferred from the V2 document.

## Scope Clarification (vs V3.1)

V3.2 is the **safety-first structured compiler** ("可审计的 Wiki 拼装器"), not the original "百科全书" goal. V3.2 把阅读体感收敛为：

- **已纳入必修**：章节间过渡与导读（依赖 LLM；纯规则路径仅占位）、全文术语表与索引（纯规则可达）、章节内语义排序（依赖 LLM；纯规则路径按启发式）。
- **仍属 V4 范畴**：跨页面知识融合、读者任务验收 (acceptance rubric)、语义质量自动评分。V4 计划应至少补齐：domain schema、quality gate、reader task validation（含 5–10 个读者使用场景 + 验收样本）。

> 用户决策记录（2026-09-05）：用户选择把"章节间过渡与导读 / 全文术语表与索引 / 章节内顺序的语义排序"覆盖进 V3.2，"读者任务验收"留到 V4 单独处理。V3.2 完成不声明已实现百科全书目标。

## 后续路径（V3.2 → V4）

V3.2 完成后，V4 计划按 P0/P1/P2 三级排序实施（详见 [`docs/superpowers/plans/2026-09-05-wiki-to-book-v4.md`](2026-09-05-wiki-to-book-v4.md)）：

- **P0**（V3.2 安全基线，9 Task）：V3.2 全部 Task 0–8 沿用作为依赖；新增 `--encyclopedic` 模式 flag 透传。
- **P1**（阅读体验完整化，6 Task）：T9 ChapterSort 语义启发式、T10 GlossaryBuilder、T11 IndexBuilder、T12 TransitionWriter、T13 ReadingExperience Manifest、T14 阅读体验验收。
- **P2**（验收 + 融合，8 Task）：T15 质量门规则硬限、T16 质量门 LLM 软评分、T17 RubricSpec YAML schema、T18 ReaderTaskRunner、T19 EncyclopedicOutline（V4 核心）、T20 CrossLinkSuggester、T21 验收 fixture + E2E、T22 V4 全量验收 + 双向回归。

V4 完成 ≠ 写作百科全书目标达成；V4 是百科全书的**工程基础**（机械可达 + 自动化验收），主观质量仍需人工放行。
