# 第四轮审查：压力测试推演（整改后 Plan 最终验证）

> 审查对象：第三轮整改后的最终 plan
> 审查日期：2026-08-19

---

## 压力测试场景

### 场景 1：Task 1 → `load('capture')` 能否成功

**推演**：loader.py L63 要求 schema.md。plan 已修正为包含 4 类基础 schema。

**验证**：schema.md 内容 `source/entity/concept/synthesis` → `_read()` L63 检查 `"schema.md" not in files` → False → 通过。

**结论**：✅ 已修复（R1 整改）。

### 场景 2：Task 2 的 `from_dict` 改动影响范围

**推演**：`from_dict` 被 `read_page` 调用，`read_page` 被 10+ 处调用。加 3 行读 `_ko_extra` 是否影响现有行为？

**分析**：
- 旧页 frontmatter 无 `_ko_extra` key → `d.get("_ko_extra")` 返回 None → `isinstance(None, dict)` → False → 不执行 → **无影响**
- 新页有 `_ko_extra` → 正确读回 → **功能增强**
- `from_dict` 返回类型不变（WikiPage）→ **接口兼容**

**结论**：✅ 向后兼容，无风险。

### 场景 3：Task 3 的 `load_template(type)` 实现细节

**推演**：服务层需要从 bundled capture 模板读取页面模板内容。

**实现路径**：
```python
from src.templates.loader import load as load_bundled_template
template = load_bundled_template('capture')
article_body = template.files['.wiki-templates/article.md']
```

**边界**：`load('capture')` 每次调用都读磁盘（`root.rglob("*")`）。高频 capture 时有 I/O 开销。

**加固**：可加 `@lru_cache` 缓存 Template 对象（模板文件不会在运行时变化）。但 v1 不需要——个人使用频率低。

**结论**：✅ 可行，v1 不需优化。

### 场景 4：Task 3 幂等检查的 TOCTOU gap

**推演**：`find_existing_by_title` 检查文件是否存在 → 不存在 → 准备写入 → 但另一个请求在间隙中创建了同名文件。

**分析**：`write_page` 有 TOCTOU 守卫（`expected_content_hash`），但 capture 不传 hash。如果文件已存在，`write_page` 会：
1. 检查 immutable → 新文件不 immutable → 跳过
2. `_snapshot_raw` → 新文件不存在 → 跳过
3. `safe_write` → 覆盖写入

**风险**：低。个人使用场景并发概率极低。即使发生，`safe_write` 的 AtomicContext 保证最后一次写入是完整的。

**结论**：✅ 可接受（个人使用场景）。

### 场景 5：Task 3 的 `_ko_extra` 在 `write_page` 中的行为

**推演**：`page._ko_extra = {"source_status": "empty"}` → `write_page` → `to_frontmatter_dict` → `_ko_extra` 进入 dict → `yaml.dump` → 写入文件。

**验证**：
- `to_frontmatter_dict` L84-86：`ko_extra = getattr(self, "_ko_extra", None)` → `{"source_status": "empty"}` → `isinstance(dict)` → True → `d["_ko_extra"] = {"source_status": "empty"}`
- `yaml.dump(fm)` → 包含 `_ko_extra: {source_status: empty}`
- `safe_write(path, content)` → 写入磁盘

**结论**：✅ 写入路径通。

### 场景 6：content 含 YAML frontmatter 分隔符 `---`

**推演**：用户粘贴的文章内容包含 `---` → 拼接后的 body 中出现假 frontmatter 分隔符 → `read_page` 解析错乱。

**分析**：
- `write_page` L141：`content = f"---\n{fm_text}---\n\n{page.body}"`
- `page.body` 中的 `---` 会被 `read_page` L152 `text.find("\n---", 4)` 误匹配为 frontmatter 结束符

**风险**：用户粘贴含 `---` 的内容 → 页面读回时 frontmatter/body 切割错误 → 内容损坏。

**加固**：capture 服务层在拼接 body 前，将内容中的 `---` 转义为 `----` 或用 fence 包裹？不——这会改变用户原始内容。

**更简单的加固**：在 body 开头加一个空行 + 注释行，确保 `---` 不在 frontmatter 结束位置附近：
```python
body = f"<!-- capture-type: {type} -->\n\n{content}"
```
`<!-- capture-type: ... -->` 注释行确保 body 不以 `---` 开头。但 `read_page` 的 `text.find("\n---", 4)` 是从 offset 4 开始搜索第一个 `\n---`，如果 content 中有 `\n---`，仍会误匹配。

**这是 `write_page`/`read_page` 的已有设计限制**，不是 capture 引入的新问题。所有 wiki 页面都有这个风险。

**结论**：⚠️ 已知限制，不在本次 scope 内修复。记录为 open risk。

### 场景 7：超长标题（1000 字符）

**推演**：`normalize_id_chars("a" * 1000)` → 1000 字符 slug → `generate_page_id(slug)` → `card_xxx_xxx_<1000-char-slug>` → 文件名超长。

**加固**：`normalize_id_chars` 后截断到合理长度（如 80 字符）。

**结论**：⚠️ 需在 Task 3 服务层加 slug 截断。

---

## 问题清单

| # | 问题 | 级别 | 加固 |
|---|------|------|------|
| T1 | content 含 `---` → frontmatter 解析错乱 | ⚠️ 已知限制 | 不在 scope 内，记录 open risk |
| T2 | 超长标题 → 文件名超长 | 🟡 优化 | Task 3 服务层加 `slug[:80]` 截断 |
| T3 | 幂等 TOCTOU gap | 🟢 可接受 | 个人使用场景，不需加固 |

---

*第四轮压力测试完成。无新的致命缺陷。T1 为已知平台限制，T2 需小幅加固。*
