# 「检索与浏览」功能 Bug 报告

> 测试范围：`POST /api/v1/projects/{id}/search`、`GET .../files`、`GET .../files/content`、`GET .../raw-files`、`GET .../wiki/graph`
> 测试项目：`novel-wiki`（436 个 wiki 页面，1361 个原始源，1872 条图谱边）
> 测试方式：curl + Python urllib 直接调用 API；结合源码审计（`hybrid_search.py` / `search_service.py` / `search.py` 路由层）

---

## 一、功能通过项 ✅

| 端点 | 状态 | 说明 |
|---|---|---|
| `GET .../files` | ✅ | 正确返回 wiki 文件树（concepts/entities/sources/synthesis + index.md/log.md） |
| `GET .../files/content?path=wiki/index.md` | ✅ | 返回完整文件内容；不存在的文件正确 404；路径遍历 `../../../etc/passwd` **被拦截**（"Path escapes wiki root"） |
| `GET .../raw-files` | ✅ | 返回 1361 个原始源，含 `path/name/ext/size/ingested` 字段；仅 54 个标记为 `ingested:true` |
| `GET .../wiki/graph` | ✅ | 436 节点 / 1872 边，含 `id/title/type/path/api_path` |
| 关键词搜索（中文） | ✅ | 7 个中文查询全部返回相关结果，score 合理（标题匹配高分 → 如 "仙侠题材类型综述" 38.0；内容匹配低分 → 如 "章节规划" 2.0）；不存在的词正确返回空 |
| 路径遍历防护 | ✅ | 文件内容端点对 `../` 路径做了归一化检查并拒绝 |

---

## 二、已确认的 Bug 🐛

### Bug #1（P0）：语义检索完全不可用
**现象**：所有搜索结果的 `source` 均为 `"keyword"`，零语义匹配。

**根因（两层）**：
1. `get_embedding_provider()` 直接 `raise RuntimeError("not configured")`——app 启动时未能初始化 embedding provider（MiniMax API 可能无 key 或网络不通），异常被 `hybrid_search.py:134-142` 静默吞掉，回退 keyword-only。
2. **LanceDB chunks 表数据目录为空**（`.index/lancedb/chunks.lance/data/` 不存在）——即便 provider 配好，也没有向量数据可检。`ingest` 链路不调用 `librarian.archive`（嵌入切块+写 LanceDB），导致向量库恒空。

**影响**：宣传的「语义检索」能力完全不工作；用户只能做逐字匹配的关键词搜索。

**修复方向**：
- 确保 `app.py` 的 lifespan startup 成功初始化 embedding provider（当前 `try/except` 只 warning 不阻断启动）。
- 在 ingest 完成后自动触发 `archive` 步骤，或在 WebUI/API 中提供手动触发 archive 的入口。

---

### Bug #2（P1）：`_keyword_search` 每次请求全文读入所有 wiki 页面
**位置**：`src/searcher/hybrid_search.py:200-204`

```python
for file in knowledge_dir.rglob("*.md"):
    ...
    content = file.read_text(encoding="utf-8")   # ← 完整读取每篇
    content_lower = content.lower()
    if query_lower in content_lower:
        ...
```

**问题**：对 436 个 wiki 页面（总计可达数 MB），每次搜索请求都把所有文件全文读入内存做线性扫描。无缓存、无索引——O(n × 文件大小) 每查询。

**影响**：搜索延迟随 wiki 规模线性增长；大规模知识库可能 OOM。

**修复方向**：引入倒排索引（inverted index）或在启动时构建并缓存，而不是每次搜索都 rglob + read_text。

---

### Bug #3（P2）：`mode` 参数被接受但完全忽略
**位置**：路由层 `search.py:11-15` 定义了 `mode: Literal["hybrid", "keyword", "vector"]`，但 `hybrid_search` 无视它——始终同时尝试语义+关键词两个分支。

**问题**：
- 用户显式指定 `mode="keyword"` 时，服务器仍在发起 embedding API 调用（浪费 API 额度与时间）。
- `mode="vector"` 理论上应纯向量检索，但不做任何区分。

**API 响应对比**：
```json
// mode="keyword" → 实际仍调了 embedding
{"query":"test","mode":"keyword","topK":2,"tokenHits":0,"vectorHits":0,"results":[]}
```
语义分支虽然返回空，但 embedding 调用已发生（若 provider 可用）。

**修复方向**：在 `search_service.py` 或 `hybrid_search` 中按 `mode` 参数分流，keyword 跳过语义调用，vector 跳过关键词扫描。

---

### Bug #4（P3）：`tokenHits` / `vectorHits` 始终为 0
**位置**：`src/services/search.py:67-68`

```python
"tokenHits": 0,        # reserved (not populated by current impl)
"vectorHits": 0,       # reserved (not populated by current impl)
```

即使关键词搜索命中多个结果，这两个字段也硬编码为 0。

**影响**：API 消费者无法区分「真的没结果」vs「功能未完成/计数缺失」。前端若依赖这两个字段做 UI 状态渲染（如「找到 N 个关键词匹配」），会显示 0。

---

### Bug #5（P4）：中文请求体在 curl shell 环境下被损毁
**现象**：`curl -d '{"query":"画面感","topK":3}'` → `"There was an error parsing the body"`；Python `urllib` 同数据正常。

**性质**：Shell/curl 对中文 JSON 体的编码问题，非后端代码 bug。但若 WebUI 的 `fetch('/search', {body: JSON.stringify({query:'画面感'})})` 也可能触发类似问题（取决于浏览器 Content-Type 头是否正确）。实测 Python SDK 正常，表明服务端 JSON 解析器本身正常。

**影响**：低——真实客户端走浏览器/Python SDK 不受影响；但调试/运维时用 curl 测中文搜索会误导。

---

## 三、潜在风险

| 风险 | 说明 |
|---|---|
| **`_keyword_search` 单文件编码异常致全局崩溃** | `file.read_text(encoding="utf-8")` 若某文件非 UTF-8，`UnicodeDecodeError` 会中止整个搜索并返回 500。当前 wiki 由系统生成（均为 UTF-8），暂不会触发，但人工放入非 UTF-8 文件即炸。 |
| **`mode="vector"` 无 provider 时静默反回空** | 用户传 `mode="vector"` 但 embedding provider 未配置 → 静默回退 `keyword_results`（见 150-153 行）→ API 说 mode=vector 但实际返回了 keyword 结果，行为不可预期。 |

---

## 四、总结

| 功能 | 状态 | 备注 |
|---|---|---|
| 文件浏览 (files/content) | ✅ 正常 | 含路径遍历防护 |
| 原始源列表 (raw-files) | ✅ 正常 | 1,361 文件，54 已摄取 |
| 知识图谱 (wiki/graph) | ✅ 正常 | 436 节点 / 1,872 边 |
| **关键词搜索** | ✅ | 中文查询准确，评分合理 |
| **语义搜索** | ❌ P0 | 两层断链：provider 未初始化 + LanceDB 数据空 |
| `tokenHits/vectorHits` | ❌ P3 | 硬编码 0，未实现 |
| `mode` 参数路由 | ❌ P2 | 被忽略，始终混合模式 |
| 搜索性能 | ⚠️ P1 | 每次全文扫描，无索引 |

**核心修复优先级**：P0（语义检索断链）> P1（关键词搜索建索引）> P2（mode 路由分流）> P3（hit 计数实现）。
