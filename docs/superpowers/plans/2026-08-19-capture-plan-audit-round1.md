# 第一轮审查：全面漏洞审计 — capture 快速捕获模板

> 审查对象：`docs/superpowers/plans/2026-08-19-capture-template-and-quick-entry.md`
> 审查方式：独立第三方审计专家视角，逐条核验代码事实（`write_page`、`SchemaRegistry`、`TaxonomyRegistry`、`loader.py`、`app.py`、`types.py`），抛弃方案正向思路。
> 审查日期：2026-08-19

---

## 审查结论

发现 **致命缺陷 3 项、重大隐患 5 项、优化疏漏 4 项**。方案当前**不可进入编码**，致命缺陷 F1 阻塞全部 Task 3–6。

---

## ① 致命缺陷（方案无法落地）

### F1 — `custom_type` 校验拦截：`write_page` 会拒绝所有 capture 页面 ⛔

**漏洞位置**：Task 3（`POST /capture` API）与 Task 4（CLI `capture`）的核心写入路径

**代码事实**：
`src/wiki/storage/page_writer.py` L106-111：
```python
if custom_type:
    registry = SchemaRegistry.from_project(paths.root)
    if not registry.is_custom(custom_type):
        raise ValueError(
            f"Custom page type {custom_type!r} is not declared in schema.md"
        )
```

方案设计 `page.custom_type = "article"`，但 `SchemaRegistry.is_custom("article")` 只在 schema.md 中有 `| article | wiki/article |` 这行时才返回 True。而 capture 的 schema.md **故意不声明** article/video-transcript/inspiration 为自定义类型（它们路由到 wiki/sources/ 或 wiki/concepts/ 这些已有目录）。

**后果**：`POST /capture` 和 CLI `capture` 写入时 100% 抛 ValueError，所有 capture 功能无法工作。

**整改建议**（3 选 1）：
- **a）推荐**：capture 服务层**不设** `page.custom_type`，改用 frontmatter body 中的 HTML 注释标记子类型（`<!-- capture-type: article -->`），custom_type 字段留空。`write_page` 不校验空字符串。
- **b）** 在 schema.md 中声明 article/video-transcript/inspiration 为 custom type，指向 `wiki/sources` / `wiki/concepts` 目录（但 `SchemaRegistry` 的 `get_directory` 会返回 `"sources"`，与现有 source type 冲突——需要验证路径去重）。
- **c）** 给 `write_page` 加一个 `skip_custom_type_check` 参数（侵入性大，不推荐）。

---

### F2 — `source_status` / `capture_context` 不入 WikiPage dataclass → frontmatter 扩展字段不可靠 ⛔

**漏洞位置**：Task 3 设计（frontmatter 扩展字段）

**代码事实**：
`WikiPage.to_frontmatter_dict()`（`types.py` L63-87）只序列化 dataclass 已知字段。`from_dict()`（L89-112）同样只读已知字段。

方案说"source_status / capture_context 走 frontmatter 扩展字段，不改 WikiPage"。但：
1. `write_page` 调用 `page.to_frontmatter_dict()` → 扩展字段**不会被序列化**到 YAML
2. 即使手动注入到 dict，`read_page` → `WikiPage.from_dict()` 会**丢弃**未知字段
3. `safe_write(path, content)` 写的是 `f"---\n{fm_text}---\n\n{page.body}"`，fm_text 来自 `to_frontmatter_dict()`

**后果**：`source_status: empty` 和 `capture_context` 永远不会出现在磁盘文件的 frontmatter 中。骨架页标记、批量检索"哪些页还空着"全部失效。

**整改建议**（2 选 1）：
- **a）推荐**：给 `WikiPage` 加 `extra_frontmatter: dict` 字段（默认空 dict），`to_frontmatter_dict` 末尾 merge，`from_dict` 读取时保留未知字段到 extra。向后兼容（旧页 extra 为空）。
- **b）** capture 服务层绕过 `write_page`，自己拼 YAML frontmatter + body 直接 `safe_write`（绕过校验层，风险大）。

---

### F3 — 方案 Tasks 3–6 无一条提到 `init_vector_store_for_paths` ⛔

**漏洞位置**：Task 3 / Task 4 的写入路径

**代码事实**：
向量库 upsert 需要 `init_vector_store_for_paths(WikiPaths)` 已调用。server 的 lifespan 自动调用了，但 CLI `capture` 命令走的是**独立进程**（`python -m src.cli capture ...`），不经过 server lifespan。

**后果**：CLI capture 写入后，如果未来加向量检索功能，这些页面不会被索引。当前不阻塞（capture 暂不写向量），但 plan 应明确声明此限制并在 Task 4 加 TODO。

**整改建议**：Task 4 实现时明确声明"CLI capture 不写向量索引"；如需支持，在 CLI 中调用 `init_vector_store_for_paths`。

---

## ② 重大隐患（容易失败）

### H1 — capture 模板 schema.md 不声明 custom types → `page_path_for` 路由退化

**漏洞位置**：Task 1 模板文件设计

**代码事实**：
`page_path_for`（page_writer.py L30-50）：当 `registry` 为 None（custom_type 为空）时，按 base PageType 路由到 `_TYPE_TO_DIR`。

如果采用 F1 整改方案 a（不设 custom_type），article 和 video-transcript 都会路由到 `wiki/sources/`，inspiration 路由到 `wiki/concepts/`——这是正确的。但方案的 `schema.md` 模板文件需要**不声明**这三个 custom type，与 Task 1 的描述一致。

**风险**：如果方案 Task 1 的 schema.md 错误地声明了 custom types，会导致 `SchemaRegistry` 创建额外目录或路径冲突。

**整改建议**：Task 1 的 schema.md 明确只声明 source/entity/concept/synthesis 四类（与 general 一致），不加 custom types。在 plan 中显式注明。

### H2 — `TaxonomyRegistry.validate` 对空 category 会报错

**漏洞位置**：Task 3 capture 服务层

**代码事实**：
`taxonomy_registry.py` L40-50：
```python
def validate(self, category: str, taxonomy_sub: str) -> list[str]:
    if self.is_empty:
        return []
    errors: list[str] = []
    if category not in self.categories:
        errors.append(f"unknown category: {category}")
        return errors
```

capture 场景中用户可能不填 category/taxonomy_sub（快速捕获，谁会选分类？）。如果项目有 taxonomy.md（非空），`validate("", "")` 会报 `unknown category: `。

`write_page` 中 taxonomy 错误在默认模式下是 **warning**（非 strict），不会阻塞。但如果项目配置了 `taxonomy_validation: strict`，会直接 raise ValueError。

**风险**：strict 模式下 capture 写入 100% 失败（用户没填 category）。

**整改建议**：capture 服务层跳过 taxonomy 校验（不设 category/taxonomy_sub），或在 plan 中声明"capture 默认不填 taxonomy，strict 模式需用户手动指定"。

### H3 — 骨架页 body 的模板版本号 HTML 注释会被 `render_for_prompt` 剥离

**漏洞位置**：Task 1 模板文件 / Q19 骨架页设计

**代码事实**：
方案设计骨架页 body 包含：
```
<!-- wiki-template-version: 2.0.0 -->
<!-- wiki-template-type: source -->
```

但 capture 快速通道**不经过 Generator/Analyzer**（正是设计意图），所以 `render_for_prompt` 不会被调用。这些注释会原样留在磁盘文件中。

**风险**：不是功能 bug，但这些注释对 capture 场景没有实际作用（不走 pipeline，不触发模板解析）。用户直接看到一堆 HTML 注释，体验不佳。

**整改建议**：骨架页 body 去掉模板版本/type 注释（这些是 pipeline 内部用的），只保留 slot 占位和警告文字。

### H4 — CLI `--stdin` 与 `--content` / `--file` 的互斥逻辑未定义

**漏洞位置**：Task 4 CLI 设计

**代码事实**：
方案 Q11 说"三选一"，但没有定义：
- 同时传 `--content` 和 `--file` 时的行为（报错？前者优先？）
- 同时传 `--stdin` 和 `--content` 时的行为
- `--file` 文件不存在时的行为
- `--file` 文件是二进制（PDF/图片）时的行为

**风险**：用户误操作时 CLI 行为不确定。

**整改建议**：Task 4 测试加 3 个互斥冲突测试（content+file → 400、content+stdin → 400、file+stdin → 400）+ file 不存在 → 400。

### H5 — `POST /capture` 路由与现有 `POST /ingest` 端点路径冲突风险

**漏洞位置**：Task 5 路由注册

**代码事实**：
现有 ingest 路由前缀是 `prefix="/api/v1"`，路径是 `/projects/{project_id}/ingest`。
capture 路由路径是 `/projects/{project_id}/capture`。
两者不冲突。但需要确认 capture router 也用 `prefix="/api/v1"`。

**风险**：如果 capture router 用了不同前缀（如 `/api/v2`），会导致前端调用路径混乱。

**整改建议**：Task 5 显式要求 capture router 用 `prefix="/api/v1"` 与 ingest 对齐。

---

## ③ 优化疏漏

### O1 — `template.json` 的 `extra_dirs` 应为空

capture 模板不需要额外目录（不像 reading 要 `wiki/characters`、`wiki/themes`）。但方案 Task 1 没显式说明 `extra_dirs: []`。

**整改建议**：Task 1 验收条件加 `extra_dirs == []`。

### O2 — `taxonomy_tags.md` 当前平台代码不读取

`src/wiki/taxonomy_registry.py` 只读 `taxonomy.md`，不读 `taxonomy_tags.md`。capture 模板带 `taxonomy_tags.md` 是对齐 novel 设计（Phase 1.4 才实现独立枚举解析），但当前完全不生效。

**整改建议**：plan 中显式声明"taxonomy_tags.md 是预留资产，当前不生效"。

### O3 — WebUI 捕获面板（Task 6）缺少 WebUI 视图注册的说明

方案只写了 `web/js/views/capture.js`，但没有说明如何在 WebUI 中注册新视图（路由、侧边栏入口）。

**整改建议**：Task 6 补充 WebUI 路由注册的具体文件和改动点。

### O4 — `--tags` 参数格式未定义

方案说 `--tags "a,b"` 但没定义分隔符（逗号？空格？多次传参？）。与现有 CLI 风格是否一致？

**整改建议**：Task 4 定义 `--tags` 接受逗号分隔字符串，拆分为 list。

---

## 整改优先级

| 优先级 | 编号 | 整改建议 |
|---|---|---|
| **P0（编码前置）** | F1 | capture 服务层不设 page.custom_type，改用 body HTML 注释标记子类型 |
| **P0** | F2 | WikiPage 加 extra_frontmatter 字段，或 capture 绕过 write_page 自己写 |
| **P0** | H1 | schema.md 不声明 custom types（显式注明） |
| **P1** | H2 | capture 跳过 taxonomy 校验或声明 strict 模式限制 |
| **P1** | H3 | 骨架页 body 去掉模板版本注释 |
| **P1** | H4 | CLI 互斥参数测试 |
| **P1** | H5 | capture router 用 `/api/v1` 前缀 |
| **P2** | F3 | CLI capture 不写向量（显式声明） |
| **P2** | O1-O4 | 文档/声明性修复 |
