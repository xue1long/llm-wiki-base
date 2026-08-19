# Capture 模板方案 — 全面漏洞审计报告

**审计日期：** 2026-08-14
**审计对象：** ruflo-kb capture bundled 模板方案（POST /capture API + CLI capture 命令）
**审计依据：** 源码实证 + 方案文档交叉比对

---

## 审查要求

按 7 步严格执行：隐含假设识别 → 异常场景穷举 → 逻辑断层 → 潜在 bug/风险/合规 → 信息盲区 → 三级分类 → 漏洞位置 + 风险后果 + 整改建议。

---

## 一、致命缺陷（方案无法落地）— 2 项

### F-1: capture 模板对非 capture 项目不可用 —— schema 声明 ≠ 注册生效

**漏洞位置：** 方案"关键设计决策" → "capture 通道对任何项目可用，不检查项目模板类型"

**隐含假设：** `SchemaRegistry.is_custom()` 会自动发现 bundled 模板中的 `schema.md`。

**实际机制：** `SchemaRegistry.from_project(root)` 读取的是**项目根目录的 `schema.md`**（`src/wiki/schema_registry.py` line 98-101），不是模板目录的。如果项目是用 `general` 模板初始化的，其 `schema.md` 只有 `source/entity/concept/synthesis` 四行，不包含 `article`/`video-transcript`/`inspiration`。

**风险后果：** `write_page()` 在 `page_writer.py` line 106-111 检查 `registry.is_custom(custom_type)`，对未声明的类型直接 `raise ValueError("Custom page type 'article' is not declared in schema.md")`。API 和 CLI 在已初始化的非 capture 项目上必然 HTTP 500。

**真实场景案例：** 用户已有一个 `research` 项目，POST `/capture` 传入 `type=article`，服务端调用 `write_page()` → `SchemaRegistry.from_project(research_root)` → `is_custom("article")` 返回 False → ValueError → HTTP 500。**所有现有项目都无法使用 capture 功能。**

**整改建议：** capture 通道必须在写入前执行 schema 合并：读取项目现有 `schema.md`，检测缺失的 custom type 行（`article | wiki/articles | source`、`video-transcript | wiki/video-transcripts | source`、`inspiration | wiki/inspirations | concept`），追加后写回。或提供 `schema_patch(schema_path, custom_types)` 工具函数。**绝不能用 `apply_template` 覆盖整个 schema.md。**

---

### F-2: `source_status` / `capture_context` 扩展字段 round-trip 必然丢失

**漏洞位置：** 方案"关键设计决策" → "不改 WikiPage dataclass"，"to_frontmatter_dict / from_dict 不改"

**隐含假设：** 扩展字段写入 frontmatter 后能被 `from_dict` 正确读回。

**实际机制：** `WikiPage.from_dict()` 是**白名单构造**（`types.py` line 90-112），只提取已知字段名。任何 `d.get("source_status")` 之类未列名的 key 都会被**静默丢弃**。`to_frontmatter_dict()` 同理只序列化 dataclass 属性（line 63-87）。

**风险后果：** 写入时如果手拼 YAML 包含 `source_status`，读回时 `WikiPage.from_dict()` 丢弃该字段。后续更新页面（如补内容）再 `write_page()` 时，序列化出来的 frontmatter 不含 `source_status` → **字段静默消失**。用户以为数据在，实际已丢失。

**真实场景案例：** 用户通过 capture 创建了一个 `article` 页，frontmatter 含 `source_status: pending`。之后用 WebUI 编辑该页保存 → `read_page()` → `WikiPage.from_dict()` 丢弃 `source_status` → `write_page()` → `to_frontmatter_dict()` 输出不含 `source_status` → 字段消失，依赖此字段的筛选/看板功能永久失效。

**整改建议（二选一）：**

1. **推荐：** 在 `WikiPage` dataclass 加 `source_status: str = ""` 和 `capture_context: str = ""` 字段，同步更新 `to_frontmatter_dict` / `from_dict`。方案声称"不改 WikiPage"，但这个声明本身是致命设计错误——扩展字段不入 dataclass 就无法 round-trip。
2. **轻量替代：** 利用已有的 `_ko_extra` 机制（`types.py` line 84-86）。修改 `from_dict()` 将未识别的字段存入 `_ko_extra` dict，`to_frontmatter_dict()` 序列化时合并回去。这样不改 dataclass 但保证 round-trip。

---

## 二、重大隐患（容易失败）— 7 项

### M-1: `apply_template` 覆盖已有 schema.md / purpose.md

**漏洞位置：** `apply_template()` (`loader.py` line 109-126) + 方案模板文件结构含 `schema.md`、`purpose.md`

**隐含假设：** 项目根目录不存在同名文件。

**实际机制：** `apply_template()` 默认 `force=False`，冲突文件被跳过（line 115-122）。如果项目已有 `schema.md`（几乎是必然的），capture 模板的 `schema.md`（含三条 custom type 声明）**不会被写入**，而项目 schema 不包含 `article/video-transcript/inspiration`，回到 F-1 的死路。如果 `force=True`，则**覆盖**项目原有 schema，销毁所有已有 custom type 声明。

**真实场景案例：** research 项目有 `thesis/methodology/finding` 三个 custom type。`apply_template("capture", root, force=True)` → 项目 schema 被 capture 的覆盖 → `thesis` 等类型全部失效 → 历史上所有 thesis 页的 `write_page` 全部报错。

**整改建议：** 不应将 `schema.md` / `purpose.md` 放在 capture 模板中。改为在 capture 服务层中做**合并注入**：读取项目现有 `schema.md`，追加缺失的 custom type 行，写回。

---

### M-2: `taxonomy.md` 覆盖导致标签体系混乱

**漏洞位置：** 模板文件结构含 `taxonomy.md` + `taxonomy_tags.md`

**隐含假设：** 项目还没有自己的 taxonomy。

**实际机制：** 同 M-1，`apply_template` 默认跳过已有文件。但若用 `force` 模式或项目无 taxonomy，则 capture 的 taxonomy（可能包含 capture 特有标签如 `待整理`、`灵感碎片`）会覆盖或冲突。

**真实场景案例：** 用户的 novel 项目有精心设计的 taxonomy（`题材/玄幻`、`角色/主角` 等），capture 模板的 taxonomy 引入不兼容的标签体系，导致 `TaxonomyRegistry.validate()` 对已有页面产生新的 validation warning/error。

**整改建议：** capture 模板不应包含 `taxonomy.md`。如果 capture 页面需要特殊标签，通过 `tags` 字段直接传入即可（方案已支持）。

---

### M-3: CLI `--file` 和 `--stdin` 的输入处理未定义边界

**漏洞位置：** CLI 设计 → `--file transcript.txt` / `--stdin`

**隐含假设：** 文件存在、可读、编码为 UTF-8、大小合理。

**未覆盖的异常场景：**
- 文件不存在（`FileNotFoundError`）—— 方案未定义错误消息
- 文件是二进制（如误传 `.pdf`）—— 读入垃圾内容写入 body
- 文件 > 100MB —— 内存爆破
- `--stdin` 在非交互终端（如 CI）被调用 —— 永久阻塞
- `--file` 和 `--content` 同时传入 —— 冲突，方案未定义优先级
- `--file` 和 `--stdin` 同时传入 —— 同上

**真实场景案例：** 用户在 CI 脚本中 `python -m src.cli capture --type article --title "x" --stdin`，没有 stdin 输入 → 进程永久阻塞 → CI 超时。

**整改建议：** 定义互斥规则（`--content`、`--file`、`--stdin` 三选一，用 argparse mutually exclusive group）；`--file` 加大小上限（如 10MB）和编码检测；`--stdin` 加超时机制（如 `select()` 5 秒无输入报错）。

---

### M-4: `page_id` 生成策略未定义

**漏洞位置：** API Response → `"page_id": "card_xxx"`

**隐含假设：** 存在一个 ID 生成器，但方案未说明调用哪个。

**实际机制：** `WikiPage.id` 需要符合 `card_<13hex_millis>_<8hex_rand>_<slug>` 格式（v2.2+），但 capture 通道是否使用同一 ID 生成器未明确。如果直接用 slug 作 ID，与现有 `id_generator` 生成的 ID 格式不一致，可能导致 `index.md` 条目、向量索引、wikilink 解析出现问题。

**真实场景案例：** capture 创建 `id=article-20260814`，而系统其他页面都是 `card_01915a3b...` 格式。`index.md` 中混合两种 ID 格式，前端渲染 ID 时截断逻辑出错。

**整改建议：** 明确调用 `src.wiki.core.id_generator` 的 `generate_id(slug)` 函数（如存在），或复用现有 pipeline 的 ID 生成逻辑。在方案中写明具体调用路径。

---

### M-5: `is_skeleton` 标记无下游消费定义

**漏洞位置：** API Response → `"is_skeleton": true`

**隐含假设：** 存在某种机制区分骨架页和完整页，前端或其他系统会利用此标记。

**实际机制：** `WikiPage` dataclass 没有 `is_skeleton` 字段。此标记**仅存在于 HTTP 响应 JSON 中**，不持久化到任何地方。页面一旦写入磁盘，无法通过读取 `WikiPage` 对象判断它是否是骨架页。

**真实场景案例：** 用户想批量筛选"待补充内容的骨架页"进行二次编辑，但 `is_skeleton` 不在 frontmatter 中，无法通过搜索/CLI 筛选。WebUI 的页面列表也无法标注哪些是骨架。

**整改建议：** 要么在 frontmatter 中加 `is_skeleton: true` 字段（需改 dataclass，与方案"不改 WikiPage"矛盾），要么用 `source_status: skeleton` 等已有扩展字段标记（回到 F-2 的 round-trip 问题，必须先解决 F-2）。两个方案必须选一个。

---

### M-6: 向量索引缺失 —— capture 页无法被语义搜索

**漏洞位置：** 方案整体设计 —— "绕过完整 ingest pipeline"

**隐含假设：** capture 页面只需要写入磁盘，不需要向量索引。

**实际机制：** 正常 pipeline 的 Writer 阶段会调用 `vector store upsert` 将页面内容向量化存入 LanceDB。capture 通道绕过了整个 pipeline，**不会生成向量嵌入**。这意味着 capture 创建的页面在 `hybrid_search`（语义搜索）中完全不可见，只能通过关键词/文件名匹配。

**真实场景案例：** 用户通过 capture 存入 50 篇文章摘要，之后用搜索功能查找"机器学习优化"相关内容 → 语义搜索结果为空（因为没有向量）→ 用户认为系统有 bug。

**整改建议：** 在 capture 写入完成后，调用 `vector store upsert` 生成嵌入（同步或异步均可）。或者在 API 文档和 CLI help 中明确说明 capture 页面不参与语义搜索，让用户知情选择。

---

### M-7: `write_page` 的 taxonomy 校验可能阻断 capture

**漏洞位置：** `write_page()` (`page_writer.py` line 96-104)

**隐含假设：** capture 页面不需要 taxonomy 分类。

**实际机制：** `write_page()` 在写入前调用 `TaxonomyRegistry.from_project(root).validate(page.category, page.taxonomy_sub)`。如果项目设置了 `taxonomy_validation == "strict"` 且 capture 页面的 `category` / `taxonomy_sub` 为空字符串，可能触发 `raise ValueError("taxonomy validation failed")`。

**真实场景案例：** 项目管理员设置了严格 taxonomy 校验，用户通过 API capture 一篇文章 → `category=""`, `taxonomy_sub=""` → strict 模式下 ValueError → HTTP 500。

**整改建议：** capture 通道应绕过 taxonomy 校验（如使用 `write_page(..., skip_taxonomy=True)` 新增参数），或者在 capture 请求中要求传入 `category` / `taxonomy_sub`（但方案 API 没有这两个字段，需补充）。

---

## 三、优化疏漏 — 6 项

### O-1: 并发 capture 无 idempotency 保护

**漏洞位置：** API 设计 — 无幂等性机制

**实际机制：** 正常 ingest 通道有 md5 去重（`generate_task_hash`），但 capture 通道没有。相同 title + content 的重复 POST 会创建多个相同页面。

**真实场景案例：** 网络抖动导致前端重试 capture 请求 → 同一篇文章生成两个 `.md` 文件（不同 ID），index.md 出现重复条目。

**整改建议：** 为 capture 请求生成 idempotency hash（基于 title + type + content 的 md5），与现有去重机制对齐。或在 API 层返回已存在的 page_id 而非重复创建。

---

### O-2: slug 冲突 / 文件名碰撞未处理

**漏洞位置：** `page_path_for()` → `wiki/<dir>/<slug>.md`

**隐含假设：** 每次 capture 的 slug 唯一。

**实际机制：** 如果两个 capture 请求 title 相同（如"读书笔记"），生成的 slug 可能相同，`page_path_for` 返回相同路径 → `write_page` 覆盖前一个页面（如果有 TOCTOU guard 会报 `WriteConflictError`，否则静默覆盖）。

**真实场景案例：** 用户 capture 两篇同名文章"读书笔记"，第二篇覆盖第一篇，丢失数据。

**整改建议：** 在 slug 生成中加入时间戳或随机后缀（如 `读书笔记-20260814-a3f2`），或在写入前检查文件是否存在并追加序号。

---

### O-3: 模板版本号 2.0.0 的"版本门炸弹"规避逻辑未文档化

**漏洞位置：** 方案 → "模板版本号 2.0.0（规避版本门炸弹）"

**实际机制：** 现有 `.wiki-templates/*.md` 的头部标注 `<!-- wiki-template-version: 2.0.0 -->`（已确认一致）。但方案说"规避版本门炸弹"暗示版本号选择有特殊考量，却未说明"版本门"具体是什么，以及 2.0.0 如何规避。

**整改建议：** 文档化"版本门"的定义和 2.0.0 的选择依据，避免后续维护者困惑或误改。

---

### O-4: API 缺少输入校验 / 类型白名单

**漏洞位置：** API Body → `"type": "article" | "video-transcript" | "inspiration"`

**实际机制：** 方案未说明是否在 API 层做类型校验。如果 `type` 字段直接传入 `write_page`，恶意或错误输入（如 `type=../../etc`）可能通过 `page_path_for` → `get_custom_dir` 产生路径问题（虽然 `SchemaRegistry._parse_schema_text` 有路径安全检查，但 custom type 未注册时直接报错而非走安全路径）。

**整改建议：** 在 API 路由层加 `type` 白名单校验（`if type not in ("article", "video-transcript", "inspiration"): raise HTTPException(400)`）。

---

### O-5: capture 通道不更新 `index.md` 和 `log.md`

**漏洞位置：** 方案整体 — 绕过 pipeline

**实际机制：** 正常 pipeline 的 Writer 阶段会 `append_to_index` 和 `log_event`。capture 通道如果只调用 `write_page`，不会更新这两个文件。`index.md` 是系统目录，`log.md` 是审计日志，缺失更新会导致：
- `project info` / `health` 命令报告页面数不准确
- 审计追踪断裂
- `stubs list` 等依赖 index 的功能遗漏 capture 页面

**整改建议：** capture 写入后调用 `append_to_index(paths, page)` 和 `log_event(paths, "capture", page.id, ...)`。

---

### O-6: `--tags` 参数解析格式未定义

**漏洞位置：** CLI → `--tags "a,b"`

**实际机制：** 方案用逗号分隔，但未处理：标签含逗号（如 `标签,含逗号`）、空格（`"a, b"` vs `"a,b"`）、空列表（`--tags ""`）、重复标签。

**整改建议：** 定义明确的分隔规则（逗号分隔，strip 空格，去重），或改为多次 `--tag` 参数（`--tag a --tag b`），后者更健壮。

---

## 四、信息盲区汇总

| # | 盲区 | 影响 | 需要补充的信息 |
|---|------|------|---------------|
| 1 | capture 页的 `WikiPage.type`（基础 PageType）应该是什么？ | 路由到不同目录，影响所有下游逻辑（heat、vector、relations） | 明确：article→source, video-transcript→source, inspiration→concept |
| 2 | `page_id` 生成器的精确调用方式 | ID 格式一致性 | 引用 `src.wiki.core.id_generator` 或等价模块 |
| 3 | `index.md` 和 `log.md` 是否需要同步更新 | 搜索/审计完整性 | 明确是/否，如果是则列出调用路径 |
| 4 | 向量嵌入是否需要同步生成 | 语义搜索可用性 | 明确是/否，如果是则说明调用方式 |
| 5 | 现有项目的 schema.md 合并策略 | F-1 的根本解决 | 提供合并函数的伪代码或接口 |
| 6 | "版本门炸弹"的具体定义 | 版本号选择的合理性 | 补充说明 |
| 7 | 前端是否消费 `is_skeleton` 标记 | 功能完整性 | 明确前端需求 |
| 8 | capture 请求的并发限制 / rate limit | 系统稳定性 | 是否需要限流 |
| 9 | `source_status` / `capture_context` 的完整取值范围 | 字段设计完整性 | 列出所有合法值 |
| 10 | `url` 字段如何映射到 `sources` 数组 | frontmatter 一致性 | 明确转换逻辑 |
| 11 | capture 模板的 `.wiki-templates/` 中三个模板各自的 `type` 值 | 模板渲染 | 每个模板的 frontmatter 示例 |
| 12 | `--file` 读取失败时的 CLI 退出码 | 脚本集成 | 定义退出码规范 |

---

## 五、隐含假设清单

| # | 假设 | 不确定性 | 实际情况 |
|---|------|----------|----------|
| 1 | `SchemaRegistry` 自动发现 capture 模板的 schema 声明 | **高** | ❌ 只读项目根 schema.md |
| 2 | 扩展字段能 round-trip 通过 `from_dict`/`to_frontmatter_dict` | **高** | ❌ 白名单构造，未知字段丢弃 |
| 3 | 项目根不存在 `schema.md` / `purpose.md` | **高** | ❌ 几乎所有项目都有 |
| 4 | slug 一定唯一 | **中** | ❌ 同 title 同 slug |
| 5 | capture 页不需要向量索引 | **中** | ⚠️ 取决于产品需求，方案未明确 |
| 6 | `is_skeleton` 标记会被下游消费 | **中** | ❌ 不持久化，无法消费 |
| 7 | taxonomy 校验不会阻断 capture | **中** | ❌ strict 模式下会阻断 |
| 8 | 用户不会重复提交相同 capture | **低** | ⚠️ 网络抖动必然发生 |
| 9 | CLI 的 `--file` 总是存在的 UTF-8 文本文件 | **低** | ❌ 未处理异常 |
| 10 | 模板版本号 2.0.0 没有副作用 | **低** | ⚠️ 需确认"版本门"机制 |

---

## 六、整改优先级建议

```
P0 (编码前必须解决):
  F-1  schema 注册问题 → 设计合并函数
  F-2  扩展字段 round-trip → 选方案改 from_dict 或加 dataclass 字段
  M-1  schema.md 覆盖问题 → 移除模板中的 schema.md，改用合并注入

P1 (编码时同步处理):
  M-2  taxonomy.md 冲突 → 移除模板中的 taxonomy.md
  M-4  page_id 生成策略 → 明确调用 id_generator
  M-6  向量索引缺失 → 明确是否需要，如需要则加 upsert
  M-7  taxonomy 校验阻断 → 加 skip_taxonomy 参数
  O-4  API 类型白名单 → 加校验
  O-5  index.md / log.md 更新 → 加调用

P2 (测试阶段补全):
  M-3  CLI 输入边界 → 加互斥组、大小限制、超时
  M-5  is_skeleton 持久化 → 与 F-2 联动解决
  O-1  idempotency → 加 hash 去重
  O-2  slug 冲突 → 加时间戳后缀
  O-3  版本文档化 → 补充说明
  O-6  tags 解析 → 定义规范
```

---

*审计完成。共发现 2 个致命缺陷、7 个重大隐患、6 个优化疏漏、12 个信息盲区、10 个隐含假设。*
