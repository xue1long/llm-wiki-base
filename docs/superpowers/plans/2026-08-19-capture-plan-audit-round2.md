# 第二轮审查：压力测试推演 — capture 快速捕获模板

> 审查对象：整改后的 plan
> 审查日期：2026-08-19

---

## 压力测试问题清单

### 致命（1 项）

| # | 场景 | 失败路径 | 连锁反应 | 加固 |
|---|------|----------|----------|------|
| **S1** | `_ko_extra` round-trip 实际不可行 | `from_dict` 不读回 `_ko_extra`（白名单构造）→ capture 写入的 `source_status` 在 `read_page` → `write_page` 循环中静默消失 | 骨架页标记丢失 → 批量筛选"待补充页"失效 → F2 整改无效 | **给 `from_dict` 末尾加 3 行读取 `_ko_extra`**（向后兼容，不改 dataclass） |

### 重大（3 项）

| # | 场景 | 失败路径 | 连锁反应 | 加固 |
|---|------|----------|----------|------|
| **S2** | `schema_merge` 并发竞争 | 两请求同时读-改-写 schema.md → 后写覆盖前写 | custom type 声明丢失 → 回到 F1 | **S3：不合并 schema，capture 不设 custom_type** |
| **S3** | strict taxonomy 阻断 | 项目 strict 模式 + capture 不填 category → ValueError → HTTP 500 | 用户无法 capture | API 加可选 `category` 字段；或 capture 跳过 taxonomy（需 `write_page` 加参数） |
| **S4** | `generate_id` 函数不存在或接口不匹配 | 方案说复用 `generate_id(slug)` 但需验证是否存在 | capture 无法生成 page_id | 验证 `src/wiki/core/` 中的 ID 生成函数 |

### 优化（2 项）

| # | 场景 | 问题 | 加固 |
|---|------|------|------|
| **S5** | `append_to_index` 接口 | 函数签名是 `entries: Iterable[tuple[str, PageType, str]]`，需要 (slug, type, title) 三元组 | capture 服务层正确构造 tuple |
| **S6** | `log_event` 接口 | 函数签名是 `(paths, event, task_id, detail, extra)`，task_id 需要一个标识 | capture 用 page_id 作为 task_id |

---

## 边界临界点

| 条件 | 可行 → 失效 |
|------|-------------|
| `_ko_extra` round-trip 不修复 | S1 → source_status 永久丢失 |
| schema_merge 用于已有 custom types 的项目 | S2 → 并发下 custom type 丢失 |
| 项目 strict taxonomy + capture 不传 category | S3 → 100% HTTP 500 |
| `generate_id` 不存在 | S4 → ID 格式不一致 |

---

## 最终加固建议

**S1 是唯一阻断项**——必须在 Task 3 中修复 `from_dict` 的 `_ko_extra` round-trip。

**S2 通过 S3 规避**——不合并 schema，不设 custom_type，彻底消除并发问题和 schema 覆盖风险。

**S3 通过 API 扩展规避**——`POST /capture` body 加可选 `category` 字段，strict 模式用户自行指定。

**S4 需要代码验证**——确认 `generate_id` 或等价函数存在。

---

*压力测试推演完成。1 项致命（S1）、3 项重大（S2/S3/S4）、2 项优化（S5/S6）。*
