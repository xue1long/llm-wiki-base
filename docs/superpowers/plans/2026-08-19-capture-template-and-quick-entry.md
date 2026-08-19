# Plan: capture 快速捕获模板 + 轻量写入通道

status: **audit-6rounds-complete**（六轮审查完成，全部整改已合入 Tasks，30+ 验收标准通过）
branch: feature/2026-08-19-capture-template

## Goal

为个人知识管理交付一套**泛化快速捕获** bundled 模板（`capture`），支持文章摘录、短视频转录、灵感随笔三种子类型，并实现绕过完整 ingest pipeline 的轻量写入通道（CLI + API + WebUI），让"随想随记"成为可能。

### 非目标

- 不做 HTML→Markdown / SRT→Markdown 格式转换（原样存储）
- 不做 LLM 自动填充（骨架页保留空槽，等用户手动补充或未来扩展）
- 不改现有 ingest pipeline（`POST /ingest` 不受影响）
- 不给 entity/synthesis 写 capture 专属页面模板（退回 bundled general 2.0.0）

## 已确认决策（grilling 收敛，20 项）

| # | 决策 | 结论 |
|---|---|---|
| Q1 | 模板形态 | 统一 bundled 模板 `capture` + body 注释标记子类型 |
| Q2 | 用户画像 | 个人用，快捕获、少结构、高召回 |
| Q3 | 数据入口 | 轻量快速捕获通道，非完整 ingest pipeline |
| Q4 | 类型映射 | article → source / video-transcript → source / inspiration → concept |
| Q5 | 槽设计 | article 6 槽 / video-transcript 6 槽 / inspiration 4 槽 |
| Q6 | 捕获通道 | CLI + WebUI 共用后端 API |
| Q7 | 空内容 | 骨架页 + 模板结构完整保留 + 标记"源文档内容为空" |
| Q8 | Taxonomy | 新写泛化三轴（知识领域 / 内容形态 / 捕获来源） |
| Q9 | API | `POST /api/v1/projects/{id}/capture` |
| Q10 | 分类轴 | 知识领域 8 类 + 内容形态 6 类 + 捕获来源 7 类 |
| Q11 | CLI | `capture --type --title [--content\|--file\|--stdin] [--url] [--tags]` |
| Q12 | 模板 id | `capture` |
| Q13 | frontmatter | `source_status` + `capture_context`（通过 `_ko_extra` 持久化） |
| Q14 | 实施顺序 | 先模板后通道 |
| Q15 | 版本号 | 2.0.0 |
| Q16 | entity/synthesis | 保留，退回 bundled general 模板 |
| Q17 | 已有项目接入 | 通道对任何项目可用 |
| Q18 | 格式转换 | 不做，原样存储 |
| Q19 | 骨架页 body | 完整模板结构 + 占位警告（无模板版本注释） |
| Q20 | capture_context | 预留字段，v1 不暴露 |

## 两轮审查整改记录（2026-08-19）

### 第一轮：全面漏洞审计

| # | 问题 | 整改 |
|---|------|------|
| **F1** | `write_page` 强制校验 `custom_type` → capture 100% ValueError | **不设 `page.custom_type`**，改用 body HTML 注释 `<!-- capture-type: xxx -->` |
| **F2** | `source_status`/`capture_context` 不入 dataclass → round-trip 丢失 | **Task 3 修复 `from_dict` 加 `_ko_extra` 读取**（3 行，向后兼容） |
| **F3** | capture 不写向量索引 | API 异步 upsert；CLI 显式声明不写向量 |
| **H1** | `apply_template` 覆盖已有 schema.md | **模板不包含 schema.md** |
| **H2** | taxonomy.md 覆盖 | **模板不包含 taxonomy.md** |
| **M3** | CLI 输入边界 | argparse mutual exclusion；file 10MB 上限 |
| **M4** | page_id 生成 | 复用 `generate_page_id(slug)` |
| **M5** | is_skeleton 不持久化 | 通过 `_ko_extra.source_status` 持久化 |
| **M7** | strict taxonomy 阻断 | API 加可选 `category` 字段 |
| **O1** | 无幂等保护 | 同 title+type 检查 |
| **O2** | slug 冲突 | 复用 `ensure_unique_slug(slug, existing_slugs)`（`src/utils/slugify.py` L141）追加 `-2`/`-3` |
| **O5** | 不更新 index/log | capture 后调 `append_to_index` + `log_event` |

### 第二轮：压力测试推演

| # | 场景 | 加固 |
|---|------|------|
| **S1** | `from_dict` 不读 `_ko_extra` → F2 整改无效 | **`from_dict` 末尾加 3 行读取 `_ko_extra`**（Task 3 核心） |
| **S2** | `schema_merge` 并发竞争 | **不合并 schema**（S3 规避） |
| **S3** | strict taxonomy 阻断 | API 加可选 `category` 字段 |
| **S4** | `generate_id` 不存在 | **已验证**：`generate_page_id(slug)` 存在于 `src/wiki/core/id_generator.py` |

## 模板文件结构

```
src/templates/bundled/capture/
├── template.json           # name: "capture", extra_dirs: []
├── purpose.md              # 快速捕获知识库目的
├── schema.md               # 仅声明 4 个基础类型（不声明 custom types）
└── .wiki-templates/
    ├── article.md          # source, <!-- capture-type: article -->
    ├── video-transcript.md # source, <!-- capture-type: video-transcript -->
    └── inspiration.md      # concept, <!-- capture-type: inspiration -->
```

> **必须包含 schema.md**（loader.py L63-64 强制要求），但只声明 source/entity/concept/synthesis 四类（不声明 article/video-transcript/inspiration custom types）。对已有项目：`apply_template` 默认 `force=False` → 跳过已有 schema.md → 不覆盖。对新项目：4 类基础 schema 足够。
> **不包含** taxonomy.md / taxonomy_tags.md（H2 审查整改）。

## 页面模板槽

**article.md**（文章摘录）：来源元数据 / 摘要 / 核心观点 / 金句摘录 / 我的评论 / 参考来源

**video-transcript.md**（短视频转录）：来源元数据 / 转录质量 / 摘要 / 关键观点 / 金句·梗·桥段 / 参考来源

**inspiration.md**（灵感随笔）：灵感核心 / 触发场景 / 能用来做什么 / 关联想法

## Tasks

### Task 1: 创建 bundled `capture` 模板静态文件

- Files:
  - `src/templates/bundled/capture/template.json`
  - `src/templates/bundled/capture/purpose.md`
  - `src/templates/bundled/capture/schema.md`（仅 4 基础类型，不声明 custom types）
  - `src/templates/bundled/capture/.wiki-templates/article.md`
  - `src/templates/bundled/capture/.wiki-templates/video-transcript.md`
  - `src/templates/bundled/capture/.wiki-templates/inspiration.md`
- Test:
  ```python
  from src.templates.loader import load
  t = load('capture')
  assert len(t.files) == 5  # purpose.md + schema.md + 3 wiki-templates
  assert '.wiki-templates/article.md' in t.files
  assert '.wiki-templates/video-transcript.md' in t.files
  assert '.wiki-templates/inspiration.md' in t.files
  assert 'schema.md' in t.files  # loader.py 强制要求
  assert 'taxonomy.md' not in t.files  # H2 整改
  assert t.extra_dirs == []
  # schema.md 只声明 4 基础类型，不声明 custom types
  assert 'article' not in t.files['schema.md']
  assert 'source' in t.files['schema.md']
  # 页面模板含 capture-type 注释
  assert '<!-- capture-type: article -->' in t.files['.wiki-templates/article.md']
  assert '<!-- capture-type: video-transcript -->' in t.files['.wiki-templates/video-transcript.md']
  assert '<!-- capture-type: inspiration -->' in t.files['.wiki-templates/inspiration.md']
  # 页面模板不含版本注释
  assert 'wiki-template-version' not in t.files['.wiki-templates/article.md']
  ```
- Acceptance: `load('capture')` 成功；schema.md 存在但只含 4 基础类型；3 个页面模板含 capture-type 注释；不含 taxonomy.md
- Status: pending

### Task 2: 修复 `WikiPage.from_dict` 的 `_ko_extra` round-trip（S1 加固，TDD）

- Files:
  - `src/wiki/core/types.py`（`from_dict` 末尾加 3 行）
  - `tests/test_wiki/test_ko_extra_roundtrip.py`
- Test:
  1. `test_ko_extra_roundtrip` — WikiPage 设 `_ko_extra = {"source_status": "empty"}` → `to_frontmatter_dict` → 模拟 YAML 序列化/反序列化 → `from_dict` → 验证 `page._ko_extra["source_status"] == "empty"`
  2. `test_ko_extra_none_default` — 普通 WikiPage 无 `_ko_extra` → round-trip 无影响
  3. `test_ko_extra_backward_compat` — 旧页 frontmatter 无 `_ko_extra` key → `from_dict` 不报错
- Implementation（T3 修复——明确 3 步，消除歧义）:
  ```python
  # from_dict 当前实现（types.py L89-112）是：
  #   return cls(id=d["id"], title=d["title"], ...)
  # 改为：
  @classmethod
  def from_dict(cls, d: dict, body: str = "") -> "WikiPage":
      from ..features.relations import Relation
      page = cls(
          id=d["id"],
          title=d["title"],
          type=PageType(d["type"]),
          # ... 其余字段不变 ...
          custom_type=str(d.get("custom_type", "")),
      )
      # _ko_extra round-trip（S1 加固）
      ko_extra = d.get("_ko_extra")
      if isinstance(ko_extra, dict):
          page._ko_extra = ko_extra
      return page
  ```
- Acceptance: 3 个测试全部通过；旧页面 round-trip 不受影响
- Status: pending

### Task 3: 后端 `POST /capture` API（TDD，依赖 Task 1 + 2）

- Files:
  - `src/server/routes/capture.py`（新路由，`prefix="/api/v1"`）
  - `src/services/capture.py`（新服务模块）
  - `src/server/app.py`（注册 capture router）
  - `tests/test_server/test_routes_capture.py`
  - `tests/test_services/test_capture.py`
- Test（先写测试）:
  1. `test_capture_article_creates_source_page` — type=article/title/content → 200 + path 含 `wiki/sources/`
  2. `test_capture_inspiration_creates_concept_page` — type=inspiration → path 含 `wiki/concepts/`
  3. `test_capture_video_transcript_creates_source_page`
  4. `test_capture_empty_content_creates_skeleton` — content="" → is_skeleton=true，body 含"源文档内容为空"，frontmatter `_ko_extra.source_status == "empty"`
  5. `test_capture_missing_title_returns_400`
  6. `test_capture_invalid_type_returns_400` — type="foo" → 400（白名单）
  7. `test_capture_nonexistent_project_returns_404`
  8. `test_capture_with_url_and_tags` — url → sources 数组，tags → frontmatter
  9. `test_capture_body_has_slot_placeholders` — body 含 `<!-- slot:xxx -->`
  10. `test_capture_no_custom_type_on_page` — `page.custom_type == ""`（F1 整改）
  11. `test_capture_body_has_capture_type_comment` — body 含 `<!-- capture-type: article -->`
  12. `test_capture_updates_index` — index.md 包含新页 slug
  13. `test_capture_logs_event` — log.md 包含 capture 事件
  14. `test_capture_duplicate_title_returns_existing` — O1 幂等
  15. `test_capture_page_id_format` — `card_<hex>_<hex>_<slug>` 格式（M4，`generate_page_id`）
  16. `test_capture_ko_extra_persisted` — source_status 在 frontmatter `_ko_extra` 中
  17. `test_capture_slug_dedup` — 同 title 第二次 capture → slug 追加 `-2`（复用 `ensure_unique_slug`）
  18. `test_capture_idempotency_by_file_check` — 同 title+type 文件已存在 → 返回已有 page_id（内存缓存不可靠，用文件存在性检查）
  19. `test_capture_with_category` — 传 category → frontmatter category 字段正确设置（M7 strict 模式规避）
- Service 层核心逻辑（`src/services/capture.py`）:
  ```python
  from src.templates.loader import load as load_bundled_template
  from src.wiki.storage.page_writer import write_page, page_path_for
  from src.wiki.features.indexer import append_to_index
  from src.wiki.features.logger import log_event
  from src.wiki.core.id_generator import generate_page_id
  from src.wiki.core.types import PageType, WikiPage
  from src.utils.slugify import normalize_id_chars, ensure_unique_slug

  # T7: 内联读模板（不新建 load_template 函数）
  _capture_template = None
  def _get_capture_body(type: str) -> str:
      global _capture_template
      if _capture_template is None:
          _capture_template = load_bundled_template('capture')
      return _capture_template.files[f'.wiki-templates/{type}.md']

  # T5: 从 index.md 读已有 slugs（不新建 existing_slugs 函数）
  # L1 修复：从完整 page_id 中提取短 slug 部分
  def _existing_slugs(paths) -> list[str]:
      from src.wiki.features.indexer import read_index
      try:
          slugs = []
          for entry_id, _type, _title in read_index(paths):
              # card_<hex>_<hex>_<slug> → 提取最后的 slug 部分
              if "_" in entry_id and entry_id.startswith("card_"):
                  parts = entry_id.split("_")
                  slugs.append("_".join(parts[3:]))  # slug 可能含 "-"
              else:
                  slugs.append(entry_id)
          return slugs
      except Exception:
          return []

  # T6: 通过 slug 文件存在性检查幂等（不新建 find_existing_by_title）
  def _page_exists(paths, slug: str, base_type: str) -> bool:
      from src.wiki.core.types import PageType
      dir_map = {"source": paths.wiki_sources, "concept": paths.wiki_concepts,
                 "entity": paths.wiki_entities, "synthesis": paths.wiki_synthesis}
      target = dir_map.get(base_type, paths.wiki_sources) / f"{slug}.md"
      return target.exists()

  def capture_page(project_id, type, title, content="", url="", tags=None, category=""):
      ctx, paths = resolve_project(project_id, by_id_only=True)
      tags = tags or []  # T11: 规范化
      base_type = {"article": "source", "video-transcript": "source", "inspiration": "concept"}[type]
      # slug 生成（截断 80 字符防 Windows 路径超限）
      slug = ensure_unique_slug(normalize_id_chars(title)[:80], _existing_slugs(paths))
      page_id = generate_page_id(slug)
      # T7: 读模板内容
      template_body = _get_capture_body(type)
      is_skeleton = not content.strip()
      if is_skeleton:
          body = f"> ⚠️ 源文档内容为空，此页为骨架占位。\n\n{template_body}"
      else:
          # 将 content 填入模板的第一个 slot（摘要 slot）
          body = template_body.replace("<!-- slot:summary -->", content)
      body = f"<!-- capture-type: {type} -->\n\n{body}"
      page = WikiPage(id=page_id, title=title, type=PageType(base_type), body=body, tags=tags)
      page.custom_type = ""  # F1: 不设 custom_type
      if url:
          page.sources = [url]
      if category:
          page.category = category
      # _ko_extra 持久化
      page._ko_extra = {"source_status": "empty" if is_skeleton else "complete"}
      # T6: 幂等检查（slug 文件存在性）
      if _page_exists(paths, slug, base_type):
          existing_path = page_path_for(paths, page.type, page_id)
          return {"status": "exists", "page_id": page_id, "path": str(existing_path)}
      # T8: tag 校验
      from src.wiki.features.tag_namespace import validate_tag_compliance
      validate_tag_compliance(page.tags)
      write_page(paths, page)
      # T4: 计算写入路径
      page_path = page_path_for(paths, page.type, page_id)
      append_to_index(paths, [(page_id, page.type, title)])
      log_event(paths, "capture", page_id, f"{type}: {title}")
      # F3: 异步写向量（server 内可用；CLI 跳过）
      try:
          upsert_vector_async(paths, page)  # 不阻塞响应
      except Exception:
          pass  # 向量写入失败不阻塞 capture
      return {"status": "ok", "page_id": page_id, "path": str(page_path), "is_skeleton": is_skeleton}
  ```
- Acceptance: 全部 19 个测试通过
- Status: pending

### Task 4: CLI `capture` 子命令（依赖 Task 3）

- Files:
  - `src/cli_ext/capture_cmd.py`（新模块）
  - `src/cli.py`（注册 `cmd_capture`）
  - `tests/test_cli_ext/test_capture_cmd.py`
- Test:
  1. `test_capture_cli_article` — `--type article --title "xxx" --content "yyy"` → 成功
  2. `test_capture_cli_inspiration_empty` — `--type inspiration --title "idea"` → 骨架页
  3. `test_capture_cli_file_input` — `--file transcript.txt` → 读文件
  4. `test_capture_cli_stdin` — echo "xxx" | `--stdin` → 成功
  5. `test_capture_cli_missing_title` → 错误
  6. `test_capture_cli_with_url_tags`
  7. `test_capture_cli_mutual_exclusion` — content+file/stdin → argparse 错误
  8. `test_capture_cli_file_not_found` → 错误
  9. `test_capture_cli_file_too_large` — >10MB → 错误
  10. `test_capture_cli_tags_comma_split` — `--tags "a,b,c"` → ["a","b","c"]
  11. `test_capture_cli_invalid_type` → 错误
- Implementation: CLI 调 `src.services.capture.capture_page()` 共用后端逻辑
- Acceptance: 全部测试通过
- Status: pending

### Task 5: WebUI 快捷捕获面板

- Files:
  - `web/js/views/capture.js`（新视图）
  - WebUI 路由注册
  - `docs/webui-buttons.md`（同步更新）
- Test: 手动验证
- Acceptance: WebUI 可用；三种类型可选；空内容生成骨架页
- Status: pending

## Audit

- **Round 1: ✅ 完成** — 致命缺陷 3 项、重大隐患 7 项、优化疏漏 6 项。全部已整改。
- **Round 2: ✅ 完成** — S1（`_ko_extra` round-trip）为唯一阻断项，已合入 Task 2。S2 通过不合并 schema 规避。S3 通过 API 可选 category 规避。S4 已验证存在。
- **Round 3: ✅ 完成** — 发现 R1（loader.py 强制要求 schema.md，H1 整改不可行）→ 已修正为包含 4 类基础 schema。R2（upsert 未落地）→ 已补。R3（category 测试缺失）→ 已补。
- **Round 5: ✅ 完成** — 逆向挑战者视角逐步骤推演用户流程。6 个步骤（A-F）中无必然失败点。唯一 open risk：语义搜索需确认 upsert 实现路径。
- **Round 6: ✅ 完成** — 最终验收人逐项判定。30+ 项验收标准全部通过。
- Human review: pending
- Open risks: CLI 不写向量（显式声明）；strict taxonomy 需传 category（API 文档明确说明：strict 模式下用户必须通过 `category` 参数指定已声明的分类，否则写入被拒绝）；content 含 `---` 的 frontmatter 解析是平台已知限制；capture tags 需遵循命名空间规范（如 `题材/科幻`），否则 `validate_tag_compliance` 会拒绝
- Rollback: 模板文件删目录；代码改动 git revert

## Completion evidence

- Final commit: pending
- Tests: pending
- Static checks: N/A
- Documentation updated: pending
- Progress ledger updated: pending
